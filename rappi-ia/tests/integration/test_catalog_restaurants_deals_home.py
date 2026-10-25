"""Restaurantes, ofertas y Home del catálogo: tarjetas, menú, bajas de precio reales y listas de la Home.

Todo sobre el catálogo de `seed_demo`. Los ocho restaurantes (9801 a 9808), con su nota, tiempo de entrega y envío:

| id   | nota | tiempo | envío  | notas del caso                                          |
| 9801 | 4,6  | 25 min | $1.490 | sin área en el nombre; populares 98002 y 98004          |
| 9802 | -    | 35 min | $0     | dos cocinas; sin populares; el primer plato no tiene foto |
| 9803 | 4,2  | 15 min | $990   | «X - Área»; popular 98010                               |
| 9804 | 4,8  | 40 min | $2.490 |                                                         |
| 9805 | 3,9  | -      | $1.990 | tiempo desconocido; un plato sin precio                 |
| 9806 | 4,6  | 20 min | $690   | misma nota que 9801 con menos opiniones                 |
| 9807 | -    | 30 min | $0     | sin ninguna foto                                        |
| 9808 | 4,9  | 10 min | $0     | ningún plato con precio: no se lista                    |

Las bajas de precio salen de comparar la oferta vigente con la corrida anterior (ver `_PREVIOUS` en el seed).

Tres tiendas con ofertas no se empujan (ni «Cerca de ti» ni las ofertas sin vertical): el sex shop 9611 y el smoking
shop 9612 del mall, y la farmacia 9111 que Rappi lista entre los súper. Cada una vende un producto corriente y uno de
concepto sensible, los dos con baja de precio (ver `_NOT_PUSHED_STORES` en el seed).
"""

import math
import types
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from test_query_budget import CountingConnection

from rappi_ia import config
from rappi_ia.agent.tools import _with_prices, clp
from rappi_ia.api import app as api
from rappi_ia.catalog import cache
from rappi_ia.catalog.deals import deals
from rappi_ia.catalog.home import home
from rappi_ia.catalog.restaurants import restaurant_menu, restaurants
from rappi_ia.catalog.stores import product_detail, vertical_stores
from rappi_ia.concepts.taxonomy import sensitive_concepts
from rappi_ia.demo.seed import DEMO_VERTICALS, seed_demo

PIZZERIA, SUSHI, SANDWICHES, GRILL, CAFE, PASTRY, CEVICHE, ICE_CREAM = range(9801, 9809)
LISTED = [PIZZERIA, SUSHI, SANDWICHES, GRILL, CAFE, PASTRY, CEVICHE]
OLD_BRANCH = 9103  # del mismo formato que 9101 pero sin ofertas vigentes
SEX_SHOP, SMOKING_SHOP, PHARMACY_IN_SUPER = 9611, 9612, 9111
NOT_PUSHED_STORES = {SEX_SHOP, SMOKING_SHOP, PHARMACY_IN_SUPER}
PLAIN_DEALS = ["96101", "96201", "91401"]  # el producto corriente de cada una, con baja de precio
SENSITIVE_DEALS = ["96102", "96202", "91402", "95001"]  # gel íntimo, papelillos, antiácido y paracetamol (farmacia)
DISH_PHOTOS = "https://imagenes.prueba.invalid/platos/"
CARD_KEYS = {"id", "name", "area", "cover", "rating", "eta", "fee", "cuisines"}
STORE_KEYS = {"id", "name", "logo", "eta", "products", "vertical"}
PRODUCT_KEYS = {
    "id", "entity_type", "entity_id", "name", "vertical", "concept", "price", "price_value", "before", "discount",
    "store", "img", "age_restricted", "store_id", "presentation",
}  # fmt: skip
RESTAURANT_NOT_FOUND = "Este restaurante no está en el catálogo"
VERTICAL_NOT_FOUND = "Esta vertical no está en el catálogo"


@pytest.fixture
def seeded(db):
    seed_demo(db)
    return db


@pytest.fixture
def client(seeded):
    def conn_override():
        yield seeded

    api.app.dependency_overrides[api.get_conn] = conn_override
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def ids(cards: list[dict]) -> list[int]:
    return [card["id"] for card in cards]


def ids_of(found: list[dict]) -> list[str]:
    return [d["entity_id"] for d in found]


def deal_summary(found: list[dict]) -> list[tuple]:
    return [(d["entity_id"], d["store_id"], d["price"], d["before"], d["discount"]) for d in found]


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distancia sobre la esfera, calculada aparte de la consulta."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


# --- Restaurantes ---------------------------------------------------------------------------------------------------


def test_restaurant_cover_is_a_dish_photo_and_name_splits_area(seeded):
    cards = {card["id"]: card for card in restaurants(seeded, limit=100)}

    assert set(cards) == set(LISTED)
    assert all(set(card) == CARD_KEYS for card in cards.values())
    sandwiches = cards[SANDWICHES]
    assert (sandwiches["name"], sandwiches["area"]) == ("Sándwiches de prueba", "Providencia")
    assert (cards[GRILL]["name"], cards[GRILL]["area"]) == ("Parrilla de prueba", "Ñuñoa")
    # Sin « - » en el nombre no hay área.
    assert (cards[PIZZERIA]["name"], cards[PIZZERIA]["area"]) == ("Pizzería de prueba Centro", "")
    # La portada es la foto de un plato popular aunque otro plato anterior tenga foto (98001 la tiene)...
    assert cards[PIZZERIA]["cover"] == f"{DISH_PHOTOS}98002.png"
    assert cards[SANDWICHES]["cover"] == f"{DISH_PHOTOS}98010.png"
    # ...y sin populares, la del primer plato con foto (98005 no la tiene)...
    assert cards[SUSHI]["cover"] == f"{DISH_PHOTOS}98006.png"
    assert cards[GRILL]["cover"] == f"{DISH_PHOTOS}98012.png"
    # ...y sin ninguna foto, la tarjeta sigue ahí.
    assert cards[CEVICHE]["cover"] is None


