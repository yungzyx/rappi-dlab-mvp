"""Límites de la API sin base: cupos por ruta, tamaño del cuerpo, solicitudes por IP, tope diario de Claude y el beacon
que valida antes de pedir conexión."""

import logging
import threading
import time
import types
from contextlib import contextmanager
from types import SimpleNamespace

import anyio
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from owner_client import OwnerClient
from rappi_ia import config
from rappi_ia.agent import compose
from rappi_ia.agent.compose import ClaudeComposer, DailyCallCap, Draft, TemplateComposer
from rappi_ia.api import agent as agent_api
from rappi_ia.api import app as api
from rappi_ia.api import identity, limits, services

ANSWER = {"kind": "resultados", "text": "Mira estas opciones.", "products": [], "intent": {"kind": "buscar"}}


@pytest.fixture
def opened():
    """Cada vez que la API pide una conexión (de un request o del connector del beacon)."""
    return []


@pytest.fixture
def client(opened, monkeypatch):
    """Un solo event loop (`with TestClient`, como uvicorn): los cupos son de anyio y se llenan desde ese loop."""
    monkeypatch.setenv("RAPPI_IA_LIGHT", "1")
    services._load_services.cache_clear()

    def conn_override():
        opened.append("get_conn")
        yield SimpleNamespace(commit=lambda: None, execute=lambda *_: None)  # solo el statement_timeout del panel

    @contextmanager
    def connection():
        opened.append("connector")
        yield SimpleNamespace(commit=lambda: None)

    agent = types.SimpleNamespace(reply=lambda *_: dict(ANSWER))
    for cap in (api.ASK_CAP, agent_api.OFFER_CAP):  # su fila (API_CAP_WAIT_S), corta: un cupo lleno no alarga el test
        monkeypatch.setattr(cap, "wait_s", 0.05)
    api.app.dependency_overrides[api.get_conn] = conn_override
    api.app.dependency_overrides[api.get_connector] = lambda: connection
    api.app.dependency_overrides[api.get_services] = lambda: types.SimpleNamespace(agent=agent, embedder=None)
    try:
        with OwnerClient(api.app) as test_client:
            yield test_client
    finally:
        api.app.dependency_overrides.clear()
        services._load_services.cache_clear()


def _take_all(cap) -> int:
    taken = 0
    while True:
        try:
            cap.slots.acquire_nowait()
        except anyio.WouldBlock:
            return taken
        taken += 1


def _give_back(cap, n: int) -> None:
    for _ in range(n):
        cap.slots.release()


@contextmanager
def full(client, cap):
    """Ocupa todos los cupos de una ruta, como si otros requests estuvieran adentro (desde el loop de la app)."""
    taken = client.portal.call(_take_all, cap)
    try:
        yield
    finally:
        client.portal.call(_give_back, cap, taken)


def test_cap_full_returns_503_with_retry_after(client):
    with full(client, api.SEARCH_CAP):
        reply = client.get("/search", params={"q": "vino", "vertical": "licores"})

    assert reply.status_code == 503
    assert reply.headers["retry-after"] == "2"
    assert reply.json()["detail"] == "Hay mucha gente ahora; intenta en unos segundos."


def test_cap_resolves_before_connection(client, opened):
    """Un request que no tiene cupo no ocupa una conexión del pool mientras espera: ni la pide."""
    with full(client, api.ASK_CAP):
        assert client.post("/agent/ask", json={"message": "una hamburguesa"}).status_code == 503
    assert opened == []

    assert client.post("/agent/ask", json={"message": "una hamburguesa"}).status_code == 200  # se liberó
    assert opened == ["get_conn"]


def test_each_expensive_route_has_its_cap(client, opened):
    order = {"user_id": "u1", "session_id": "s", "cart_id": "c", "vertical": "licores", "lines": []}
    order["lines"] = [{"entity_type": "catalog_item", "entity_id": "1"}]
    requests = [
        (api.ASK_CAP, lambda: client.post("/agent/ask", json={"message": "vino"})),
        (api.SEARCH_CAP, lambda: client.get("/search", params={"q": "vino"})),
        (
            agent_api.OFFER_CAP,
            lambda: client.post("/agent/offer", json={"moment": "plan", "context": {"occasion": "x"}}),
        ),
        (api.ORDERS_CAP, lambda: client.post("/orders", json=order)),
    ]
    for cap, send in requests:
        with full(client, cap):
            assert send().status_code == 503, cap.name
    assert opened == []


