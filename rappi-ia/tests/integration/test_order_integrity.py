"""`POST /orders` no confía en el cliente: el precio sale del catálogo, un producto que no existe es un 400, y un pedido
en "Rappi hoy" (modo actual) no enseña nada al perfil de la persona."""

from contextlib import contextmanager

import pytest

from owner_client import OwnerClient
from rappi_ia.api import app as api
from rappi_ia.demo import seed
from rappi_ia.events import store as events
from rappi_ia.layers.segments import load_signals, user_metrics
from rappi_ia.offers.personal import bought_brands, user_interests

CHIPS = "91001"  # Papas fritas clásicas 180 g (prueba), del súper del catálogo de prueba
COOKIES = "91002"  # Galletas de vainilla: $1.290 en una tienda del súper (9101) y $1.350 en la otra (9102)
NO_STOCK = "91202"  # Mermelada de damasco: agotada, sin oferta vigente
PIZZA = "98002"  # un plato de un restaurante de prueba
BRAND = "marca-prueba"


@pytest.fixture
def client(db):
    seed.seed_demo(db)
    db.execute("INSERT INTO product_brands (brand_key, name) VALUES (%s, 'Marca de prueba')", (BRAND,))
    db.execute(
        "INSERT INTO item_brands (entity_type, entity_id, brand_key, source) VALUES ('catalog_item', %s, %s, 'regla')",
        (CHIPS, BRAND),
    )
    db.commit()

    @contextmanager
    def shared_connection():  # el recálculo de segmentos después de un pedido: en la base de tests, sin cerrarla
        yield db

    def conn_override():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    api.app.dependency_overrides[api.get_connector] = lambda: shared_connection
    yield OwnerClient(api.app)
    api.app.dependency_overrides.clear()


def _order(client, user, cart, mode=None, lines=None, vertical="grocery", key=None, **line):
    body = {
        "user_id": user,
        "session_id": f"s-{cart}",
        "cart_id": cart,
        "vertical": vertical,
        "lines": lines or [{"entity_type": "catalog_item", "entity_id": CHIPS, "concept_id": "snacks-salados", **line}],
        **({"client_order_id": key} if key is not None else {}),
    }
    return client.post("/orders", json=body if mode is None else {**body, "mode": mode})


def _lines(db, order_id):
    return db.execute(
        "SELECT entity_id, unit_price, concept_id FROM app_order_lines WHERE order_id = %s ORDER BY line_no",
        (order_id,),
    ).fetchall()


def test_client_unit_price_is_ignored(client, db):
    catalog_price = client.get(f"/catalog/products/catalog_item/{CHIPS}").json()["price_value"]
    reply = _order(client, "u1", "c1", unit_price=1e8, qty=2)
    assert reply.status_code == 200, reply.text
    order_id = reply.json()["order_id"]

    total = db.execute("SELECT total FROM app_orders WHERE order_id = %s", (order_id,)).fetchone()[0]
    line_price = db.execute("SELECT unit_price FROM app_order_lines WHERE order_id = %s", (order_id,)).fetchone()[0]
    placed = db.execute("SELECT value FROM app_events WHERE type = 'order_placed'").fetchone()[0]
    assert float(total) == float(placed) == 2 * catalog_price and float(line_price) == catalog_price


def test_unknown_entity_is_400(client, db):
    for entity_id in ["999999999", "proto:1"]:
        reply = _order(client, "u1", "c1", entity_id=entity_id)
        assert reply.status_code == 400 and reply.json() == {"detail": "Producto no disponible"}, entity_id
    assert db.execute("SELECT count(*) FROM app_orders").fetchone()[0] == 0


