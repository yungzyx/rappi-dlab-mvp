"""El pool de conexiones de la API contra `rappi_ia_test`: tope de conexiones, ajustes que no pasan de un request a
otro, 503 cuando no queda una libre, y las escrituras anónimas acotadas (un `ensure_user` por lote, purga de
inactivos)."""

import logging
import threading
import time
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import anyio
import pytest
from psycopg.pq import TransactionStatus
from rappi_scraper.storage.search import build_search_documents

from conftest import add_price, add_product, add_store
from owner_client import OwnerClient
from rappi_ia import cli, config
from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.rappi_agent import Context, RappiAgent
from rappi_ia.api import app as api
from rappi_ia.api import deps, services
from rappi_ia.api.services import Services
from rappi_ia.concepts.pipeline import build_concepts
from rappi_ia.db import connect
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents
from rappi_ia.events import store as events
from rappi_ia.retrieval import hybrid
from rappi_ia.retrieval.hybrid import CANDIDATES, VECTOR_RANDOM_PAGE_COST

POOL_MAX = 3


@pytest.fixture
def make_pool(monkeypatch):
    """Instala en la API un pool propio (el de la API real nunca se abre en los tests) y lo cierra al final."""
    pools = []

    def make(url: str, max_size: int = POOL_MAX, timeout: float = 3.0, wait: bool = True):
        monkeypatch.setattr(config, "API_POOL_MIN", 1)
        monkeypatch.setattr(config, "API_POOL_MAX", max_size)
        monkeypatch.setattr(config, "API_POOL_TIMEOUT_S", timeout)
        pool = deps.make_pool(url)
        pool.open(wait=wait)
        pools.append(pool)
        monkeypatch.setattr(deps, "_pool", pool)
        monkeypatch.setattr(deps, "_gate", deps.gate_for(pool))  # el turno, del tamaño del pool (como open_pool)
        return pool

    yield make
    for pool in pools:
        pool.close(timeout=1)


@pytest.fixture
def client():
    embedder = HashEmbedder()
    api.app.dependency_overrides[api.get_services] = lambda: Services(
        RappiAgent(embedder, TemplateComposer()), embedder
    )
    yield OwnerClient(api.app)
    api.app.dependency_overrides.clear()


@pytest.fixture
def live_client(monkeypatch):
    """Un solo event loop para todos los requests, como uvicorn (`with TestClient`): los turnos y cupos son de anyio
    y sus esperas viven en el loop. Corre el lifespan (sin modelos; el pool real no se abre en los tests)."""
    monkeypatch.setenv("RAPPI_IA_LIGHT", "1")
    services._load_services.cache_clear()
    embedder = HashEmbedder()
    api.app.dependency_overrides[api.get_services] = lambda: Services(
        RappiAgent(embedder, TemplateComposer()), embedder
    )
    try:
        with OwnerClient(api.app) as client:
            yield client
    finally:
        api.app.dependency_overrides.clear()
        services._load_services.cache_clear()


def _catalog(db) -> None:
    add_store(db, 1, "supermercado", "Súper")
    for pid, name, price in [(100, "Papas fritas Lays Clásicas 180 g", 1990), (101, "Papas Kryzpo Original", 2290)]:
        add_product(db, pid, name, 1, "Snacks salados")
        add_price(db, 1, pid, price)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, HashEmbedder())
    db.commit()


def test_fifty_requests_stay_within_pool(db, test_url, make_pool, live_client):
    pool = make_pool(test_url)
    barrier = threading.Barrier(50)
    done = threading.Event()
    seen = []

    def sample():  # en su propia conexión, en autocommit: pg_stat_activity se congela dentro de una transacción
        with connect(test_url, autocommit=True) as watcher:
            while not done.is_set():
                seen.append(
                    watcher.execute(
                        """SELECT count(*) FROM pg_stat_activity
                           WHERE application_name = 'rappi-ia-api' AND datname = current_database()"""
                    ).fetchone()[0]
                )

    def call(_):
        barrier.wait()  # los 50 a la vez
        return live_client.get("/profile/u1").status_code

    watcher = threading.Thread(target=sample)
    watcher.start()
    try:
        with ThreadPoolExecutor(50) as executor:
            statuses = list(executor.map(call, range(50)))
    finally:
        done.set()
        watcher.join()

    assert statuses == [200] * 50
    assert seen and max(seen) <= POOL_MAX
    assert pool.get_stats()["connections_num"] <= POOL_MAX  # nunca abrió más de las que caben