def test_the_panel_waits_its_turn_instead_of_failing(client, opened, monkeypatch):
    """El panel pide ~16 métricas a la vez: con un cupo que rechaza al tiro, casi todas caerían a los datos guardados.
    Su cupo hace fila (hasta el tope del panel) en vez de responder 503."""
    assert api.ANALYTICS_CAP.wait_s == config.API_TIMEOUT_ANALYTICS_MS / 1000

    monkeypatch.setitem(api.ANALYTICS, "kpis", lambda conn, source: {"usuarios": 0})
    in_line = threading.Event()
    slots = api.ANALYTICS_CAP.slots

    class Watched:  # avisa cuando un request se pone en la fila
        def __getattr__(self, name):
            return getattr(slots, name)

        async def acquire(self):
            in_line.set()
            await slots.acquire()  # sin ceder el loop entre el aviso y quedar en la fila

    monkeypatch.setattr(api.ANALYTICS_CAP, "slots", Watched())
    replies = []
    with full(client, api.ANALYTICS_CAP):
        waiting = threading.Thread(target=lambda: replies.append(client.get("/analytics/kpis").status_code))
        waiting.start()
        assert in_line.wait(timeout=5)  # está esperando su turno, no rechazado
        assert replies == []
    waiting.join()  # se liberó un cupo: el que esperaba entra

    assert replies == [200]
    assert opened == ["get_conn"]


@contextmanager
def waiting_in_line(monkeypatch, cap):
    """Avisa cuando un request se pone en la fila de `cap`."""
    in_line = threading.Event()
    slots = cap.slots

    class Watched:
        def __getattr__(self, name):
            return getattr(slots, name)

        async def acquire(self):
            in_line.set()
            await slots.acquire()  # sin ceder el loop entre el aviso y quedar en la fila

    monkeypatch.setattr(cap, "slots", Watched())
    yield in_line


@pytest.mark.parametrize("route", ["ask", "offer"])
def test_mochi_waits_a_moment_for_a_free_slot(route, client, opened, monkeypatch):
    """La Home pide dos ofertas por persona: con 3 personas a la vez, un cupo que rechazaba al tiro dejaba ofertas con
    503 (y a Mochi callado). /agent/ask y /agent/offer hacen una fila corta: el que espera entra cuando se libera un
    cupo."""
    monkeypatch.setattr(agent_api, "make_offer", lambda *_: None)
    cap, send = {
        "ask": (api.ASK_CAP, lambda: client.post("/agent/ask", json={"message": "vino"})),
        "offer": (agent_api.OFFER_CAP, lambda: client.post("/agent/offer", json={"moment": "recompra", "context": {}})),
    }[route]
    monkeypatch.setattr(cap, "wait_s", 5)
    replies = []
    with waiting_in_line(monkeypatch, cap) as in_line, full(client, cap):
        waiting = threading.Thread(target=lambda: replies.append(send().status_code))
        waiting.start()
        assert in_line.wait(timeout=5)  # está esperando su turno, no rechazado
        assert replies == []
    waiting.join()  # se liberó un cupo: el que esperaba entra

    assert replies == [200 if route == "ask" else 204]
    assert opened == ["get_conn"]


@pytest.mark.parametrize("route", ["ask", "offer"])
def test_mochi_gives_up_after_its_short_wait(route, client, opened, monkeypatch):
    cap, send = {
        "ask": (api.ASK_CAP, lambda: client.post("/agent/ask", json={"message": "vino"})),
        "offer": (agent_api.OFFER_CAP, lambda: client.post("/agent/offer", json={"moment": "recompra", "context": {}})),
    }[route]
    monkeypatch.setattr(cap, "wait_s", 0.3)
    with full(client, cap):
        start = time.monotonic()
        reply = send()

    assert reply.status_code == 503 and reply.headers["retry-after"] == "2"
    assert time.monotonic() - start >= 0.3  # esperó su fila antes de rendirse
    assert opened == []


def test_a_waiting_cap_gives_up_after_its_wait(monkeypatch):
    cap = limits.concurrency_cap("lento", 1, wait_s=0.2)
    app = FastAPI()

    @app.get("/lento", dependencies=[Depends(cap)])
    def slow() -> dict:
        return {"ok": True}

    with TestClient(app) as client:
        with full(client, cap):
            reply = client.get("/lento")

        assert reply.status_code == 503 and reply.headers["retry-after"] == "2"
        assert client.get("/lento").status_code == 200


