"""Caché de embeddings de texto (`text_embeddings`) contra `rappi_ia_test`, con un embedder espía."""

import tracemalloc

import numpy as np
import pytest
from rappi_scraper.storage.search import SEARCH_DOCUMENTS_LOCK, VERTICALS, build_search_documents

from conftest import add_product, add_store
from rappi_ia import config
from rappi_ia.concepts import knn
from rappi_ia.concepts.knn import ItemText, embed_texts, item_texts
from rappi_ia.db import connect, database_url
from rappi_ia.embeddings import text_store
from rappi_ia.embeddings.base import HashEmbedder

NAMES = [
    "Sal",
    "Pañales Babysec Premium Talla G paquete ahorro de 60 unidades",
    "Té verde",
    "Cerveza Kunstmann Torobayo 330 cc",
    "Arroz",
    "Papas fritas Lays Clásicas 180 g",
    "Leche entera Colun caja 1 L pack de 12 unidades",
    "Pan",
]


class SpyEmbedder(HashEmbedder):
    """Anota los textos que recibe en cada llamada (en el orden en que llegan al modelo)."""

    def __init__(self):
        super().__init__()
        self.calls: list[list[str]] = []

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        self.calls.append(list(texts))
        return super().embed_documents(texts)


def _parse(text: str) -> np.ndarray:
    return np.array([float(x) for x in text.strip("[]").split(",")], dtype=np.float32)


def test_pending_texts_reach_the_model_sorted_by_length(db, monkeypatch):
    """Cada lote se rellena hasta su texto más largo: ordenados por largo, los lotes salen parejos."""
    add_store(db, 1, "supermercado", "Súper")
    add_store(db, 2, "licores", "Botillería")
    for pid, name in enumerate(NAMES, start=100):
        add_product(db, pid, name, 1 + pid % 2)
    # La 101 también en el súper: mismo texto en dos verticales, un solo hash.
    db.execute("INSERT INTO store_products (store_id, sku, master_product_id) VALUES (1, 'sku-101-b', 101)")
    db.commit()
    build_search_documents(db)
    monkeypatch.setattr(text_store, "BATCH_SIZE", 3)
    spy = SpyEmbedder()

    embedded = text_store.embed_pending(db, spy)

    sent = [text for call in spy.calls for text in call]
    assert all(len(call) <= 3 for call in spy.calls)
    assert [len(t) for t in sent] == sorted(len(t) for t in sent)
    distinct = db.execute("SELECT count(DISTINCT content_hash) FROM search_documents").fetchone()[0]
    assert embedded == len(sent) == distinct
    # Mismo hash → el vector de SU texto (el orden por largo no cruza hashes con vectores).
    rows = db.execute(
        """SELECT DISTINCT d.content, e.embedding::text FROM search_documents d
           JOIN text_embeddings e ON e.content_hash = d.content_hash AND e.embedding_model = %s""",
        (spy.model_name,),
    ).fetchall()
    assert len({content for content, _ in rows}) == distinct
    for content, vector in rows:
        assert np.allclose(_parse(vector), HashEmbedder().embed_documents([content])[0], atol=1e-5)
    calls = len(spy.calls)
    assert text_store.embed_pending(db, spy) == 0 and len(spy.calls) == calls  # incremental


def test_new_item_names_reach_the_model_sorted_by_length(db, monkeypatch):
    monkeypatch.setattr(knn, "EMBED_BATCH", 3)  # varios lotes: el orden tiene que ser global, no por llamada
    items = [ItemText("catalog_item", str(i), name) for i, name in enumerate(NAMES)]
    spy = SpyEmbedder()

    vectors = embed_texts(db, spy, items)

    assert len(spy.calls) > 1 and all(len(call) <= 3 for call in spy.calls)
    sent = [text for call in spy.calls for text in call]
    assert sorted(sent) == sorted(NAMES)
    assert [len(t) for t in sent] == sorted(len(t) for t in sent)
    assert np.allclose(vectors, HashEmbedder().embed_documents(NAMES), atol=1e-5)


class SpyConnection:
    """Delega en la conexión real y anota el `maintenance_work_mem` vigente en cada CREATE INDEX."""

    def __init__(self, conn):
        self._conn = conn
        self.memory_at_create: list[str] = []

    def execute(self, query, params=None):
        text = query if isinstance(query, str) else query.as_string(self._conn)
        if "CREATE INDEX" in text:
            self.memory_at_create.append(self._conn.execute("SHOW maintenance_work_mem").fetchone()[0])
        return self._conn.execute(query, params)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_hnsw_indexes_get_more_memory_only_inside_their_transaction(db, monkeypatch):
    """Con los 64 MB por defecto el grafo de una partición grande no cabe y pgvector lo construye lento."""
    monkeypatch.setattr(config, "HNSW_MAINTENANCE_WORK_MEM", "123MB")
    before = db.execute("SHOW maintenance_work_mem").fetchone()[0]
    db.commit()
    spy = SpyConnection(db)

    created = text_store.ensure_hnsw_indexes(spy, "modelo-test", 64)

    assert len(created) == len(VERTICALS)
    assert spy.memory_at_create == ["123MB"] * len(VERTICALS)
    assert db.execute("SHOW maintenance_work_mem").fetchone()[0] == before != "123MB"  # SET LOCAL: no queda fijado


def _cache_names(db, model: str, names: list[str], dim: int) -> None:
    """Vectores de ejemplo en el caché de nombres, generados en SQL (sin formatear miles de literales en Python)."""
    db.execute(
        """INSERT INTO text_embeddings (content_hash, embedding_model, embedding)
           SELECT md5('nombre|' || name), %s,
                  (SELECT array_agg(sin(n * d + 1)::real ORDER BY d) FROM generate_series(1, %s) d)::vector
           FROM unnest(%s::text[]) WITH ORDINALITY AS x(name, n)""",
        (model, dim, names),
    )
    db.commit()