def test_actual_mode_orders_do_not_feed_interests(client, db):
    """En "Rappi hoy" no se aprende: la marca que repite y los conceptos de sus líneas no entran a su perfil, aunque
    un cliente mande el concepto. El mismo pedido en la propuesta sí entra (control)."""
    for n in (1, 2):
        assert _order(client, "u-hoy", f"hoy-{n}", mode="actual").status_code == 200
        assert _order(client, "u-propuesta", f"prop-{n}").status_code == 200
    modes = dict(db.execute("SELECT user_id, min(mode) FROM app_orders GROUP BY 1").fetchall())
    assert modes == {"u-hoy": "actual", "u-propuesta": "propuesta"}

    assert bought_brands(db, "u-propuesta") == user_interests(db, "u-propuesta").brands == {BRAND: 2}
    assert bought_brands(db, "u-hoy") == user_interests(db, "u-hoy").brands == {}
    # Las líneas de pedido son señales de los segmentos (y su evidencia, conceptos del perfil).
    assert _line_concepts(db, "u-propuesta") == ["snacks-salados", "snacks-salados"]
    assert _line_concepts(db, "u-hoy") == []


def test_line_is_priced_at_its_own_store(client, db):
    """Cada tienda tiene su precio (en la base real, hasta el doble): la línea guarda el de la tienda de donde vino, y
    solo sin tienda el de la ficha del producto (la oferta más barata)."""
    item = {"entity_type": "catalog_item", "entity_id": COOKIES}
    prices = []
    for n, lines in enumerate(([{**item, "store_id": 9102}], [{**item, "store_id": 9101}], [item])):
        reply = _order(client, "u1", f"c{n}", lines=lines)
        assert reply.status_code == 200, reply.text
        prices += [float(price) for _, price, _ in _lines(db, reply.json()["order_id"])]
    assert prices == [1350, 1290, 1290]


def test_an_order_is_one_store(client, db):
    """Un pedido es de una tienda: líneas de dos tiendas en un mismo pedido son un 400 (la app manda uno por tienda), y
    una línea sin tienda no cuenta como otra."""
    item = {"entity_type": "catalog_item", "entity_id": COOKIES}
    mixed = _order(client, "u1", "c1", lines=[{**item, "store_id": 9102}, {**item, "store_id": 9101}])
    assert mixed.status_code == 400 and mixed.json() == {"detail": "Un pedido es de una sola tienda"}
    assert db.execute("SELECT count(*) FROM app_orders").fetchone()[0] == 0
    assert _order(client, "u1", "c1", lines=[{**item, "store_id": 9102}, item]).status_code == 200


def test_two_products_without_store_sold_in_two_stores_are_not_one_order(client, db):
    """Sin `store_id` en ninguna línea, la tienda de un producto es la de su ficha (la oferta más barata, la que pone su
    precio): un café que solo vende el súper y un helado que solo vende Turbo son dos tiendas, un 400, y no un pedido
    cotizado en dos lugares sin ninguna tienda guardada."""
    coffee, ice_cream = ({"entity_type": "catalog_item", "entity_id": i} for i in ("91004", "93001"))

    mixed = _order(client, "u1", "c1", lines=[coffee, ice_cream])

    assert mixed.status_code == 400 and mixed.json() == {"detail": "Un pedido es de una sola tienda"}
    assert _order(client, "u1", "c2", lines=[coffee]).status_code == 200
    assert db.execute("SELECT store_id FROM app_order_lines").fetchall() == [(9101,)]  # queda con la de su ficha


def test_a_line_without_store_is_priced_at_the_store_of_the_order(client, db):
    """Con la tienda del pedido conocida (otra línea la trae), la línea sin tienda va en esa: con su precio de ahí, o
    fuera (`lineas_omitidas`) si ahí no se vende. Nunca con el precio de otra tienda."""
    cookies = {"entity_type": "catalog_item", "entity_id": COOKIES}
    ice_cream = {"entity_type": "catalog_item", "entity_id": "93001"}  # solo en Turbo

    reply = _order(client, "u1", "c1", lines=[{**cookies, "store_id": 9102}, cookies, ice_cream])

    assert reply.status_code == 200 and reply.json()["lineas_omitidas"] == 1
    lines = db.execute("SELECT entity_id, unit_price, store_id FROM app_order_lines ORDER BY line_no").fetchall()
    assert [(e, float(p), s) for e, p, s in lines] == [(COOKIES, 1350, 9102), (COOKIES, 1350, 9102)]


