"""Entradas de la API sin base: `get_conn` se reemplaza por una conexión falsa (lo que no pasa la validación ni llega a
la base) y los servicios por un agente que responde fijo."""

import json
import logging
import math
import sys
import types
from contextlib import contextmanager

import anyio
import pytest
from psycopg import DataError
from psycopg.errors import QueryCanceled

from owner_client import OwnerClient
from rappi_ia.api import app as api
from rappi_ia.api import deps, services


class FakeConn:
    """Una conexión que no responde ninguna consulta: `error` es lo que levanta al ejecutar una."""

    def __init__(self, error: Exception | None = None):
        self.error = error or AssertionError("Este test no debía llegar a la base")
        self.commits = 0

    def execute(self, *_, **__):
        raise self.error

    def cursor(self):
        raise self.error

    @contextmanager
    def transaction(self):
        yield

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


JSON = {"content-type": "application/json"}
ANSWER = {"kind": "resultados", "text": "Mira estas opciones.", "products": [], "intent": {"kind": "buscar"}}


@pytest.fixture
def conn():
    return FakeConn()


@pytest.fixture
def client(conn):
    agent = types.SimpleNamespace(reply=lambda *_: dict(ANSWER))
    api.app.dependency_overrides[api.get_conn] = lambda: conn
    api.app.dependency_overrides[api.get_services] = lambda: types.SimpleNamespace(agent=agent)
    yield OwnerClient(api.app)
    api.app.dependency_overrides.clear()


def test_price_max_nan_is_422(client):
    for value in ["nan", "inf", "-1"]:
        assert client.get("/search", params={"q": "vino", "price_max": value}).status_code == 422, value


def test_long_user_id_is_422(client):
    long = "u" * 10_000
    assert client.get("/recommendations", params={"user_id": long}).status_code == 422
    assert client.get(f"/profile/{long}").status_code == 422
    assert client.delete(f"/profile/{long}").status_code == 422
    assert client.delete("/profile/u1", params={"concept": long}).status_code == 422
    assert client.get("/search", params={"q": "vino", "vertical": long}).status_code == 422
    assert client.get("/search", params={"q": "vino", "current": long}).status_code == 422
    assert client.get("/catalog/restaurants", params={"cuisine": long}).status_code == 422
    assert client.post("/agent/ask", json={"message": "vino", "vertical": long}).status_code == 422
    line = {"entity_type": "catalog_item", "entity_id": "1", "concept_id": long}
    order = {"user_id": "u1", "session_id": "s", "cart_id": "c", "vertical": "licores", "lines": [line]}
    assert client.post("/orders", json=order).status_code == 422
    assert (
        client.post("/orders", json={**order, "vertical": long, "lines": [{**line, "concept_id": None}]}).status_code
        == 422
    )


def test_profile_nan_is_422(client):
    for value in [math.nan, math.inf]:
        body = {"message": "vino", "profile": {"cerveza": value}}
        # json.dumps escribe NaN e Infinity, que el parser de la API acepta: la validación es la que los frena.
        assert client.post("/agent/ask", content=json.dumps(body), headers=JSON).status_code == 422, value


def test_order_placed_event_is_400(client):
    """`order_placed` solo nace en /orders, con un pedido detrás: el cliente no puede inventarlo."""
    event = {"type": "order_placed", "session_id": "s1", "value": 5000}
    assert client.post("/events", json={"user_id": "u1", "events": [event]}).status_code == 400


def test_event_value_cap_is_422(client):
    event = {"type": "cart_add", "session_id": "s1", "value": 1e12}
    assert client.post("/events", json={"user_id": "u1", "events": [event]}).status_code == 422


def test_event_value_accepts_a_big_cart_line():
    """Un carro de Electro (un televisor de $12.488.700) pasa: el tope es el mismo que el precio de una línea."""
    event = api.EventIn(type="cart_add", session_id="s1", value=12_488_700)
    assert event.value == 12_488_700
    price_cap = next(m.le for m in api.OrderLineIn.model_fields["unit_price"].metadata if hasattr(m, "le"))
    assert price_cap == api.MAX_EVENT_VALUE


