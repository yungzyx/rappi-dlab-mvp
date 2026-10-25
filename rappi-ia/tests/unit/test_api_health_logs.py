"""Salud lista o no lista, registros con hora y request id, y errores sin datos de personas. Sin base: `get_conn` se
reemplaza por una conexión falsa."""

import logging
import subprocess
import types
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from psycopg import DataError, OperationalError
from psycopg_pool import PoolTimeout

from owner_client import OwnerClient
from rappi_ia import config
from rappi_ia.api import app as api
from rappi_ia.api import deps, logs
from rappi_ia.config import PROJECT_ROOT

EVENTS = {"user_id": "secret-user-1", "events": [{"type": "app_open", "session_id": "s1"}]}


class Conn:
    """Responde lo que /health le pregunta: documentos de las estadísticas y, si hacen falta, el conteo."""

    def __init__(self, documents=5):
        self.documents = documents

    def execute(self, query, *_):
        return types.SimpleNamespace(fetchone=lambda: (self.documents,))

    @contextmanager
    def transaction(self):
        yield

    def commit(self):
        pass

    def rollback(self):
        pass


MODEL = types.SimpleNamespace(model_name="falso")


def services(embedder=MODEL, missing=None):
    agent = types.SimpleNamespace(composer=types.SimpleNamespace(name="plantillas"))
    return api.Services(agent, embedder, missing or {})


@pytest.fixture(autouse=True)
def no_pending_migrations(monkeypatch):
    monkeypatch.setattr(api, "pending_migrations", lambda conn: [])


@pytest.fixture
def conn():
    return Conn()


@pytest.fixture
def client(conn):
    api.app.dependency_overrides[api.get_conn] = lambda: conn
    api.app.dependency_overrides[api.get_services] = lambda: services()
    yield OwnerClient(api.app)
    api.app.dependency_overrides.clear()


def test_live_without_db():
    """Sin pool ni conexión: el proceso vive. (`get_conn` sin pool abierto fallaría.)"""
    with TestClient(api.app) as bare:
        reply = bare.get("/live")

    assert reply.status_code == 200 and reply.json() == {"ok": True}


def test_health_is_ready_with_documents(client):
    body = client.get("/health").json()

    assert body["ok"] is True and body["documentos"] == 5
    assert body["capacidades"]["faltantes"] == []


def _raises(error):
    def broken():
        raise error
        yield  # pragma: no cover

    return broken


def test_health_503_when_db_down(client):
    api.app.dependency_overrides[api.get_conn] = _raises(OperationalError("connection to server at 10.0.0.5 failed"))

    reply = client.get("/health")

    assert reply.status_code == 503
    assert reply.json() == {"ok": False, "motivos": ["base"]}  # ni el texto del error ni la dirección


def test_health_503_when_the_pool_is_exhausted_and_idle(client):
    """Ninguna conexión en uso y el pool sin poder conectarse: Postgres no responde."""
    api.app.dependency_overrides[api.get_conn] = _raises(PoolTimeout("couldn't get a connection after 3 sec"))

    reply = client.get("/health")

    assert reply.status_code == 503 and reply.json() == {"ok": False, "motivos": ["base"]}


def test_health_503_when_the_api_is_saturated(client, monkeypatch):
    monkeypatch.setattr(deps, "connections_in_use", lambda: 3)
    api.app.dependency_overrides[api.get_conn] = _raises(PoolTimeout("sin turno"))

    reply = client.get("/health")

    assert reply.status_code == 503 and reply.json() == {"ok": False, "motivos": ["saturada"]}


def test_other_routes_keep_their_database_error_text(client):
    api.app.dependency_overrides[api.get_conn] = _raises(OperationalError("connection refused"))

    reply = client.get("/profile/u1")

    assert reply.status_code == 503 and reply.json() == {"detail": "Base de datos no disponible"}


def test_health_503_without_documents(client, conn):
    conn.documents = 0

    assert client.get("/health").json() == {"ok": False, "motivos": ["sin_documentos"]}