def test_restaurant_card_has_rating_eta_fee_and_cuisines(seeded):
    cards = {card["id"]: card for card in restaurants(seeded, limit=100)}

    assert cards[PIZZERIA]["rating"] == 4.6 and isinstance(cards[PIZZERIA]["rating"], float)
    assert (cards[PIZZERIA]["eta"], cards[PIZZERIA]["fee"]) == ("25 min", "$1.490")
    assert cards[PIZZERIA]["cuisines"] == ["Pizzas"]
    assert cards[SUSHI]["cuisines"] == ["Hamburguesa", "Sushi"]  # en orden alfabético
    # Sin nota, el campo queda vacío; con envío gratis, es «$0»; sin tiempo de entrega, tampoco hay.
    assert cards[SUSHI]["rating"] is None and cards[SUSHI]["fee"] == "$0"
    assert cards[CAFE]["eta"] is None and cards[CAFE]["fee"] == "$1.990"


def test_name_splits_at_the_last_separator(seeded):
    seeded.execute("UPDATE stores SET name = 'Local - Mall - Costanera' WHERE store_id = %s", (PIZZERIA,))

    card = next(c for c in restaurants(seeded, limit=100) if c["id"] == PIZZERIA)

    assert (card["name"], card["area"]) == ("Local - Mall", "Costanera")


def test_restaurants_sort_by_rating_eta_or_fee(seeded):
    # Mejor nota primero; con la misma nota, más opiniones (9801 y 9806 tienen 4,6); sin nota al final.
    assert ids(restaurants(seeded)) == [GRILL, PIZZERIA, PASTRY, SANDWICHES, CAFE, SUSHI, CEVICHE]
    # Menos tiempo primero; el desconocido (9805) al final, no como el más rápido.
    assert ids(restaurants(seeded, sort="eta")) == [SANDWICHES, PASTRY, PIZZERIA, CEVICHE, SUSHI, GRILL, CAFE]
    # Menor envío primero; con el mismo envío ($0 en 9802 y 9807), mejor nota y luego el id.
    assert ids(restaurants(seeded, sort="fee")) == [SUSHI, CEVICHE, PASTRY, SANDWICHES, PIZZERIA, CAFE, GRILL]


def test_restaurants_filter_by_cuisine_and_limit(seeded):
    assert ids(restaurants(seeded, cuisine="Sushi")) == [SUSHI]
    assert ids(restaurants(seeded, cuisine="Pastelería y Postres")) == [PASTRY]  # la heladería no tiene precios
    assert restaurants(seeded, cuisine="Cocina que no existe") == []
    assert ids(restaurants(seeded, sort="fee", limit=2)) == [SUSHI, CEVICHE]
    assert restaurants(seeded, limit=0) == []


def test_restaurants_come_from_the_catalog_cache_until_a_new_run(seeded, monkeypatch):
    """La lista recorre todos los platos: se guarda por orden y largo hasta una corrida nueva (o su TTL). Con cocina
    (texto libre) se consulta siempre."""
    now = [1000.0]
    monkeypatch.setattr(cache, "_now", lambda: now[0])
    counting = CountingConnection(seeded)
    first = restaurants(counting, sort="eta", limit=5)

    counting.statements.clear()
    assert restaurants(counting, sort="eta", limit=5) == first
    assert not any("menu_items" in s for s in counting.statements)  # de la caché
    assert restaurants(counting, sort="fee", limit=5) != first  # cada orden es su propia entrada
    assert ids(restaurants(counting, sort="eta", limit=2)) == ids(first)[:2]  # y cada largo
    counting.statements.clear()
    restaurants(counting, cuisine="Sushi")
    restaurants(counting, cuisine="Sushi")
    assert sum("menu_items" in s for s in counting.statements) == 2

    seeded.execute("UPDATE restaurant_details SET eta = '5 min' WHERE store_id = %s", (CAFE,))
    assert restaurants(counting, sort="eta", limit=5) == first  # sin corrida nueva sigue la guardada
    seeded.execute("INSERT INTO scrape_runs (kind, status) VALUES ('restaurants', 'done')")
    now[0] += cache.VERSION_TTL_S + 1  # la versión se vuelve a preguntar

    assert ids(restaurants(counting, sort="eta", limit=5))[0] == CAFE


def test_only_restaurants_with_a_priced_dish_are_listed(seeded):
    # 9808 es la mejor nota, la más rápida y la de envío gratis, pero sus dos platos no tienen precio real
    # (uno sin precio y otro de $5, bajo MIN_PRICE).
    for sort in ("rating", "eta", "fee"):
        assert ICE_CREAM not in ids(restaurants(seeded, sort=sort, limit=100))
    assert restaurant_menu(seeded, ICE_CREAM) is None

    run_id = seeded.execute("SELECT max(run_id) FROM scrape_runs").fetchone()[0]
    seeded.execute("UPDATE menu_price_snapshots SET price = 2500 WHERE item_id = 98022 AND run_id = %s", (run_id,))
    cache.clear()  # sin corrida nueva: como si la caché del catálogo hubiera vencido

    assert ICE_CREAM in ids(restaurants(seeded, limit=100))
    assert restaurant_menu(seeded, ICE_CREAM) is not None


