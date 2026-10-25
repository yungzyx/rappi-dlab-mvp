"""Precarga de los índices de la búsqueda al arrancar la API (extensión pg_prewarm, migración 034).

En frío, la primera búsqueda en una vertical lee del disco su índice HNSW (restaurantes, ~740 MB) y su índice de texto
sin tildes: hasta un segundo por vertical. Al arrancar, un hilo aparte los lee con `pg_prewarm(…, 'read')`, que los
deja en la caché del sistema operativo: los HNSW suman más que shared_buffers (128 MB en local, 1 GB en producción) y
el modo `prefetch` no existe en macOS. No bloquea el arranque ni /health, usa su propia conexión (no una del pool) y
tiene un tope de tiempo. Si falta la extensión, el permiso o la base, anota un aviso y la API sigue igual, en frío.
Se apaga con API_PREWARM=0 (los tests).
"""

import logging
import threading
import time

import psycopg

from .. import config
from ..db import database_url

log = logging.getLogger(__name__)

BUDGET_S = 120  # tope de la precarga entera; un índice que no alcanza a leerse se corta (statement_timeout)

# Los HNSW y los de texto sin tildes (`tsv_unaccent`) de las particiones de search_documents: primero los más usados
# (idx_scan) y, con el mismo uso (estadísticas recién borradas), los más grandes.
INDEXES = """
    SELECT i.indexrelid::regclass::text
    FROM pg_inherits p
    JOIN pg_index i ON i.indrelid = p.inhrelid
    JOIN pg_class c ON c.oid = i.indexrelid
    JOIN pg_am am ON am.oid = c.relam
    LEFT JOIN pg_stat_user_indexes s ON s.indexrelid = i.indexrelid
    WHERE p.inhparent = 'search_documents'::regclass
      AND (am.amname = 'hnsw'
           OR (am.amname = 'gin' AND EXISTS (SELECT 1 FROM pg_attribute a
                                             WHERE a.attrelid = i.indrelid AND a.attnum = ANY (i.indkey)
                                               AND a.attname = 'tsv_unaccent')))
    ORDER BY coalesce(s.idx_scan, 0) DESC, pg_relation_size(i.indexrelid) DESC, 1
"""


def prewarm_search_indexes(url: str | None = None, budget_s: float = BUDGET_S) -> list[str]:
    """Lee los índices de la búsqueda (INDEXES) hasta `budget_s` segundos, contados desde que conecta: cada consulta
    (también revisar la extensión y listar los índices) lleva de statement_timeout lo que queda. Devuelve los que
    alcanzó a leer. Nunca lanza: un error (sin extensión, sin permiso, sin base) queda en un aviso."""
    start = time.monotonic()
    done: list[str] = []
    indexes: list[str] = []
    try:
        with psycopg.connect(
            url or database_url(), connect_timeout=3, autocommit=True, application_name="rappi-ia-precarga"
        ) as conn:

            def within_budget() -> bool:
                left = budget_s - (time.monotonic() - start)
                if left > 0:
                    conn.execute(
                        "SELECT set_config('statement_timeout', %s, false)", (f"{max(int(left * 1000), 1)}ms",)
                    )
                return left > 0

            if not within_budget():
                raise psycopg.errors.QueryCanceled("sin tiempo")
            if not conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_prewarm'").fetchone():
                log.warning(
                    "Precarga de la búsqueda: falta la extensión pg_prewarm (migración 034; en producción la crea el "
                    "superusuario, ver docs/despliegue.md). La búsqueda arranca en frío."
                )
                return done
            indexes = [name for (name,) in conn.execute(INDEXES)]
            for name in indexes:
                if not within_budget():
                    raise psycopg.errors.QueryCanceled("sin tiempo")
                conn.execute("SELECT pg_prewarm(%s::regclass, 'read')", (name,))
                done.append(name)
    except psycopg.errors.QueryCanceled:
        log.warning(
            "Precarga de la búsqueda: se cumplió el tope de %s s con %d de %d índices leídos",
            budget_s,
            len(done),
            len(indexes),
        )
        return done
    except (psycopg.Error, RuntimeError) as exc:  # RuntimeError: falta DATABASE_URL
        log.warning("No se pudo precargar los índices de la búsqueda (%d leídos): %s", len(done), exc)
        return done
    log.info("Precarga de la búsqueda: %d índices en %.1f s", len(done), time.monotonic() - start)
    return done


def start() -> threading.Thread | None:
    """Lanza la precarga en un hilo daemon (no retiene el cierre de la API). Con API_PREWARM=0, nada."""
    if not config.API_PREWARM:
        return None
    thread = threading.Thread(target=prewarm_search_indexes, name="precarga-busqueda", daemon=True)
    thread.start()
    return thread
