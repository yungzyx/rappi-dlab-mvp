"""Después del pedido: la calificación (`order_rated`), que en `propuesta` pausa la recompra y el "volver" de lo que
salió mal; la disponibilidad de "Pídelo de nuevo" (`POST /catalog/availability`) y el OnTop de Turbo (momento
`ontop`). Sobre el catálogo de prueba (`seed_demo`)."""

from datetime import UTC, datetime, time, timedelta

import pytest

from owner_client import OwnerClient
from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.rappi_agent import RappiAgent
from rappi_ia.api import app as api
from rappi_ia.api.services import Services
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents
from rappi_ia.events import store as events
from rappi_ia.motor.build import refresh_user_conn
from rappi_ia.motor.model import TZ
from rappi_ia.offers.winback import PAUSE_DAYS, paused

USER = "u-calificacion"
COFFEE = ("catalog_item", "91004")  # café molido, solo en el súper
COOKIES = ("catalog_item", "91002")
ICE_CREAM = ("catalog_item", "93001")  # helado, solo en Turbo
TURBO_CENTRO = 9301


def today():
    return datetime.now(TZ).date()


@pytest.fixture
def client(db):
    seed_demo(db)
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


def bought(db, vertical, concept, entity, days_ago, store_id=None, user=USER):
    """Un pedido `propuesta` a mediodía de hace `days_ago` días; devuelve su carro."""
    ts = datetime.combine(today() - timedelta(days=days_ago), time(12), TZ)
    line = {"entity_type": entity[0], "entity_id": entity[1], "concept_id": concept, "unit_price": 1990}
    if store_id is not None:
        line["store_id"] = store_id
    cart = f"c-{vertical}-{concept}-{days_ago}"
    events.record_order(db, user, f"s-{days_ago}", cart, vertical, [line], ts=ts)
    return cart


def rhythm(db, vertical, concept, entity, last_days_ago, every=7, times=3):
    """`times` pedidos del concepto cada `every` días; devuelve el carro del último. Recalcula su motor."""
    carts = [bought(db, vertical, concept, entity, last_days_ago + n * every) for n in range(times)]
    refresh_user_conn(db, USER)
    return carts[0]


def rate(client, cart, stars, reasons=(), mode=None):
    payload = {"stars": stars, "reasons": list(reasons), **({"mode": mode} if mode else {})}
    event = {"type": "order_rated", "session_id": "s-rate", "cart_id": cart, "surface": "tracking", "payload": payload}
    return client.post("/events", json={"user_id": USER, "events": [event]})


def offer(client, moment, context=None, user_id=USER):
    body = {"moment": moment, "context": context or {}, **({"user_id": user_id} if user_id else {})}
    return client.post("/agent/offer", json=body)


def rating_of(db, cart):
    return db.execute(
        "SELECT rating, rating_reasons, rated_at FROM app_orders WHERE user_id = %s AND cart_id = %s", (USER, cart)
    ).fetchone()


# ── calificación ─────────────────────────────────────────────────────────────
def test_a_rating_is_saved_in_every_order_of_its_cart(client, db):
    cart = "c-dos-verticales"
    for vertical in ("supermercado", "turbo"):
        line = {"entity_type": "catalog_item", "entity_id": "91001", "unit_price": 1990}
        events.record_order(db, USER, "s-1", cart, vertical, [line])

    assert rate(client, cart, 2, ["tarde", "faltante", "tarde"]).status_code == 200

    rows = db.execute("SELECT rating, rating_reasons FROM app_orders WHERE cart_id = %s", (cart,)).fetchall()
    assert rows == [(2, ["tarde", "faltante"])] * 2
    [(kind, payload)] = db.execute("SELECT type, payload FROM app_events WHERE type = 'order_rated'").fetchall()
    assert payload["stars"] == 2


def test_a_rating_in_rappi_hoy_is_kept_as_an_event_but_teaches_nothing(client, db):
    cart = bought(db, "supermercado", "cafe", COFFEE, 1)

    assert rate(client, cart, 1, ["mal_estado"], mode="actual").status_code == 200

    assert rating_of(db, cart) == (None, None, None)
    assert db.execute("SELECT count(*) FROM app_events WHERE type = 'order_rated'").fetchone()[0] == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"stars": 0},
        {"stars": 6},
        {"stars": "5"},
        {"stars": True},
        {"stars": 2, "reasons": ["no-existe"]},
        {"stars": 2, "reasons": "tarde"},
    ],
)
def test_a_rating_that_is_not_one_is_rejected(client, db, payload):
    event = {"type": "order_rated", "session_id": "s-rate", "cart_id": "c-x", "payload": payload}
    assert client.post("/events", json={"user_id": USER, "events": [event]}).status_code == 400


def test_a_rating_needs_its_order(client, db):
    event = {"type": "order_rated", "session_id": "s-rate", "payload": {"stars": 4}}
    assert client.post("/events", json={"user_id": USER, "events": [event]}).status_code == 400


def test_an_order_keeps_the_store_of_each_line(client, db):
    line = {"entity_type": "catalog_item", "entity_id": "93001", "store_id": TURBO_CENTRO}
    order = {"user_id": USER, "session_id": "s-1", "cart_id": "c-1", "vertical": "turbo", "lines": [line]}

    assert client.post("/orders", json=order).status_code == 200

    assert db.execute("SELECT store_id FROM app_order_lines").fetchall() == [(TURBO_CENTRO,)]


# ── la pausa ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(("stars", "offered"), [(3, False), (2, False), (4, True), (5, True)])
def test_a_bad_rating_pauses_the_repeat_of_its_concept(client, db, stars, offered):
    last = rhythm(db, "supermercado", "cafe", COFFEE, last_days_ago=7)
    assert offer(client, "recompra").status_code == 200

    rate(client, last, stars)

    assert offer(client, "recompra").status_code == (200 if offered else 204)