def _vectors_as_before(db, model: str, items: list[ItemText]) -> np.ndarray:
    """El método anterior: `embedding::text` a un dict de strings y después número por número."""
    cached = dict(
        db.execute(
            "SELECT content_hash, embedding::text FROM text_embeddings WHERE embedding_model = %s", (model,)
        ).fetchall()
    )
    return np.stack([_parse(cached[it.content_hash]) for it in items])


def test_item_vectors_match_the_text_method(db):
    embedder = HashEmbedder(dim=32)
    _cache_names(db, embedder.model_name, NAMES[:5], embedder.dim)
    # Repetidos (mismo nombre en dos ítems) y nombres sin vector, que se embeben y quedan en el caché.
    names = NAMES[:5] + [NAMES[0], NAMES[3]] + NAMES[5:]
    items = [ItemText("menu_item", str(i), name) for i, name in enumerate(names)]

    vectors = embed_texts(db, embedder, items)

    assert vectors.shape == (len(items), embedder.dim) and vectors.dtype == np.float32
    assert np.allclose(vectors, _vectors_as_before(db, embedder.model_name, items), atol=1e-6)
    assert np.array_equal(vectors[[5, 6]], vectors[[0, 3]])
    assert np.allclose(vectors[-3:], embedder.embed_documents(NAMES[5:]), atol=1e-6)


def test_cached_item_vectors_are_not_kept_as_text(db):
    """~220k nombres × 768 como texto eran ~1,6 GB antes de convertirlos: ahora van directo a la matriz."""
    embedder = HashEmbedder(dim=256)
    names = [f"producto de ejemplo {i}" for i in range(10000)]
    _cache_names(db, embedder.model_name, names, embedder.dim)
    items = [ItemText("catalog_item", str(i), name) for i, name in enumerate(names)]

    tracemalloc.start()
    try:
        vectors = embed_texts(db, embedder, items)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()

    assert vectors.shape == (10000, 256)
    assert np.allclose(vectors, _vectors_as_before(db, embedder.model_name, items), atol=1e-6)
    assert peak < 2 * vectors.nbytes, f"pico de {peak / 1e6:.1f} MB para una matriz de {vectors.nbytes / 1e6:.1f} MB"


def _add_vector(db, content_hash: str, model: str, days_old: int) -> None:
    db.execute(
        """INSERT INTO text_embeddings (content_hash, embedding_model, embedding, created_at)
           VALUES (%s, %s, '[1,0,0]', now() - make_interval(days => %s))""",
        (content_hash, model, days_old),
    )


def _cache_with_documents_and_names(db) -> tuple[set[str], set[str]]:
    """Catálogo chico con sus vectores de documentos y de nombres (kNN), todos de hace 30 días."""
    add_store(db, 1, "supermercado", "Súper")
    for pid, name in enumerate(NAMES[:4], start=100):
        add_product(db, pid, name, 1)
    db.commit()
    build_search_documents(db)
    embedder = HashEmbedder()
    text_store.embed_pending(db, embedder)
    embed_texts(db, embedder, item_texts(db))
    db.execute("UPDATE text_embeddings SET created_at = now() - interval '30 days'")
    db.commit()
    documents = {h for (h,) in db.execute("SELECT content_hash FROM search_documents").fetchall()}
    names = {item.content_hash for item in item_texts(db)}
    return documents, names


def _cached(db) -> set[tuple[str, str]]:
    return set(db.execute("SELECT content_hash, embedding_model FROM text_embeddings").fetchall())


def test_prune_deletes_only_old_vectors_that_nothing_uses(db):
    documents, names = _cache_with_documents_and_names(db)
    assert documents and names and not documents & names  # el kNN usa hashes que no están en search_documents
    model = HashEmbedder().model_name
    _add_vector(db, "huerfano-viejo", model, 8)
    _add_vector(db, "huerfano-otro-modelo", "modelo-viejo", 60)
    _add_vector(db, "huerfano-reciente", model, 6)
    _add_vector(db, next(iter(documents)), "modelo-viejo", 60)  # un hash en uso se conserva con cualquier modelo
    db.commit()
    before = _cached(db)

    result = text_store.prune_orphan_embeddings(db)

    after = _cached(db)
    assert before - after == {("huerfano-viejo", model), ("huerfano-otro-modelo", "modelo-viejo")}
    assert result == {"vectores_borrados": 2, "vectores_que_quedan": len(after)}
    assert {(h, model) for h in documents | names} | {("huerfano-reciente", model)} <= after
    assert text_store.prune_orphan_embeddings(db)["vectores_borrados"] == 0
    # Ningún documento quedó sin su vector en el caché.
    assert text_store.embed_pending(db, HashEmbedder()) == 0


def test_prune_waits_for_the_scraper(db):
    _cache_with_documents_and_names(db)
    _add_vector(db, "huerfano-viejo", "modelo-test", 30)
    db.execute("INSERT INTO scrape_runs (kind, status) VALUES ('stores', 'running')")
    db.commit()
    with pytest.raises(text_store.ScrapeRunning):
        text_store.prune_orphan_embeddings(db)
    db.execute("UPDATE scrape_runs SET status = 'done'")
    db.commit()
    with connect(database_url("DATABASE_URL_TEST")) as scraper:
        scraper.execute("SELECT pg_advisory_xact_lock(%s)", (SEARCH_DOCUMENTS_LOCK,))  # reescritura en curso
        with pytest.raises(text_store.ScrapeRunning):
            text_store.prune_orphan_embeddings(db)
        scraper.rollback()
    assert text_store.prune_orphan_embeddings(db)["vectores_borrados"] == 1