def test_the_order_keeps_the_vertical_and_concepts_of_the_catalog(client, db):
    """La vertical del pedido es una de su tienda (la que manda la app si la tienda es de esa, porque una tienda puede
    ser de dos; si no, la suya) y el concepto de cada línea es el del catálogo (`item_concepts`): lo que se guarda
    alimenta el motor, los segmentos y el panel, y no se le cree al cliente."""
    chips_concept = db.execute(
        "SELECT concept_id FROM item_concepts WHERE entity_type = 'catalog_item' AND entity_id = %s", (CHIPS,)
    ).fetchone()[0]
    wrong = _order(client, "u1", "c1", vertical="liquor", concept_id="cerveza")
    assert wrong.status_code == 200, wrong.text
    assert db.execute("SELECT vertical FROM app_orders").fetchone() == ("supermercado",)
    assert [concept for _, _, concept in _lines(db, wrong.json()["order_id"])] == [chips_concept]

    db.execute("INSERT INTO store_verticals (store_id, vertical) VALUES (9101, 'turbo')")  # el súper también es Turbo
    both = _order(client, "u1", "c2", vertical="turbo", lines=[
        {"entity_type": "catalog_item", "entity_id": CHIPS, "store_id": 9101}
    ])  # fmt: skip
    assert both.status_code == 200, both.text
    assert db.execute("SELECT vertical FROM app_orders WHERE cart_id = 'c2'").fetchone() == ("turbo",)

    dish = _order(client, "u1", "c3", vertical="grocery", lines=[{"entity_type": "menu_item", "entity_id": PIZZA}])
    assert dish.status_code == 200, dish.text
    assert db.execute("SELECT vertical FROM app_orders WHERE cart_id = 'c3'").fetchone() == ("restaurantes",)


def test_two_restaurants_without_store_are_not_one_order(client, db):
    """La tienda de un plato la dice el servidor (su restaurante), no solo el `store_id` que manda el cliente: dos
    platos de dos restaurantes sin tienda son un 400, como con tienda, y no un pedido cotizado en dos lugares."""
    dishes = [client.get(f"/catalog/products/menu_item/{dish}").json() for dish in (PIZZA, "98010")]
    assert dishes[0]["store_id"] != dishes[1]["store_id"]
    lines = [{"entity_type": "menu_item", "entity_id": dish["entity_id"]} for dish in dishes]

    for sent in (lines, [lines[0], {**lines[1], "store_id": dishes[1]["store_id"]}]):
        mixed = _order(client, "u1", "c1", vertical="restaurants", lines=sent)
        assert mixed.status_code == 400 and mixed.json() == {"detail": "Un pedido es de una sola tienda"}
    assert db.execute("SELECT count(*) FROM app_orders").fetchone()[0] == 0

    # Uno solo, sin tienda, sí: queda guardado con su restaurante.
    assert _order(client, "u1", "c1", vertical="restaurants", lines=lines[:1]).status_code == 200
    assert db.execute("SELECT store_id FROM app_order_lines").fetchone() == (dishes[0]["store_id"],)


def test_a_resent_order_is_saved_once(client, db):
    """La respuesta se perdió en el camino y la app reenvía el mismo pedido (la misma `client_order_id`): devuelve el
    que ya estaba, sin otra compra ni otro `order_placed`. Otra clave, u otra persona con la misma, es otro pedido."""
    first = _order(client, "u1", "c1", key="k-1")
    again = _order(client, "u1", "c1", key="k-1")
    assert first.status_code == again.status_code == 200
    assert again.json() == first.json()
    assert db.execute("SELECT count(*) FROM app_orders").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM app_events WHERE type = 'order_placed'").fetchone()[0] == 1

    assert _order(client, "u1", "c1", key="k-2").json()["order_id"] != first.json()["order_id"]
    assert _order(client, "u2", "c1", key="k-1").json()["order_id"] != first.json()["order_id"]
    assert db.execute("SELECT count(*) FROM app_orders").fetchone()[0] == 3