def test_the_pause_ends_after_a_month(client, db):
    last = rhythm(db, "supermercado", "cafe", COFFEE, last_days_ago=7)

    rate(client, last, 1)
    # Calificado hace un mes y un día (la app no manda una hora tan vieja: se corre en la base).
    db.execute(
        "UPDATE app_orders SET rated_at = %s WHERE cart_id = %s",
        (datetime.now(UTC) - timedelta(days=PAUSE_DAYS + 1), last),
    )

    assert offer(client, "recompra").status_code == 200


def test_a_bad_rating_in_rappi_hoy_does_not_pause(client, db):
    last = rhythm(db, "supermercado", "cafe", COFFEE, last_days_ago=7)

    rate(client, last, 1, mode="actual")

    assert offer(client, "recompra").status_code == 200


def test_a_bad_rating_pauses_the_winback_of_its_concept(client, db):
    last = rhythm(db, "supermercado", "cafe", COFFEE, last_days_ago=20)
    assert offer(client, "volver").status_code == 200

    rate(client, last, 2, ["mal_estado"])

    assert offer(client, "volver").status_code == 204


def test_a_bad_rating_keeps_its_store_out_of_the_winback(client, db):
    # Dejó Turbo hace 40 días (tres pedidos de helado, sin concepto: no arman recompra) y sigue pidiendo en el súper.
    for days in (40, 50, 60):
        bought(db, "turbo", None, ICE_CREAM, days)
    bought(db, "supermercado", None, COOKIES, 5)
    refresh_user_conn(db, USER)
    body = offer(client, "volver").json()
    [product] = body["products"]
    assert body["reason"]["basis"][0]["kind"] == "vuelta"

    # Un pedido de otra cosa en esa misma tienda salió mal: su helado no se ofrece.
    cart = bought(db, "turbo", None, COOKIES, 2, store_id=product["store_id"])
    rate(client, cart, 1, ["equivocado"])

    assert offer(client, "volver").status_code == 204


def test_paused_reads_concepts_and_stores_of_bad_orders_only(client, db):
    good = bought(db, "supermercado", "cafe", COFFEE, 3, store_id=9101)
    bad = bought(db, "turbo", "helados", ICE_CREAM, 2, store_id=TURBO_CENTRO)
    rate(client, good, 5)
    rate(client, bad, 3, ["tarde"])

    hold = paused(db, USER)

    assert hold.concepts == {"helados"} and hold.stores == {TURBO_CENTRO}
    assert paused(db, None).concepts == frozenset()


# ── "Pídelo de nuevo" ────────────────────────────────────────────────────────
def test_availability_gives_the_current_price_in_the_same_store(client, db):
    lines = [
        {"entity_type": "catalog_item", "entity_id": "93001", "store_id": TURBO_CENTRO},
        {"entity_type": "catalog_item", "entity_id": "93001", "store_id": 9101},  # el súper no vende helado
        {"entity_type": "catalog_item", "entity_id": "99999999"},
    ]

    reply = client.post("/catalog/availability", json={"lines": lines})

    assert reply.status_code == 200, reply.text
    first, other_store, missing = reply.json()["lines"]
    assert first == {**lines[0], "available": True, "price": 3990.0}  # el vigente, no el de la corrida anterior
    assert other_store["available"] is False and other_store["price"] is None
    assert missing == {**lines[2], "store_id": None, "available": False, "price": None}


def test_availability_needs_lines(client):
    assert client.post("/catalog/availability", json={"lines": []}).status_code == 422


# ── OnTop de Turbo ───────────────────────────────────────────────────────────
def test_ontop_offers_turbo_products_with_its_assumed_window(client, db):
    items = [{"entity_type": "menu_item", "entity_id": "98001"}]

    reply = offer(client, "ontop", {"vertical": "restaurants", "items": items}, user_id=None)

    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["moment"] == "ontop" and body["vertical"] == "turbo" and body["plazo_min"] == 15
    assert body["products"] and all(p["vertical"] == "turbo" and not p["age_restricted"] for p in body["products"])
    assert body["text"].endswith("sin costo de envío extra (de ejemplo).")
    assert {"kind": "ontop", "id": "turbo@15min", "source": "rappi+supuesto"} in body["reason"]["basis"]
    assert body["actions"] == [{"label": "Ver toda la tienda", "route": ["turbo"]}]


def test_ontop_leaves_out_what_the_order_already_has(client, db):
    first = offer(
        client, "ontop", {"vertical": "supermercado", "items": [{"entity_type": "menu_item", "entity_id": "1"}]}
    )
    shown = [{"entity_type": p["entity_type"], "entity_id": p["entity_id"]} for p in first.json()["products"]]

    again = offer(client, "ontop", {"vertical": "supermercado", "items": shown})

    if again.status_code == 200:
        kept = {(p["entity_type"], p["entity_id"]) for p in again.json()["products"]}
        assert not kept & {(s["entity_type"], s["entity_id"]) for s in shown}


def test_a_turbo_order_has_no_ontop(client, db):
    items = [{"entity_type": "catalog_item", "entity_id": "93001"}]
    assert offer(client, "ontop", {"vertical": "turbo", "items": items}).status_code == 204


def test_ontop_needs_the_order(client):
    assert offer(client, "ontop", {"vertical": "restaurantes", "items": []}).status_code == 422
    assert offer(client, "ontop", {"items": [{"entity_type": "menu_item", "entity_id": "1"}]}).status_code == 422
