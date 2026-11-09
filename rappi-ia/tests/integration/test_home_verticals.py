"""GET /profile/{id}/verticales: el orden de los accesos chicos de la Home según lo que más usa cada persona."""

import pytest
from fastapi.testclient import TestClient

from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.rappi_agent import RappiAgent
from rappi_ia.api import app as api
from rappi_ia.api import identity
from rappi_ia.api.services import Services
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.motor.combos import OWN_SIGNALS_ONLY
from rappi_ia.motor.home import HOME_FIXED, HOME_ORDERABLE, MIN_USE_DAYS, OWN_CONCEPT_GROUPS

FIXED_ORDER = ["supermercado", "farmacia", "mall", "licores", "conveniencia", "chocolateria"]
CHIPS = {"entity_type": "catalog_item", "entity_id": "91001"}
MEDICINE = {"entity_type": "catalog_item", "entity_id": "95001", "concept_id": "medicamentos"}  # el paracetamol
BEER = {"entity_type": "catalog_item", "entity_id": "94001", "concept_id": "cerveza"}
# Unos Doritos de una botillería (la tarea 1 de la prueba con personas): un snack, no un trago.
DORITOS = {"entity_type": "catalog_item", "entity_id": "91001", "concept_id": "snacks-salados"}


@pytest.fixture
def client(db):
    seed_demo(db)
    embedder = HashEmbedder()

    def conn_override():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    api.app.dependency_overrides[api.get_services] = lambda: Services(
        RappiAgent(embedder, TemplateComposer()), embedder
    )
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def person(user_id: str = "u-home") -> tuple[str, dict]:
    return user_id, {"X-User-Token": identity.sign(user_id)}


def order(client, who, vertical: str, n: int, mode: str = "propuesta", line: dict = CHIPS) -> None:
    user_id, headers = who
    body = {
        "user_id": user_id,
        "session_id": f"s-{vertical}-{n}",
        "cart_id": f"c-{vertical}-{n}-{mode}",
        "vertical": vertical,
        "lines": [line],
        "mode": mode,
    }
    assert client.post("/orders", json=body, headers=headers).status_code == 200


def visit(client, db, who, vertical: str, days_ago: int, kind: str = "vertical_open", product: dict | None = None):
    """Un evento de hace `days_ago` días (la API los guarda con la hora de llegada: se atrasa en la base)."""
    user_id, headers = who
    session = f"s-{vertical}-{kind}-{days_ago}"
    event = {"type": kind, "session_id": session, "vertical": vertical, **(product or {})}
    assert client.post("/events", json={"user_id": user_id, "events": [event]}, headers=headers).status_code == 200
    db.execute(
        "UPDATE app_events SET ts = ts - make_interval(days => %s) WHERE user_id = %s AND session_id = %s",
        (days_ago, user_id, session),
    )


def verticales(client, who) -> dict:
    user_id, headers = who
    reply = client.get(f"/profile/{user_id}/verticales", headers=headers)
    assert reply.status_code == 200, reply.text
    return reply.json()


def test_constants():
    assert HOME_FIXED == ("restaurantes", "turbo")
    assert tuple(FIXED_ORDER) == HOME_ORDERABLE
    assert MIN_USE_DAYS == 2
    assert set(OWN_CONCEPT_GROUPS) == OWN_SIGNALS_ONLY


def test_new_person_gets_the_fixed_order(client):
    body = verticales(client, person())
    assert body["fixed"] == ["restaurantes", "turbo"]
    assert [v["id"] for v in body["order"]] == FIXED_ORDER
    assert body["personalized"] is False
    assert all(v["reason"] is None for v in body["order"])


def test_pharmacy_orders_put_pharmacy_first(client):
    who = person()
    for n in range(3):
        order(client, who, "farmacia", n, line=MEDICINE)
    body = verticales(client, who)
    assert [v["id"] for v in body["order"]][0] == "farmacia"
    assert sorted(v["id"] for v in body["order"]) == sorted(FIXED_ORDER)
    assert body["personalized"] is True
    first, *rest = body["order"]
    assert first["reason"] == {
        "text": "Porque pides seguido en farmacia.",
        "basis": [{"kind": "afinidad_vertical", "id": "farmacia", "source": "eventos"}],
    }
    assert first["score"] > 0 and all(v["reason"] is None for v in rest)