def test_a_resend_that_races_the_first_order_does_not_save_another(client, db):
    """Si el reenvío pasa la revisión antes de que el primero quede guardado, el INSERT no crea otro pedido."""
    line = {"entity_type": "catalog_item", "entity_id": CHIPS, "store_id": 9101, "unit_price": 1}
    first = events.record_order(db, "u1", "s", "c1", "supermercado", [line], client_order_id="k-1")
    again = events.record_order(db, "u1", "s", "c1", "supermercado", [line], client_order_id="k-1")
    assert again == first
    assert db.execute("SELECT count(*) FROM app_order_lines").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM app_events WHERE type = 'order_placed'").fetchone()[0] == 1


@pytest.mark.parametrize("key", ["", "con espacio", "x" * 65])
def test_an_invalid_order_key_is_rejected(client, db, key):
    assert _order(client, "u1", "c1", key=key).status_code == 422


def test_two_restaurants_in_one_cart_are_two_orders(client, db):
    """Dos restaurantes del mismo carro son dos pedidos (dos filas en app_orders, dos `order_placed`), una sola compra:
    el abandono de la persona no baja de 0 por tener dos pedidos en un carro pagado."""
    dishes = [client.get(f"/catalog/products/menu_item/{dish}").json() for dish in (PIZZA, "98010")]
    assert dishes[0]["store_id"] != dishes[1]["store_id"]
    for dish in dishes:
        line = {"entity_type": "menu_item", "entity_id": dish["entity_id"], "store_id": dish["store_id"]}
        assert _order(client, "u-dos", "c-dos", vertical="restaurants", lines=[line]).status_code == 200
    orders = db.execute("SELECT vertical, cart_id FROM app_orders WHERE user_id = 'u-dos'").fetchall()
    assert orders == [("restaurantes", "c-dos")] * 2
    placed = db.execute("SELECT count(*) FROM app_events WHERE user_id = 'u-dos' AND type = 'order_placed'")
    assert placed.fetchone()[0] == 2
    carts = ["c-dos", "c-sin-pagar-1", "c-sin-pagar-2"]  # MIN_CARTS_FOR_ABANDONMENT
    events.record(
        db,
        [events.Event("u-dos", f"s-{cart}", "cart_add", vertical="restaurantes", cart_id=cart) for cart in carts],
        "prototype",
    )
    # Uno de tres carros pagado (con dos pedidos): 2/3 abandonados, no 1/3.
    assert user_metrics(db, "prototype", "u-dos")["u-dos"]["tasa_abandono"] == pytest.approx(2 / 3)


def test_the_order_says_whether_the_person_is_pro(client, db):
    """`pro` del pedido queda en la persona (app_users.pro): lo último que dijo la app; sin él, no cambia."""
    pro = lambda: db.execute("SELECT pro FROM app_users WHERE user_id = 'u-pro'").fetchone()[0]  # noqa: E731
    body = {"user_id": "u-pro", "session_id": "s", "cart_id": "c1", "vertical": "grocery"}
    line = {"entity_type": "catalog_item", "entity_id": CHIPS}
    assert client.post("/orders", json={**body, "lines": [line]}).status_code == 200
    assert pro() is None
    assert client.post("/orders", json={**body, "cart_id": "c2", "lines": [line], "pro": True}).status_code == 200
    assert pro() is True
    assert client.post("/orders", json={**body, "cart_id": "c3", "lines": [line]}).status_code == 200
    assert pro() is True
    assert client.post("/orders", json={**body, "cart_id": "c4", "lines": [line], "pro": False}).status_code == 200
    assert pro() is False


