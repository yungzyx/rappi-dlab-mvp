"""Una ocasión sin concepto nombrado («algo para la once») se busca por sus conceptos también en una sola vertical, con
la misma reescritura que la búsqueda agrupada (`retrieval.hybrid.occasion_search`). Antes la búsqueda de una vertical
la buscaba tal cual: en Turbo, «algo para la once» traía berenjenas y detergente (vecinos vectoriales de «once»)."""

import pytest
from fastapi.testclient import TestClient

from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.grouped_search import search_grouped
from rappi_ia.agent.rappi_agent import RappiAgent
from rappi_ia.agent.tools import search_products
from rappi_ia.api import app as api
from rappi_ia.api.services import Services
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents
from rappi_ia.retrieval.hybrid import occasion_search

COFFEE = "91004"  # el café molido del súper de `seed_demo`


@pytest.fixture
def demo(db):
    seed_demo(db)
    embedder = HashEmbedder()
    embed_search_documents(db, embedder)
    return db, embedder


def _once_concepts() -> list[str]:
    taxonomy = load_taxonomy()
    return [c for c in taxonomy.occasions["once"].concepts if not taxonomy.concepts[c].sensitive]


def test_an_occasion_in_one_vertical_is_searched_by_its_concepts(demo):
    db, embedder = demo

    outcome = search_products(db, "supermercado", "algo para la once", None, embedder, correct=True)

    assert outcome.result.query_concepts == _once_concepts()
    assert COFFEE in {p.entity_id for p in outcome.products}
    assert {p.concept for p in outcome.products} <= set(_once_concepts())
    assert outcome.corrected_query is None  # una ocasión no se corrige


def test_one_vertical_and_the_grouped_search_rewrite_the_occasion_alike(demo):
    db, embedder = demo

    alone = search_products(db, "supermercado", "algo para la once", None, embedder, k=6)
    grouped = search_grouped(db, "algo para la once", embedder, current="supermercado", limit=6)

    assert alone.result.query == occasion_search("algo para la once")[0]
    assert [p.entity_id for p in grouped.groups[0].products] == [p.entity_id for p in alone.products]


def test_the_vertical_endpoint_shows_the_occasion_products(demo):
    db, embedder = demo

    def conn_override():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    api.app.dependency_overrides[api.get_services] = lambda: Services(
        RappiAgent(embedder, TemplateComposer()), embedder
    )
    try:
        body = TestClient(api.app).get("/search", params={"q": "algo para la once", "vertical": "supermercado"}).json()
    finally:
        api.app.dependency_overrides.clear()

    assert body["corrected_query"] is None
    assert COFFEE in {p["entity_id"] for p in body["products"]}
    assert {p["concept"] for p in body["products"]} <= set(_once_concepts())


def test_a_named_concept_wins_over_the_occasion(demo):
    """«café para la once» pide café: la ocasión solo completa lo que no se nombró (como el agente)."""
    db, embedder = demo

    outcome = search_products(db, "supermercado", "café para la once", None, embedder)

    assert outcome.result.query_concepts == ["cafe"]
    assert {p.concept for p in outcome.products} == {"cafe"}