def test_caps_take_their_size_from_config():
    assert api.ASK_CAP.limit == config.API_MAX_CONCURRENT_ASK == 4
    assert api.SEARCH_CAP.limit == config.API_MAX_CONCURRENT_SEARCH == 8
    assert api.ORDERS_CAP.limit == config.API_MAX_CONCURRENT_ORDERS == 4
    assert api.ANALYTICS_CAP.limit == config.API_MAX_CONCURRENT_ANALYTICS == 2
    # La fila de Mochi más la del pool (3 s) cabe en el tope de la app para una oferta (5 s); la búsqueda y los
    # pedidos rechazan al tiro.
    assert api.ASK_CAP.wait_s == agent_api.OFFER_CAP.wait_s == config.API_CAP_WAIT_S == 1.5
    assert api.SEARCH_CAP.wait_s == api.ORDERS_CAP.wait_s == 0


def _echo_app(**rate) -> FastAPI:
    app = FastAPI()

    @app.post("/echo")
    async def echo(request: Request) -> dict:
        return {"bytes": len(await request.body())}

    @app.get("/ping")
    def ping() -> dict:
        return {"ok": True}

    app.add_middleware(limits.MaxBodySize, max_bytes=100)
    if rate:
        app.add_middleware(limits.RateLimit, **rate)
    return app


def test_body_over_limit_is_413():
    client = TestClient(_echo_app())

    assert client.post("/echo", content=b"x" * 100).json() == {"bytes": 100}
    declared = client.post("/echo", content=b"x" * 101)  # por Content-Length, sin leer el cuerpo
    assert declared.status_code == 413
    assert declared.json()["detail"] == "Solicitud demasiado grande"

    def chunks():  # sin Content-Length: se cuenta lo que llega
        for _ in range(5):
            yield b"x" * 30

    assert client.post("/echo", content=chunks()).status_code == 413


def test_the_api_caps_every_body():
    """Un JSON enorme para /orders o /agent/ask se corta antes de leerlo entero (Starlette lo leía a memoria)."""
    reply = TestClient(api.app).post(
        "/agent/ask", content=b"x" * (config.API_MAX_BODY_BYTES + 1), headers={"content-type": "application/json"}
    )
    assert reply.status_code == 413
    assert config.API_MAX_BODY_BYTES == 524_288


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_rate_limit_429_then_recovers():
    clock = Clock()
    client = TestClient(_echo_app(per_minute=3, writes_per_minute=2, clock=clock))

    assert [client.get("/ping").status_code for _ in range(3)] == [200, 200, 200]
    blocked = client.get("/ping")
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "Demasiadas solicitudes; espera un momento."
    assert 1 <= int(blocked.headers["retry-after"]) <= 120

    clock.now += 2 * limits.RateLimit.WINDOW_S  # pasó la ventana: vuelve a responder
    assert client.get("/ping").status_code == 200


def test_rate_limit_counts_writes_apart():
    clock = Clock()
    client = TestClient(_echo_app(per_minute=10, writes_per_minute=2, clock=clock))

    assert [client.post("/echo", content=b"{}").status_code for _ in range(3)] == [200, 200, 429]
    assert client.get("/ping").status_code == 200  # las lecturas tienen su propio tope


def test_rate_limit_retry_after_says_when_it_frees():
    clock = Clock()
    limiter = limits.RateLimit(None, per_minute=2, writes_per_minute=0, clock=clock)

    assert limiter.wait("1.2.3.4", write=False) == 0
    assert limiter.wait("1.2.3.4", write=False) == 0
    retry = limiter.wait("1.2.3.4", write=False)
    assert retry > 0
    clock.now += retry
    assert limiter.wait("1.2.3.4", write=False) == 0  # a la hora que dijo, ya pasa


def test_rate_limit_memory_is_bounded():
    limiter = limits.RateLimit(None, per_minute=5, writes_per_minute=5, max_clients=10, clock=Clock())

    for i in range(1000):
        limiter.wait(f"10.0.{i // 256}.{i % 256}", write=True)

    assert len(limiter.clients) == 10
    assert "10.0.3.231" in limiter.clients  # se quedan las últimas IPs, no las primeras


