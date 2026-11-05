""" "Pedir por mí" (offers/autonomy.py, migración 049) sobre el catálogo de prueba: por defecto Mochi deja revisar
antes; con permiso pide solo "lo de siempre" en las tiendas elegidas, hasta el tope, sin alcohol, +18, farmacia ni bebé,
ni en una tienda cerrada o bajo la compra mínima, y `POST /orders` lo vuelve a revisar todo. Se apaga en un toque y se
va con "Olvidar" y la purga."""

from contextlib import contextmanager
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import psycopg
import pytest

from owner_client import OwnerClient
from rappi_ia import delivery
from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.rappi_agent import RappiAgent
from rappi_ia.analytics import queries
from rappi_ia.api import app as api
from rappi_ia.api.services import Services
from rappi_ia.catalog import hours
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.events import store as events
from rappi_ia.motor.build import refresh_user_conn
from rappi_ia.motor.model import TZ

USER = "u-autonomia"
CENTRO, NORTE = 9101, 9102  # súper de prueba: sin mínimo y con mínimo de $8.490
COFFEE = {"entity_type": "catalog_item", "entity_id": "91004", "qty": 1}  # $3.990 en el Centro


@pytest.fixture
def client(db):
    seed_demo(db)
    db.commit()
    embedder = HashEmbedder()

    def conn_override():
        yield db

    @contextmanager
    def shared_connection():  # el recálculo después de un pedido, con la conexión del test
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    api.app.dependency_overrides[api.get_connector] = lambda: shared_connection
    api.app.dependency_overrides[api.get_services] = lambda: Services(
        RappiAgent(embedder, TemplateComposer()), embedder
    )
    yield OwnerClient(api.app)
    api.app.dependency_overrides.clear()


def order(client, store_id, vertical, *lines, user=USER, cart="c-1", **extra):
    body = {
        "user_id": user,
        "session_id": "s-autonomia",
        "cart_id": cart,
        "vertical": vertical,
        "lines": [{**line, "store_id": store_id} for line in lines],
        **extra,
    }
    return client.post("/orders", json=body)


def say(client, message, user=USER, mode="propuesta"):
    body = {"message": message, "user_id": user, "session_id": "s-autonomia", "mode": mode}
    reply = client.post("/agent/ask", json=body)
    assert reply.status_code == 200, reply.text
    return reply.json()


def allow(client, stores, cap=20_000, user=USER):
    reply = client.put(f"/profile/{user}/autonomia", json={"tiendas": stores, "tope": cap})
    assert reply.status_code == 200, reply.text
    return reply.json()


def orders_of(db, user=USER):
    return db.execute("SELECT count(*) FROM app_orders WHERE user_id = %s", (user,)).fetchone()[0]


def test_by_default_mochi_leaves_it_to_review(client, db):
    assert order(client, CENTRO, "supermercado", COFFEE).status_code == 200
    setting = client.get(f"/profile/{USER}/autonomia").json()
    assert setting["modo"] == "revisar" and setting["tiendas"] == [] and setting["tope"] is None
    assert [s["id"] for s in setting["opciones"]["tiendas"]] == [CENTRO]

    reply = say(client, "pide lo de siempre en el supermercado de prueba centro")
    assert reply["intent"]["kind"] == "autopedido"
    plan = reply["autopedido"]
    assert plan["modo"] == "revisar" and plan["codigo"] == "sin_permiso"
    assert plan["tienda"] == {"id": CENTRO, "name": "Supermercado de prueba Centro", "vertical": "supermercado"}
    assert [(line["product"]["entity_id"], line["qty"]) for line in plan["lineas"]] == [("91004", 1)]
    assert plan["subtotal"] == 3990 and plan["basis"] == []
    assert "Revísalo antes de pedir" in reply["text"]
    assert reply["actions"] == [{"label": "Cómo pido por ti", "panel": "autonomia"}]
    assert orders_of(db) == 1  # armarlo no pide nada