def test_query_canceled_is_504(client, conn):
    """Una consulta que pasó el statement_timeout no es «base caída»: la app no debe decir «Sin conexión»."""
    conn.error = QueryCanceled("canceling statement due to statement timeout")
    reply = client.get("/profile/u1")
    assert reply.status_code == 504
    assert reply.json() == {"detail": "La consulta tardó demasiado"}


def test_log_ask_db_error_keeps_answer(client, conn, caplog):
    """Registrar la consulta es secundario: un error de la base al guardarla no tumba la respuesta ya calculada."""
    conn.error = DataError("valor fuera de rango")
    with caplog.at_level(logging.WARNING):
        reply = client.post("/agent/ask", json={"message": "vino", "user_id": "u1", "session_id": "s1", "profile": {}})
    assert reply.status_code == 200 and reply.json()["text"] == ANSWER["text"]
    assert "No se pudo registrar" in caplog.text


# Un error de Postgres puede traer la fila que falló, con texto de la persona: el log lleva solo la clase y el sqlstate.
PRIVATE = "Failing row contains (u1, s1, quiero algo para mi ex)"


def _db_error(cls):
    error = cls(PRIVATE)
    error.sqlstate = "22001"  # psycopg lo lee del diagnóstico; aquí se fija a mano
    return error


def test_log_ask_db_error_hides_row_text(client, conn, caplog):
    conn.error = _db_error(DataError)
    with caplog.at_level(logging.WARNING):
        reply = client.post("/agent/ask", json={"message": "vino", "user_id": "u1", "session_id": "s1", "profile": {}})
    assert reply.status_code == 200
    assert "No se pudo registrar" in caplog.text
    assert "DataError" in caplog.text and "22001" in caplog.text
    assert "Failing row" not in caplog.text and "mi ex" not in caplog.text


def test_invalid_data_log_hides_row_text(client, conn, caplog):
    conn.error = _db_error(DataError)
    with caplog.at_level(logging.WARNING):
        reply = client.get("/profile/u1")
    assert reply.status_code == 400
    assert "DataError" in caplog.text and "22001" in caplog.text
    assert "Failing row" not in caplog.text and "mi ex" not in caplog.text


def test_startup_runtime_error_goes_to_faltantes(monkeypatch):
    """Un error inesperado al cargar el modelo (torch, MPS) no impide que la API arranque: queda en `faltantes`."""

    def broken_embedder():
        raise RuntimeError("MPS backend out of memory")

    monkeypatch.delenv("RAPPI_IA_LIGHT", raising=False)
    monkeypatch.setitem(sys.modules, "rappi_ia.embeddings.models", types.SimpleNamespace(text_embedder=broken_embedder))

    def broken_composer():
        raise RuntimeError("cliente de Anthropic roto")

    monkeypatch.setattr(services, "default_composer", broken_composer)
    loaded = services._load_services.__wrapped__()
    assert loaded.embedder is None and "MPS backend out of memory" in loaded.missing["busqueda_semantica"]
    assert loaded.agent.composer.name == "plantillas" and "redaccion_llm" in loaded.missing


def test_each_request_class_has_its_own_statement_timeout(monkeypatch):
    """5 s para lo que espera una pantalla y 30 s para el panel; se fija al abrir la conexión del request."""
    sent = []

    class Recorder(FakeConn):
        def execute(self, query, params=None):
            sent.append(params)

    class Pool:
        @contextmanager
        def connection(self, timeout=None):
            yield Recorder()

    monkeypatch.setattr(deps, "_pool", Pool())

    async def check():
        opened = deps.get_conn()
        conn = await anext(opened)
        assert sent == [("5000ms",)] and conn.commits == 1
        deps.get_analytics_conn(conn)
        assert sent[-1] == ("30000ms",)
        await opened.aclose()

    anyio.run(check)