def test_a_restaurant_uses_the_last_price_of_its_dishes(seeded):
    # Una corrida nueva sin precio para los dos platos con precio de 9805 lo deja sin precios; uno nuevo y válido en
    # su plato sin precio lo lista de nuevo: cuenta el último precio de cada plato.
    new_run = seeded.execute(
        "INSERT INTO scrape_runs (kind, status) VALUES ('restaurants', 'done') RETURNING run_id"
    ).fetchone()[0]
    for item_id in (98015, 98016):
        seeded.execute(
            "INSERT INTO menu_price_snapshots (run_id, item_id, price, is_available) VALUES (%s, %s, NULL, true)",
            (new_run, item_id),
        )

    assert CAFE not in ids(restaurants(seeded, limit=100))

    seeded.execute(
        "INSERT INTO menu_price_snapshots (run_id, item_id, price, is_available) VALUES (%s, 98017, 5990, true)",
        (new_run,),
    )
    cache.clear()  # la misma corrida: como si la caché del catálogo hubiera vencido

    assert CAFE in ids(restaurants(seeded, limit=100))


def test_a_store_that_is_not_a_restaurant_is_never_listed(seeded):
    seeded.execute("DELETE FROM store_verticals WHERE store_id = %s", (PIZZERIA,))
    cache.clear()  # sin corrida nueva: como si la caché del catálogo hubiera vencido

    assert PIZZERIA not in ids(restaurants(seeded, limit=100))
    assert restaurant_menu(seeded, PIZZERIA) is None


# --- Menú -----------------------------------------------------------------------------------------------------------


def test_menu_lists_popular_first_then_sections_in_order(seeded):
    menu = restaurant_menu(seeded, PIZZERIA)

    assert set(menu) == {"restaurant", "sections"}
    assert menu["restaurant"] == next(card for card in restaurants(seeded, limit=100) if card["id"] == PIZZERIA)
    assert [section["name"] for section in menu["sections"]] == ["Lo más pedido", "Pizzas", "Bebidas", "Postres"]
    by_section = {s["name"]: [item["entity_id"] for item in s["items"]] for s in menu["sections"]}
    # Los populares (98002 y 98004) abren el menú y siguen en su sección, que queda completa.
    assert by_section == {
        "Lo más pedido": ["98002", "98004"],
        "Pizzas": ["98001", "98002"],
        "Bebidas": ["98003"],
        "Postres": ["98004"],
    }


def test_menu_dishes_have_the_product_shape_with_the_restaurant_as_store(seeded):
    menu = restaurant_menu(seeded, PIZZERIA)

    pepperoni = menu["sections"][1]["items"][0]
    assert set(pepperoni) == PRODUCT_KEYS
    assert pepperoni["id"] == "menu-98001" and pepperoni["entity_type"] == "menu_item"
    assert (pepperoni["price"], pepperoni["price_value"]) == ("$12.990", 12990.0)
    assert (pepperoni["before"], pepperoni["discount"]) == (None, None)
    assert (pepperoni["store"], pepperoni["store_id"], pepperoni["vertical"]) == (
        "Pizzería de prueba Centro",
        PIZZERIA,
        "restaurantes",
    )
    assert pepperoni["img"] == f"{DISH_PHOTOS}98001.png" and pepperoni["age_restricted"] is False
    soda = menu["sections"][2]["items"][0]
    assert soda["img"] is None  # sin foto


def test_menu_follows_the_position_of_the_sections(seeded):
    seeded.execute("UPDATE menu_sections SET position = 10 - position WHERE store_id = %s", (PIZZERIA,))

    names = [section["name"] for section in restaurant_menu(seeded, PIZZERIA)["sections"]]

    assert names == ["Lo más pedido", "Postres", "Bebidas", "Pizzas"]


def test_menu_without_popular_dishes_has_no_most_ordered_section(seeded):
    sections = restaurant_menu(seeded, SUSHI)["sections"]

    assert [section["name"] for section in sections] == ["Rolls", "Hamburguesas", "Bebidas"]


def test_menu_hides_dishes_without_a_price_and_the_sections_they_empty(seeded):
    cafe = restaurant_menu(seeded, CAFE)

    # 98017 no tiene precio.
    assert [(s["name"], [i["entity_id"] for i in s["items"]]) for s in cafe["sections"]] == [
        ("Lo más pedido", ["98015"]),
        ("Desayunos", ["98015", "98016"]),
    ]

    seeded.execute("UPDATE menu_price_snapshots SET price = NULL WHERE item_id = 98003")
    names = [s["name"] for s in restaurant_menu(seeded, PIZZERIA)["sections"]]
    assert names == ["Lo más pedido", "Pizzas", "Postres"]  # la sección que se quedó sin platos no sale


def _add_best_sellers(conn, store_id: int, items: dict[int, list[int]]) -> None:
    """Como guarda el scraper un menú con «Más vendidos» (migración 040): la sección va primera y cada plato repetido
    queda una vez, con su sección propia en `section_id` y las demás en `extra_section_ids`."""
    conn.execute("UPDATE menu_sections SET position = position + 1 WHERE store_id = %s", (store_id,))
    conn.execute(
        "INSERT INTO menu_sections (store_id, section_id, name, position) VALUES (%s, 99, 'Más vendidos', 0)",
        (store_id,),
    )
    for item_id, extra in items.items():
        conn.execute("UPDATE menu_items SET extra_section_ids = %s WHERE item_id = %s", (extra, item_id))


