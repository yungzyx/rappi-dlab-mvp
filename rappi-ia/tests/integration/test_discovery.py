"""Descubrimiento sobre el catálogo de `seed_demo`: filtros y orden de restaurantes, abierto o cerrado según el horario
publicado, tiendas y restaurantes en la búsqueda, "Lo que sea", comparar un producto entre tiendas, "Pocas unidades" y
similares, promos de la tienda, "Para ti" en la tienda y lo que el buscador muestra antes de escribir.

La hora local de los tests es un jueves a las 13:00 (conftest.py: todos los restaurantes que publican horario están
abiertos); los que prueban un cerrado pasan su propia hora.
"""

from datetime import datetime, timedelta

import pytest

from owner_client import OwnerClient
from rappi_ia.api import app as api
from rappi_ia.catalog.for_you import store_for_you
from rappi_ia.catalog.hours import TZ
from rappi_ia.catalog.restaurants import Filters, restaurant_menu, restaurants, search_restaurants
from rappi_ia.catalog.stores import product_stores, search_stores, store_page, vertical_stores
from rappi_ia.demo.seed import seed_demo
from rappi_ia.events import store as events
from rappi_ia.events.searches import TOP_MIN_PEOPLE, recent_searches, top_searches
from rappi_ia.offers import preferences

CENTRO, EXPRESS_CENTRO, FARMACIA, MALL_CENTRO = 9101, 9201, 9501, 9601
PIZZERIA, SUSHI, SANDWICHES, PARRILLA, CAFE = 9801, 9802, 9803, 9804, 9805
CHOCOLATE, TALLARINES, CAFE_MOLIDO, PARACETAMOL = "92002", "91101", "91004", "95001"
NIGHT = datetime(2026, 10, 22, 23, 50, tzinfo=TZ)  # jueves 23:50: solo la Parrilla (hasta la 1:00) sigue abierta


@pytest.fixture
def seeded(db):
    seed_demo(db)
    return db


@pytest.fixture
def client(seeded):
    def conn_override():
        yield seeded

    api.app.dependency_overrides[api.get_conn] = conn_override
    yield OwnerClient(api.app)
    api.app.dependency_overrides.clear()


def ids(cards):
    return [card["id"] for card in cards]


def concept_of(conn, entity_id: str) -> str:
    return conn.execute(
        "SELECT concept_id FROM item_concepts WHERE entity_type = 'catalog_item' AND entity_id = %s", (entity_id,)
    ).fetchone()[0]


# ── Restaurantes: filtros, orden y horario ──────────────────────────────────


def test_restaurant_filters_narrow_the_list(seeded):
    everyone = ids(restaurants(seeded))
    fast = restaurants(seeded, filters=Filters(max_eta=35))
    assert ids(fast) and all(int(card["eta"].split()[0]) <= 35 for card in fast)  # sin tiempo no es rápido
    assert set(ids(fast)) < set(everyone)
    assert all(card["rating"] >= 4.5 for card in restaurants(seeded, filters=Filters(min_rating=4.5)))
    # Destacados: nota desde 4,5 con al menos 100 opiniones (regla propia).
    assert ids(restaurants(seeded, filters=Filters(top=True))) == [PARRILLA, PIZZERIA]
    # Con promociones: algún plato rebajado (el churrasco de los Sándwiches).
    promo = restaurants(seeded, filters=Filters(promo=True))
    assert ids(promo) == [SANDWICHES] and promo[0]["promo"] is True
    assert {card["id"]: card["promo"] for card in restaurants(seeded)}[PIZZERIA] is False


def test_recommended_puts_the_most_reviewed_first(seeded):
    reviews = [card["reviews"] for card in restaurants(seeded, sort="recommended") if card["reviews"] is not None]
    assert reviews == sorted(reviews, reverse=True) and reviews[0] == 300