def test_health_503_with_pending_migrations(client, monkeypatch):
    monkeypatch.setattr(api, "pending_migrations", lambda conn: ["099_nueva.sql"])

    reply = client.get("/health")

    assert reply.status_code == 503
    assert reply.json() == {"ok": False, "motivos": ["migraciones_pendientes"]}  # sin el nombre del archivo


def test_health_503_light_mode_when_semantic_required(client, monkeypatch):
    monkeypatch.setattr(config, "API_REQUIRE_SEMANTIC", True)
    api.app.dependency_overrides[api.get_services] = lambda: services(None, {"busqueda_semantica": "RAPPI_IA_LIGHT=1"})

    reply = client.get("/health")

    assert reply.status_code == 503 and reply.json() == {"ok": False, "motivos": ["busqueda_semantica"]}


def test_health_light_mode_is_ready_when_semantic_is_optional(client):
    api.app.dependency_overrides[api.get_services] = lambda: services(None, {"busqueda_semantica": "RAPPI_IA_LIGHT=1"})

    reply = client.get("/health")

    assert reply.status_code == 200 and reply.json()["capacidades"]["faltantes"] == ["busqueda_semantica"]


def test_health_has_no_exception_text(client):
    detail = "no se pudo cargar el modelo: /Users/yo/.cache/huggingface/hub/models--x (OSError)"
    api.app.dependency_overrides[api.get_services] = lambda: services(
        None, {"busqueda_semantica": detail, "redaccion_llm": "RuntimeError: clave sk-secreta"}
    )

    text = client.get("/health").text

    assert '"faltantes":["busqueda_semantica","redaccion_llm"]' in text.replace(" ", "")
    assert not any(leak in text for leak in ("/Users", "cache", "OSError", "sk-secreta", "RuntimeError"))


def test_model_name_only_in_local(client, monkeypatch):
    model = types.SimpleNamespace(model_name="e5-secreto")
    api.app.dependency_overrides[api.get_services] = lambda: services(model)
    monkeypatch.setattr(config, "API_PRODUCTION", False)
    assert client.get("/health").json()["capacidades"]["busqueda_semantica"] == "e5-secreto"

    monkeypatch.setattr(config, "API_PRODUCTION", True)
    text = client.get("/health").text
    assert "e5-secreto" not in text and client.get("/health").json()["capacidades"]["busqueda_semantica"] is True


# ── Registros ────────────────────────────────────────────────────────────────
def test_rappi_ia_info_logs_appear(caplog):
    """Con el logging de la API configurado (en el lifespan), un `log.info` de `rappi_ia.*` sale: antes se perdía."""
    with TestClient(api.app):
        logging.getLogger("rappi_ia.layers.segments").info("Segmentos recalculados: 3")

    assert any(
        r.name == "rappi_ia.layers.segments" and r.levelno == logging.INFO and "Segmentos recalculados" in r.message
        for r in caplog.records
    )


def test_log_format_has_time_level_name_and_request_id():
    logs.configure_logging("INFO")
    logs.configure_logging("INFO")  # idempotente: un solo handler de la API
    handlers = [h for h in logging.getLogger().handlers if getattr(h, logs._HANDLER_MARK, False)]

    assert len(handlers) == 1
    record = logging.getLogger("rappi_ia.x").makeRecord("rappi_ia.x", logging.INFO, "f.py", 1, "hola", (), None)
    line = handlers[0].format(record)
    assert line[:4].isdigit()  # empieza con la fecha
    assert line.endswith(" INFO rappi_ia.x [-] hola")


def _api_text(caplog):
    """Lo que registró la API (el cliente de pruebas, httpx, registra además la URL que pide)."""
    return "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("rappi_ia"))


def _access(caplog):
    return [r for r in caplog.records if r.name == "rappi_ia.api.logs"]


def test_access_log_uses_route_template(client, caplog, monkeypatch):
    logs.configure_logging("INFO")  # lo que hace el lifespan
    monkeypatch.setattr(api.events, "profile", lambda conn, user_id: {})
    with caplog.at_level(logging.INFO):
        reply = client.get("/profile/proto-abc?x=1")

    lines = [r.getMessage() for r in _access(caplog)]
    assert lines and lines[0].startswith("GET /profile/{user_id} 200 ")
    assert lines[0].endswith(" ms")
    assert "proto-abc" not in _api_text(caplog) and "x=1" not in _api_text(caplog)
    assert _access(caplog)[0].request_id == reply.headers["X-Request-ID"]


