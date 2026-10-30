"""Los flujos del pedido de la fase 8 (migración 050): cancelar (`order_cancelled`), que deja el pedido cancelado y
fuera de la recompra, el motor y los segmentos; la calificación de un pedido por tienda; y programar, el tipo de
entrega y la preferencia de sustitución en `POST /orders`. Sobre el catálogo de prueba (`seed_demo`)."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime, time, timedelta

import pytest

from owner_client import OwnerClient
from rappi_ia.analytics import queries
from rappi_ia.api import app as api
from rappi_ia.api import identity
from rappi_ia.demo.seed import seed_demo
from rappi_ia.events import store as events
from rappi_ia.motor.build import refresh_user_conn
from rappi_ia.motor.data import load_orders
from rappi_ia.motor.model import TZ
from rappi_ia.offers import autonomy
from rappi_ia.offers.winback import paused

USER = "u-flujos"
COFFEE = ("catalog_item", "91004")  # café molido, en el súper Centro
ICE_CREAM = ("catalog_item", "93001")  # helado, solo en Turbo
SUPER_CENTRO, TURBO_CENTRO = 9101, 9301


@pytest.fixture
def client(db):
    seed_demo(db)

    def conn_override():
        yield db

    @contextmanager
    def shared():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    api.app.dependency_overrides[api.get_connector] = lambda: shared
    yield OwnerClient(api.app)
    api.app.dependency_overrides.clear()


def bought(db, vertical, entity, days_ago, store_id, cart, concept="cafe"):
    ts = datetime.combine(datetime.now(TZ).date() - timedelta(days=days_ago), time(12), TZ)
    line = {"entity_type": entity[0], "entity_id": entity[1], "concept_id": concept, "unit_price": 1990}
    events.record_order(db, USER, f"s-{days_ago}", cart, vertical, [{**line, "store_id": store_id}], ts=ts)


def cancel(client, cart, reason="ya_no", stage="antes_de_tienda", store_id=None, mode=None, vertical=None):
    payload = {"reason": reason, "stage": stage}
    payload |= {"store_id": store_id} if store_id is not None else {}
    payload |= {"mode": mode} if mode else {}
    event = {"type": "order_cancelled", "session_id": "s-c", "cart_id": cart, "surface": "tracking", "payload": payload}
    if vertical:
        event["vertical"] = vertical
    return client.post("/events", json={"user_id": USER, "events": [event]})


def statuses(db, cart):
    return dict(
        db.execute(
            """SELECT o.vertical, o.status FROM app_orders o WHERE o.user_id = %s AND o.cart_id = %s""", (USER, cart)
        ).fetchall()
    )


# ── cancelar ─────────────────────────────────────────────────────────────────
def test_cancelling_one_store_leaves_the_other_order_of_the_cart(client, db):
    bought(db, "supermercado", COFFEE, 0, SUPER_CENTRO, "c-dos")
    bought(db, "turbo", ICE_CREAM, 0, TURBO_CENTRO, "c-dos", concept="helados")

    assert cancel(client, "c-dos", reason="demora", stage="en_tienda", store_id=TURBO_CENTRO).status_code == 200

    assert statuses(db, "c-dos") == {"supermercado": "confirmado", "turbo": "cancelado"}
    reason, at = db.execute("SELECT cancel_reason, cancelled_at FROM app_orders WHERE status = 'cancelado'").fetchone()
    assert reason == "demora" and at is not None


def test_without_store_the_vertical_picks_the_order(client, db):
    bought(db, "supermercado", COFFEE, 0, SUPER_CENTRO, "c-dos")
    bought(db, "turbo", ICE_CREAM, 0, TURBO_CENTRO, "c-dos", concept="helados")

    cancel(client, "c-dos", vertical="turbo")

    assert statuses(db, "c-dos") == {"supermercado": "confirmado", "turbo": "cancelado"}


def test_a_cancellation_in_rappi_hoy_also_cancels_the_order(client, db):
    """Es lo que pasó con el pedido, no algo que se aprende: queda en los dos modos."""
    bought(db, "supermercado", COFFEE, 0, SUPER_CENTRO, "c-hoy")

    cancel(client, "c-hoy", mode="actual")

    assert statuses(db, "c-hoy") == {"supermercado": "cancelado"}


def test_a_repeated_cancellation_keeps_the_first_time(client, db):
    bought(db, "supermercado", COFFEE, 0, SUPER_CENTRO, "c-1")
    cancel(client, "c-1", reason="pago")
    first = db.execute("SELECT cancelled_at FROM app_orders").fetchone()[0]

    cancel(client, "c-1", reason="otro")

    assert db.execute("SELECT cancelled_at, cancel_reason FROM app_orders").fetchone() == (first, "pago")


@pytest.mark.parametrize(
    "payload",
    [
        {"reason": "no-existe", "stage": "antes_de_tienda"},
        {"reason": "ya_no", "stage": "en_camino"},
        {"reason": "ya_no"},
        {"reason": "ya_no", "stage": "antes_de_tienda", "store_id": "9101"},
        {"reason": "ya_no", "stage": "antes_de_tienda", "store_id": True},
    ],
)
def test_a_cancellation_that_is_not_one_is_rejected(client, db, payload):
    event = {"type": "order_cancelled", "session_id": "s-c", "cart_id": "c-x", "payload": payload}
    assert client.post("/events", json={"user_id": USER, "events": [event]}).status_code == 400


def test_a_cancellation_needs_its_order(client, db):
    event = {"type": "order_cancelled", "session_id": "s-c", "payload": {"reason": "ya_no", "stage": "programado"}}
    assert client.post("/events", json={"user_id": USER, "events": [event]}).status_code == 400


# ── un pedido cancelado no cuenta ────────────────────────────────────────────
def test_a_cancelled_order_does_not_count_for_the_motor_or_the_repeat(client, db):
    for n, days in enumerate((21, 14, 7)):
        bought(db, "supermercado", COFFEE, days, SUPER_CENTRO, f"c-{n}")
    refresh_user_conn(db, USER)
    assert db.execute("SELECT orders FROM replenishment WHERE user_id = %s", (USER,)).fetchone() == (3,)

    cancel(client, "c-2")  # el recálculo corre en segundo plano, con la conexión del test

    assert [o.cart_id for o in load_orders(db, "prototype", USER)] == ["c-0", "c-1"]
    assert db.execute("SELECT orders FROM replenishment WHERE user_id = %s", (USER,)).fetchone() in (None, (2,))
    assert db.execute("SELECT orders FROM user_vertical_affinity WHERE user_id = %s", (USER,)).fetchone() == (2,)


def test_a_cancellation_by_beacon_also_recalculates_the_motor(client, db):
    """Lo que quedó en cola al cerrar la pestaña llega por el beacon: también recalcula a la persona."""
    for n, days in enumerate((21, 14, 7)):
        bought(db, "supermercado", COFFEE, days, SUPER_CENTRO, f"c-{n}")
    refresh_user_conn(db, USER)
    payload = {"reason": "ya_no", "stage": "antes_de_tienda"}
    event = {"type": "order_cancelled", "session_id": "s-c", "cart_id": "c-2", "payload": payload}
    body = {"user_id": USER, "events": [event], "token": identity.sign(USER)}

    reply = client.post("/events/beacon", content=json.dumps(body), headers={"content-type": "text/plain"})

    assert reply.status_code == 204
    assert statuses(db, "c-2") == {"supermercado": "cancelado"}
    assert db.execute("SELECT orders FROM user_vertical_affinity WHERE user_id = %s", (USER,)).fetchone() == (2,)


def test_a_cancelled_order_is_not_the_usual_order_of_its_store(client, db):
    """ "Pedir por mí" repite el último pedido de la tienda: uno cancelado no es lo de siempre."""
    bought(db, "supermercado", COFFEE, 3, SUPER_CENTRO, "c-viejo")
    bought(db, "supermercado", ("catalog_item", "91002"), 0, SUPER_CENTRO, "c-nuevo", concept="galletas")
    cancel(client, "c-nuevo")

    found = autonomy.usual(db, USER, {"id": SUPER_CENTRO, "name": "Súper", "vertical": "supermercado"})
    assert [line["product"]["entity_id"] for line in found.lines] == [COFFEE[1]]


def test_a_cancelled_order_does_not_count_in_the_business_panel(client, db, monkeypatch):
    """El panel (analytics/queries.py y capa.v_embudo_sesion) tampoco cuenta un pedido cancelado: ni en los pedidos de
    30 días, la serie semanal, Pro y sin Pro, el embudo ni los autopedidos."""
    line = {"entity_type": COFFEE[0], "entity_id": COFFEE[1], "concept_id": "cafe", "unit_price": 1990}
    for cart in ("c-ok", "c-no"):
        steps = [
            events.Event(USER, cart, kind, vertical="supermercado", cart_id=cart, entity_type=COFFEE[0])
            for kind in ("cart_add", "checkout_start")
        ]
        events.record(db, steps)
        events.record_order(
            db,
            USER,
            cart,
            cart,
            "supermercado",
            [{**line, "store_id": SUPER_CENTRO}],
            pro=True,
            placed={"origin": autonomy.ORIGIN},
        )

    cancel(client, "c-no")

    assert queries.kpis(db, "prototype")["pedidos_30d"] == 1
    assert sum(week["pedidos"] for week in queries.weekly(db, "prototype")) == 1
    assert [row["piden"] for row in queries.funnel(db, "prototype")] == [1]
    assert queries.offers(db, "prototype")["autopedidos"] == {"pedidos": 1, "personas": 1}
    funnel = db.execute(
        """SELECT session_id, pedido, pedidos, monto_pedidos FROM capa.v_embudo_sesion
           WHERE user_id = %s AND session_id LIKE 'c-%%' ORDER BY 1""",
        (USER,),
    ).fetchall()
    assert funnel == [("c-no", False, 0, 0), ("c-ok", True, 1, 1990)]
    monkeypatch.setattr(queries, "MIN_GROUP_USERS", 1)  # una sola persona: el grupo sale igual
    [pro] = queries.pro_split(db, "prototype")["grupos"]
    assert (pro["grupo"], pro["pedidos_30d"], pro["recompra_pct"]) == ("pro", 1, 0)


# ── la calificación de un pedido por tienda ──────────────────────────────────
def test_a_rating_with_its_store_rates_only_that_order(client, db):
    bought(db, "supermercado", COFFEE, 0, SUPER_CENTRO, "c-dos")
    bought(db, "turbo", ICE_CREAM, 0, TURBO_CENTRO, "c-dos", concept="helados")
    event = {
        "type": "order_rated",
        "session_id": "s-r",
        "cart_id": "c-dos",
        "payload": {"stars": 2, "reasons": ["tarde"], "store_id": SUPER_CENTRO},
    }

    assert client.post("/events", json={"user_id": USER, "events": [event]}).status_code == 200

    rows = dict(db.execute("SELECT vertical, rating FROM app_orders WHERE cart_id = 'c-dos'").fetchall())
    assert rows == {"supermercado": 2, "turbo": None}


def test_a_cancelled_order_cannot_be_rated_nor_pause_the_repeat(client, db):
    """Un pedido cancelado no llegó: su calificación no queda y no pausa la recompra ni el "volver" de su tienda."""
    bought(db, "supermercado", COFFEE, 0, SUPER_CENTRO, "c-no")
    cancel(client, "c-no")
    event = {"type": "order_rated", "session_id": "s-r", "cart_id": "c-no", "payload": {"stars": 1}}

    assert client.post("/events", json={"user_id": USER, "events": [event]}).status_code == 200

    assert db.execute("SELECT rating FROM app_orders WHERE cart_id = 'c-no'").fetchone() == (None,)
    assert SUPER_CENTRO not in paused(db, USER).stores


# ── programar, tipo de entrega y sustitución ─────────────────────────────────
def order_body(**extra):
    line = {"entity_type": COFFEE[0], "entity_id": COFFEE[1], "store_id": SUPER_CENTRO, "qty": 1}
    line |= extra.pop("line", {})
    return {
        "user_id": USER,
        "session_id": "s-1",
        "cart_id": "c-p",
        "vertical": "supermercado",
        "lines": [line],
        **extra,
    }


def test_an_order_keeps_its_slot_its_delivery_type_and_the_substitution_of_each_line(client, db):
    slot = (datetime.now(UTC) + timedelta(hours=3)).replace(minute=0, second=0, microsecond=0)
    body = order_body(scheduled_for=slot.isoformat(), delivery_type="sin_prisa", line={"substitution": "reembolso"})

    assert client.post("/orders", json=body).status_code == 200

    assert db.execute("SELECT scheduled_for, delivery_type, status FROM app_orders").fetchone() == (
        slot,
        "sin_prisa",
        "confirmado",
    )
    assert db.execute("SELECT substitution FROM app_order_lines").fetchone() == ("reembolso",)


def test_a_slot_without_zone_is_utc_whatever_the_zone_of_the_session(client, db):
    """La API valida una hora sin zona como UTC: se guarda igual, aunque la sesión de Postgres esté en Santiago."""
    db.execute("SET TimeZone = 'America/Santiago'")
    slot = (datetime.now(UTC) + timedelta(hours=3)).replace(minute=0, second=0, microsecond=0)

    assert (
        client.post("/orders", json=order_body(scheduled_for=slot.replace(tzinfo=None).isoformat())).status_code == 200
    )

    assert db.execute("SELECT scheduled_for FROM app_orders").fetchone() == (slot,)


def test_an_order_for_now_has_no_slot(client, db):
    assert client.post("/orders", json=order_body()).status_code == 200
    assert db.execute("SELECT scheduled_for, delivery_type FROM app_orders").fetchone() == (None, None)


@pytest.mark.parametrize("hours", [-3, 24 * 3])
def test_a_slot_is_for_today_or_tomorrow(client, db, hours):
    slot = datetime.now(UTC) + timedelta(hours=hours)
    assert client.post("/orders", json=order_body(scheduled_for=slot.isoformat())).status_code == 400


@pytest.mark.parametrize("extra", [{"delivery_type": "express"}, {"line": {"substitution": "lo-que-sea"}}])
def test_an_unknown_delivery_type_or_substitution_is_rejected(client, db, extra):
    assert client.post("/orders", json=order_body(**extra)).status_code == 422


def test_an_order_by_mochi_is_never_scheduled(client, db):
    slot = datetime.now(UTC) + timedelta(hours=2)
    body = order_body(scheduled_for=slot.isoformat(), autopedido={"request_id": "r-1"})

    reply = client.post("/orders", json=body)

    assert reply.status_code == 400 and "no se programa" in reply.json()["detail"]
    assert db.execute("SELECT count(*) FROM app_orders").fetchone()[0] == 0
