"""Cuántas consultas hace la búsqueda de la app: `/search` sin vertical recorre las 8 verticales, así que cada consulta
de más por vertical se paga ocho veces. Y ninguna búsqueda vuelve a contar la partición entera de una vertical (es lo
que `/health` dejó de hacer por costoso): ese conteo sale de la caché del catálogo."""

import re

import pytest
from fastapi.testclient import TestClient

from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.rappi_agent import RappiAgent
from rappi_ia.api import app as api
from rappi_ia.api.services import Services
from rappi_ia.catalog import cache
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents

GROUPED_SEARCH_BUDGET = 40  # con la caché del catálogo caliente (la versión y los conteos por vertical ya leídos)
# Con la caché vacía: + la versión del catálogo, un conteo por vertical, los lexemas de la consulta y su df en cada
# vertical (51 medidas). El df se cuenta una vez por vertical y palabra hasta que cambia el catálogo (o 10 min).
COLD_GROUPED_SEARCH_BUDGET = 54
# `count(*)` de una vertical entera: sin otro filtro que la vertical.
PARTITION_COUNT = re.compile(
    r"count\(\*\)(?:::\w+)?(?:\s+AS\s+\w+)?\s+FROM\s+search_documents(?:\s+\w+)?\s+WHERE\s+(?:\w+\.)?vertical\s*=\s*"
    r"%(?:\(\w+\))?s\s*\)",
    re.IGNORECASE,
)


class CountingConnection:
    """La conexión del test que anota cada consulta que pasa por `execute`."""

    def __init__(self, conn):
        self._conn = conn
        self.statements: list[str] = []

    def execute(self, query, *args, **kwargs):
        self.statements.append(str(query))
        return self._conn.execute(query, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


@pytest.fixture
def counted(db):
    seed_demo(db)
    embedder = HashEmbedder()
    embed_search_documents(db, embedder)
    db.commit()
    counting = CountingConnection(db)

    def conn_override():
        yield counting

    api.app.dependency_overrides[api.get_conn] = conn_override
    api.app.dependency_overrides[api.get_services] = lambda: Services(
        RappiAgent(embedder, TemplateComposer()), embedder
    )
    yield TestClient(api.app), counting
    api.app.dependency_overrides.clear()


def _search(client, counting, q: str) -> list[str]:
    counting.statements.clear()
    reply = client.get("/search", params={"q": q})
    assert reply.status_code == 200, reply.text
    return list(counting.statements)


def test_grouped_search_query_count_under_budget(counted):
    """Mide la caché caliente: la primera búsqueda la llena y se cuenta la segunda."""
    client, counting = counted
    _search(client, counting, "xyz")

    statements = _search(client, counting, "xyz")

    assert len(statements) <= GROUPED_SEARCH_BUDGET, f"{len(statements)} consultas"


def test_grouped_search_query_count_with_a_cold_cache(counted):
    client, counting = counted
    cache.clear()

    statements = _search(client, counting, "xyz")

    assert len(statements) <= COLD_GROUPED_SEARCH_BUDGET, f"{len(statements)} consultas"


def test_no_partition_count_per_search(counted):
    client, counting = counted
    _search(client, counting, "xyz")

    for q in ("xyz", "papas fritas", "algo para el carrete"):
        statements = _search(client, counting, q)
        assert not [s for s in statements if PARTITION_COUNT.search(s)], q


def test_partition_count_pattern_matches_the_old_queries():
    """El patrón reconoce los dos conteos que hacía la búsqueda: si no, el test de arriba no probaría nada."""
    old_lexical = "docs AS MATERIALIZED (SELECT count(*)::float AS n FROM search_documents WHERE vertical = %(v)s)"
    old_concept = "round(%(share)s * (SELECT count(*) FROM search_documents\n     WHERE vertical = %(v)s)))"
    assert PARTITION_COUNT.search(old_lexical) and PARTITION_COUNT.search(old_concept)
    bounded = "SELECT count(*) FROM (SELECT 1 FROM search_documents WHERE vertical = %s AND entity_type = ANY(%s)"
    assert not PARTITION_COUNT.search(bounded)