def test_closed_restaurants_go_last_with_their_published_hours(seeded):
    at_night = restaurants(seeded, now=NIGHT)
    states = {card["id"]: card["hours"] for card in at_night}
    assert states[PARRILLA]["open"] is True and states[PARRILLA]["closes_at"] == "01:00"
    assert states[PIZZERIA] | {"source": "horario"} == states[PIZZERIA]
    assert (states[PIZZERIA]["open"], states[PIZZERIA]["opens_at"], states[PIZZERIA]["opens_tomorrow"]) == (
        False,
        "11:00",
        True,
    )
    assert states[SUSHI]["open"] is None  # no publica horario: no se sabe, y no va al final
    closed = [card["id"] for card in at_night if card["hours"]["open"] is False]
    assert ids(at_night)[-len(closed) :] == closed
    # El orden por nota se mantiene dentro de cada grupo, y a la hora de los tests nadie está cerrado.
    assert all(card["hours"]["open"] is not False for card in restaurants(seeded))


def test_menu_card_says_if_the_restaurant_is_closed(seeded):
    assert restaurant_menu(seeded, CAFE, now=NIGHT)["restaurant"]["hours"]["open"] is False
    assert restaurant_menu(seeded, CAFE)["restaurant"]["hours"]["open"] is True


def test_restaurant_list_endpoint_takes_the_filters(client):
    body = client.get("/catalog/restaurants", params={"top": "true", "sort": "recommended"}).json()
    assert ids(body) == [PARRILLA, PIZZERIA]
    assert client.get("/catalog/restaurants", params={"max_eta": 0}).status_code == 422


# ── Búsqueda: tiendas, restaurantes y "Lo que sea" ──────────────────────────


def test_search_finds_stores_by_name_one_per_format(seeded):
    found = search_stores(seeded, "supermercado de PRUEBA")
    # 9103 es del formato de 9101 pero no lo bajó la última corrida; 9104 solo se descubrió.
    assert ids(found) == [CENTRO, 9102]
    assert found[0]["promos"][0]["threshold"] == 15000
    assert search_stores(seeded, "te") == []  # dos letras calzarían casi cualquier nombre
    assert search_stores(seeded, "rueba") == []  # calza el comienzo de una palabra, no el medio


def test_search_finds_restaurants_by_name_or_cuisine(seeded):
    assert ids(search_restaurants(seeded, "pizzeria")) == [PIZZERIA]
    assert PIZZERIA in ids(search_restaurants(seeded, "pizzas"))  # su cocina
    closed_last = search_restaurants(seeded, "de prueba", now=NIGHT)
    assert closed_last[-1]["hours"]["open"] is False


def test_grouped_search_adds_places_and_offers_whim_only_when_allowed(client):
    body = client.get("/search", params={"q": "chocolateria de prueba"}).json()
    assert [s["id"] for s in body["places"]["stores"]] == [9701, 9702]
    assert body["unmet"] is False and body["whim_allowed"] is False
    nothing = client.get("/search", params={"q": "zapatillas de cuero xyz"}).json()
    assert nothing["unmet"] is True and nothing["whim_allowed"] is True
    assert nothing["places"] == {"stores": [], "restaurants": []}
    assert client.get("/search", params={"q": "droga xyz"}).json()["whim_allowed"] is False


# ── Comparar entre tiendas, pocas unidades y similares ──────────────────────


def test_product_stores_compare_price_eta_and_fee(seeded):
    reply = product_stores(seeded, CHOCOLATE)
    stores = reply["stores"]
    assert reply["count"] == 4 and [s["store_id"] for s in stores][0] == EXPRESS_CENTRO
    assert [s["price"] for s in stores] == sorted(
        [s["price"] for s in stores], key=lambda p: int(p[1:].replace(".", ""))
    )
    cheapest = [s["store_id"] for s in stores if s["best_price"]]
    fastest = {s["store_id"] for s in stores if s["fastest"]}
    assert cheapest == [EXPRESS_CENTRO]
    assert fastest == {s["store_id"] for s in stores if s["eta_minutes"] == min(x["eta_minutes"] for x in stores)}
    assert all(s["fee"].startswith("$") and s["eta"].endswith(" min") for s in stores)
    assert reply["here"] is None and reply["similar"] == []


