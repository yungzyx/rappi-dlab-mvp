"""Las ofertas de Mochi (`POST /agent/offer`, todos sus momentos) y la búsqueda llevan a tiendas de la ciudad de la demo
(`config.PROFILE_CITY`; en el catálogo de prueba, todas son de Santiago hasta que un test mueve alguna a Viña del Mar).
La búsqueda muestra la misma ficha en una tienda de la ciudad sin cambiar qué sale ni en qué orden; una oferta cambia
el producto de otra ciudad por esa ficha en la tienda más barata de la ciudad o lo saca (engine.py: `_in_demo_city`).
"""

import pytest

from rappi_ia.agent.tools import search_products
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents
from rappi_ia.offers import engine
from rappi_ia.offers.engine import Offer, PlanOffer, make_offer

COLA = "91003"  # súper: $1.790 en el Centro (9101) y $1.850 en el Norte (9102)
CENTRO, NORTE = 9101, 9102
PIZZA_DISH = "98001"


@pytest.fixture
def seeded(db):
    seed_demo(db)
    embed_search_documents(db, HashEmbedder())
    return db


def to_other_city(conn, *store_ids: int) -> None:
    conn.execute("UPDATE stores SET city = 'Viña del Mar' WHERE store_id = ANY(%s)", (list(store_ids),))


def other_city_stores(conn) -> set[int]:
    return {s for (s,) in conn.execute("SELECT store_id FROM stores WHERE city = 'Viña del Mar'")}


def card(conn, entity_id: str, vertical: str = "supermercado") -> dict:
    """La tarjeta de un producto como la arma una oferta, con su precio en la vertical."""
    return engine._priced_in_vertical(conn, vertical, [entity_id])[entity_id].to_dict()


def test_search_shows_the_same_product_from_a_store_of_the_demo_city_without_moving_the_order(seeded):
    embedder = HashEmbedder()

    def found():
        return search_products(seeded, "supermercado", "gaseosa cola", None, embedder).products

    before = found()
    cola = next(p for p in before if p.entity_id == COLA)
    assert (cola.store_id, cola.price_value) == (CENTRO, 1790)  # la más barata

    to_other_city(seeded, CENTRO)
    after = found()
    assert [p.id for p in after] == [p.id for p in before]  # qué sale y en qué orden no cambia
    cola = next(p for p in after if p.entity_id == COLA)
    assert (cola.store, cola.store_id, cola.price_value) == ("Supermercado de prueba Norte", NORTE, 1850)

    to_other_city(seeded, NORTE)  # en ninguna de la ciudad: la búsqueda lo sigue mostrando, con la más barata
    last = found()
    assert [p.id for p in last] == [p.id for p in before]
    cola = next(p for p in last if p.entity_id == COLA)
    assert (cola.store_id, cola.price_value) == (CENTRO, 1790)
    # Lo que Mochi propone solo (una oferta) no lo trae: no ocupa el lugar de otro producto
    offered = search_products(seeded, "supermercado", "gaseosa cola", None, embedder, offer=True).products
    assert COLA not in {p.entity_id for p in offered}


def test_an_offer_product_from_another_city_moves_to_the_cheapest_store_of_the_city_or_leaves(seeded):
    to_other_city(seeded, CENTRO, 9802)
    products = [card(seeded, COLA), card(seeded, "91004")]
    assert [p["store_id"] for p in products] == [CENTRO, CENTRO]  # sin la ciudad: la más barata de todas
    dish = engine._priced_in_vertical(seeded, "restaurantes", [PIZZA_DISH])[PIZZA_DISH].to_dict()
    dish = {**dish, "store_id": 9802}  # un plato de un local de otra ciudad: no hay otra ficha, sale
    no_page = {**card(seeded, "91002"), "store_id": None}  # sin tienda que se abra: queda igual

    kept = engine._city_products(seeded, [*products, dish, no_page])

    assert [(p["entity_id"], p["store_id"], p["price"]) for p in kept] == [
        (COLA, NORTE, "$1.850"),
        ("91004", NORTE, "$4.190"),
        ("91002", None, no_page["price"]),
    ]
    assert kept[0]["store"] == "Supermercado de prueba Norte" and kept[0]["name"] == products[0]["name"]
    assert engine._city_products(seeded, products, avoid=frozenset({NORTE})) == []  # nunca una tienda en pausa


def test_a_repeat_offer_opens_the_store_its_product_moved_to(seeded):
    product = card(seeded, COLA)
    action = {"label": engine.REPEAT_ACTION, "route": ["super"], "store_id": product["store_id"]}
    found = Offer("recompra", "¿Repetimos gaseosa?", [product], "supermercado", {}, [action])
    to_other_city(seeded, CENTRO)

    moved = engine._in_demo_city(seeded, found)

    assert moved.products[0]["store_id"] == NORTE and moved.actions[0]["store_id"] == NORTE
    to_other_city(seeded, NORTE)
    assert engine._in_demo_city(seeded, found) is None  # sin tienda en la ciudad no queda nada que ofrecer: 204


@pytest.mark.parametrize(
    ("moment", "context"),
    [
        ("carrito", {"product": {"entity_type": "catalog_item", "entity_id": "91001"}}),
        ("checkout", {"cart": [{"entity_type": "catalog_item", "entity_id": "91001"}]}),
        ("vertical_por_probar", {}),
        ("ontop", {"vertical": "restaurantes", "items": []}),
        ("plan", {"occasion": "once"}),
    ],
)
def test_every_offer_moment_only_proposes_stores_of_the_demo_city(seeded, moment, context):
    embedder = HashEmbedder()
    first = make_offer(seeded, embedder, moment, context)
    assert first is not None and first.products
    to_other_city(seeded, *{p["store_id"] for p in first.products if p["store_id"] is not None})

    again = make_offer(seeded, embedder, moment, context)

    away = other_city_stores(seeded)
    assert again is None or all(p["store_id"] not in away for p in again.products)
    if isinstance(again, PlanOffer):
        assert {s["store_id"] for s in again.stores} <= {p["store_id"] for p in again.products}


def test_a_kit_that_loses_a_product_says_only_what_it_brings(seeded):
    kit = make_offer(seeded, HashEmbedder(), "plan", {"occasion": "carrete"})
    licores = {p["store_id"] for p in kit.products if p["vertical"] == "licores"}
    assert licores and "cerveza" in kit.text
    to_other_city(seeded, 9401, 9402)  # las dos botillerías: lo de Licores no tiene tienda en la ciudad

    again = make_offer(seeded, HashEmbedder(), "plan", {"occasion": "carrete"})

    assert all(p["vertical"] != "licores" for p in again.products)
    assert again.text == engine._plan_text(engine.load_taxonomy().occasions["carrete"], again.products)
    assert again.vertical == again.products[0]["vertical"]
    assert [s["store_id"] for s in again.stores] == list(dict.fromkeys(p["store_id"] for p in again.products))
