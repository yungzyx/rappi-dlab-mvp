"""Embeddings de texto de `search_documents`: caché por contenido, copia a cada partición e índices HNSW.

Es incremental y se puede cortar: solo embebe textos (content_hash) que aún no tienen vector para el modelo,
y guarda por lotes.
"""

import hashlib
import logging
import time

from psycopg import Connection
from rappi_scraper.storage.search import SEARCH_DOCUMENTS_LOCK, VERTICALS

from ..concepts.knn import item_texts
from ..db import set_index_build_memory
from .base import TextEmbedder, to_pgvector

log = logging.getLogger(__name__)

BATCH_SIZE = 256
# Un vector sin uso se borra solo si se creó hace más de esto: no toca lo que embed-text o concepts acaban de escribir,
# y un texto que vuelve después se recalcula (unos segundos por cada mil).
ORPHAN_MIN_AGE_DAYS = 7


class ScrapeRunning(RuntimeError):
    pass


def scrape_running(conn: Connection) -> bool:
    return bool(conn.execute("SELECT 1 FROM scrape_runs WHERE status = 'running' LIMIT 1").fetchone())


def pending_texts(conn: Connection, model: str, limit: int | None = None) -> list[tuple[str, str]]:
    """(content_hash, content) sin vector en el caché para este modelo."""
    return conn.execute(
        """SELECT DISTINCT ON (d.content_hash) d.content_hash, d.content
           FROM search_documents d
           WHERE NOT EXISTS (SELECT 1 FROM text_embeddings e
                             WHERE e.content_hash = d.content_hash AND e.embedding_model = %s)
           ORDER BY d.content_hash
           LIMIT %s""",
        (model, limit),
    ).fetchall()


def embed_pending(conn: Connection, embedder: TextEmbedder, limit: int | None = None) -> int:
    pending = pending_texts(conn, embedder.model_name, limit)
    # Por largo: el modelo rellena cada lote hasta su texto más largo; con textos parecidos no se pierde cómputo.
    pending.sort(key=lambda row: len(row[1]))
    log.info("%d textos por embeber con %s", len(pending), embedder.model_name)
    started = time.monotonic()
    for start in range(0, len(pending), BATCH_SIZE):
        batch = pending[start : start + BATCH_SIZE]
        vectors = embedder.embed_documents([content for _, content in batch])
        with (
            conn.cursor() as cur,
            cur.copy("COPY text_embeddings (content_hash, embedding_model, embedding) FROM STDIN") as copy,
        ):
            for (content_hash, _), vector in zip(batch, vectors, strict=True):
                copy.write_row((content_hash, embedder.model_name, to_pgvector(vector)))
        conn.commit()
        done = start + len(batch)
        if done % (BATCH_SIZE * 10) == 0 or done == len(pending):
            rate = done / max(time.monotonic() - started, 1e-6)
            log.info("  %d/%d textos (%.0f/s)", done, len(pending), rate)
    return len(pending)


def sync_document_embeddings(conn: Connection, model: str) -> int:
    """Copia los vectores del caché a `search_documents` (donde los usa el índice HNSW de cada partición).

    Toma el mismo candado que `build_search_documents` del scraper: si la reescritura está en curso, no espera ni
    compite por las filas (deadlock); avisa que hay que correrlo después."""
    if not conn.execute("SELECT pg_try_advisory_xact_lock(%s)", (SEARCH_DOCUMENTS_LOCK,)).fetchone()[0]:
        conn.rollback()
        raise ScrapeRunning("El scraper está reescribiendo los documentos de búsqueda: embed-text corre después")
    updated = conn.execute(
        """UPDATE search_documents d
           SET embedding = e.embedding, embedding_model = e.embedding_model
           FROM text_embeddings e
           WHERE e.content_hash = d.content_hash AND e.embedding_model = %s
             AND (d.embedding IS NULL OR d.embedding_model IS DISTINCT FROM %s)""",
        (model, model),
    ).rowcount
    conn.commit()
    return updated