def test_product_stores_only_compare_stores_of_the_demo_city_and_keep_the_open_one(seeded):
    # La tienda más barata del chocolate pasa a Temuco: sale de la comparación, y "Mejor precio" y "Más rápido" se
    # marcan entre las que quedan. Si la persona la abrió por su id (`store_id`), sigue ahí, como `here`.
    seeded.execute("UPDATE stores SET city = 'Temuco' WHERE store_id = %s", (EXPRESS_CENTRO,))

    reply = product_stores(seeded, CHOCOLATE)
    stores = reply["stores"]
    assert EXPRESS_CENTRO not in [s["store_id"] for s in stores]
    assert reply["count"] == 3 == len(stores)
    cheapest = min(s["price_value"] for s in stores)
    assert [s["best_price"] for s in stores] == [s["price_value"] == cheapest for s in stores]
    assert stores[0]["best_price"]
    assert any(s["fastest"] for s in stores)

    opened = product_stores(seeded, CHOCOLATE, EXPRESS_CENTRO)
    assert opened["here"]["store_id"] == EXPRESS_CENTRO and opened["count"] == 4
    assert [s["store_id"] for s in opened["stores"]][0] == EXPRESS_CENTRO


def test_low_stock_and_sold_out_with_similar_products(seeded):
    coffee = product_stores(seeded, CAFE_MOLIDO, CENTRO)["here"]
    assert coffee["available"] is True and coffee["low_stock"] is True
    reply = product_stores(seeded, TALLARINES, CENTRO)
    assert reply["here"]["available"] is False and reply["count"] == 1  # en la otra tienda sí hay
    similar = reply["similar"]
    assert similar and all(p["concept"] == concept_of(seeded, TALLARINES) for p in similar)
    assert TALLARINES not in [p["entity_id"] for p in similar]
    assert [p["price_value"] for p in similar] == sorted(p["price_value"] for p in similar)


def test_substitutes_come_even_if_the_product_is_available(seeded):
    """Los cambios en vivo del Súper: el agotado es simulado, así que el producto está disponible y aun así se piden los
    sustitutos del mismo concepto en la misma tienda."""
    assert product_stores(seeded, CAFE_MOLIDO, CENTRO)["similar"] == []
    reply = product_stores(seeded, CAFE_MOLIDO, CENTRO, substitutes=True)
    assert reply["here"]["available"] is True
    similar = reply["similar"]
    assert similar and all(p["concept"] == concept_of(seeded, CAFE_MOLIDO) for p in similar)
    assert CAFE_MOLIDO not in [p["entity_id"] for p in similar]
    # Sin la tienda no hay sustitutos (son de esa tienda).
    assert product_stores(seeded, CAFE_MOLIDO, substitutes=True)["similar"] == []


def test_product_stores_endpoint(client):
    assert client.get(f"/catalog/products/catalog_item/{CHOCOLATE}/stores").json()["count"] == 4
    assert client.get("/catalog/products/menu_item/98001/stores").status_code == 404
    assert client.get("/catalog/products/catalog_item/abc/stores").status_code == 404
    reply = client.get(f"/catalog/products/catalog_item/{CAFE_MOLIDO}/stores?store_id={CENTRO}&sustitutos=true")
    assert reply.json()["similar"]


# ── Promos y estado de la tienda ────────────────────────────────────────────


def test_store_cards_carry_their_published_promos_and_state(seeded):
    page = store_page(seeded, CENTRO)["store"]
    assert [p["title"] for p in page["promos"]] == [
        "Envío gratis sobre $15.000 (prueba)",
        "10% OFF en despensa (prueba)",
    ]
    assert page["hours"] == {
        "source": "descarga",
        "open": True,
        "closes_at": None,
        "opens_at": None,
        "opens_tomorrow": False,
        "today": None,
    }
    mall = {card["id"]: card for card in vertical_stores(seeded, "mall")}
    assert (mall[MALL_CENTRO]["hours"]["open"], mall[MALL_CENTRO]["hours"]["opens_at"]) == (False, "10:00")
    assert mall[MALL_CENTRO]["promos"] == []


# ── "Para ti" en la tienda ──────────────────────────────────────────────────


