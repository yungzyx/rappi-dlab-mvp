"""La búsqueda de la app en varias verticales a la vez (`grouped_search.search_each`), con conexiones falsas: el orden
de los resultados es el de las verticales, nunca usa más conexiones extra que el tope, sin una libre busca en serie con
la de la petición, cada vertical cierra su transacción, los hilos llevan el id del request y un error de una vertical
llega a quien llamó después de devolver todas."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import numpy as np
import pytest

from rappi_ia.agent import grouped_search
from rappi_ia.agent.grouped_search import PARALLEL_SEARCHES, search_each
from rappi_ia.api import logs
from rappi_ia.embeddings.base import MemoizedQueryEmbedder

VERTICALS = ["supermercado", "conveniencia", "turbo", "restaurantes", "farmacia", "licores", "chocolateria", "mall"]


class FakeConn(str):
    """Una conexión falsa: se compara como su nombre y anota sus commit y rollback."""

    def __new__(cls, name: str):
        conn = super().__new__(cls, name)
        conn.done = []
        return conn

    def commit(self):
        self.done.append("commit")

    def rollback(self):
        self.done.append("rollback")


class Spares:
    """Conexiones extra falsas: `available` dice cuántas puede entregar; anota cuántas hay afuera a la vez."""

    def __init__(self, available: int):
        self.available = available
        self.out = 0
        self.max_out = 0
        self.lock = threading.Lock()

    @contextmanager
    def __call__(self):
        with self.lock:
            if self.available <= 0:
                conn = None
            else:
                self.available -= 1
                self.out += 1
                self.max_out = max(self.max_out, self.out)
                conn = FakeConn(f"extra-{self.out}")
        try:
            yield conn
        finally:
            if conn is not None:
                with self.lock:
                    self.out -= 1
                    self.available += 1


def slow_search(seen: list):
    def search(conn, vertical):
        seen.append((conn, vertical, threading.current_thread().name))
        time.sleep(0.05 * (len(VERTICALS) - VERTICALS.index(vertical)) / len(VERTICALS))  # las primeras, al final
        return f"{vertical}@resultado"

    return search


def test_results_keep_the_order_of_the_verticals():
    seen = []
    spares = Spares(available=10)

    results = search_each(FakeConn("peticion"), VERTICALS, slow_search(seen), spares)

    assert results == [f"{v}@resultado" for v in VERTICALS]
    assert {conn for conn, _, _ in seen} - {"peticion"}  # también usó conexiones extra
    assert spares.out == 0  # todas devueltas


def test_never_more_spare_connections_than_the_cap():
    seen = []
    spares = Spares(available=10)

    search_each(FakeConn("peticion"), VERTICALS, slow_search(seen), spares)

    assert spares.max_out <= PARALLEL_SEARCHES
    assert len({conn for conn, _, _ in seen}) <= PARALLEL_SEARCHES + 1  # las extra y la de la petición


def test_without_a_free_connection_it_searches_in_series_with_the_request_connection():
    seen = []

    results = search_each(FakeConn("peticion"), VERTICALS, slow_search(seen), Spares(available=0))

    assert results == [f"{v}@resultado" for v in VERTICALS]
    assert [(conn, vertical) for conn, vertical, _ in seen] == [("peticion", v) for v in VERTICALS]
    assert {name for _, _, name in seen} == {threading.current_thread().name}


def test_with_some_free_connections_it_uses_only_those():
    seen = []
    spares = Spares(available=1)

    results = search_each(FakeConn("peticion"), VERTICALS, slow_search(seen), spares)

    assert results == [f"{v}@resultado" for v in VERTICALS]
    assert {conn for conn, _, _ in seen} <= {"peticion", "extra-1"}


def test_one_vertical_or_no_spare_factory_searches_in_series():
    seen = []
    assert search_each(FakeConn("peticion"), ["turbo"], slow_search(seen), Spares(available=10)) == ["turbo@resultado"]
    assert search_each(FakeConn("peticion"), VERTICALS[:2], slow_search(seen), None) == [
        f"{v}@resultado" for v in VERTICALS[:2]
    ]
    assert {conn for conn, _, _ in seen} == {"peticion"}


def test_an_error_in_one_vertical_reaches_the_caller_after_returning_every_connection():
    spares = Spares(available=10)

    def search(conn, vertical):
        if vertical == "turbo":
            raise RuntimeError("la consulta tardó demasiado")
        time.sleep(0.01)
        return vertical

    with pytest.raises(RuntimeError, match="tardó demasiado"):
        search_each(FakeConn("peticion"), VERTICALS, search, spares)

    assert spares.out == 0


def test_the_cap_is_small():
    """Cada vertical en paralelo es una conexión más del pool (API_POOL_MAX, 10 por defecto): el tope es chico."""
    assert 1 <= grouped_search.PARALLEL_SEARCHES <= 4


def test_the_query_is_embedded_once_even_from_several_threads():
    """Las verticales se buscan en hilos y cada una embebe la consulta: el modelo la codifica una sola vez."""
    calls = []

    class SlowModel:
        model_name, dim = "lento", 2

        def embed_queries(self, texts):
            calls.append(list(texts))
            time.sleep(0.05)
            return np.ones((len(texts), 2), dtype=np.float32)

        def embed_documents(self, texts):
            raise AssertionError("no embebe documentos")

    memo = MemoizedQueryEmbedder(SlowModel())
    with ThreadPoolExecutor(4) as pool:
        vectors = list(pool.map(lambda _: memo.embed_queries(["sushi"]), range(8)))

    assert calls == [["sushi"]]
    assert all(v.shape == (1, 2) for v in vectors)


def test_each_vertical_in_parallel_ends_its_transaction():
    """Una conexión extra no queda «idle in transaction» mientras termina la vertical más lenta (Postgres la corta a
    los 10 s): cada vertical confirma la suya al terminar."""
    request, spares = FakeConn("peticion"), Spares(available=10)
    used = []

    def search(conn, vertical):
        used.append(conn)
        return vertical

    search_each(request, VERTICALS, search, spares)

    assert sum(conn.done.count("commit") for conn in set(used)) == len(VERTICALS)
    assert all(conn.done[-1] == "commit" for conn in set(used))


def test_a_failed_vertical_rolls_back_its_connection_for_the_next_one():
    request = FakeConn("peticion")
    used = []

    def search(conn, vertical):
        used.append(conn)
        if vertical == "turbo":
            raise RuntimeError("falló turbo")
        return vertical

    with pytest.raises(RuntimeError, match="falló turbo"):
        search_each(request, VERTICALS, search, Spares(available=10))

    assert "rollback" in [step for conn in set(used) for step in conn.done]


def test_the_worker_threads_keep_the_request_id():
    """Los registros de una vertical buscada en otro hilo llevan el id del request (logs.request_id)."""
    seen = []

    def search(conn, vertical):
        seen.append(logs.request_id.get())
        time.sleep(0.01)
        return vertical

    token = logs.request_id.set("req-123")
    try:
        search_each(FakeConn("peticion"), VERTICALS, search, Spares(available=10))
    finally:
        logs.request_id.reset(token)

    assert seen == ["req-123"] * len(VERTICALS)