def test_menu_lists_a_repeated_dish_in_every_section_it_is_in(seeded):
    # 98003 (bebida) y 98002 (pizza, popular) también están en «Más vendidos».
    _add_best_sellers(seeded, PIZZERIA, {98003: [99], 98002: [99]})

    menu = restaurant_menu(seeded, PIZZERIA)
    sections = [(s["name"], [i["entity_id"] for i in s["items"]]) for s in menu["sections"]]

    assert sections == [
        ("Lo más pedido", ["98002", "98004"]),  # el popular, una sola vez aunque esté en dos secciones
        ("Más vendidos", ["98002", "98003"]),
        ("Pizzas", ["98001", "98002"]),
        ("Bebidas", ["98003"]),
        ("Postres", ["98004"]),
    ]


def test_menu_never_repeats_a_dish_within_a_section(seeded):
    # Un arreglo con repetidos, con la sección propia del plato (Pizzas es la 1) y con una sección que ya no existe.
    _add_best_sellers(seeded, PIZZERIA, {98001: [99, 99, 1, 12345]})

    menu = restaurant_menu(seeded, PIZZERIA)
    by_section = {s["name"]: [i["entity_id"] for i in s["items"]] for s in menu["sections"]}

    assert by_section["Más vendidos"] == ["98001"]
    assert by_section["Pizzas"] == ["98001", "98002"]
    assert len(by_section) == 5  # la sección que no existe no suma nada


def test_best_sellers_without_a_priced_dish_do_not_show(seeded):
    _add_best_sellers(seeded, PIZZERIA, {98003: [99]})
    seeded.execute("UPDATE menu_price_snapshots SET price = NULL WHERE item_id = 98003")

    names = [s["name"] for s in restaurant_menu(seeded, PIZZERIA)["sections"]]

    assert names == ["Lo más pedido", "Pizzas", "Postres"]


def test_menu_of_something_that_is_not_a_listed_restaurant_is_none(seeded):
    for store_id in (999_999, 9101, ICE_CREAM, -1, 2**63):
        assert restaurant_menu(seeded, store_id) is None, store_id


# --- Ofertas --------------------------------------------------------------------------------------------------------


def test_deals_only_include_real_price_drops_with_before_and_discount(seeded):
    found = deals(seeded)

    assert deal_summary(found) == [
        ("91002", 9102, "$1.350", "$1.790", "-25%"),  # bajó en las dos tiendas: sale la de mayor baja, entera
        ("92002", 9201, "$1.490", "$1.890", "-21%"),
        ("92004", 9201, "$1.590", "$1.990", "-20%"),  # tiene precio de lista ($1.990) y bajó de $1.790: vale la lista
        ("93001", 9301, "$3.990", "$4.990", "-20%"),
        ("94001", 9401, "$1.290", "$1.590", "-19%"),
        ("97001", 9701, "$2.490", "$2.990", "-17%"),
        ("96001", 9601, "$24.990", "$29.990", "-17%"),
        ("91004", 9101, "$3.990", "$4.590", "-13%"),
        ("91003", 9101, "$1.790", "$1.990", "-10%"),
    ]
    # No entran: las papas (91001: subieron), el jugo (91005: igual), la mermelada (91202: bajó, pero agotada), el atún
    # (91201: su precio es de una corrida anterior) ni el paracetamol (95001: farmacia).
    assert not {"91001", "91005", "91202", "91201", "95001"} & {d["entity_id"] for d in found}
    assert all(set(d) == PRODUCT_KEYS and d["entity_type"] == "catalog_item" for d in found)


def test_deals_take_price_before_store_and_vertical_from_one_offer(seeded):
    found = {d["entity_id"]: d for d in deals(seeded)}

    galletas = found["91002"]  # en el Centro cuestan menos ($1.290), pero la baja es la de Norte
    assert (galletas["store"], galletas["store_id"], galletas["vertical"]) == (
        "Supermercado de prueba Norte",
        9102,
        "supermercado",
    )
    assert (galletas["price_value"], galletas["before"]) == (1350.0, "$1.790")
    cerveza = found["94001"]  # en Botillería Oriente (9402) cuesta $1.190, pero solo la del Centro bajó
    assert (cerveza["store"], cerveza["store_id"], cerveza["vertical"]) == (
        "Botillería de prueba Centro",
        9401,
        "licores",
    )
    assert cerveza["age_restricted"] is True  # la marca +18 se mantiene
    # Cada oferta es el último precio de su tienda, y lo que dice "antes" es mayor.
    for deal in found.values():
        latest = seeded.execute(
            "SELECT price FROM price_snapshots WHERE store_id = %s AND sku = %s ORDER BY scraped_at DESC LIMIT 1",
            (deal["store_id"], f"sku-{deal['entity_id']}"),
        ).fetchone()[0]
        assert float(latest) == deal["price_value"]
        assert deal["discount"] and deal["before"]