def test_with_permission_it_orders_alone_and_the_order_says_so(client, db):
    order(client, CENTRO, "supermercado", {**COFFEE, "qty": 2})
    assert allow(client, [CENTRO])["modo"] == "pedir"

    reply = say(client, "pídeme lo de siempre")  # sin tienda: la de su último pedido
    plan = reply["autopedido"]
    assert plan["modo"] == "pedir" and plan["subtotal"] == 7980 and plan["tope"] == 20000
    assert "dentro de tu tope de $20.000" in reply["text"]
    assert {(b["kind"], b["id"]) for b in plan["basis"]} >= {
        ("permiso", "pedir-por-mi"),
        ("tope", "20000"),
        ("regla", "lo-de-siempre"),
    }
    assert orders_of(db) == 1  # la API no pide: la app espera la ventana de deshacer

    twice = {**COFFEE, "qty": 2}
    placed = order(client, CENTRO, "supermercado", twice, cart="c-auto", autopedido={"request_id": "r-1"})
    assert placed.status_code == 200, placed.text
    origin, surface, request_id, payload = db.execute(
        """SELECT origin, surface, request_id, payload FROM app_events
           WHERE user_id = %s AND type = 'order_placed' AND cart_id = 'c-auto'""",
        (USER,),
    ).fetchone()
    assert (origin, surface, request_id) == ("agent-autopedido", "agent", "r-1")
    assert payload["autopedido"] is True
    assert {"kind": "tope", "id": "20000", "source": "persona"} in payload["basis"]
    # El panel los cuenta aparte de las ofertas aceptadas.
    assert queries.offers(db, "prototype")["autopedidos"] == {"pedidos": 1, "personas": 1}


def test_never_over_the_cap(client, db):
    order(client, CENTRO, "supermercado", COFFEE)
    allow(client, [CENTRO], cap=3000)
    plan = say(client, "lo de siempre en el centro")["autopedido"]
    assert plan["modo"] == "revisar" and plan["codigo"] == "tope"
    assert "pasa tu tope de $3.000" in plan["motivo"]
    # Aunque la app insista, la API no lo pide.
    rejected = order(client, CENTRO, "supermercado", COFFEE, cart="c-auto", autopedido={})
    assert rejected.status_code == 409 and rejected.json()["detail"]["codigo"] == "tope"
    assert orders_of(db) == 1


@pytest.mark.parametrize(
    "line",
    [
        {"entity_type": "catalog_item", "entity_id": "94001", "qty": 1},  # cerveza: +18
        {"entity_type": "catalog_item", "entity_id": "91007", "qty": 1},  # pañales: bebé
    ],
)
def test_never_alcohol_or_baby(client, line):
    order(client, CENTRO, "supermercado", COFFEE, line)
    allow(client, [CENTRO])
    plan = say(client, "pide lo de siempre en el supermercado de prueba centro")["autopedido"]
    assert plan["modo"] == "revisar" and plan["codigo"] == "guardia"
    rejected = order(client, CENTRO, "supermercado", COFFEE, line, cart="c-auto", autopedido={})
    assert rejected.status_code == 409


def test_never_a_spirits_pack_labelled_as_juice(client, db):
    """En la base del 04-11-2026, "Eristoff 40 750cc + Bebida o Jugo 1.5lt" tenía concepto jugos y ninguna marca +18:
    el nombre lo dice (offers/guards.py, ALCOHOL_NAME_WORDS)."""
    juice = {"entity_type": "catalog_item", "entity_id": "91005", "qty": 1}
    db.execute(
        "UPDATE catalog_items SET name = 'Eristoff 40 750cc + Bebida o Jugo 1.5lt', is_alcoholic = false,"
        " age_restricted = false WHERE master_product_id = 91005"
    )
    order(client, CENTRO, "supermercado", COFFEE, juice)
    allow(client, [CENTRO])
    plan = say(client, "pide lo de siempre en el supermercado de prueba centro")["autopedido"]
    assert plan["modo"] == "revisar" and plan["codigo"] == "guardia"
    rejected = order(client, CENTRO, "supermercado", COFFEE, juice, cart="c-auto", autopedido={})
    assert rejected.status_code == 409


def test_a_pharmacy_cannot_be_chosen(client):
    paracetamol = {"entity_type": "catalog_item", "entity_id": "95001", "qty": 1}
    order(client, 9501, "farmacia", paracetamol)
    order(client, CENTRO, "supermercado", COFFEE, cart="c-2")
    options = client.get(f"/profile/{USER}/autonomia").json()["opciones"]["tiendas"]
    assert [s["id"] for s in options] == [CENTRO]
    reply = client.put(f"/profile/{USER}/autonomia", json={"tiendas": [9501], "tope": 20000})
    assert reply.status_code == 422
    allow(client, [CENTRO])
    assert say(client, "lo de siempre en la farmacia de prueba")["autopedido"]["codigo"] == "tienda_no_elegida"


