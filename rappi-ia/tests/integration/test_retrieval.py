"""Embeddings (con el modelo falso de hashing) y búsqueda híbrida dentro de un vertical, contra `rappi_ia_test`."""

import pytest
from rappi_scraper.storage.search import SEARCH_DOCUMENTS_LOCK, build_search_documents

from conftest import add_price, add_product, add_store
from rappi_ia.concepts.pipeline import build_concepts
from rappi_ia.db import connect, database_url
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import ScrapeRunning, embed_search_documents, hnsw_index_name
from rappi_ia.retrieval import hybrid
from rappi_ia.retrieval.hybrid import Filters, retrieve


@pytest.fixture
def catalog(db):
    add_store(db, 1, "supermercado", "Súper")
    add_store(db, 2, "licores", "Botillería")
    add_product(db, 100, "Pañales Babysec Premium Talla G", 1, "Pañales")
    add_product(db, 101, "Cerveza Escudo Lata 470 cc", 2, "Cervezas")
    add_product(db, 102, "Cerveza Kunstmann Torobayo 330 cc", 2, "Cervezas")
    add_product(db, 103, "Papas fritas Lays Clásicas 180 g", 2, "Snacks salados")
    add_product(db, 104, "Cerveza Cristal Botella 1 L", 2, "Cervezas")  # 3 cervezas: surtido no testimonial
    # El mismo producto también en el súper: mismo texto, un solo embedding en el caché.
    db.execute("INSERT INTO store_products (store_id, sku, master_product_id) VALUES (1, 'sku-101-b', 101)")
    add_price(db, 2, 101, 1290)
    add_price(db, 2, 102, 2990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    return db


def test_embeddings_are_cached_by_content_and_indexed_per_vertical(catalog):
    embedder = HashEmbedder()
    first = embed_search_documents(catalog, embedder)

    assert first["documentos_con_vector"] == first["documentos_total"]
    distinct_texts = catalog.execute("SELECT count(DISTINCT content_hash) FROM search_documents").fetchone()[0]
    assert first["textos_nuevos"] == distinct_texts < first["documentos_total"]  # 101 está en dos verticales
    index = hnsw_index_name("licores", embedder.model_name)
    assert catalog.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s", (index,)).fetchone()

    again = embed_search_documents(catalog, embedder)
    assert again["textos_nuevos"] == 0 and again["indices_creados"] == 0


def test_text_embeddings_wait_for_a_running_scrape(catalog):
    """La copia a search_documents podría trabarse (deadlock) con la reescritura del final de la corrida."""
    catalog.execute("INSERT INTO scrape_runs (kind, status) VALUES ('stores', 'running')")
    with pytest.raises(ScrapeRunning):
        embed_search_documents(catalog, HashEmbedder())


def test_vectors_are_not_copied_while_the_scraper_rewrites_documents(catalog):
    """La corrida ya está 'done' cuando el scraper reescribe search_documents: el candado es lo que los separa."""
    with connect(database_url("DATABASE_URL_TEST")) as scraper:
        scraper.execute("SELECT pg_advisory_xact_lock(%s)", (SEARCH_DOCUMENTS_LOCK,))  # reescritura en curso
        with pytest.raises(ScrapeRunning):
            embed_search_documents(catalog, HashEmbedder())
        scraper.rollback()
    assert embed_search_documents(catalog, HashEmbedder())["documentos_actualizados"] > 0


def test_concept_assortment_is_materialized_by_build_concepts(catalog):
    rows = catalog.execute("SELECT vertical, items FROM concept_assortment WHERE concept_id = 'cerveza'").fetchall()
    assert sorted(rows) == [("licores", 3), ("supermercado", 1)]  # la 101 también se vende en el súper


def test_lexical_ignores_accents_and_enie(catalog):
    result = retrieve(catalog, "supermercado", "panales talla g", mode="lexico")
    assert result.hits[0].entity_id == "100"
    assert result.hits[0].concept_id == "panales"


def test_hybrid_stays_in_vertical_and_boosts_query_concept(catalog):
    embedder = HashEmbedder()
    embed_search_documents(catalog, embedder)

    result = retrieve(catalog, "licores", "cerveza", embedder)

    assert {h.vertical for h in result.hits} == {"licores"}
    assert {h.entity_id for h in result.hits[:3]} == {"101", "102", "104"}
    assert all(h.concept_id == "cerveza" for h in result.hits[:3])
    assert not result.unmet


def test_price_filter_applies_inside_each_retriever(catalog):
    embedder = HashEmbedder()
    embed_search_documents(catalog, embedder)

    result = retrieve(catalog, "licores", "cerveza", embedder, filters=Filters(price_max=2000))

    assert [h.entity_id for h in result.hits if h.concept_id == "cerveza"] == ["101"]


def test_price_filter_gives_the_same_hits_with_exact_search_and_with_hnsw(catalog, monkeypatch):
    """Con pocos documentos bajo el tope se revisan todos (no corta en hnsw.max_scan_tuples); el resultado es el
    mismo que por el índice."""
    embedder = HashEmbedder()
    embed_search_documents(catalog, embedder)
    price = catalog.execute(
        "SELECT price_min FROM search_documents WHERE vertical = 'licores' AND entity_id = '101'"
    ).fetchone()[0]
    assert price == 1290  # columna generada desde metadata (migración 013)

    query_vector = embedder.embed_queries(["cerveza"])[0]
    exact = hybrid._vector(catalog, "licores", query_vector, embedder, Filters(price_max=2000))
    monkeypatch.setattr(hybrid, "EXACT_SEARCH_MAX", 0)  # obliga el camino por HNSW
    by_index = hybrid._vector(catalog, "licores", query_vector, embedder, Filters(price_max=2000))
    assert [key for key, _ in exact] == [key for key, _ in by_index] == [("catalog_item", "101")]


def test_unmet_demand_rules(catalog):
    embedder = HashEmbedder()
    embed_search_documents(catalog, embedder)

    # La consulta nombra un concepto que no está en el vertical y nada calza todas sus palabras.
    missing = retrieve(catalog, "licores", "ramen vegano", embedder)
    assert missing.unmet and "no está en licores" in missing.unmet_reason
    assert retrieve(catalog, "licores", "whisky", embedder).unmet
    # El concepto existe en el vertical aunque la consulta no calce palabra por palabra.
    assert not retrieve(catalog, "licores", "chela", embedder).unmet
    # Algo calza todas las palabras: nunca es "sin resultado".
    assert not retrieve(catalog, "licores", "torobayo", embedder).unmet
    # Sin concepto nombrado, decide el coseno contra τ.
    assert "τ" in (retrieve(catalog, "licores", "xyzzy qwerty", embedder).unmet_reason or "")


def test_unmet_does_not_depend_on_the_price_cap(catalog, monkeypatch):
    """«Sin resultado» es «no existe», no «no cabe en el tope»: el coseno, igual que la coincidencia estricta, se
    mide sin el filtro de precio. Antes, con tope, lo que el vertical sí tiene a otro precio quedaba «sin resultado»."""
    embedder = HashEmbedder()
    embed_search_documents(catalog, embedder)
    monkeypatch.setattr(hybrid, "UNNAMED_TAU", 0.2)
    query = "torobayo xyz"  # sin concepto, ocasión ni coincidencia estricta: decide el coseno contra UNNAMED_TAU

    free = retrieve(catalog, "licores", query, embedder)
    capped = retrieve(catalog, "licores", query, embedder, filters=Filters(price_max=2000))

    assert free.query_concepts == [] and free.strict_lexical_matches == 0 and not free.unmet
    assert not capped.unmet and capped.max_cosine == free.max_cosine
    assert "102" not in [h.entity_id for h in capped.hits]  # el ranking sí respeta el tope (la Torobayo vale 2.990)


def test_a_query_without_words_to_search_is_not_unmet_by_cosine(catalog, monkeypatch):
    """«té» es stopword: sin palabras que buscar, la primera condición de «sin resultado» (que nada calce todas las
    palabras) no se puede evaluar, y el coseno solo no basta para marcarla."""
    embedder = HashEmbedder()
    embed_search_documents(catalog, embedder)
    monkeypatch.setattr(hybrid, "thresholds", lambda: {"licores": 0.99})

    tea = retrieve(catalog, "licores", "té", embedder)

    assert tea.query_concepts == [] and tea.strict_lexical_matches == 0 and tea.max_cosine < 0.99
    assert not tea.unmet and not tea.has_words
    assert retrieve(catalog, "licores", "xyzzy", embedder).unmet  # con palabras, el coseno sí decide


def test_hyphenated_words_keep_their_weight(db):
    """`to_tsquery` volvía a separar el lexema «coca-col» en 'coca-col' <-> 'coca' <-> 'col' ('coca' no existe en el
    índice): la palabra más rara y específica de la consulta no sumaba su IDF."""
    add_store(db, 5, "conveniencia", "Express")
    add_product(db, 300, "Coca-Cola Zero 1,5 L", 5, "Bebidas")
    add_product(db, 301, "Pack Coca Cola Original + Coca Cola Light", 5, "Bebidas")
    add_product(db, 302, "Agua Mineral Cachantun Sin Gas 1,6 L", 5, "Aguas")
    db.commit()
    build_search_documents(db)

    scores = dict(
        hybrid._lexical(db, "conveniencia", "coca-cola", Filters(), hybrid.vertical_doc_count(db, "conveniencia"))
    )

    assert scores[("catalog_item", "300")] > scores[("catalog_item", "301")]


def test_unknown_vertical_is_rejected(catalog):
    with pytest.raises(ValueError):
        retrieve(catalog, "aerolineas", "algo")
