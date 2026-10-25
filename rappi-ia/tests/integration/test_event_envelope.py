"""El sobre de cada evento (migración 043): id, hora y orden del cliente, desde dónde, la respuesta que lo originó y la
sesión de la app (`app_sessions`)."""

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from rappi_scraper.storage.search import build_search_documents

from conftest import add_price, add_product, add_store
from owner_client import OwnerClient
from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.rappi_agent import RappiAgent
from rappi_ia.api import app as api
from rappi_ia.api.services import Services
from rappi_ia.concepts.pipeline import build_concepts
from rappi_ia.delivery import PERSON_TABLES, unknown_person_tables
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents
from rappi_ia.events import store as events
from rappi_ia.events.synth import generate


@pytest.fixture
def client(db):
    add_store(db, 1, "supermercado", "Súper")
    for pid, name, price in [(100, "Papas fritas Lays Clásicas 180 g", 1990), (101, "Ramitas Evercrisp 250 g", 1590)]:
        add_product(db, pid, name, 1, "Snacks salados")
        add_price(db, 1, pid, price)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embedder = HashEmbedder()
    embed_search_documents(db, embedder)

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
    yield OwnerClient(api.app)
    api.app.dependency_overrides.clear()


def _event(**extra):
    return {"type": "cart_add", "session_id": "s-sobre", "vertical": "grocery", "cart_id": "c1", **extra}


def test_a_retried_batch_does_not_duplicate_events(client, db):
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    batch = [_event(client_event_id=first, seq=0), _event(client_event_id=second, seq=1)]
    assert client.post("/events", json={"user_id": "u-sobre", "events": batch}).json() == {"guardados": 2}
    # El mismo lote otra vez (la app no supo si llegó) más uno nuevo: solo entra el nuevo.
    again = [*batch, _event(client_event_id=str(uuid.uuid4()), seq=2)]
    assert client.post("/events", json={"user_id": "u-sobre", "events": again}).json() == {"guardados": 1}
    rows = db.execute("SELECT seq FROM app_events WHERE user_id = 'u-sobre' ORDER BY seq").fetchall()
    assert rows == [(0,), (1,), (2,)]
    # Sin id (un cliente de antes) se guarda siempre, como hasta ahora.
    old = [_event(), _event()]
    assert client.post("/events", json={"user_id": "u-sobre", "events": old}).json() == {"guardados": 2}


def test_the_envelope_is_saved_with_the_event(client, db):
    when = datetime.now(UTC) - timedelta(minutes=3)
    event = _event(
        client_event_id=str(uuid.uuid4()),
        client_ts=when.isoformat(),
        seq=4,
        surface="search",
        origin="resultados",
        position=2,
        request_id="abc123def456",
    )
    assert client.post("/events", json={"user_id": "u-sobre", "events": [event]}).status_code == 200
    row = db.execute(
        "SELECT client_ts, seq, surface, origin, position, request_id FROM app_events WHERE user_id = 'u-sobre'"
    ).fetchone()
    assert row == (when, 4, "search", "resultados", 2, "abc123def456")


def test_a_client_clock_far_from_the_arrival_is_not_saved(client, db):
    far = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    assert client.post("/events", json={"user_id": "u-reloj", "events": [_event(client_ts=far)]}).status_code == 200
    assert db.execute("SELECT client_ts FROM app_events WHERE user_id = 'u-reloj'").fetchone() == (None,)


@pytest.mark.parametrize(
    "bad",
    [
        {"surface": "pantalla-nueva"},
        {"origin": "Con Mayúsculas"},
        {"position": -1},
        {"request_id": "con espacios"},
        {"client_event_id": "no-es-uuid"},
    ],
)
def test_an_envelope_out_of_shape_is_a_422(client, bad):
    assert client.post("/events", json={"user_id": "u-sobre", "events": [_event(**bad)]}).status_code == 422


def test_the_old_payload_origin_fills_the_column_and_readers_see_both(client, db):
    """Un cliente de antes manda el origen en `payload.origen`: llega a la columna. Una fila escrita antes de la
    migración (solo en el payload) la siguen leyendo winback y el panel."""
    legacy = {"type": "suggestion_shown", "session_id": "s", "concept_id": "snacks-salados", "vertical": "grocery"}
    batch = [{**legacy, "payload": {"origen": "agent-carrito"}}, {**legacy, "origin": "agent-plan"}]
    assert client.post("/events", json={"user_id": "u-origen", "events": batch}).json() == {"guardados": 2}
    rows = db.execute("SELECT origin FROM app_events WHERE user_id = 'u-origen' ORDER BY event_id").fetchall()
    assert rows == [("agent-carrito",), ("agent-plan",)]
    db.execute(
        """INSERT INTO app_events (user_id, session_id, type, concept_id, vertical, payload, source)
           VALUES ('u-origen', 's', 'suggestion_shown', 'snacks-salados', 'supermercado',
                   '{"origen": "agent-checkout"}', 'prototype')"""
    )
    db.commit()
    moments = client.get("/analytics/offers", params={"source": "prototype"}).json()["data"]["momentos"]
    shown = {m["momento"]: m["mostradas"] for m in moments}
    assert shown["carrito"] == shown["plan"] == shown["checkout"] == 1


