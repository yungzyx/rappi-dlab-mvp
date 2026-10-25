"""El complemento prefiere la marca que la persona compra (`offers/personal.py`, `bought_brands`): entre los productos
del concepto que se ofrece, el de su marca va primero y el porqué la nombra. Sin una marca suya entre esos productos,
la oferta es la de siempre."""

import pytest

from owner_client import OwnerClient
from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.rappi_agent import RappiAgent
from rappi_ia.api import app as api
from rappi_ia.api.services import Services
from rappi_ia.demo import seed
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents
from rappi_ia.events import store as events

BEER, COLA = "94001", "91003"
# Un segundo snack salado en Express: con la cerveza, el complemento tiene dos candidatos del mismo concepto.
OTHER_CHIPS = 92901
OTHER_CHIPS_ROW = (OTHER_CHIPS, "Papas fritas onduladas 150 g (prueba)", "Snacks salados", False,
                   {"conveniencia": (2390, 2390)})  # fmt: skip


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(seed, "_PRODUCTS", [*seed._PRODUCTS, OTHER_CHIPS_ROW])
    seed.seed_demo(db)
    embedder = HashEmbedder()
    embed_search_documents(db, embedder)

    def conn_override():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    api.app.dependency_overrides[api.get_services] = lambda: Services(
        RappiAgent(embedder, TemplateComposer()), embedder
    )
    yield OwnerClient(api.app)
    api.app.dependency_overrides.clear()


def _brand(db, brand_key, name, *products):
    db.execute("INSERT INTO product_brands (brand_key, name) VALUES (%s, %s)", (brand_key, name))
    for product in products:
        db.execute(
            """INSERT INTO item_brands (entity_type, entity_id, brand_key, source)
               VALUES ('catalog_item', %s, %s, 'regla')""",
            (str(product), brand_key),
        )


def _orders(db, user, product, n):
    for i in range(n):
        events.record_order(
            db, user, "s1", f"c-{user}-{product}-{i}", "conveniencia",
            [{"entity_type": "catalog_item", "entity_id": str(product), "unit_price": 1000}],
        )  # fmt: skip


def cart_offer(client, user_id=None):
    body = {"moment": "carrito", "context": {"product": {"entity_type": "catalog_item", "entity_id": BEER}}}
    if user_id:
        body["user_id"] = user_id
    reply = client.post("/agent/offer", json=body)
    assert reply.status_code == 200, reply.text
    return reply.json()


def test_complement_prefers_the_brand_you_buy(client, db):
    anonymous = cart_offer(client)
    ids = [p["entity_id"] for p in anonymous["products"]]
    assert anonymous["reason"]["concept"] == "snacks-salados" and len(ids) == 2
    second = ids[1]  # el que hoy no encabeza la oferta
    _brand(db, "marca-b", "Marca Bé", second)
    _orders(db, "u1", second, 2)

    body = cart_offer(client, "u1")

    assert [p["entity_id"] for p in body["products"]] == [second, ids[0]]
    assert body["reason"]["text"] == "Para completar lo que llevas. Es Marca Bé, la marca que compras."
    assert body["reason"]["basis"] == [{"kind": "marca", "id": "marca-b", "score": 2, "source": "pedidos"}]
    assert body["reason"]["concept"] == "snacks-salados" and body["text"] == anonymous["text"]
    assert cart_offer(client) == anonymous  # sin usuario, la de siempre


def test_complement_names_the_brand_with_most_orders(client, db):
    first, second = (p["entity_id"] for p in cart_offer(client)["products"])
    _brand(db, "marca-a", "Marca A", first)
    _brand(db, "marca-b", "Marca Bé", second)
    _orders(db, "u1", first, 2)
    _orders(db, "u1", second, 3)

    body = cart_offer(client, "u1")

    assert [p["entity_id"] for p in body["products"]] == [second, first]
    assert body["reason"]["text"].endswith(" Es Marca Bé, la marca que compras.")


def test_complement_without_bought_brand_is_unchanged(client, db):
    anonymous = cart_offer(client)
    _brand(db, "marca-c", "Marca Ce", COLA)
    _orders(db, "u1", COLA, 2)  # su marca no está entre los snacks
    second = anonymous["products"][1]["entity_id"]
    _brand(db, "marca-b", "Marca Bé", second)
    _orders(db, "u2", second, 1)  # un solo pedido: todavía no es «su marca»

    assert cart_offer(client, "u1") == anonymous
    assert cart_offer(client, "u2") == anonymous