def test_rate_limit_zero_is_off():
    limiter = limits.RateLimit(None, per_minute=0, writes_per_minute=0, clock=Clock())

    assert all(limiter.wait("1.2.3.4", write=True) == 0 for _ in range(500))
    assert limiter.clients == {}


def test_rate_limit_exempt_hosts():
    limiter = limits.RateLimit(None, per_minute=1, writes_per_minute=1, exempt=("127.0.0.1",), clock=Clock())

    assert all(limiter.wait("127.0.0.1", write=True) == 0 for _ in range(5))
    assert limiter.wait("1.2.3.4", write=False) == 0
    assert limiter.wait("1.2.3.4", write=False) > 0


RESULTS = Draft(kind="resultados", concept_label="🍺 Cerveza", vertical_label="Licores", product_names=["Escudo"])


def _composer(calls: list) -> ClaudeComposer:
    def create(**_):
        calls.append(1)
        return SimpleNamespace(
            stop_reason="end_turn", content=[SimpleNamespace(type="text", text='{"text": "Te dejo {p1}."}')]
        )

    composer = ClaudeComposer.__new__(ClaudeComposer)  # sin red ni clave
    composer.model, composer._fallback = "claude-sonnet-5", TemplateComposer()
    composer._client = SimpleNamespace(messages=SimpleNamespace(create=create))
    return composer


def test_llm_daily_cap_uses_template(monkeypatch, caplog):
    monkeypatch.setattr(config, "LLM_DAILY_CALL_CAP", 2)
    monkeypatch.setattr(ClaudeComposer, "calls", DailyCallCap())
    calls = []
    composer = _composer(calls)

    with caplog.at_level(logging.WARNING, logger="rappi_ia.agent.compose"):
        texts = [composer.compose(RESULTS) for _ in range(4)]

    assert texts[:2] == ["Te dejo Escudo."] * 2
    assert texts[2:] == [TemplateComposer().compose(RESULTS)] * 2
    assert len(calls) == 2
    warnings = [r.getMessage() for r in caplog.records if "Tope diario" in r.getMessage()]
    assert warnings == ["Tope diario de redacción con Claude alcanzado (2): se usan plantillas."]  # una sola vez


def test_llm_daily_cap_resets_each_santiago_day(monkeypatch):
    monkeypatch.setattr(config, "LLM_DAILY_CALL_CAP", 1)
    monkeypatch.setattr(ClaudeComposer, "calls", DailyCallCap())
    day = ["2026-10-11"]
    monkeypatch.setattr(compose, "_santiago_today", lambda: day[0])
    calls = []
    composer = _composer(calls)

    composer.compose(RESULTS)
    composer.compose(RESULTS)
    day[0] = "2026-10-12"
    composer.compose(RESULTS)

    assert len(calls) == 2


def test_llm_daily_cap_zero_never_calls(monkeypatch):
    monkeypatch.setattr(config, "LLM_DAILY_CALL_CAP", 0)
    monkeypatch.setattr(ClaudeComposer, "calls", DailyCallCap())
    calls = []

    assert _composer(calls).compose(RESULTS) == TemplateComposer().compose(RESULTS)
    assert calls == []


def test_beacon_bad_origin_opens_no_connection(client, opened, monkeypatch):
    monkeypatch.setattr(api.events, "record", lambda conn, events, source: len(events))
    headers = {"content-type": "text/plain"}
    token = identity.sign("u1")
    body = f'{{"user_id": "u1", "events": [], "token": "{token}"}}'

    assert (
        client.post("/events/beacon", content=body, headers={**headers, "origin": "https://evil.com"}).status_code
        == 403
    )
    assert client.post("/events/beacon", content=b"x" * (api.MAX_BEACON_BYTES + 1), headers=headers).status_code == 413
    assert client.post("/events/beacon", content="{roto", headers=headers).status_code == 422
    bad_type = f'{{"user_id": "u1", "events": [{{"type": "order_placed", "session_id": "s"}}], "token": "{token}"}}'
    assert client.post("/events/beacon", content=bad_type.replace(token, "otro"), headers=headers).status_code == 401
    assert client.post("/events/beacon", content=bad_type, headers=headers).status_code == 400
    assert opened == []

    assert client.post("/events/beacon", content=body, headers=headers).status_code == 204
    assert opened == ["connector"]  # la conexión se abre solo para guardar