def test_each_session_is_recorded_once_with_what_the_app_says(client, db):
    start = datetime.now(UTC) - timedelta(minutes=10)
    session = {"app_version": "1.2.0", "platform": "web", "mode": "propuesta", "entry": "enlace"}
    first = [_event(client_ts=(start + timedelta(minutes=1)).isoformat()), _event(client_ts=start.isoformat())]
    body = {"user_id": "u-sesion", "events": first, "session": session}
    assert client.post("/events", json=body).status_code == 200
    # Un lote posterior de la misma sesión, con otro modo, no cambia lo que ya se sabía.
    later = {"user_id": "u-sesion", "events": [_event()], "session": {**session, "mode": "actual"}}
    assert client.post("/events", json=later).status_code == 200
    rows = db.execute(
        "SELECT started_at, app_version, platform, mode, entry, source FROM app_sessions WHERE user_id = 'u-sesion'"
    ).fetchall()
    assert rows == [(start, "1.2.0", "web", "propuesta", "enlace", "prototype")]


def test_an_ask_starts_a_session_and_the_app_fills_it_in_later(client, db):
    ask = {"message": "papas fritas", "user_id": "u-pregunta", "session_id": "s-sobre"}
    assert client.post("/agent/ask", json=ask).status_code == 200
    body = {"user_id": "u-pregunta", "events": [_event()], "session": {"app_version": "1.2.0", "platform": "web"}}
    assert client.post("/events", json=body).status_code == 200
    row = db.execute("SELECT app_version, platform FROM app_sessions WHERE user_id = 'u-pregunta'").fetchall()
    assert row == [("1.2.0", "web")]


def test_responses_that_rank_things_carry_the_request_id(client, db):
    header = {"X-Request-ID": "pedido-1"}
    assert client.get("/search", params={"q": "papas"}, headers=header).json()["request_id"] == "pedido-1"
    assert client.get("/search", params={"q": "papas", "vertical": "grocery"}, headers=header).json()["request_id"] == (
        "pedido-1"
    )
    assert client.get("/catalog/home", headers=header).json()["request_id"] == "pedido-1"
    assert client.get("/profile/u-id/verticales", headers=header).json()["request_id"] == "pedido-1"
    recs = client.get("/recommendations", params={"user_id": "u-id"}, headers=header).json()
    assert recs["request_id"] == "pedido-1"
    # Sin cabecera, la API le da uno propio (el de su línea en el log) y lo devuelve también en X-Request-ID.
    reply = client.get("/search", params={"q": "papas"})
    assert reply.json()["request_id"] == reply.headers["x-request-id"]


def test_the_ask_event_keeps_the_id_of_its_answer(client, db):
    ask = {"message": "papas fritas", "user_id": "u-ask", "session_id": "s-ask"}
    reply = client.post("/agent/ask", json=ask, headers={"X-Request-ID": "pregunta-1"}).json()
    assert reply["request_id"] == "pregunta-1"
    row = db.execute("SELECT request_id, surface FROM app_events WHERE user_id = 'u-ask'").fetchone()
    assert row == ("pregunta-1", "agent")


def test_forgetting_a_person_also_deletes_their_sessions(client, db):
    assert client.post("/events", json={"user_id": "proto-olvido", "events": [_event()]}).status_code == 200
    assert db.execute("SELECT count(*) FROM app_sessions WHERE user_id = 'proto-olvido'").fetchone()[0] == 1
    assert client.delete("/profile/proto-olvido").status_code == 200
    assert db.execute("SELECT count(*) FROM app_sessions WHERE user_id = 'proto-olvido'").fetchone()[0] == 0


def test_sessions_are_a_person_table_for_the_delivery_dump(db):
    assert "app_sessions" in PERSON_TABLES
    assert unknown_person_tables(db) == []


def test_the_simulation_fills_the_envelope_and_its_sessions(db):
    seed_demo(db)
    generate(db, users=20, weeks=8, seed=3, until=datetime(2026, 10, 4).date())
    missing = db.execute(
        """SELECT count(*) FROM app_events
           WHERE source = 'synthetic' AND (client_event_id IS NULL OR client_ts IS NULL OR seq IS NULL)"""
    ).fetchone()[0]
    assert missing == 0
    # Cada sesión empieza en 0 y sus eventos están en su tabla de sesiones.
    firsts = db.execute(
        "SELECT count(*) FILTER (WHERE seq = 0), count(DISTINCT (user_id, session_id)) FROM app_events"
        " WHERE source = 'synthetic'"
    ).fetchone()
    sessions = db.execute("SELECT count(*) FROM app_sessions WHERE source = 'synthetic'").fetchone()[0]
    assert firsts[0] == firsts[1] == sessions > 0
    # La misma semilla da los mismos ids.
    ids = db.execute("SELECT client_event_id FROM app_events WHERE source = 'synthetic' ORDER BY 1").fetchall()
    generate(db, users=20, weeks=8, seed=3, until=datetime(2026, 10, 4).date())
    assert db.execute("SELECT client_event_id FROM app_events WHERE source = 'synthetic' ORDER BY 1").fetchall() == ids


def test_record_counts_only_what_went_in(db):
    event_id = uuid.uuid4()
    one = events.Event("u-cuenta", "s", "search", client_event_id=event_id)
    assert events.record(db, [one, one]) == 1