def test_request_id_is_taken_from_the_proxy_only_if_well_formed(client, monkeypatch):
    monkeypatch.setattr(api.events, "profile", lambda conn, user_id: {})

    good = client.get("/profile/u", headers={"X-Request-ID": "abc-123.def"})
    bad = client.get("/profile/u", headers={"X-Request-ID": "a b\tc"})

    assert good.headers["X-Request-ID"] == "abc-123.def"
    assert bad.headers["X-Request-ID"] != "a b\tc" and len(bad.headers["X-Request-ID"]) == 12


def test_unknown_path_is_not_logged(client, caplog):
    with caplog.at_level(logging.INFO):
        client.get("/profile/u1/otro-secreto")

    assert "otro-secreto" not in _api_text(caplog) and "<sin ruta>" in _api_text(caplog)


def test_health_checks_are_quiet_at_info(client, caplog):
    with caplog.at_level(logging.INFO):
        client.get("/live")
        client.get("/health")

    assert not _access(caplog)


def test_server_errors_are_logged_as_warnings(client, caplog, monkeypatch):
    def boom(conn, user_id):
        raise RuntimeError("fallo")

    monkeypatch.setattr(api.events, "profile", boom)
    with caplog.at_level(logging.INFO):
        OwnerClient(api.app, raise_server_exceptions=False).get("/profile/u1")

    line = _access(caplog)[0]
    assert line.levelno == logging.WARNING and line.getMessage().startswith("GET /profile/{user_id} 500 ")


def test_invalid_data_logs_the_template_not_the_path(client, caplog, monkeypatch):
    def bad(conn, user_id):
        raise DataError("value too long")

    monkeypatch.setattr(api.events, "profile", bad)
    with caplog.at_level(logging.WARNING):
        reply = client.get("/profile/proto-privado")

    assert reply.status_code == 400
    assert "/profile/{user_id}" in caplog.text and "proto-privado" not in caplog.text


# ── Errores sin ids ──────────────────────────────────────────────────────────
def test_other_source_error_is_generic(client, caplog, monkeypatch):
    def record(conn, events, source="prototype"):
        raise ValueError("El usuario secret-user-1 es de otra fuente")

    monkeypatch.setattr(api.events, "record", record)
    with caplog.at_level(logging.WARNING):
        reply = client.post("/events", json=EVENTS)

    assert reply.status_code == 400 and reply.json() == {"detail": "Solicitud no válida"}
    assert "secret-user-1" not in reply.text and "secret-user-1" not in caplog.text
    assert "El usuario <id> es de otra fuente" in caplog.text  # el detalle sí queda en el log, sin el id


def test_order_other_source_errors_are_generic(client, caplog, monkeypatch):
    def other_source(*_, **__):
        raise ValueError("El usuario secret-user-1 es de otra fuente")

    order = {
        "user_id": "secret-user-1",
        "session_id": "s",
        "cart_id": "c",
        "vertical": "supermercado",
        "lines": [{"entity_type": "catalog_item", "entity_id": "1"}],
    }
    monkeypatch.setattr(api.events, "catalog_prices", lambda conn, lines: ([{"price": 1}], 0))
    monkeypatch.setattr(api.events, "record_order", other_source)
    with caplog.at_level(logging.WARNING):
        reply = client.post("/orders", json=order)

    assert reply.status_code == 400 and reply.json() == {"detail": "Solicitud no válida"}
    assert "secret-user-1" not in caplog.text


# ── Arranque ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("target", ["serve", "serve-lan"])
def test_uvicorn_starts_without_its_own_access_log(target):
    """Su línea de acceso lleva la ruta con el id y la query; la de la API lleva la plantilla."""
    dry_run = subprocess.run(
        ["make", "-n", "-C", str(PROJECT_ROOT), target], capture_output=True, text=True, check=True
    ).stdout

    assert "uvicorn" in dry_run and "--no-access-log" in dry_run