def test_a_burst_does_not_starve_the_threadpool(test_url, make_pool, live_client):
    """100 requests a la vez en un solo event loop (como uvicorn) con 3 conexiones y 3 turnos: los que esperan conexión
    no ocupan los 40 hilos del threadpool, así los que ya tienen una pueden correr su endpoint. Antes, todos los hilos
    quedaban esperando en el pool, nadie devolvía su conexión y la mitad salía con 503 a los 3 s."""
    pool = make_pool(test_url)
    assert deps._gate.limit == pool.max_size == POOL_MAX
    barrier = threading.Barrier(100)

    def call(_):
        barrier.wait()
        return live_client.get("/profile/u1").status_code

    with ThreadPoolExecutor(100) as executor:
        statuses = list(executor.map(call, range(100)))

    assert statuses == [200] * 100


def test_set_local_does_not_leak_to_next_request(db, test_url, make_pool, client):
    """La búsqueda vectorial sube `hnsw.ef_search` y baja `random_page_cost` solo en su transacción: con una sola
    conexión en el pool, el request siguiente la recibe con los valores normales."""
    _catalog(db)
    # El valor de sesión se fija en la URL: el servidor local puede tener otro (p. ej. 1.1 con ALTER SYSTEM).
    default_page_cost = "4"
    assert default_page_cost != str(VECTOR_RANDOM_PAGE_COST)  # si no, la prueba no prueba nada
    separator = "&" if "?" in test_url else "?"
    pool = make_pool(f"{test_url}{separator}options=-c%20random_page_cost%3D{default_page_cost}", max_size=1)

    reply = client.get("/search", params={"q": "papas fritas", "vertical": "supermercado", "mode": "vector"})
    assert reply.status_code == 200 and reply.json()["products"]

    with pool.connection() as conn:
        assert conn.execute("SELECT current_setting('hnsw.ef_search', true)").fetchone()[0] != str(CANDIDATES)
        assert conn.execute("SELECT current_setting('hnsw.iterative_scan', true)").fetchone()[0] != "relaxed_order"
        assert conn.execute("SELECT current_setting('random_page_cost')").fetchone()[0] == default_page_cost