def test_used_verticals_go_by_own_use(client):
    """Entre los que la persona usa, primero el que más usa; después el resto, en el orden de siempre."""
    who = person()
    for n in range(3):
        order(client, who, "farmacia", n, line=MEDICINE)
    order(client, who, "supermercado", 0)
    body = verticales(client, who)
    assert [v["id"] for v in body["order"]] == [
        "farmacia",
        "supermercado",
        "mall",
        "licores",
        "conveniencia",
        "chocolateria",
    ]
    assert body["order"][0]["reason"]["text"] == "Porque pides seguido en farmacia."


def test_heavy_restaurant_user_sees_own_use_first(client, db):
    """Con muchos pedidos de Restaurantes (y una población que después de Restaurantes pide Súper), manda el uso
    propio: Farmacia (3 pedidos) antes que Súper (2), y el texto dice la verdad."""
    db.execute(
        """INSERT INTO vertical_transitions (data_source, from_vertical, to_vertical, n, prob)
           VALUES ('synthetic', 'restaurantes', 'supermercado', 10, 1.0),
                  ('prototype', 'restaurantes', 'supermercado', 10, 1.0)"""
    )
    who = person()
    for n in range(3):
        order(client, who, "farmacia", n, line=MEDICINE)
    for n in range(2):
        order(client, who, "supermercado", n)
    for n in range(8):
        order(client, who, "restaurantes", n)
    body = verticales(client, who)
    assert [v["id"] for v in body["order"]][:2] == ["farmacia", "supermercado"]
    assert body["order"][0]["reason"]["text"] == "Porque pides seguido en farmacia."


def test_restaurant_orders_alone_keep_the_fixed_order(client):
    """Restaurantes va fijo arriba: sin afinidad entre los 6, el orden es el de siempre."""
    who = person()
    for n in range(3):
        order(client, who, "restaurantes", n)
    body = verticales(client, who)
    assert [v["id"] for v in body["order"]] == FIXED_ORDER
    assert body["personalized"] is False


def test_vertical_open_events_count(client, db):
    who = person()
    for days_ago in range(4):
        visit(client, db, who, "mall", days_ago)
    body = verticales(client, who)
    assert body["order"][0]["id"] == "mall"
    assert body["personalized"] is True
    # Sin pedidos en Rappi Mall, "pides seguido" sería falso (en la base real, 39 de 97 Home personalizadas)
    assert body["order"][0]["reason"]["text"] == "Porque entras seguido a Rappi Mall."


def test_opening_a_vertical_without_ordering_there_does_not_say_you_order(client, db):
    """Pedidos en Express y visitas al súper que pesan más: el súper va primero, pero no "pides seguido en el súper"."""
    who = person()
    order(client, who, "conveniencia", 0)
    for days_ago in range(8):
        visit(client, db, who, "supermercado", days_ago)
    body = verticales(client, who)
    assert [v["id"] for v in body["order"]][:2] == ["supermercado", "conveniencia"]
    assert body["order"][0]["reason"]["text"] == "Porque entras seguido al súper."


def test_one_visit_does_not_reorder(client):
    """Ver y agregar al carro el mismo día (aunque sean varias sesiones) no es "entrar seguido": la Home no cambia."""
    who = person()
    events = [
        {"type": kind, "session_id": f"s{n}", "vertical": "supermercado", **CHIPS}
        for n, kind in enumerate(("search", "view_store", "view_item", "cart_add", "vertical_open"))
    ]
    assert client.post("/events", json={"user_id": who[0], "events": events}, headers=who[1]).status_code == 200
    body = verticales(client, who)
    assert [v["id"] for v in body["order"]] == FIXED_ORDER
    assert body["personalized"] is False
    assert all(v["reason"] is None for v in body["order"])


def test_visits_on_two_days_reorder(client, db):
    """Con señales en `MIN_USE_DAYS` días distintos sí: el súper sube y Mochi dice "entras seguido"."""
    who = person()
    visit(client, db, who, "supermercado", 0, "cart_add", CHIPS)
    visit(client, db, who, "supermercado", 3, "view_item", CHIPS)
    body = verticales(client, who)
    assert body["order"][0]["id"] == "supermercado"
    assert body["personalized"] is True
    assert body["order"][0]["reason"]["text"] == "Porque entras seguido al súper."


