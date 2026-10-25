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
from rappi_ia.motor.home import HOME_FIXED, HOME_ORDERABLE

FIXED_ORDER = ["supermercado", "farmacia", "mall", "licores", "conveniencia", "chocolateria"]
CHIPS = {"entity_type": "catalog_item", "entity_id": "91001"}


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


def order(client, who, vertical: str, n: int, mode: str = "propuesta") -> None:
    user_id, headers = who
    body = {
        "user_id": user_id,
        "session_id": f"s-{vertical}-{n}",
        "cart_id": f"c-{vertical}-{n}-{mode}",
        "vertical": vertical,
        "lines": [CHIPS],
        "mode": mode,
    }
    assert client.post("/orders", json=body, headers=headers).status_code == 200


def verticales(client, who) -> dict:
    user_id, headers = who
    reply = client.get(f"/profile/{user_id}/verticales", headers=headers)
    assert reply.status_code == 200, reply.text
    return reply.json()


def test_constants():
    assert HOME_FIXED == ("restaurantes", "turbo")
    assert tuple(FIXED_ORDER) == HOME_ORDERABLE


def test_new_person_gets_the_fixed_order(client):
    body = verticales(client, person())
    assert body["fixed"] == ["restaurantes", "turbo"]
    assert [v["id"] for v in body["order"]] == FIXED_ORDER
    assert body["personalized"] is False
    assert all(v["reason"] is None for v in body["order"])


def test_pharmacy_orders_put_pharmacy_first(client):
    who = person()
    for n in range(3):
        order(client, who, "farmacia", n)
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
        order(client, who, "farmacia", n)
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
        order(client, who, "farmacia", n)
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


def test_vertical_open_events_count(client):
    who = person()
    events = [{"type": "vertical_open", "session_id": f"s{n}", "vertical": "mall"} for n in range(4)]
    assert client.post("/events", json={"user_id": who[0], "events": events}, headers=who[1]).status_code == 200
    body = verticales(client, who)
    assert body["order"][0]["id"] == "mall"
    assert body["personalized"] is True
    # Sin pedidos en Rappi Mall, «pides seguido» sería falso (en la base real, 39 de 97 Home personalizadas)
    assert body["order"][0]["reason"]["text"] == "Porque entras seguido a Rappi Mall."


def test_opening_a_vertical_without_ordering_there_does_not_say_you_order(client):
    """Pedidos en Express y visitas al súper que pesan más: el súper va primero, pero no «pides seguido en el súper»."""
    who = person()
    order(client, who, "conveniencia", 0)
    events = [{"type": "vertical_open", "session_id": f"s{n}", "vertical": "supermercado"} for n in range(8)]
    assert client.post("/events", json={"user_id": who[0], "events": events}, headers=who[1]).status_code == 200
    body = verticales(client, who)
    assert [v["id"] for v in body["order"]][:2] == ["supermercado", "conveniencia"]
    assert body["order"][0]["reason"]["text"] == "Porque entras seguido al súper."


def test_actual_mode_does_not_reorder(client):
    who = person()
    for n in range(3):
        order(client, who, "farmacia", n, mode="actual")
    body = verticales(client, who)
    assert [v["id"] for v in body["order"]] == FIXED_ORDER
    assert body["personalized"] is False


def test_actual_mode_events_do_not_reorder(client):
    """Un toque en «Rappi hoy» llega con `payload.mode = 'actual'`: no enseña."""
    who = person()
    events = [
        {"type": "vertical_open", "session_id": f"s{n}", "vertical": "mall", "payload": {"mode": "actual"}}
        for n in range(4)
    ]
    assert client.post("/events", json={"user_id": who[0], "events": events}, headers=who[1]).status_code == 200
    body = verticales(client, who)
    assert [v["id"] for v in body["order"]] == FIXED_ORDER
    assert body["personalized"] is False


def test_other_person_is_403(client):
    alice, _ = person("u-alice")
    _, as_bob = person("u-bob")
    reply = client.get(f"/profile/{alice}/verticales", headers=as_bob)
    assert (reply.status_code, reply.json()) == (403, {"detail": "No autorizado"})
    assert client.get(f"/profile/{alice}/verticales").status_code == 401