def test_store_for_you_follows_the_person_and_the_guards(seeded):
    chocolate = concept_of(seeded, CHOCOLATE)
    medicine = concept_of(seeded, PARACETAMOL)
    events.record(
        seeded,
        [
            events.Event("p-gusto", "s1", "cart_add", concept_id=chocolate, entity_type="catalog_item"),
            events.Event("p-gusto", "s1", "cart_add", concept_id=medicine, entity_type="catalog_item"),
        ],
    )
    picks = store_for_you(seeded, EXPRESS_CENTRO, "p-gusto")
    assert [p["entity_id"] for p in picks["products"]] == [CHOCOLATE]
    assert picks["basis"] == [{"kind": "interes", "id": chocolate, "source": "eventos:persona"}]
    assert store_for_you(seeded, FARMACIA, "p-gusto") == {"products": [], "basis": []}  # Farmacia no se ofrece
    assert store_for_you(seeded, EXPRESS_CENTRO, "sin-historial") == {"products": [], "basis": []}


def test_store_for_you_leaves_out_what_the_person_cannot_eat(seeded):
    """Su dieta y sus alergias filtran "Para ti" de la tienda, como el de la Home: sin lactosa, nada "con leche"."""
    chocolate = concept_of(seeded, CHOCOLATE)
    events.record(seeded, [events.Event("p-leche", "s1", "cart_add", concept_id=chocolate, entity_type="catalog_item")])
    assert [p["entity_id"] for p in store_for_you(seeded, EXPRESS_CENTRO, "p-leche")["products"]] == [CHOCOLATE]

    preferences.add(seeded, "p-leche", [("alergia", "lactosa")])

    assert store_for_you(seeded, EXPRESS_CENTRO, "p-leche")["products"] == []


def test_store_for_you_endpoint_is_only_for_its_owner(client):
    body = client.get(f"/catalog/stores/{EXPRESS_CENTRO}/para-ti", params={"user_id": "p-nueva"}).json()
    assert body["products"] == [] and body["request_id"]
    other = client.get(
        f"/catalog/stores/{EXPRESS_CENTRO}/para-ti", params={"user_id": "p-nueva"}, headers={"X-User-Token": "x"}
    )
    assert other.status_code == 401


# ── Antes de escribir: recientes y lo más buscado ───────────────────────────


def searches(user_id: str, *queries: str, ago_days: int = 1, unmet: bool = False):
    when = datetime.now(TZ) - timedelta(days=ago_days)
    return [
        events.Event(
            user_id, "s", "search", ts=when + timedelta(minutes=i), query=q, results=0 if unmet else 5, unmet=unmet
        )
        for i, q in enumerate(queries)
    ]


def test_recent_searches_are_the_persons_latest_without_repeats(seeded):
    events.record(seeded, searches("p-1", "Pizza", "agua", "pizza", "mi correo es a@b.cl"))
    assert recent_searches(seeded, "p-1") == ["pizza", "agua"]  # el correo quedó tapado al guardarse: no se muestra
    assert recent_searches(seeded, "p-2") == []


def test_top_searches_use_one_population_with_enough_people(seeded):
    for n in range(TOP_MIN_PEOPLE):
        events.record(seeded, searches(f"sim-{n}", "papas fritas", "cerveza"), source="synthetic")
    events.record(seeded, searches("sim-x", "kebab"), source="synthetic")  # una sola persona
    events.record(seeded, searches("sim-y", "hielo", unmet=True), source="synthetic")
    for n in range(TOP_MIN_PEOPLE):
        events.record(seeded, searches(f"p-{n}", "helado"))  # del prototipo: otra población
    assert top_searches(seeded, "synthetic") == ["papas fritas"]  # la cerveza no se propone sola
    assert top_searches(seeded, "prototype") == ["helado"]


def test_a_top_search_has_to_find_something_in_the_catalog(seeded):
    """`results` y `unmet` los manda la app: una búsqueda inventada con "5 resultados" no llega a "Lo más buscado"."""
    for n in range(TOP_MIN_PEOPLE):
        events.record(seeded, searches(f"p-{n}", "helado", "compra aquí www", "pizzeria de prueba"))
    assert top_searches(seeded, "prototype") == ["helado", "pizzeria de prueba"]


def test_searches_endpoint_declares_its_population(client):
    body = client.get("/profile/p-1/busquedas").json()
    assert body == {"recientes": [], "mas_buscado": [], "poblacion": "synthetic", "request_id": body["request_id"]}