def test_only_in_the_chosen_stores(client, db):
    galletas = {"entity_type": "catalog_item", "entity_id": "91002", "qty": 8}
    order(client, CENTRO, "supermercado", COFFEE)
    order(client, NORTE, "supermercado", galletas, cart="c-2")
    allow(client, [CENTRO])
    plan = say(client, "pide lo de siempre en el supermercado de prueba norte")["autopedido"]
    assert plan["tienda"]["id"] == NORTE and plan["codigo"] == "tienda_no_elegida"
    rejected = order(client, NORTE, "supermercado", galletas, cart="c-auto", autopedido={})
    assert rejected.status_code == 409 and rejected.json()["detail"]["codigo"] == "tienda_no_elegida"


def test_never_under_the_minimum(client):
    galletas = {"entity_type": "catalog_item", "entity_id": "91002", "qty": 1}  # $1.790 en el Norte (mínimo $8.490)
    order(client, NORTE, "supermercado", galletas)
    allow(client, [NORTE])
    plan = say(client, "pide lo de siempre en el norte")["autopedido"]
    assert plan["codigo"] == "minimo" and "$8.490" in plan["motivo"]


def test_never_in_a_closed_store(client, monkeypatch):
    aros = {"entity_type": "catalog_item", "entity_id": "96002", "qty": 1}  # la tienda mall Centro, cerrada al bajarla
    order(client, 9601, "mall", aros)
    pizza = {"entity_type": "menu_item", "entity_id": "98001", "qty": 1}  # la Pizzería abre de 11:00 a 23:30
    order(client, 9801, "restaurantes", pizza, cart="c-2")
    allow(client, [9601, 9801])
    assert say(client, "lo de siempre en la tienda mall")["autopedido"]["codigo"] == "cerrada"
    assert say(client, "lo de siempre en la pizzeria")["autopedido"]["modo"] == "pedir"  # jueves 13:00
    monkeypatch.setattr(hours, "now_local", lambda: datetime(2026, 10, 22, 5, 0, tzinfo=ZoneInfo("America/Santiago")))
    plan = say(client, "lo de siempre en la pizzeria")["autopedido"]
    assert plan["codigo"] == "cerrada" and "según el horario que publicó" in plan["motivo"]


def test_not_alone_after_a_bad_rating_of_that_store(client, db):
    """Como la recompra y el "volver" (`winback.paused`): una tienda que calificó mal hace poco se revisa antes."""
    order(client, CENTRO, "supermercado", COFFEE)
    allow(client, [CENTRO])
    rating = {"type": "order_rated", "session_id": "s-r", "cart_id": "c-1"}
    rating["payload"] = {"stars": 2, "reasons": ["faltante"], "store_id": CENTRO}
    assert client.post("/events", json={"user_id": USER, "events": [rating]}).status_code == 200

    plan = say(client, "pide lo de siempre en el supermercado de prueba centro")["autopedido"]

    assert plan["modo"] == "revisar" and plan["codigo"] == "calificacion"
    assert "calificaste mal un pedido de Supermercado de prueba Centro" in plan["motivo"]
    rejected = order(client, CENTRO, "supermercado", COFFEE, cart="c-auto", autopedido={})
    assert rejected.status_code == 409 and rejected.json()["detail"]["codigo"] == "calificacion"


def test_only_the_usual_and_undo_sends_nothing(client, db):
    order(client, CENTRO, "supermercado", COFFEE)
    allow(client, [CENTRO])
    assert say(client, "lo de siempre")["autopedido"]["modo"] == "pedir"
    # Deshacer es no mandar el pedido: nada queda.
    assert orders_of(db) == 1
    # Otra cantidad u otro producto ya no es lo de siempre.
    rejected = order(client, CENTRO, "supermercado", {**COFFEE, "qty": 3}, cart="c-auto", autopedido={})
    assert rejected.status_code == 409 and rejected.json()["detail"]["codigo"] == "distinto"
    # En "Rappi hoy" tampoco.
    rejected = order(client, CENTRO, "supermercado", COFFEE, cart="c-auto", autopedido={}, mode="actual")
    assert rejected.status_code == 409
    assert orders_of(db) == 1


def test_it_turns_off_in_one_tap(client):
    order(client, CENTRO, "supermercado", COFFEE)
    allow(client, [CENTRO])
    assert client.delete(f"/profile/{USER}/autonomia").json()["modo"] == "revisar"
    assert say(client, "lo de siempre")["autopedido"]["codigo"] == "sin_permiso"


def test_not_in_rappi_today(client):
    order(client, CENTRO, "supermercado", COFFEE)
    allow(client, [CENTRO])
    reply = say(client, "pide lo de siempre", mode="actual")
    assert "autopedido" not in reply and "Rappi hoy" in reply["text"]