def test_deals_by_vertical(seeded):
    assert deal_summary(deals(seeded, "licores")) == [("94001", 9401, "$1.290", "$1.590", "-19%")]
    assert deal_summary(deals(seeded, "supermercado")) == [
        ("91002", 9102, "$1.350", "$1.790", "-25%"),
        ("91401", PHARMACY_IN_SUPER, "$1.490", "$1.790", "-17%"),
        ("91004", 9101, "$3.990", "$4.590", "-13%"),
        ("91003", 9101, "$1.790", "$1.990", "-10%"),
    ]
    assert ids_of(deals(seeded, "conveniencia")) == ["92002", "92004"]
    assert ids_of(deals(seeded, "turbo")) == ["93001"]
    # En Retail, que se abre a propósito, están los productos corrientes del sex shop y del smoking shop.
    assert deal_summary(deals(seeded, "mall")) == [
        ("96201", SMOKING_SHOP, "$990", "$1.290", "-23%"),
        ("96101", SEX_SHOP, "$5.990", "$7.490", "-20%"),
        ("96001", 9601, "$24.990", "$29.990", "-17%"),
    ]
    assert ids_of(deals(seeded, "chocolateria")) == ["97001"]
    # Restaurantes no vende productos del catálogo; una vertical que no existe, tampoco.
    assert deals(seeded, "restaurantes") == []
    assert deals(seeded, "no-existe") == []


def test_deals_limit_keeps_the_biggest_discounts(seeded):
    assert ids_of(deals(seeded, limit=3)) == ["91002", "92002", "92004"]
    assert deals(seeded, limit=0) == []


def test_deals_without_vertical_never_include_pharmacy(seeded):
    everything = deals(seeded, limit=100)

    assert "95003" not in ids_of(everything)
    assert "farmacia" not in {d["vertical"] for d in everything}
    # La vitamina C (-17%) es una baja de la farmacia: sin la regla estaría entre las ofertas. Con la vertical, sale.
    assert deal_summary(deals(seeded, "farmacia")) == [("95003", 9501, "$4.990", "$5.990", "-17%")]


def test_deals_without_vertical_leave_out_stores_that_are_not_pushed(seeded):
    everything = deals(seeded, limit=100)

    # Sus productos corrientes tienen una baja de precio real (-20 %, -23 % y -17 %), pero son de un sex shop, un
    # smoking shop y una farmacia: no se empujan.
    assert NOT_PUSHED_STORES.isdisjoint(d["store_id"] for d in everything)
    assert set(PLAIN_DEALS).isdisjoint(ids_of(everything))
    # Con la vertical abierta a propósito (Retail, Súper), sus ofertas corrientes siguen ahí.
    assert {"96101", "96201"} <= set(ids_of(deals(seeded, "mall", limit=100)))
    assert "91401" in ids_of(deals(seeded, "supermercado", limit=100))


def test_deals_never_push_sensitive_concepts_in_any_vertical(seeded):
    # Los cuatro productos de prueba son de un concepto sensible y tienen una baja de precio real.
    concepts = dict(
        seeded.execute(
            """SELECT entity_id, concept_id FROM item_concepts
               WHERE entity_type = 'catalog_item' AND entity_id = ANY(%s)""",
            (SENSITIVE_DEALS,),
        )
    )
    assert set(concepts) == set(SENSITIVE_DEALS)
    assert set(concepts.values()) <= sensitive_concepts()

    for vertical in (None, *DEMO_VERTICALS):
        found = deals(seeded, vertical, limit=100)
        assert set(SENSITIVE_DEALS).isdisjoint(ids_of(found)), vertical
        assert sensitive_concepts().isdisjoint(d["concept"] for d in found), vertical


def test_a_deal_whose_concept_turns_sensitive_stops_being_offered(seeded):
    assert "91003" in ids_of(deals(seeded, "supermercado"))  # la gaseosa del Centro, -10 %

    seeded.execute("UPDATE item_concepts SET concept_id = 'medicamentos' WHERE entity_id = '91003'")

    assert "91003" not in ids_of(deals(seeded, "supermercado", limit=100))
    assert "91003" not in ids_of(deals(seeded, limit=100))


def test_drops_agree_with_v_price_changes(seeded):
    """Las bajas se buscan por índice, solo para las ofertas de la corrida; es la misma definición que la vista."""
    in_view = {
        (store_id, sku, clp(float(before)))
        for store_id, sku, before in seeded.execute(
            """SELECT v.store_id, v.sku, v.precio_anterior FROM v_price_changes v
               JOIN v_store_format_runs f ON f.store_id = v.store_id AND f.format_run_id = v.run_id
               WHERE v.diferencia < 0"""
        )
    }
    found = deals(seeded, limit=100) + [d for vertical in DEMO_VERTICALS for d in deals(seeded, vertical, limit=100)]

    # Todas las bajas de la vista que son ofertas vigentes salen, con el mismo precio de antes (la bebida energética
    # sale con su precio de lista, no con el anterior).
    from_drops = {(d["store_id"], f"sku-{d['entity_id']}", d["before"]) for d in found} - {
        (9201, "sku-92004", "$1.990")
    }
    assert from_drops <= in_view
    # Las demás bajas de la vista no son ofertas vigentes: la mermelada (91202) está agotada y la bebida energética
    # ya salió; las galletas del Centro (91002 en 9101) perdieron contra las de Norte, que bajaron más; y los productos
    # de concepto sensible (paracetamol, gel íntimo, papelillos y antiácido) no se ofrecen como oferta.
    assert in_view - from_drops == {
        (9201, "sku-92004", "$1.790"),
        (9101, "sku-91202", "$1.990"),
        (9101, "sku-91002", "$1.490"),
        (9501, "sku-95001", "$2.990"),
        (SEX_SHOP, "sku-96102", "$4.990"),
        (SMOKING_SHOP, "sku-96202", "$1.690"),
        (PHARMACY_IN_SUPER, "sku-91402", "$3.990"),
    }