def test_a_dish_is_priced_only_at_its_restaurant(client, db):
    dish = client.get(f"/catalog/products/menu_item/{PIZZA}").json()
    line = {"entity_type": "menu_item", "entity_id": PIZZA}
    own = _order(client, "u1", "c1", vertical="restaurants", lines=[{**line, "store_id": dish["store_id"]}])
    assert own.status_code == 200 and float(_lines(db, own.json()["order_id"])[0][1]) == dish["price_value"]
    other = _order(client, "u1", "c2", vertical="restaurants", lines=[{**line, "store_id": dish["store_id"] + 1}])
    assert other.status_code == 400


def test_lines_without_a_current_price_are_skipped(client, db, caplog):
    """Un pedido con algo agotado o que esa tienda no vende guarda el resto y dice cuántas líneas omitió; solo sin
    ninguna línea con precio es un 400."""
    lines = [
        {"entity_type": "catalog_item", "entity_id": CHIPS, "qty": 2},
        {"entity_type": "catalog_item", "entity_id": NO_STOCK},
        {"entity_type": "catalog_item", "entity_id": "93001", "store_id": 9101},  # el helado: ese súper no lo vende
    ]
    with caplog.at_level("WARNING"):
        reply = _order(client, "u1", "c1", lines=lines)
    assert reply.status_code == 200, reply.text
    assert reply.json()["lineas_omitidas"] == 2 and "2 línea(s) sin precio vigente" in caplog.text
    order_id = reply.json()["order_id"]
    assert [entity for entity, *_ in _lines(db, order_id)] == [CHIPS]
    chips = client.get(f"/catalog/products/catalog_item/{CHIPS}").json()["price_value"]
    assert float(db.execute("SELECT total FROM app_orders WHERE order_id = %s", (order_id,)).fetchone()[0]) == 2 * chips

    assert _order(client, "u1", "c2", lines=lines[1:]).status_code == 400
    assert _order(client, "u1", "c3").json()["lineas_omitidas"] == 0


def test_actual_mode_lines_keep_no_concept(client, db):
    """Aunque un cliente mande el concepto, un pedido de "Rappi hoy" no lo guarda (como los eventos de ese modo)."""
    reply = _order(client, "u1", "c1", mode="actual")
    assert _lines(db, reply.json()["order_id"])[0][2] is None
    reply = _order(client, "u1", "c2")
    assert _lines(db, reply.json()["order_id"])[0][2] == "snacks-salados"


def test_brand_concentration_ignores_actual_orders(client, db):
    """La concentración de marca (un segmento) es un gusto: los pedidos de "Rappi hoy" no cuentan."""
    for n in range(3):
        _order(client, "u-hoy", f"hoy-{n}", mode="actual", qty=2)
        _order(client, "u-propuesta", f"prop-{n}", qty=2)
    assert "concentracion_marca" in user_metrics(db, "prototype", "u-propuesta").get("u-propuesta", {})
    assert "concentracion_marca" not in user_metrics(db, "prototype", "u-hoy").get("u-hoy", {})


def _line_concepts(db, user):
    signals = load_signals(db, "prototype", user).get(user, [])
    return [s.concept for s in signals if s.type == "order_line"]


def test_events_cannot_fake_an_order(client, db):
    """`order_placed` solo nace en /orders: por /events era un pedido sin pedido detrás (pesa 5 en el perfil)."""
    fake = {"type": "order_placed", "session_id": "s1", "concept_id": "snacks-salados", "value": 5000}
    assert client.post("/events", json={"user_id": "u1", "events": [fake]}).status_code == 400
    assert db.execute("SELECT count(*) FROM app_events").fetchone()[0] == 0
    assert events.profile(db, "u1") == {}
