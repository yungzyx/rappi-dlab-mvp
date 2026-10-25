"""`/search` sin vertical: busca en todas las verticales que corresponden y agrupa los resultados, con un solo
embedding por consulta. Con `vertical`, la respuesta de siempre."""

import numpy as np
import pytest
from fastapi.testclient import TestClient
from rappi_scraper.storage.search import VERTICALS

from rappi_ia.agent import grouped_search
from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.grouped_search import SCREEN_VERTICALS, search_grouped
from rappi_ia.agent.rappi_agent import RappiAgent
from rappi_ia.agent.verticals import ranked_verticals
from rappi_ia.api import app as api
from rappi_ia.api.services import Services
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents


class CountingEmbedder(HashEmbedder):
    def __init__(self):
        super().__init__()
        self.query_calls = 0

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        self.query_calls += 1
        return super().embed_queries(texts)


class FixedCosineEmbedder(HashEmbedder):
    """Toda consulta queda a coseno `cosine` de todo documento: como e5, donde los cosenos se concentran y aun una
    consulta sin sentido supera el τ de las verticales con τ bajo (Mall y chocolaterías, 0,70)."""

    def __init__(self, cosine: float):
        super().__init__(model_name=f"coseno-fijo-{cosine}")
        self.cosine = cosine

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        out[:, 0] = 1.0
        return out

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        out[:, 0], out[:, 1] = self.cosine, (1 - self.cosine**2) ** 0.5
        return out


def _fixed_cosine(db, cosine: float) -> FixedCosineEmbedder:
    seed_demo(db)
    embedder = FixedCosineEmbedder(cosine)
    embed_search_documents(db, embedder)
    return embedder


@pytest.fixture
def demo(db):
    seed_demo(db)
    embedder = CountingEmbedder()
    embed_search_documents(db, embedder)
    return db, embedder


@pytest.fixture
def client(demo):
    db, embedder = demo

    def conn_override():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    api.app.dependency_overrides[api.get_services] = lambda: Services(
        RappiAgent(embedder, TemplateComposer()), embedder
    )
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def test_grouped_search_puts_the_typical_vertical_first(demo):
    db, embedder = demo
    typical = ranked_verticals(db, ["cerveza"])[0]

    result = search_grouped(db, "cerveza", embedder, current=None, limit=6)

    groups = {group.vertical: group for group in result.groups}
    assert result.groups[0].vertical == typical == "licores"
    assert len(groups) >= 2  # la cerveza también está en el súper, en Express y en Turbo
    assert all(group.products for group in result.groups)
    assert groups["licores"].prototype_vertical == "liquor"
    assert SCREEN_VERTICALS["turbo"] == "turbo" and SCREEN_VERTICALS["conveniencia"] == "express"  # Turbo, su pantalla


def test_grouped_search_embeds_the_query_once(demo):
    db, embedder = demo
    embedder.query_calls = 0

    search_grouped(db, "lata", embedder, current=None, limit=6)

    assert embedder.query_calls == 1  # las 8 verticales comparten el vector


def test_grouped_search_looks_where_the_concept_is_typical_plus_the_current_vertical(demo, monkeypatch):
    db, embedder = demo
    searched = []
    real = grouped_search.search_products

    def spy(conn, vertical, *args, **kwargs):
        searched.append(vertical)
        return real(conn, vertical, *args, **kwargs)

    monkeypatch.setattr(grouped_search, "search_products", spy)
    typical = ranked_verticals(db, ["cerveza"])[:3]

    search_grouped(db, "cerveza", embedder, current="mall", limit=6)
    assert searched == [*typical, "mall"]

    searched.clear()
    search_grouped(db, "cerveza", embedder, current="licores", limit=6)  # ya estaba entre las típicas
    assert searched == typical

    searched.clear()
    search_grouped(db, "lata", embedder, current="mall", limit=6)  # sin concepto ni ocasión: todas
    assert sorted(searched) == sorted(VERTICALS)


def test_grouped_search_puts_the_current_vertical_first_when_it_has_products(demo):
    db, embedder = demo
    base = [g.vertical for g in search_grouped(db, "cerveza", embedder, current=None, limit=6).groups]
    assert base[0] == "licores" and len(base) >= 3
    current = base[-1]  # una vertical con cerveza que no es la más típica

    led = [g.vertical for g in search_grouped(db, "cerveza", embedder, current=current, limit=6).groups]

    assert led[0] == current
    assert led[1:] == [v for v in base if v != current]  # el resto conserva su orden


def test_grouped_search_current_vertical_leads_also_without_a_concept(demo):
    db, embedder = demo
    base = [g.vertical for g in search_grouped(db, "lata", embedder, current=None, limit=6).groups]
    assert len(base) >= 2
    current = base[-1]

    led = [g.vertical for g in search_grouped(db, "lata", embedder, current=current, limit=6).groups]

    assert led[0] == current
    assert sorted(led) == sorted(base)


def test_grouped_search_current_vertical_without_products_does_not_appear(demo):
    db, embedder = demo
    base = [g.vertical for g in search_grouped(db, "cerveza", embedder, current=None, limit=6).groups]
    without = 0
    for current in (v for v in VERTICALS if v not in base):
        led = [g.vertical for g in search_grouped(db, "cerveza", embedder, current=current, limit=6).groups]
        if current not in led:  # sin cerveza: no aparece y nada se mueve
            without += 1
            assert led == base
        else:  # con cerveza (Turbo, que no es típica): encabeza
            assert led[0] == current
    assert without >= 1


def test_grouped_search_limit_is_per_group(demo):
    db, embedder = demo

    result = search_grouped(db, "cerveza", embedder, current=None, limit=1)

    assert result.groups and all(len(group.products) == 1 for group in result.groups)


