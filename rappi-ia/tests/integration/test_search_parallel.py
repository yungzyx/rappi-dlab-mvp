"""`/search` sin vertical busca las verticales en paralelo con conexiones extra del pool, sin hacer fila por ellas: con
el pool libre devuelve los mismos grupos que en serie, con el pool agotado también (en serie, sin trabarse ni fallar),
nunca pasa el tope del pool ni el de conexiones extra por búsqueda y deja la reserva del pool a los demás requests.
Contra `rappi_ia_test` con el catálogo de prueba."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest

from owner_client import OwnerClient
from rappi_ia import config
from rappi_ia.agent import grouped_search
from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.grouped_search import PARALLEL_SEARCHES, search_grouped
from rappi_ia.agent.rappi_agent import RappiAgent
from rappi_ia.agent.tools import SearchOutcome
from rappi_ia.api import app as api
from rappi_ia.api import deps, services
from rappi_ia.api.services import Services
from rappi_ia.db import connect
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents
from rappi_ia.offers.engine import make_offer
from rappi_ia.retrieval.hybrid import RetrievalResult

# Con concepto (sus verticales típicas), con ocasión, sin ninguno (las 8 verticales) y sin resultado.
QUERIES = ["cerveza", "papas fritas", "algo para el carrete", "pizza", "chocolate", "café", "xyzzy", "té"]


@pytest.fixture
def catalog(db):
    seed_demo(db)
    embed_search_documents(db, HashEmbedder())
    db.commit()
    return db


@pytest.fixture
def make_pool(monkeypatch):
    """Instala en la API un pool propio sobre `rappi_ia_test` (el de la API real nunca se abre en los tests), ya con
    todas sus conexiones abiertas: una conexión extra espera al pool solo SPARE_WAIT_S (50 ms), y en un CI lento abrir
    una nueva tarda más (la búsqueda iba en serie y la prueba fallaba a ratos)."""
    pools = []

    def make(url: str, max_size: int):
        monkeypatch.setattr(config, "API_POOL_MIN", max_size)
        monkeypatch.setattr(config, "API_POOL_MAX", max_size)
        monkeypatch.setattr(config, "API_POOL_TIMEOUT_S", 3.0)
        pool = deps.make_pool(url)
        pool.open(wait=True)
        pools.append(pool)
        monkeypatch.setattr(deps, "_pool", pool)
        monkeypatch.setattr(deps, "_gate", deps.gate_for(pool))
        return pool

    yield make
    for pool in pools:
        pool.close(timeout=1)


@pytest.fixture
def client(monkeypatch):
    """Un solo event loop para todos los requests, como uvicorn: el turno de las conexiones vive en él."""
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


@pytest.fixture
def spares(monkeypatch):
    """Anota las conexiones extra que entrega `deps.spare_connection`: cuántas a la vez (lo más) y cuántas en total."""
    seen = {"out": 0, "max_out": 0, "given": 0, "refused": 0}
    lock = threading.Lock()
    real = deps.spare_connection

    @contextmanager
    def counted():
        with real() as conn:
            with lock:
                if conn is None:
                    seen["refused"] += 1
                else:
                    seen["given"] += 1
                    seen["out"] += 1
                    seen["max_out"] = max(seen["max_out"], seen["out"])
            try:
                yield conn
            finally:
                if conn is not None:
                    with lock:
                        seen["out"] -= 1

    monkeypatch.setattr(deps, "spare_connection", counted)
    return seen


def _serial(test_url, q: str) -> dict:
    with connect(test_url) as conn:
        return search_grouped(conn, q, HashEmbedder(), None, 6).to_dict()


def test_with_a_free_pool_the_groups_are_the_same_as_in_series(catalog, test_url, make_pool, client, spares):
    make_pool(test_url, max_size=10)

    for q in QUERIES:
        reply = client.get("/search", params={"q": q})
        assert reply.status_code == 200, reply.text
        assert reply.json() == _serial(test_url, q), q

    assert spares["given"] > 0  # sí buscó en paralelo
    assert spares["max_out"] <= PARALLEL_SEARCHES


def test_the_profile_offer_searches_its_steps_with_spare_connections(catalog, test_url, make_pool, client, spares):
    """El momento `perfil` de `/agent/offer` busca los peldaños de la escalera a la vez con las mismas conexiones extra
    (y el mismo tope) que `/search`, y responde lo mismo que en serie."""
    make_pool(test_url, max_size=10)

    for profile_id in ("asiatico", "carrete"):
        reply = client.post("/agent/offer", json={"moment": "perfil", "context": {"perfil": profile_id}})
        with connect(test_url) as conn:
            serial = make_offer(conn, HashEmbedder(), "perfil", {"perfil": profile_id})
        assert serial is not None, profile_id  # una escalera de verdad, no dos 204
        assert (reply.status_code, reply.json()) == (200, serial.to_dict()), profile_id

    assert spares["given"] > 0
    assert spares["max_out"] <= PARALLEL_SEARCHES


def test_with_the_pool_exhausted_it_searches_in_series_without_errors(catalog, test_url, make_pool, client, spares):
    """Con un pool de una conexión, la petición tiene la única: no hay turno libre para otra y busca en serie."""
    make_pool(test_url, max_size=1)

    for q in QUERIES:
        reply = client.get("/search", params={"q": q})
        assert reply.status_code == 200, reply.text
        assert reply.json() == _serial(test_url, q), q

    assert spares["given"] == 0 and spares["refused"] > 0


def test_with_the_pool_simulated_empty_it_searches_in_series(catalog, test_url, make_pool, client, monkeypatch):
    make_pool(test_url, max_size=10)

    @contextmanager
    def none_free():
        yield None

    monkeypatch.setattr(deps, "spare_connection", none_free)

    for q in ("cerveza", "papas fritas"):
        reply = client.get("/search", params={"q": q})
        assert reply.status_code == 200 and reply.json() == _serial(test_url, q), q


def test_concurrent_searches_never_pass_the_pool(catalog, test_url, make_pool, client, spares):
    """Seis búsquedas a la vez (bajo el cupo de /search, API_MAX_CONCURRENT_SEARCH) contra un pool de 4: nunca más de 4
    conexiones de la API en Postgres, todas responden 200 y ninguna búsqueda usa más conexiones extra que el tope."""
    make_pool(test_url, max_size=4)
    clients = 6
    barrier = threading.Barrier(clients)
    done = threading.Event()
    seen = []

    def sample():
        with connect(test_url, autocommit=True) as watcher:
            while not done.is_set():
                seen.append(
                    watcher.execute(
                        """SELECT count(*) FROM pg_stat_activity
                           WHERE application_name = 'rappi-ia-api' AND datname = current_database()"""
                    ).fetchone()[0]
                )

    def call(i):
        barrier.wait()
        return client.get("/search", params={"q": QUERIES[i % len(QUERIES)]}).status_code

    watcher = threading.Thread(target=sample)
    watcher.start()
    try:
        with ThreadPoolExecutor(clients) as executor:
            codes = list(executor.map(call, range(clients)))
    finally:
        done.set()
        watcher.join()

    assert set(codes) == {200}
    assert max(seen) <= 4
    assert spares["max_out"] <= 3  # 4 en el pool, una es de la petición


def test_the_query_is_embedded_once_per_search(catalog, test_url, make_pool, monkeypatch):
    """Con las verticales en paralelo, el modelo codifica la consulta una vez por búsqueda (la memoria de la búsqueda se
    comparte entre los hilos)."""
    calls = []

    class Counting(HashEmbedder):
        def embed_queries(self, texts):
            calls.append(list(texts))
            return super().embed_queries(texts)

    embedder = Counting()
    monkeypatch.setenv("RAPPI_IA_LIGHT", "1")
    services._load_services.cache_clear()
    api.app.dependency_overrides[api.get_services] = lambda: Services(
        RappiAgent(embedder, TemplateComposer()), embedder
    )
    try:
        with OwnerClient(api.app) as client:
            make_pool(test_url, max_size=10)
            for q in ("papas fritas", "xyzzy"):  # con concepto (sus verticales típicas) y sin él (las 8)
                calls.clear()
                assert client.get("/search", params={"q": q}).status_code == 200
                assert calls == [[q]], q
    finally:
        api.app.dependency_overrides.clear()
        services._load_services.cache_clear()


SLOW_S = 0.6  # lo que tarda cada vertical falsa


def test_searches_in_parallel_leave_room_for_other_requests(catalog, test_url, make_pool, client, spares, monkeypatch):
    """Dos búsquedas lentas a la vez (8 verticales cada una) contra un pool de 4: la primera toma una conexión extra y
    la segunda ninguna (quedaría bajo la reserva), así que /health no hace fila detrás de ellas. Sin la reserva, la
    primera se quedaba con las 4 conexiones hasta su última vertical y /health esperaba más de un segundo."""
    make_pool(test_url, max_size=4)
    active = {"now": 0}
    busy = threading.Condition()

    def slow(conn, vertical, query, concepts, embedder, price_max=None, k=6, mode="hibrido", words=None):
        with busy:
            active["now"] += 1
            busy.notify_all()
        time.sleep(SLOW_S)
        with busy:
            active["now"] -= 1
        result = RetrievalResult(vertical, query, [], [], 0, 0.5, False, True, "vertical lenta", True)
        return SearchOutcome(result, [])

    monkeypatch.setattr(grouped_search, "search_products", slow)
    with ThreadPoolExecutor(2) as executor:
        searches = [executor.submit(client.get, "/search", params={"q": "xyzzy"})]
        with busy:  # la primera ya busca en paralelo
            assert busy.wait_for(lambda: active["now"] >= 2, timeout=5)
        searches.append(executor.submit(client.get, "/search", params={"q": "xyzzy"}))
        with busy:  # y la segunda también: 2 verticales de la primera y 1 de la segunda (en serie)
            assert busy.wait_for(lambda: active["now"] >= 3, timeout=5)
        start = time.perf_counter()
        health = client.get("/health")
        waited = time.perf_counter() - start
        codes = [future.result().status_code for future in searches]

    assert health.status_code == 200, health.text
    assert codes == [200, 200]
    assert waited < SLOW_S / 2, f"/health esperó {waited:.2f} s"
    assert spares["max_out"] == 1
