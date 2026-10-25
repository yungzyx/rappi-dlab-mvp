"""Un kit no ofrece productos de nombre pelado («Café», «POLLO»): no dicen qué producto es. Se salta al siguiente
candidato del concepto."""

import pytest
from fastapi.testclient import TestClient

from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.rappi_agent import RappiAgent
from rappi_ia.api import app as api
from rappi_ia.api.services import Services
from rappi_ia.demo import seed
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents

# Tres productos que el kit elegiría primero (la búsqueda vectorial los pone delante del café de prueba): el nombre
# mismo del concepto, una sola palabra en mayúsculas y una palabra con artículo. Con los 3 primeros candidatos pelados,
# el kit tiene que mirar más allá.
BARE_COFFEE = 91991
BARE_COFFEE_ROWS = [
    (BARE_COFFEE, "Café", "Café", False, {"supermercado": (1990, 1990)}),
    (BARE_COFFEE + 1, "CAFE", "Café", False, {"supermercado": (1990, 1990)}),
    (BARE_COFFEE + 2, "El Café", "Café", False, {"supermercado": (1990, 1990)}),
]


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(seed, "_PRODUCTS", [*seed._PRODUCTS, *BARE_COFFEE_ROWS])
    seed.seed_demo(db)
    embedder = HashEmbedder()
    embed_search_documents(db, embedder)

    def conn_override():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    api.app.dependency_overrides[api.get_services] = lambda: Services(
        RappiAgent(embedder, TemplateComposer()), embedder
    )
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def test_kit_skips_products_named_with_a_single_word(client):
    reply = client.post("/agent/offer", json={"moment": "plan", "context": {"occasion": "once"}})

    assert reply.status_code == 200, reply.text
    products = reply.json()["products"]
    coffee = next(p for p in products if p["concept"] == "cafe")
    assert coffee["name"] == "Café molido tostado 250 g (prueba)"
    assert not {str(BARE_COFFEE + i) for i in range(3)} & {p["entity_id"] for p in products}
    assert all(len(p["name"].split()) > 1 for p in products)