class PlannerSpy:
    """La conexión del test que anota el `random_page_cost` con que se planifica cada búsqueda vectorial."""

    def __init__(self, conn):
        self._conn = conn
        self.page_costs: list[str] = []

    def execute(self, query, *args, **kwargs):
        if "<=>" in str(query):
            self.page_costs.append(self._conn.execute("SELECT current_setting('random_page_cost')").fetchone()[0])
        return self._conn.execute(query, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_the_vector_search_plans_with_the_ssd_page_cost_only_in_its_transaction(db):
    """La búsqueda vectorial se planifica con VECTOR_RANDOM_PAGE_COST (así las verticales de 5 a 8 mil documentos usan
    su HNSW). Es local a la transacción: al confirmarla o deshacerla vuelve el valor de antes, también si la sesión
    tenía otro."""
    _catalog(db)
    embedder = HashEmbedder()
    vector = embedder.embed_queries(["papas fritas"])[0]
    # Valores de sesión fijos: el servidor local puede tener `random_page_cost` = 1.1 (ALTER SYSTEM).
    for session_value, end in (("4", db.commit), ("2.5", db.rollback)):
        db.execute(f"SET random_page_cost = {session_value}")
        db.commit()  # de sesión: un SET dentro de una transacción deshecha se deshace con ella
        before = db.execute("SELECT current_setting('random_page_cost')").fetchone()[0]
        assert before != str(VECTOR_RANDOM_PAGE_COST)
        spy = PlannerSpy(db)

        found = hybrid._vector(spy, "supermercado", vector, embedder, hybrid.Filters())

        assert found
        assert spy.page_costs == [str(VECTOR_RANDOM_PAGE_COST)]
        end()
        assert db.execute("SELECT current_setting('random_page_cost')").fetchone()[0] == before


def test_pool_timeout_is_503(test_url, make_pool, client):
    make_pool(test_url, max_size=1, timeout=0.2)

    with deps._checkout(config.API_TIMEOUT_INTERACTIVE_MS):  # otro request tiene la única conexión
        reply = client.get("/profile/u1")

    assert reply.status_code == 503
    assert reply.json()["detail"] == "Hay mucha gente ahora; intenta en unos segundos."
    assert reply.headers["retry-after"] == "2"
    assert client.get("/profile/u1").status_code == 200  # se liberó


def test_an_order_releases_its_connection_before_recalculating_segments(db, test_url, make_pool, live_client, caplog):
    """Con una sola conexión: el pedido devuelve la suya (y su turno) antes de la tarea en segundo plano, que toma
    otra del pool por el mismo turno. Antes, la del pedido seguía tomada hasta que terminaba la tarea, y la tarea
    esperaba hasta el timeout."""
    _catalog(db)
    make_pool(test_url, max_size=1, timeout=1)
    api.app.dependency_overrides[api.get_connector] = lambda: deps.pooled_connection
    order = {
        "user_id": "p-pedido",
        "session_id": "s",
        "cart_id": "c",
        "vertical": "supermercado",
        "lines": [{"entity_type": "catalog_item", "entity_id": "100", "store_id": 1}],
    }

    with caplog.at_level(logging.INFO, logger="rappi_ia.layers.segments"):
        reply = live_client.post("/orders", json=order)

    assert reply.status_code == 200, reply.text
    assert "Segmentos recalculados" in caplog.text
    assert "p-pedido" not in caplog.text  # el registro no lleva el id de la persona
    assert "No se pudieron recalcular" not in caplog.text
    assert deps.connections_in_use() == 0


def test_a_cancelled_request_returns_its_connection(test_url, make_pool):
    """Un request cancelado (el cliente se fue) devuelve su conexión y su turno igual."""
    pool = make_pool(test_url, max_size=1)

    async def cancel_while_holding():
        connections = deps.get_conn()
        await anext(connections)
        assert deps.connections_in_use() == 1
        with pytest.raises(anyio.get_cancelled_exc_class()):
            await connections.athrow(anyio.get_cancelled_exc_class()())

    anyio.run(cancel_while_holding)

    assert deps.connections_in_use() == 0
    assert pool.get_stats()["pool_available"] == 1
    assert deps._gate.slots.value == 1


def test_a_broken_connection_is_replaced_before_use(db, test_url, make_pool, live_client):
    """Una conexión que Postgres cortó (reinicio, idle timeout) no le llega a un request: el pool la revisa."""
    make_pool(test_url, max_size=1)
    assert live_client.get("/profile/u1").status_code == 200
    db.execute(
        """SELECT pg_terminate_backend(pid) FROM pg_stat_activity
           WHERE application_name = 'rappi-ia-api' AND datname = current_database()"""
    )
    db.commit()

    assert live_client.get("/profile/u1").status_code == 200


def test_after_a_postgres_restart_the_next_request_gets_a_healthy_connection(db, test_url, make_pool, live_client):
    """Un reinicio de Postgres corta todas las conexiones del pool. Antes, el pool las encontraba una a una, esperando
    1 s y 2 s entre cada una: con todas muertas, el request salía con 503 a los 3 s (y el siguiente también). Ahora la
    primera muerta hace revisar todo el pool en otro hilo y el request recibe una nueva."""
    pool = make_pool(test_url, max_size=POOL_MAX)
    held = [pool.getconn() for _ in range(POOL_MAX)]  # las tres abiertas y libres
    for conn in held:
        pool.putconn(conn)
    killed = db.execute(
        """SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity
           WHERE application_name = 'rappi-ia-api' AND datname = current_database()"""
    ).fetchone()[0]
    db.commit()
    assert killed == POOL_MAX

    start = time.monotonic()
    reply = live_client.get("/profile/u1")

    assert reply.status_code == 200
    assert time.monotonic() - start < 1.5  # lo que la app espera a /health antes de decir «Sin conexión»
    assert live_client.get("/profile/u1").status_code == 200


def test_waiting_for_a_turn_counts_against_the_pool_timeout(monkeypatch):
    """La espera total (turno más pool) no pasa de API_POOL_TIMEOUT_S: el pool recibe lo que queda."""
    asked = []

    class Pool:
        max_size, timeout = 1, 3.0

        @contextmanager
        def connection(self, timeout=None):
            asked.append(timeout)
            yield SimpleNamespace(execute=lambda *_: None, commit=lambda: None)

    pool = Pool()
    monkeypatch.setattr(deps, "_pool", pool)
    monkeypatch.setattr(deps, "_gate", deps.gate_for(pool))

    async def once():
        connections = deps.get_conn()
        await anext(connections)
        await connections.aclose()

    anyio.run(once)

    assert len(asked) == 1 and 0 < asked[0] <= 3.0


def test_api_without_pool_refuses_to_connect(client):
    """Sin `lifespan` (un TestClient sin `with`) no hay pool: nunca se abre una conexión por fuera de él."""
    assert deps._pool is None
    with pytest.raises(RuntimeError, match="pool"):
        client.get("/profile/u1")


def test_ask_commits_before_composing_with_the_llm(db):
    """Claude puede tardar segundos: la conexión no queda «idle in transaction» mientras redacta."""
    _catalog(db)
    seen = []

    class Remote(TemplateComposer):
        name, remote = "claude", True

        def compose(self, draft):
            seen.append((draft.kind, db.info.transaction_status))
            return super().compose(draft)

    RappiAgent(None, Remote()).reply(db, "papas fritas", Context())

    assert seen == [("resultados", TransactionStatus.IDLE)]


def test_record_ensures_user_once_per_batch(db, monkeypatch):
    calls = []
    ensure = events.ensure_user
    monkeypatch.setattr(
        events,
        "ensure_user",
        lambda conn, user_id, source="prototype", **extra: (
            calls.append(user_id),
            ensure(conn, user_id, source, **extra),
        ),
    )
    batch = [events.Event("u-lote", "s1", "app_open") for _ in range(200)]

    assert events.record(db, batch) == 200
    assert calls == ["u-lote"]
    calls.clear()
    events.record(db, [events.Event("u-a", "s", "app_open"), events.Event("u-b", "s", "app_open")] * 3)
    assert calls == ["u-a", "u-b"]


def test_record_refuses_other_source_before_writing(db):
    events.record(db, [events.Event("sim-1", "s", "app_open")], source="synthetic")

    with pytest.raises(ValueError, match="otra fuente"):
        events.record(db, [events.Event("p-1", "s", "app_open"), events.Event("sim-1", "s", "app_open")])


def test_purge_removes_only_inactive_prototype_users(db, capsys):
    old = datetime.now(UTC) - timedelta(days=200)
    recent = datetime.now(UTC) - timedelta(days=10)
    for user_id, source in [
        ("p-viejo", "prototype"),
        ("p-evento", "prototype"),
        ("p-pedido", "prototype"),
        ("s-viejo", "synthetic"),
    ]:
        db.execute("INSERT INTO app_users (user_id, source, created_at) VALUES (%s, %s, %s)", (user_id, source, old))
    events.ensure_user(db, "p-nuevo")  # recién llegado, sin actividad todavía
    events.record(db, [events.Event("p-viejo", "s", "app_open", ts=old)])
    events.record(
        db, [events.Event("p-evento", "s", "app_open", ts=old), events.Event("p-evento", "s", "ask", ts=recent)]
    )
    events.record(db, [events.Event("s-viejo", "s", "app_open", ts=old)], source="synthetic")
    db.execute(
        """INSERT INTO app_orders (order_id, user_id, session_id, cart_id, ts, vertical, total, source)
           VALUES ('ord-1', 'p-pedido', 's', 'c', %s, 'licores', 1000, 'prototype')""",
        (recent,),
    )

    assert events.purge_inactive_users(db, days=180) == 1

    users = {row[0] for row in db.execute("SELECT user_id FROM app_users")}
    assert users == {"p-evento", "p-pedido", "p-nuevo", "s-viejo"}
    assert db.execute("SELECT count(*) FROM app_events WHERE user_id = 'p-viejo'").fetchone()[0] == 0
    assert config.PROTOTYPE_USER_RETENTION_DAYS == 180

    cli.cmd_purge(db, Namespace(dias=None))
    assert "Usuarios del prototipo sin actividad en 180 días borrados: 0" in capsys.readouterr().out