def test_it_goes_with_forget_and_the_purge(client, db):
    def saved():
        return db.execute("SELECT count(*) FROM agent_autonomy WHERE user_id = %s", (USER,)).fetchone()[0]

    order(client, CENTRO, "supermercado", COFFEE)
    allow(client, [CENTRO])
    assert client.delete(f"/profile/{USER}?concept=cafe").status_code == 200
    assert saved() == 1  # olvidar un concepto no apaga el permiso
    assert client.delete(f"/profile/{USER}").status_code == 200
    assert saved() == 0
    order(client, CENTRO, "supermercado", COFFEE)
    allow(client, [CENTRO])
    db.execute("UPDATE app_users SET created_at = now() - interval '400 days' WHERE user_id = %s", (USER,))
    db.execute("UPDATE app_events SET ts = now() - interval '400 days' WHERE user_id = %s", (USER,))
    db.execute("UPDATE app_orders SET ts = now() - interval '400 days' WHERE user_id = %s", (USER,))
    assert events.purge_inactive_users(db, 30) == 1
    assert saved() == 0


def test_populations_never_mix(client, db):
    db.execute("INSERT INTO app_users (user_id, source) VALUES ('u-simulada', 'synthetic')")
    db.commit()
    reply = client.put("/profile/u-simulada/autonomia", json={"tiendas": [CENTRO], "tope": 20000})
    assert reply.status_code == 400
    with pytest.raises(psycopg.errors.RaiseException), db.transaction():
        db.execute(
            "INSERT INTO agent_autonomy (user_id, store_ids, max_total, source)"
            " VALUES ('u-simulada', ARRAY[9101], 20000, 'prototype')"
        )


def test_it_is_a_person_table(db):
    assert "agent_autonomy" in delivery.PERSON_TABLES
    assert delivery.unknown_person_tables(db) == []
    comment = db.execute("SELECT obj_description('agent_autonomy'::regclass)").fetchone()[0]
    assert "PERSON_TABLES" in comment


def test_the_repeat_offer_suggests_it_in_a_chosen_store(client, db):
    today = datetime.now(TZ).date()
    coffee = {**COFFEE, "concept_id": "cafe", "store_id": CENTRO}
    for days in (21, 14, 7):
        ts = datetime.combine(today - timedelta(days=days), time(12), TZ)
        events.record_order(db, USER, f"s-{days}", f"c-{days}", "supermercado", [coffee], ts=ts)
    refresh_user_conn(db, USER)
    db.commit()

    def actions():
        reply = client.post("/agent/offer", json={"moment": "recompra", "user_id": USER, "context": {}})
        assert reply.status_code == 200, reply.text
        return reply.json()["actions"]

    assert all("ask" not in action for action in actions())
    allow(client, [CENTRO])
    assert actions()[-1] == {
        "label": "Pide lo de siempre por mí",
        "ask": "Pide lo de siempre en Supermercado de prueba Centro",
    }


def test_the_stores_ordered_from_are_options_for_favorites(client, db):
    """ "Mis preferencias" ofrece marcar como favoritas las tiendas donde ya pidió (sin escribirlas), y marcarla la
    guarda."""
    before = client.get(f"/profile/{USER}/preferencias").json()
    assert not any(o["tipo"] == "tienda" for o in before["opciones"])
    assert order(client, CENTRO, "supermercado", COFFEE).status_code == 200
    store = {"tipo": "tienda", "valor": "Supermercado de prueba Centro", "nombre": "Supermercado de prueba Centro"}
    assert store in client.get(f"/profile/{USER}/preferencias").json()["opciones"]
    saved = client.put(
        f"/profile/{USER}/preferencias", json={"preferencias": [{"tipo": "tienda", "valor": store["valor"]}]}
    )
    assert saved.json()["preferencias"] == [store]


def test_a_store_whose_only_order_was_cancelled_is_not_an_option(client):
    """Ni "Mis preferencias" ni "Pedir por mí" ofrecen una tienda de la que solo hay un pedido cancelado."""
    assert order(client, CENTRO, "supermercado", COFFEE).status_code == 200
    cancelled = {"type": "order_cancelled", "session_id": "s-c", "cart_id": "c-1"}
    cancelled["payload"] = {"reason": "ya_no", "stage": "antes_de_tienda"}
    assert client.post("/events", json={"user_id": USER, "events": [cancelled]}).status_code == 200

    options = client.get(f"/profile/{USER}/preferencias").json()["opciones"]
    assert not any(o["tipo"] == "tienda" for o in options)
    assert client.get(f"/profile/{USER}/autonomia").json()["opciones"]["tiendas"] == []
