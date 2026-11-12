"""Las ofertas de Mochi (`POST /agent/offer`, todos sus momentos) y la búsqueda llevan a tiendas de la ciudad de la demo
(`config.PROFILE_CITY`; en el catálogo de prueba, todas son de Santiago hasta que un test mueve alguna a Viña del Mar).
La búsqueda y Mochi muestran la misma ficha en una tienda de la ciudad, y lo que solo vende otra ciudad (o un plato de
un local de otra ciudad) va después de lo de la ciudad, sin sacarlo (tools.py: `_city_first`); una oferta cambia el
producto de otra ciudad por esa ficha en la tienda más barata de la ciudad o lo saca (engine.py: `_in_demo_city`).
"""

from dataclasses import replace

import pytest

from rappi_ia.agent.grouped_search import search_grouped
from rappi_ia.agent.rappi_agent import Context, RappiAgent
from rappi_ia.agent.tools import Product, search_products
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

    to_other_city(seeded, NORTE)  # en ninguna de la ciudad (como todo el súper): lo sigue mostrando, con la más barata
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


ONLY_CENTRO = {"91126", "91127", "91128", "91201", "91202"}  # el súper de prueba Centro es el único que los vende


def test_search_puts_what_only_another_city_sells_after_the_city_without_leaving_it_out(seeded):
    embedder = HashEmbedder()

    def found():
        return search_products(seeded, "supermercado", "prueba", None, embedder, k=50).products

    before = found()
    only_centro = ONLY_CENTRO & {p.entity_id for p in before}
    assert only_centro and before[-1].entity_id not in only_centro

    to_other_city(seeded, CENTRO)
    after = found()

    assert {p.id for p in after} == {p.id for p in before}  # no saca nada
    away = [p.entity_id in only_centro for p in after]
    assert away == sorted(away)  # todo lo de la ciudad primero
    assert all(p.in_city == (p.entity_id not in only_centro) for p in after)
    # Cada parte, en el orden de la búsqueda
    order = [p.id for p in before]
    for part in ([p for p in after if p.in_city], [p for p in after if not p.in_city]):
        assert [p.id for p in part] == sorted((p.id for p in part), key=order.index)


def test_dishes_of_a_place_of_another_city_go_after_and_a_wider_pool_fills_with_the_city(seeded):
    embedder = HashEmbedder()

    def found(k):
        return search_products(seeded, "restaurantes", "prueba", None, embedder, k=k).products

    first_two = found(2)
    assert first_two
    to_other_city(seeded, *{p.store_id for p in first_two})

    after = found(50)
    away = other_city_stores(seeded)
    flags = [p.store_id in away for p in after]
    assert flags == sorted(flags) and any(flags) and not all(flags)
    # Con k=1 los 2 candidatos de siempre son de otra ciudad: se mira más abajo y sale uno de la ciudad
    (only,) = found(1)
    assert only.in_city and only.store_id not in away


def test_grouped_search_shows_the_city_first(seeded):
    embedder = HashEmbedder()
    before = search_grouped(seeded, "prueba", embedder, None, 6)
    dishes = next(g for g in before.groups if g.vertical == "restaurantes").products
    to_other_city(seeded, dishes[0].store_id)
    away = other_city_stores(seeded)

    grouped = search_grouped(seeded, "prueba", embedder, None, 6)
    for group in grouped.groups:
        flags = [p.store_id in away for p in group.products]
        assert flags == sorted(flags)
    assert next(g for g in grouped.groups if g.vertical == "restaurantes").products[0].store_id not in away


def test_of_two_with_the_same_name_the_search_keeps_the_one_of_the_city(seeded):
    embedder = HashEmbedder()

    def found():
        return search_products(seeded, "restaurantes", "prueba", None, embedder, k=50).products

    first, *rest = found()
    twin = next(p for p in rest if p.store_id != first.store_id)  # otro local, más abajo
    seeded.execute("UPDATE menu_items SET name = %s WHERE item_id = %s", (first.name, int(twin.entity_id)))
    to_other_city(seeded, first.store_id)

    after = found()

    named = [p for p in after if p.name == first.name]
    assert [p.id for p in named] == [twin.id]  # el de otra ciudad con el mismo nombre se va, no el de la ciudad
    assert named[0].in_city


def test_mochi_shows_the_city_first_also_after_ordering_by_price(seeded, monkeypatch):
    """La búsqueda ya pone lo de la ciudad primero, pero "barato" reordena por precio: lo de otra ciudad, más barato,
    no sube a los primeros."""
    from rappi_ia.agent import rappi_agent

    def priced(entity_id, price, in_city):
        return Product(f"cat-{entity_id}", "catalog_item", entity_id, f"Papas fritas {entity_id}", "supermercado",
                       "snacks-salados", price, None, "Tienda", None, store_id=1, in_city=in_city)  # fmt: skip

    found = [priced("1", 3000, True), priced("2", 2500, True), priced("3", 2000, True), priced("4", 900, False)]
    real = rappi_agent.search_products

    def search(conn, vertical, query, concepts, *args, **kwargs):
        outcome = real(conn, vertical, query, concepts, *args, **kwargs)
        return replace(outcome, products=list(found))

    monkeypatch.setattr(rappi_agent, "search_products", search)
    reply = RappiAgent(HashEmbedder()).reply(seeded, "papas fritas baratas", Context(vertical="supermercado"))

    assert [p["entity_id"] for p in reply["products"]] == ["3", "2", "1", "4"]  # por precio, dentro de cada ciudad
