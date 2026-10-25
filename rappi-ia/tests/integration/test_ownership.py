"""Identidad anónima firmada contra `rappi_ia_test`: un id ajeno (visto en un log, por ejemplo) ya no basta para leer,
escribir ni borrar los datos de otra persona. Cada persona saca su sesión con `POST /session`."""

import json
import logging
import re
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.rappi_agent import RappiAgent
from rappi_ia.api import app as api
from rappi_ia.api import identity
from rappi_ia.api.limits import RateLimit
from rappi_ia.api.services import Services
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder

LEGACY = "proto-0123456789abcdef"
NEW_ID = re.compile(r"proto-[0-9a-f]{16}")
APP_OPEN = [{"type": "app_open", "session_id": "s1"}]


@pytest.fixture
def client(db):
    seed_demo(db)
    embedder = HashEmbedder()

    def conn_override():
        yield db

    @contextmanager
    def shared_connection():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    api.app.dependency_overrides[api.get_connector] = lambda: shared_connection
    api.app.dependency_overrides[api.get_services] = lambda: Services(
        RappiAgent(embedder, TemplateComposer()), embedder
    )
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def session(client, legacy: str | None = None) -> tuple[str, dict]:
    """Una sesión nueva (o la del id viejo): el id y la cabecera con su token."""
    reply = client.post("/session", json={"legacy_user_id": legacy})
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert identity.verify(body["token"]) == body["user_id"]
    return body["user_id"], {"X-User-Token": body["token"]}


def events_of(db, user_id: str) -> int:
    return db.execute("SELECT count(*) FROM app_events WHERE user_id = %s", (user_id,)).fetchone()[0]


def test_delete_other_profile_is_403(client, db):
    alice, as_alice = session(client)
    _, as_bob = session(client)
    assert client.post("/events", json={"user_id": alice, "events": APP_OPEN}, headers=as_alice).status_code == 200

    for method in ("GET", "DELETE"):
        reply = client.request(method, f"/profile/{alice}", headers=as_bob)
        assert (reply.status_code, reply.json()) == (403, {"detail": "No autorizado"}), method
    assert events_of(db, alice) == 1

    assert client.get(f"/profile/{alice}", headers=as_alice).status_code == 200
    assert client.delete(f"/profile/{alice}", headers=as_alice).json()["eventos_borrados"] == 1


def test_get_other_recommendations_is_403(client):
    alice, as_alice = session(client)
    _, as_bob = session(client)
    offer = {"moment": "plan", "user_id": alice, "context": {"occasion": "carrete"}}
    ask = {"message": "cerveza", "user_id": alice, "session_id": "s1"}

    assert client.get("/recommendations", params={"user_id": alice}, headers=as_bob).status_code == 403
    assert client.get("/agent/plans", params={"user_id": alice}, headers=as_bob).status_code == 403
    assert client.post("/agent/offer", json=offer, headers=as_bob).status_code == 403
    assert client.post("/agent/ask", json=ask, headers=as_bob).status_code == 403

    assert client.get("/recommendations", params={"user_id": alice}, headers=as_alice).status_code == 200
    assert client.get("/agent/plans", params={"user_id": alice}, headers=as_alice).status_code == 200
    assert client.post("/agent/ask", json=ask, headers=as_alice).status_code == 200


def test_events_body_user_mismatch_is_403(client, db):
    alice, _ = session(client)
    _, as_bob = session(client)
    order = {
        "user_id": alice,
        "session_id": "s1",
        "cart_id": "c1",
        "vertical": "supermercado",
        "lines": [{"entity_type": "catalog_item", "entity_id": "91001"}],
    }

    assert client.post("/events", json={"user_id": alice, "events": APP_OPEN}, headers=as_bob).status_code == 403
    assert client.post("/orders", json=order, headers=as_bob).status_code == 403
    assert events_of(db, alice) == 0
    assert db.execute("SELECT count(*) FROM app_orders").fetchone()[0] == 0


def test_owner_is_decided_on_the_validated_body_not_on_the_query(client, db):
    """`?user_id=<mío>` con mi token y el cuerpo a nombre de otra persona: manda el `user_id` del cuerpo validado."""
    alice, _ = session(client)
    mallory, as_mallory = session(client)
    order = {
        "user_id": alice,
        "session_id": "s1",
        "cart_id": "c1",
        "vertical": "supermercado",
        "lines": [{"entity_type": "catalog_item", "entity_id": "91001"}],
    }
    mine = {"user_id": mallory}

    events = {"user_id": alice, "events": APP_OPEN}
    assert client.post("/events", params=mine, json=events, headers=as_mallory).status_code == 403
    assert client.post("/orders", params=mine, json=order, headers=as_mallory).status_code == 403
    ask = {"message": "cerveza", "user_id": alice, "session_id": "s1"}
    assert client.post("/agent/ask", params=mine, json=ask, headers=as_mallory).status_code == 403
    offer = {"moment": "plan", "user_id": alice, "context": {"occasion": "carrete"}}
    assert client.post("/agent/offer", params=mine, json=offer, headers=as_mallory).status_code == 403
    assert events_of(db, alice) == 0
    assert db.execute("SELECT count(*) FROM app_orders").fetchone()[0] == 0