def prune_orphan_embeddings(conn: Connection, min_age_days: int = ORPHAN_MIN_AGE_DAYS) -> dict:
    """Borra del caché los vectores que ya nadie usa, de cualquier modelo, creados hace más de `min_age_days`.

    Usan el caché dos lectores: `search_documents` (su `content_hash`) y el kNN de conceptos (el hash del nombre de
    cada producto y plato, `concepts/knn.py`, que no está en `search_documents`). Se conserva todo hash que use
    cualquiera de los dos. Toma el candado de `build_search_documents`: los documentos no cambian mientras borra.
    VACUUM no corre dentro de una transacción: queda para autovacuum (el espacio se reusa) o `VACUUM FULL` a mano."""
    if scrape_running(conn):
        raise ScrapeRunning("Hay una corrida del scraper en curso: prune-embeddings corre después")
    if not conn.execute("SELECT pg_try_advisory_xact_lock(%s)", (SEARCH_DOCUMENTS_LOCK,)).fetchone()[0]:
        conn.rollback()
        raise ScrapeRunning("El scraper está reescribiendo los documentos de búsqueda: prune-embeddings corre después")
    names = {item.content_hash for item in item_texts(conn)}  # antes del COPY: durante él la conexión no consulta
    conn.execute("CREATE TEMP TABLE name_hashes (content_hash text PRIMARY KEY) ON COMMIT DROP")
    with conn.cursor() as cur, cur.copy("COPY name_hashes (content_hash) FROM STDIN") as copy:
        for content_hash in names:
            copy.write_row((content_hash,))
    deleted = conn.execute(
        """DELETE FROM text_embeddings e
           WHERE e.created_at < now() - make_interval(days => %s)
             AND NOT EXISTS (SELECT 1 FROM search_documents d WHERE d.content_hash = e.content_hash)
             AND NOT EXISTS (SELECT 1 FROM name_hashes n WHERE n.content_hash = e.content_hash)""",
        (min_age_days,),
    ).rowcount
    conn.execute("ANALYZE text_embeddings")
    conn.commit()
    remaining = conn.execute("SELECT count(*) FROM text_embeddings").fetchone()[0]
    return {"vectores_borrados": deleted, "vectores_que_quedan": remaining}


def hnsw_index_name(vertical: str, model: str) -> str:
    return f"search_documents_{vertical}_hnsw_{hashlib.md5(model.encode()).hexdigest()[:8]}"


def ensure_hnsw_indexes(conn: Connection, model: str, dim: int) -> list[str]:
    """Un índice HNSW por partición (vertical), parcial por modelo: las búsquedas nunca cruzan verticales."""
    created = []
    for vertical in VERTICALS:
        name = hnsw_index_name(vertical, model)
        exists = conn.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s", (name,)).fetchone()
        if exists:
            continue
        set_index_build_memory(conn)
        conn.execute(
            f"""CREATE INDEX {name} ON search_documents_{vertical}
                USING hnsw ((embedding::vector({int(dim)})) vector_cosine_ops)
                WHERE embedding_model = '{model.replace("'", "''")}'"""
        )
        created.append(name)
    conn.commit()
    return created


def embed_search_documents(conn: Connection, embedder: TextEmbedder, limit: int | None = None) -> dict:
    # La copia a search_documents bloquea filas que el scraper reescribe al final de su corrida (deadlock).
    if scrape_running(conn):
        raise ScrapeRunning("Hay una corrida del scraper en curso: embed-text corre después (make post-refresh)")
    embedded = embed_pending(conn, embedder, limit)
    synced = sync_document_embeddings(conn, embedder.model_name)
    indexes = ensure_hnsw_indexes(conn, embedder.model_name, embedder.dim)
    coverage = conn.execute(
        """SELECT count(*) FILTER (WHERE embedding_model = %s), count(*) FROM search_documents""",
        (embedder.model_name,),
    ).fetchone()
    return {
        "textos_nuevos": embedded,
        "documentos_actualizados": synced,
        "indices_creados": len(indexes),
        "documentos_con_vector": coverage[0],
        "documentos_total": coverage[1],
    }