def test_a_store_rebate_is_a_deal_even_without_earlier_prices(seeded):
    # El súper turbo Sur (9302) solo tiene la corrida actual: no hay precio anterior, pero la tienda rebaja el producto.
    seeded.execute(
        "UPDATE price_snapshots SET real_price = 3000, discount_pct = 17 WHERE store_id = 9302 AND sku = 'sku-91001'"
    )

    found = deals(seeded, "turbo")

    assert deal_summary(found) == [
        ("93001", 9301, "$3.990", "$4.990", "-20%"),
        ("91001", 9302, "$2.490", "$3.000", "-17%"),
    ]


def list_price(conn, store_id: int, product_id: int, real_price: int) -> None:
    """La tienda marca un precio de lista para una oferta del catálogo de prueba (sin corrida nueva: se olvida la
    caché del catálogo, como si hubiera vencido)."""
    conn.execute(
        """UPDATE price_snapshots SET real_price = %s, discount_pct = 100 * (1 - price / %s)
           WHERE store_id = %s AND sku = %s AND run_id = (SELECT max(run_id) FROM price_snapshots)""",
        (real_price, real_price, store_id, f"sku-{product_id}"),
    )
    cache.clear()


def test_deals_leave_out_discounts_above_sixty_percent(seeded):
    before = ids_of(deals(seeded, limit=100))
    # El jugo (91005) cuesta $1.590. Un precio de lista de $10.600 son -85 %: un precio por kilo contra uno por
    # unidad (como en la fruta a granel), no una rebaja real.
    list_price(seeded, 9101, 91005, 10600)

    assert "91005" not in ids_of(deals(seeded, limit=100))
    assert "91005" not in ids_of(deals(seeded, "supermercado", limit=100))
    assert ids_of(deals(seeded, limit=100)) == before  # lo demás queda igual

    # Con -40 % sí es una oferta.
    list_price(seeded, 9101, 91005, 2650)

    assert deal_summary([d for d in deals(seeded, limit=100) if d["entity_id"] == "91005"]) == [
        ("91005", 9101, "$1.590", "$2.650", "-40%")
    ]


def test_the_discount_cap_is_inclusive_at_sixty_percent(seeded):
    list_price(seeded, 9101, 91005, 3975)  # $1.590 de $3.975: -60 % justo

    assert "91005" in ids_of(deals(seeded, "supermercado", limit=100))

    list_price(seeded, 9101, 91005, 3980)  # -60,05 %

    assert "91005" not in ids_of(deals(seeded, "supermercado", limit=100))


def test_deals_leave_out_drops_above_sixty_percent_too(seeded):
    # La gaseosa (91003, $1.790) venía de $6.000 en la corrida anterior: -70 %.
    seeded.execute(
        "UPDATE price_snapshots SET price = 6000 "
        "WHERE store_id = 9101 AND sku = 'sku-91003' AND scraped_at < now() - interval '1 day'"
    )

    assert "91003" not in ids_of(deals(seeded, limit=100))


def test_an_impossible_discount_in_one_store_does_not_hide_the_real_one_in_another(seeded):
    # Las galletas (91002) tienen su mayor baja en Norte (9102). Si esa fuera de -80 %, sale la del Centro (-13 %).
    seeded.execute(
        "UPDATE price_snapshots SET price = 6750 "
        "WHERE store_id = 9102 AND sku = 'sku-91002' AND scraped_at < now() - interval '1 day'"
    )

    found = {d["entity_id"]: d for d in deals(seeded, "supermercado", limit=100)}

    assert (found["91002"]["store_id"], found["91002"]["before"], found["91002"]["discount"]) == (
        9101,
        "$1.490",
        "-13%",
    )


def test_a_drop_only_counts_against_the_previous_price_of_the_current_offer(seeded):
    new_run = seeded.execute(
        "INSERT INTO scrape_runs (kind, status) VALUES ('stores', 'done') RETURNING run_id"
    ).fetchone()[0]
    # Una descarga más reciente del súper Centro (9101) con solo dos productos: las galletas subieron de $1.290 a
    # $1.490 y la gaseosa sigue en $1.790. Lo demás de esa tienda deja de estar vigente.
    for sku, price in (("sku-91002", 1490), ("sku-91003", 1790)):
        seeded.execute(
            "INSERT INTO price_snapshots (run_id, store_id, sku, price, in_stock) VALUES (%s, 9101, %s, %s, true)",
            (new_run, sku, price),
        )

    found = {d["entity_id"]: d for d in deals(seeded, "supermercado")}

    # Antes las galletas del Centro habían bajado de $1.490 a $1.290; ahora subieron, así que esa baja ya no cuenta.
    # La de Norte, que sigue vigente, conserva la suya. La gaseosa quedó igual y el café ya no está vigente. La
    # farmacia 9111 no se tocó: su cepillo sigue con su baja.
    assert list(found) == ["91002", "91401"] and found["91002"]["store_id"] == 9102


# --- Home -----------------------------------------------------------------------------------------------------------