def test_owner_is_decided_after_cleaning_the_body(client, db):
    """`{"user_id": <mío>, "user_id\\u0000": <otra>}`: la limpieza de \\x00 deja la segunda clave como `user_id`."""
    alice, _ = session(client)
    mallory, as_mallory = session(client)
    headers = {**as_mallory, "content-type": "application/json"}

    def smuggled(**fields) -> str:
        return json.dumps(fields)[:-1] + f', "user_id\\u0000": "{alice}"}}'

    events = smuggled(user_id=mallory, events=APP_OPEN)
    assert client.post("/events", content=events, headers=headers).status_code == 403
    order = smuggled(
        user_id=mallory,
        session_id="s1",
        cart_id="c1",
        vertical="supermercado",
        lines=[{"entity_type": "catalog_item", "entity_id": "91001"}],
    )
    assert client.post("/orders", content=order, headers=headers).status_code == 403
    ask = smuggled(message="cerveza", user_id=mallory, session_id="s1")
    assert client.post("/agent/ask", content=ask, headers=headers).status_code == 403
    assert events_of(db, alice) == 0
    assert db.execute("SELECT count(*) FROM app_orders").fetchone()[0] == 0


def test_missing_token_is_401(client, caplog):
    alice, as_alice = session(client)
    token = as_alice["X-User-Token"]
    forged = {"X-User-Token": f"{alice}.{'A' * 43}"}

    with caplog.at_level(logging.DEBUG):
        for headers in ({}, forged, {"X-User-Token": "basura"}):
            reply = client.get(f"/profile/{alice}", headers=headers)
            assert (reply.status_code, reply.json()) == (401, {"detail": "Falta la sesión"})
        assert client.post("/events", json={"user_id": alice, "events": APP_OPEN}).status_code == 401
        assert client.get("/recommendations", params={"user_id": alice}).status_code == 401

    # Ni el id ni el token quedan en los registros de la API (los de httpx son del cliente de prueba)
    logged = "\n".join(r.getMessage() for r in caplog.records if not r.name.startswith(("httpx", "httpcore")))
    assert "/profile/{user_id} 401" in logged
    assert alice not in logged and token not in logged


def test_legacy_id_claimed_once(client, db):
    db.execute("INSERT INTO app_users (user_id, source) VALUES (%s, 'prototype')", (LEGACY,))
    db.execute("INSERT INTO app_users (user_id, source) VALUES ('proto-fedcba9876543210', 'synthetic')")
    db.execute("INSERT INTO app_users (user_id, source) VALUES ('u-viejo', 'prototype')")
    db.commit()

    claimed, as_legacy = session(client, LEGACY)
    again, _ = session(client, LEGACY)

    assert claimed == LEGACY
    assert again != LEGACY and NEW_ID.fullmatch(again)
    assert client.get(f"/profile/{LEGACY}", headers=as_legacy).status_code == 200
    # Un usuario simulado, un id sin el formato del prototipo o uno que no existe nunca se reclaman
    for other in ("proto-fedcba9876543210", "u-viejo", "proto-1111111111111111"):
        user_id, _ = session(client, other)
        assert user_id != other and NEW_ID.fullmatch(user_id)
    # Un id ya firmado tampoco, aunque su fila se haya creado con el primer evento
    signed = "proto-2222222222222222"
    as_signed = {"X-User-Token": identity.sign(signed)}
    assert client.post("/events", json={"user_id": signed, "events": APP_OPEN}, headers=as_signed).status_code == 200
    assert session(client, signed)[0] != signed
    issued = db.execute("SELECT user_id FROM app_users WHERE token_issued_at IS NULL ORDER BY user_id").fetchall()
    assert issued == [("proto-fedcba9876543210",), ("u-viejo",)]


def test_new_users_per_ip_cap_is_429(client, monkeypatch):
    # Un cliente que no es este equipo (el TestClient llega como «testclient»): el tope de la API, con 2 por día
    monkeypatch.setattr(api, "NEW_USERS", RateLimit(None, per_minute=2, writes_per_minute=0, window_s=86_400))
    session(client)
    session(client)

    reply = client.post("/session", json={"legacy_user_id": None})

    assert reply.status_code == 429
    assert reply.json() == {"detail": "Demasiadas solicitudes; espera un momento."}
    assert int(reply.headers["Retry-After"]) > 60  # la ventana es de un día


def test_new_users_cap_spares_loopback_only_where_exempt(client, monkeypatch):
    monkeypatch.setattr(
        api, "NEW_USERS", RateLimit(None, per_minute=1, writes_per_minute=0, exempt=("127.0.0.1",), window_s=86_400)
    )
    local = TestClient(api.app, client=("127.0.0.1", 50000))
    for _ in range(3):
        session(local)
    session(client)
    assert client.post("/session", json={"legacy_user_id": None}).status_code == 429


def test_beacon_with_body_token(client, db):
    alice, as_alice = session(client)
    _, as_bob = session(client)
    headers = {"content-type": "text/plain;charset=UTF-8", "origin": "http://localhost:5174"}

    def beacon(token: str | None) -> int:
        body = {"user_id": alice, "events": APP_OPEN, **({"token": token} if token else {})}
        return client.post("/events/beacon", content=json.dumps(body), headers=headers).status_code

    assert beacon(None) == 401
    assert beacon(as_bob["X-User-Token"]) == 403
    assert events_of(db, alice) == 0
    assert beacon(as_alice["X-User-Token"]) == 204
    assert events_of(db, alice) == 1


def test_anonymous_ask_still_works(client, db):
    reply = client.post("/agent/ask", json={"message": "cerveza"})

    assert reply.status_code == 200 and reply.json()["text"]
    assert client.get("/agent/plans").status_code == 200
    assert client.post("/agent/offer", json={"moment": "plan", "context": {"occasion": "carrete"}}).status_code == 200
    assert db.execute("SELECT count(*) FROM app_users").fetchone()[0] == 0