def test_doritos_from_a_liquor_store_do_not_move_licores(client, db):
    """Unos Doritos de una botillería no son uso de Licores: ni vistos y agregados en un día, ni en varios días, ni
    pedidos. La Home no cambia y Mochi no dice "entras seguido a Licores"."""
    who = person()
    visit(client, db, who, "licores", 0, "view_item", DORITOS)
    visit(client, db, who, "licores", 0, "cart_add", DORITOS)
    assert verticales(client, who)["personalized"] is False
    visit(client, db, who, "licores", 4, "cart_add", DORITOS)
    visit(client, db, who, "licores", 9, "view_store")  # entrar a la tienda no trae concepto: tampoco cuenta
    order(client, who, "licores", 0, line=DORITOS)
    body = verticales(client, who)
    assert [v["id"] for v in body["order"]] == FIXED_ORDER
    assert body["personalized"] is False
    assert all(v["reason"] is None for v in body["order"])


def test_alcohol_in_licores_counts(client, db):
    """Lo propio de Licores sí cuenta: cerveza agregada en dos días la sube con "entras seguido" y un pedido de
    cerveza, con "pides seguido"."""
    who = person()
    visit(client, db, who, "licores", 0, "cart_add", BEER)
    visit(client, db, who, "licores", 2, "cart_add", BEER)
    body = verticales(client, who)
    assert body["order"][0]["id"] == "licores"
    assert body["order"][0]["reason"]["text"] == "Porque entras seguido a Licores."
    order(client, who, "licores", 0, line=BEER)
    assert verticales(client, who)["order"][0]["reason"]["text"] == "Porque pides seguido en Licores."


def test_pharmacy_needs_its_own_concepts(client, db):
    """Farmacia igual: unas papas pedidas o agregadas en una farmacia no la suben; tocar su acceso en dos días, sí."""
    who = person()
    order(client, who, "farmacia", 0)
    visit(client, db, who, "farmacia", 3, "cart_add", CHIPS)
    assert verticales(client, who)["personalized"] is False
    visit(client, db, who, "farmacia", 1)
    visit(client, db, who, "farmacia", 5)
    body = verticales(client, who)
    assert body["order"][0]["id"] == "farmacia"
    assert body["order"][0]["reason"]["text"] == "Porque entras seguido a farmacia."


def test_actual_mode_does_not_reorder(client):
    who = person()
    for n in range(3):
        order(client, who, "farmacia", n, mode="actual")
    body = verticales(client, who)
    assert [v["id"] for v in body["order"]] == FIXED_ORDER
    assert body["personalized"] is False


def test_actual_mode_events_do_not_reorder(client):
    """Un toque en "Rappi hoy" llega con `payload.mode = 'actual'`: no enseña."""
    who = person()
    events = [
        {"type": "vertical_open", "session_id": f"s{n}", "vertical": "mall", "payload": {"mode": "actual"}}
        for n in range(4)
    ]
    assert client.post("/events", json={"user_id": who[0], "events": events}, headers=who[1]).status_code == 200
    body = verticales(client, who)
    assert [v["id"] for v in body["order"]] == FIXED_ORDER
    assert body["personalized"] is False


def test_mochi_explaining_a_move_or_being_hidden_is_saved_and_does_not_reorder(client, db):
    """`vertical_reorder_shown` (Mochi dijo por qué movió un acceso) y `agent_visibility` (ocultarlo o traerlo de
    vuelta) llegan por /events con su sobre (migración 052), pero no enseñan: el orden sigue siendo el fijo."""
    who = person()
    events = [
        {
            "type": "vertical_reorder_shown",
            "session_id": "s-mueve",
            "vertical": "mall",
            "surface": "home",
            "origin": "agent-reorden",
            "position": 0,
            "request_id": "abc123",
            "payload": {"antes": 2},
        },
        {"type": "agent_visibility", "session_id": "s-mueve", "origin": "cuenta", "payload": {"visible": False}},
    ]
    reply = client.post("/events", json={"user_id": who[0], "events": events}, headers=who[1])
    assert reply.status_code == 200, reply.text
    rows = db.execute(
        """SELECT type, vertical, position, payload FROM app_events
           WHERE user_id = %s AND type IN ('vertical_reorder_shown', 'agent_visibility') ORDER BY type""",
        (who[0],),
    ).fetchall()
    assert rows == [
        ("agent_visibility", None, None, {"visible": False}),
        ("vertical_reorder_shown", "mall", 0, {"antes": 2}),
    ]
    body = verticales(client, who)
    assert [v["id"] for v in body["order"]] == FIXED_ORDER
    assert body["personalized"] is False


def test_other_person_is_403(client):
    alice, _ = person("u-alice")
    _, as_bob = person("u-bob")
    reply = client.get(f"/profile/{alice}/verticales", headers=as_bob)
    assert (reply.status_code, reply.json()) == (403, {"detail": "No autorizado"})
    assert client.get(f"/profile/{alice}/verticales").status_code == 401
