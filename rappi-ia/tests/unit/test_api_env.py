"""La API según su entorno (`API_ENV`): local para la demo en este equipo, producción para un servidor tras un proxy."""

import importlib

import pytest
from fastapi.testclient import TestClient

from rappi_ia import config
from rappi_ia.api import app as api
from rappi_ia.api.deps import get_conn
from rappi_ia.api.limits import RateLimit

ENV_VARS = (
    "API_ENV",
    "API_ENABLE_ANALYTICS",
    "API_DOCS",
    "API_ALLOW_LAN",
    "API_CORS_ORIGINS",
    "API_RATE_PER_MIN",
    "API_RATE_WRITE_PER_MIN",
)
PUBLIC_ORIGIN = "https://demo.example.cl"


@pytest.fixture
def load_api(monkeypatch):
    """Recarga la configuración y la app con las variables dadas (se leen al importar); al final deja las de siempre."""

    def load(**env: str):
        for name in ENV_VARS:
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        importlib.reload(config)
        return importlib.reload(api)

    yield load
    monkeypatch.undo()
    importlib.reload(config)
    importlib.reload(api)


def beacon(module, origin: str | None) -> int:
    """El estado de un beacon con cuerpo roto: 422 = pasó la revisión del origen, 403 = lo rechazó (no toca la base)."""
    module.app.dependency_overrides[get_conn] = lambda: None
    headers = {"content-type": "text/plain", **({"origin": origin} if origin else {})}
    return TestClient(module.app).post("/events/beacon", content="{no es json", headers=headers).status_code


def preflight_allows(module, origin: str) -> bool:
    reply = TestClient(module.app).options(
        "/events", headers={"Origin": origin, "Access-Control-Request-Method": "POST"}
    )
    return reply.headers.get("access-control-allow-origin") == origin


def test_local_is_the_default(load_api):
    module = load_api()

    assert config.API_ENV == "local"
    assert config.API_ENABLE_ANALYTICS and config.API_DOCS
    assert preflight_allows(module, "http://localhost:5174")
    assert TestClient(module.app).get("/docs").status_code == 200


def test_an_unknown_environment_is_refused(load_api, monkeypatch):
    monkeypatch.setenv("API_ENV", "prod")

    with pytest.raises(RuntimeError, match="API_ENV"):
        importlib.reload(config)


def test_production_rejects_localhost_origin(load_api):
    module = load_api(API_ENV="production", API_CORS_ORIGINS=PUBLIC_ORIGIN)

    for origin in ("http://localhost:5174", "http://127.0.0.1:5175"):
        assert not preflight_allows(module, origin), origin
        assert beacon(module, origin) == 403, origin
    assert preflight_allows(module, PUBLIC_ORIGIN)


def test_production_without_origins_accepts_none(load_api):
    module = load_api(API_ENV="production")

    assert config.API_CORS_ORIGINS == []
    assert not preflight_allows(module, "http://localhost:5174")
    assert beacon(module, "http://localhost:5174") == 403


def test_production_ignores_allow_lan(load_api):
    module = load_api(API_ENV="production", API_ALLOW_LAN="1", API_CORS_ORIGINS=PUBLIC_ORIGIN)

    assert config.API_ALLOW_LAN is False
    assert not preflight_allows(module, "http://192.168.1.20:5174")
    assert beacon(module, "http://192.168.1.20:5174") == 403


def test_beacon_accepts_configured_https_origin(load_api):
    module = load_api(API_ENV="production", API_CORS_ORIGINS=f"{PUBLIC_ORIGIN},https://otro.example.cl")

    assert beacon(module, PUBLIC_ORIGIN) == 422
    assert beacon(module, "https://otro.example.cl") == 422
    assert beacon(module, "https://evil.example.com") == 403
    assert beacon(module, None) == 422  # sin Origin: un cliente que no es un navegador


def test_beacon_accepts_its_own_origin_without_configuration(load_api):
    """Sitio y API en el mismo origen (proxy en /api): el navegador manda Origin igual a la página, o sea al Host."""
    module = load_api(API_ENV="production")

    assert config.API_CORS_ORIGINS == []
    assert beacon(module, "https://testserver") == 422  # el TestClient llama a «testserver»
    assert beacon(module, "http://testserver") == 422  # tras un proxy TLS la API ve http y el navegador manda https


def test_beacon_rejects_origins_that_only_resemble_its_host(load_api):
    module = load_api(API_ENV="production")

    for origin in (
        "https://evil.example.com",
        "https://testserver.evil.example.com",
        "https://evil-testserver",
        "https://testserver:8443",
        "https://testserver@evil.example.com",
        "null",
    ):
        assert beacon(module, origin) == 403, origin


def test_analytics_off_is_404(load_api):
    module = load_api(API_ENV="production")

    assert not config.API_ENABLE_ANALYTICS
    client = TestClient(module.app)
    assert client.get("/analytics/kpis").status_code == 404
    assert client.get("/analytics/catalog").status_code == 404


def test_analytics_can_be_turned_on_in_production(load_api):
    module = load_api(API_ENV="production", API_ENABLE_ANALYTICS="1")

    assert "/analytics/{name}" in module.app.openapi()["paths"]


def test_analytics_can_be_turned_off_locally(load_api):
    module = load_api(API_ENABLE_ANALYTICS="0")

    assert TestClient(module.app).get("/analytics/kpis").status_code == 404


def test_docs_off_is_404(load_api):
    module = load_api(API_ENV="production")

    client = TestClient(module.app)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


def test_docs_can_be_turned_on_in_production(load_api):
    module = load_api(API_ENV="production", API_DOCS="1")

    assert TestClient(module.app).get("/openapi.json").status_code == 200


def rate_limit(module) -> dict:
    return next(m for m in module.app.user_middleware if m.cls is RateLimit).kwargs


def test_local_limits_by_ip_except_this_mac(load_api):
    """120 por minuto y 60 escrituras por IP. En local este equipo no tiene tope: la demo y `make mvp-check` piden mucho
    desde 127.0.0.1 (los tests de la suite tampoco: conftest lo apaga)."""
    limits = rate_limit(load_api())

    assert (limits["per_minute"], limits["writes_per_minute"]) == (120, 60)
    assert limits["exempt"] == ("127.0.0.1", "::1")


def test_production_limits_every_ip(load_api):
    """En producción, sin excepciones: tras un proxy sin --proxy-headers todos llegarían como su IP."""
    limits = rate_limit(load_api(API_ENV="production", API_RATE_PER_MIN="30", API_RATE_WRITE_PER_MIN="10"))

    assert (limits["per_minute"], limits["writes_per_minute"]) == (30, 10)
    assert limits["exempt"] == ()