def test_home_nearby_is_sorted_by_distance_and_skips_pharmacy(seeded):
    rows = seeded.execute(
        """SELECT s.store_id, s.lat, s.lng, v.vertical FROM stores s JOIN store_verticals v USING (store_id)
           WHERE s.lat IS NOT NULL"""
    ).fetchall()
    by_distance = sorted(rows, key=lambda r: haversine_km(config.MVP_HOME_LAT, config.MVP_HOME_LNG, r[1], r[2]))
    # Entre las más cercanas hay restaurantes, la farmacia 9501, la sucursal 9103 (sin ofertas vigentes) y las tres
    # tiendas que no se empujan (las más cercanas de todas): no entran.
    expected = [
        store_id
        for store_id, _, _, vertical in by_distance
        if vertical not in ("farmacia", "restaurantes") and store_id != OLD_BRANCH and store_id not in NOT_PUSHED_STORES
    ][:6]

    nearby = home(seeded)["nearby_stores"]

    assert expected == [9402, 9102, 9602, 9101, 9301, 9702]
    assert ids(nearby) == expected
    nearest = [store_id for store_id, *_ in by_distance]
    assert nearest.index(9501) < nearest.index(expected[-1]) and nearest.index(OLD_BRANCH) < nearest.index(expected[-1])
    assert all(nearest.index(store_id) < nearest.index(expected[0]) for store_id in LISTED + [ICE_CREAM])
    assert all(nearest.index(store_id) < nearest.index(expected[0]) for store_id in NOT_PUSHED_STORES)
    assert all(set(card) == STORE_KEYS and card["products"] > 0 for card in nearby)
    # Es la misma tarjeta que da la lista de su vertical.
    assert nearby[3] == vertical_stores(seeded, "supermercado")[0]
    assert (nearby[0]["name"], nearby[0]["vertical"]) == ("Botillería de prueba Oriente", "licores")


def test_home_nearby_never_pushes_sex_shops_smoking_shops_or_pharmacies_listed_as_supermarkets(seeded):
    # Las tres tienen ofertas vigentes y están más cerca del punto fijo que cualquier otra tienda, pero el subvertical
    # que Rappi les da (Sex shop, Smoking shop, Farmacia) las deja fuera de «Cerca de ti».
    assert NOT_PUSHED_STORES.isdisjoint(ids(home(seeded)["nearby_stores"]))
    # Quien abre Retail o Súper a propósito sí las ve: esas listas no cambian.
    assert {SEX_SHOP, SMOKING_SHOP} <= set(ids(vertical_stores(seeded, "mall")))
    assert PHARMACY_IN_SUPER in ids(vertical_stores(seeded, "supermercado"))


def test_home_nearby_leaves_out_restaurants_even_when_they_have_catalog_prices(seeded):
    # Un restaurante con precios de catálogo (una sucursal descargada) sería la tienda más cercana de la lista.
    run_id = seeded.execute("SELECT max(run_id) FROM scrape_runs WHERE kind = 'stores'").fetchone()[0]
    seeded.execute("INSERT INTO aisles (store_id, aisle_id, name) VALUES (%s, 100, 'Despensa')", (PIZZERIA,))
    seeded.execute(
        "INSERT INTO store_products (store_id, sku, master_product_id, aisle_id) VALUES (%s, 'sku-91001', 91001, 100)",
        (PIZZERIA,),
    )
    seeded.execute(
        "INSERT INTO price_snapshots (run_id, store_id, sku, price, in_stock) VALUES (%s, %s, 'sku-91001', 1990, true)",
        (run_id, PIZZERIA),
    )
    # Quedó como una tienda descargada, con pasillo, producto y precio vigentes.
    downloaded = seeded.execute("SELECT count(*) FROM v_store_format_runs WHERE store_id = %s", (PIZZERIA,))
    assert downloaded.fetchone() == (1,)

    assert PIZZERIA not in ids(home(seeded)["nearby_stores"])


def test_home_nearby_follows_the_configured_point(seeded, monkeypatch):
    lat, lng = seeded.execute("SELECT lat, lng FROM stores WHERE store_id = 9302").fetchone()
    monkeypatch.setattr(config, "MVP_HOME_LAT", lat)
    monkeypatch.setattr(config, "MVP_HOME_LNG", lng)

    assert ids(home(seeded)["nearby_stores"])[0] == 9302


def test_home_restaurant_lists_sort_by_eta_and_fee(seeded):
    reply = home(seeded)

    assert set(reply) == {"nearby_stores", "fast_restaurants", "low_fee_restaurants"}
    assert ids(reply["fast_restaurants"]) == [
        SANDWICHES,
        PASTRY,
    ]  # 15 y 20 min; 9808 (10 min) no tiene platos con precio
    # Seis de los siete locales, de menor a mayor envío; el de $2.490 (9804) queda fuera.
    assert ids(reply["low_fee_restaurants"]) == [SUSHI, CEVICHE, PASTRY, SANDWICHES, PIZZERIA, CAFE]
    assert all(set(card) == CARD_KEYS for card in reply["fast_restaurants"] + reply["low_fee_restaurants"])
    assert [card["eta"] for card in reply["fast_restaurants"]] == ["15 min", "20 min"]
    assert [card["fee"] for card in reply["low_fee_restaurants"]] == ["$0", "$0", "$690", "$990", "$1.490", "$1.990"]


def test_restaurant_lists_only_show_places_in_the_demo_city(seeded):
    # Como en la base real (un local de Valparaíso con envío gratis y nota 5,0): la Home y la lista de restaurantes son
    # de la ciudad de la demo (config.PROFILE_CITY, el Gran Santiago). Su menú se sigue abriendo (la búsqueda lo
    # puede mostrar).
    seeded.execute("UPDATE stores SET city = 'Valparaíso' WHERE store_id IN (%s, %s)", (SUSHI, SANDWICHES))
    seeded.execute(
        "UPDATE restaurant_details SET eta = '5 min', delivery_cost = 0, rating = 5 WHERE store_id = %s", (SUSHI,)
    )

    reply = home(seeded)

    assert ids(reply["fast_restaurants"]) == [PASTRY, PIZZERIA]
    assert ids(reply["low_fee_restaurants"]) == [CEVICHE, PASTRY, PIZZERIA, CAFE, GRILL]
    assert SUSHI not in ids(restaurants(seeded)) and SANDWICHES not in ids(restaurants(seeded))
    assert restaurant_menu(seeded, SUSHI)["restaurant"]["id"] == SUSHI