def test_grouped_search_unmet_only_when_no_group_has_products(demo):
    db, embedder = demo

    found = search_grouped(db, "cerveza", embedder, current="mall", limit=6)  # el mall no trae cerveza, el resto sí
    nothing = search_grouped(db, "xyzzy", embedder, current=None, limit=6)

    assert found.groups and found.unmet is False and found.unmet_reason is None
    assert nothing.groups == [] and nothing.unmet is True and nothing.unmet_reason


def test_grouped_search_returns_products_only_and_does_not_apply_offer_guards(demo):
    db, embedder = demo

    result = search_grouped(db, "cerveza", embedder, current=None, limit=6)

    products = [p for group in result.groups for p in group.products]
    assert {p.entity_type for p in products} <= {"catalog_item", "menu_item"}  # nunca tiendas
    assert any(p.age_restricted for p in products)  # es lo que la persona pidió: las guardias son de las ofertas


def test_grouped_endpoint_shape(client):
    body = client.get("/search", params={"q": "cerveza"}).json()

    assert set(body) == {"query", "groups", "unmet", "unmet_reason", "corrected_query"}
    assert body["query"] == "cerveza" and body["unmet"] is False
    first = body["groups"][0]
    assert set(first) == {"vertical", "prototype_vertical", "products"}
    assert (first["vertical"], first["prototype_vertical"]) == ("licores", "liquor")
    assert len(first["products"]) <= 6  # el límite por grupo es 6 por defecto
    limited = client.get("/search", params={"q": "cerveza", "current": "retail", "limit": 2}).json()
    assert all(len(group["products"]) <= 2 for group in limited["groups"])
    nothing = client.get("/search", params={"q": "xyzzy"}).json()
    assert (nothing["groups"], nothing["unmet"]) == ([], True) and nothing["unmet_reason"]


def test_vertical_search_is_unchanged(client):
    body = client.get("/search", params={"q": "cerveza", "vertical": "licores"}).json()

    assert set(body) == {"vertical", "products", "unmet", "unmet_reason", "corrected_query"}
    assert body["vertical"] == "licores" and body["products"] and body["unmet"] is False
    assert client.get("/search", params={"q": "cerveza", "vertical": "liquor"}).json() == body  # id del prototipo
    one = client.get("/search", params={"q": "cerveza", "vertical": "licores", "limit": 1}).json()
    assert len(one["products"]) == 1
    assert client.get("/search", params={"q": "cerveza", "vertical": "aerolineas"}).status_code == 400
    assert client.get("/search", params={"q": "cerveza", "vertical": "pet"}).status_code == 400
    assert client.get("/search", params={"q": "cerveza", "mode": "otro"}).status_code == 400


def test_grouped_search_without_a_concept_is_unmet_for_nonsense_although_low_tau_verticals_pass(db):
    embedder = _fixed_cosine(db, 0.8)  # sobre el τ del Mall, las chocolaterías y Turbo; bajo UNNAMED_TAU

    for query in ("xyzzy", "asdfgh"):
        result = search_grouped(db, query, embedder, current=None, limit=6)

        assert (result.groups, result.unmet) == ([], True), query
        assert result.unmet_reason


def test_grouped_search_without_a_concept_keeps_close_neighbours_over_the_all_verticals_cut(db):
    embedder = _fixed_cosine(db, 0.95)

    result = search_grouped(db, "xyzzy", embedder, current=None, limit=6)

    assert result.groups and result.unmet is False  # el corte es más estricto, no «siempre sin resultado»


def test_grouped_search_with_an_exact_word_in_one_vertical_shows_only_that_group(db):
    embedder = _fixed_cosine(db, 0.8)
    assert grouped_search.detect_concepts("ultradelgadas") == []

    result = search_grouped(db, "ultradelgadas", embedder, current="mall", limit=6)

    assert [group.vertical for group in result.groups] == ["farmacia"]  # solo las toallas; ni la pantalla actual
    assert "Toallas higiénicas ultradelgadas x 10 (prueba)" in [p.name for p in result.groups[0].products]


def test_grouped_search_for_an_occasion_goes_to_the_verticals_of_its_concepts(demo, monkeypatch):
    db, embedder = demo
    carrete = load_taxonomy().occasions["carrete"]
    assert grouped_search.detect_concepts("algo para el carrete") == []
    searched = []
    real = grouped_search.search_products

    def spy(conn, vertical, *args, **kwargs):
        searched.append(vertical)
        return real(conn, vertical, *args, **kwargs)

    monkeypatch.setattr(grouped_search, "search_products", spy)

    result = search_grouped(db, "algo para el carrete", embedder, current=None, limit=6)

    assert searched == ranked_verticals(db, list(carrete.concepts))[:3]
    assert result.groups and result.unmet is False
    assert {p.concept for group in result.groups for p in group.products} <= set(carrete.concepts)
    assert embedder.query_calls == 1


def test_grouped_search_never_shows_a_sensitive_product_that_was_not_named(demo):
    db, embedder = demo
    sensitive = {c.id for c in load_taxonomy().concepts.values() if c.sensitive}
    reached = 0
    # Palabras de productos sensibles del seed (paracetamol, antiácido, gel íntimo) que no nombran su concepto.
    for query in ("comprimidos", "efervescente", "hidratante", "prueba"):
        assert grouped_search.detect_concepts(query) == [], query
        result = search_grouped(db, query, embedder, current="farmacia", limit=50)

        shown = [p for group in result.groups for p in group.products]
        assert not [p.name for p in shown if p.concept in sensitive], query
        reached += bool(shown)
    assert reached >= 3  # las búsquedas traen otros productos: el filtro es de lo sensible, no de todo