def test_home_never_calls_a_restaurant_with_an_unknown_eta_fast(seeded):
    seeded.execute("UPDATE restaurant_details SET eta = '' WHERE store_id <> %s", (PIZZERIA,))

    assert ids(home(seeded)["fast_restaurants"]) == [PIZZERIA]

    seeded.execute("UPDATE restaurant_details SET eta = ''")
    cache.clear()  # sin corrida nueva: como si la caché del catálogo hubiera vencido

    assert home(seeded)["fast_restaurants"] == []


def test_home_of_an_empty_catalog_has_empty_lists(db):
    assert home(db) == {"nearby_stores": [], "fast_restaurants": [], "low_fee_restaurants": []}


# --- Endpoints ------------------------------------------------------------------------------------------------------


def test_restaurants_endpoint_sorts_filters_and_validates(client):
    reply = client.get("/catalog/restaurants")

    assert reply.status_code == 200
    assert ids(reply.json()) == [GRILL, PIZZERIA, PASTRY, SANDWICHES, CAFE, SUSHI, CEVICHE]
    assert ids(client.get("/catalog/restaurants?sort=eta&limit=2").json()) == [SANDWICHES, PASTRY]
    assert ids(client.get("/catalog/restaurants?cuisine=Pizzas").json()) == [PIZZERIA]
    assert client.get("/catalog/restaurants?cuisine=Nada").json() == []
    for query in ("sort=precio", "limit=0", "limit=101", "limit=x"):
        assert client.get(f"/catalog/restaurants?{query}").status_code == 422, query


def test_menu_endpoint_and_its_404(client):
    reply = client.get(f"/catalog/restaurants/{PIZZERIA}/menu")

    assert reply.status_code == 200
    assert reply.json()["restaurant"]["id"] == PIZZERIA
    assert reply.json()["sections"][0]["name"] == "Lo más pedido"
    for store_id in (999_999, 9101, ICE_CREAM):
        missing = client.get(f"/catalog/restaurants/{store_id}/menu")
        assert (missing.status_code, missing.json()) == (404, {"detail": RESTAURANT_NOT_FOUND}), store_id


def test_deals_endpoint_takes_a_vertical_in_either_vocabulary(client):
    everything = client.get("/catalog/deals")
    assert everything.status_code == 200 and len(everything.json()) == 9

    licores = client.get("/catalog/deals?vertical=licores&limit=1")
    assert licores.status_code == 200 and ids_of(licores.json()) == ["94001"]

    missing = client.get("/catalog/deals?vertical=no-existe")
    assert (missing.status_code, missing.json()) == (404, {"detail": VERTICAL_NOT_FOUND})
    for query in ("limit=0", "limit=101"):
        assert client.get(f"/catalog/deals?{query}").status_code == 422, query


def test_home_endpoint(client):
    reply = client.get("/catalog/home")

    assert reply.status_code == 200
    body = reply.json()
    assert [len(body[key]) for key in ("nearby_stores", "fast_restaurants", "low_fee_restaurants")] == [6, 2, 6]


@pytest.mark.parametrize("newer_first", [True, False])
def test_dish_prices_read_latest_menu_prices(seeded, newer_first):
    """El precio de un plato sale de `latest_menu_prices` (desempate por corrida) en el menú, el detalle y el agente,
    no de ordenar el historial: dos snapshots con la misma fecha (un CSV importado dos veces) dan el de la corrida más
    nueva, llegue en el orden que llegue. Con datos normales, lo mismo que antes para todos los platos."""
    older, newer = (
        seeded.execute(
            "INSERT INTO scrape_runs (kind, status) VALUES ('restaurants', 'done') RETURNING run_id"
        ).fetchone()[0]
        for _ in range(2)
    )
    arrivals = [(newer, 11990), (older, 15990)]
    # La misma fecha para los dos y más nueva que la de los platos sembrados (`now()`), relativa a hoy: con una fija
    # (era el 01-01-2030), desde ese día lo sembrado sería lo más nuevo y el test fallaría.
    when = datetime.now(UTC) + timedelta(days=1)
    for run, price in arrivals if newer_first else arrivals[::-1]:
        seeded.execute(
            "INSERT INTO menu_price_snapshots (run_id, item_id, price, real_price, scraped_at)"
            " VALUES (%s, 98001, %s, %s, %s)",
            (run, price, price, when),
        )
    latest = dict(seeded.execute("SELECT item_id::text, price FROM latest_menu_prices").fetchall())
    assert latest["98001"] == 11990

    menu = {
        item["entity_id"]: item["price_value"]
        for store_id in LISTED
        for section in restaurant_menu(seeded, store_id)["sections"]
        for item in section["items"]
    }
    assert menu == {item_id: float(latest[item_id]) for item_id in menu}
    assert menu["98001"] == 11990
    assert product_detail(seeded, "menu_item", "98001")["price_value"] == 11990
    hits = [
        types.SimpleNamespace(
            entity_type="menu_item", entity_id=item_id, concept_id=None, vertical="restaurantes", metadata={}
        )
        for item_id in menu
    ]
    agent = {p.entity_id: p.price_value for p in _with_prices(seeded, "restaurantes", hits)}
    assert agent == menu
