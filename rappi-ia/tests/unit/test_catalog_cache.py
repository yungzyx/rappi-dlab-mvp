"""La caché del catálogo: un valor se reutiliza mientras no haya una corrida nueva ni pase su TTL."""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from rappi_ia.catalog import cache


class FakeConn:
    """Responde la última corrida terminada (`catalog_version`) y cuenta cuántas veces se preguntó."""

    def __init__(self, run_id: int | None = 7):
        self.run_id = run_id
        self.asked = 0

    def execute(self, sql, params=None):
        assert "scrape_runs" in sql
        self.asked += 1
        return self

    def fetchone(self):
        return (self.run_id,)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(cache, "_now", clock)
    cache.clear()
    yield clock
    cache.clear()


def _counter():
    calls = []

    def compute():
        calls.append(1)
        return {"vez": len(calls)}

    return compute, calls


def test_cache_hits_same_version(clock):
    conn, (compute, calls) = FakeConn(), _counter()

    first = cache.cached("home", conn, compute)
    clock.now += cache.VERSION_TTL_S + 1  # vuelve a preguntar la versión: la misma
    second = cache.cached("home", conn, compute)

    assert first is second and calls == [1]
    assert conn.asked == 2
    assert cache.cached("otra", conn, compute) == {"vez": 2}  # cada nombre es su propia entrada


def test_new_run_invalidates(clock):
    conn, (compute, _) = FakeConn(), _counter()
    cache.cached("home", conn, compute)

    conn.run_id = 8  # terminó una corrida nueva
    assert cache.cached("home", conn, compute) == {"vez": 1}  # la versión se reutiliza unos segundos
    clock.now += cache.VERSION_TTL_S + 1

    assert cache.cached("home", conn, compute) == {"vez": 2}
    assert cache.catalog_version(conn) == 8


def test_value_expires_after_its_ttl(clock):
    """Lo que cambia sin corrida (`make post-refresh`, `make layers`) se ve cuando vence el TTL."""
    conn, (compute, _) = FakeConn(), _counter()
    cache.cached("home", conn, compute, ttl_s=60)

    clock.now += 59
    assert cache.cached("home", conn, compute, ttl_s=60) == {"vez": 1}
    clock.now += 2
    assert cache.cached("home", conn, compute, ttl_s=60) == {"vez": 2}


def test_concurrent_misses_compute_once(clock):
    """En frío, seis personas abren la Home a la vez: el catálogo se recorre una vez y los demás esperan ese valor."""
    conn, calls = FakeConn(), []
    started, barrier = threading.Event(), threading.Barrier(6)

    def slow():
        calls.append(1)
        started.set()
        time.sleep(0.2)  # los otros cinco llegan mientras tanto
        return {"vez": len(calls)}

    def ask(_):
        barrier.wait()
        return cache.cached("home", conn, slow)

    with ThreadPoolExecutor(6) as executor:
        values = list(executor.map(ask, range(6)))

    assert calls == [1]
    assert all(value is values[0] for value in values)
    assert cache.cached("otra", conn, slow) == {"vez": 2}  # otro nombre no espera a "home"


def test_a_slow_load_does_not_keep_the_others_waiting_forever(clock, monkeypatch):
    """Quien espera tiene la transacción quieta: si el que calcula tarda más que LOADING_WAIT_S, lo calcula él (si no,
    la API cortaría su transacción a los 10 s)."""
    monkeypatch.setattr(cache, "LOADING_WAIT_S", 0.05)
    conn, release = FakeConn(), threading.Event()

    def stuck():
        release.wait(2)
        return {"de": "el lento"}

    with ThreadPoolExecutor(1) as executor:
        slow = executor.submit(cache.cached, "home", conn, stuck)
        time.sleep(0.02)  # el lento ya tiene el candado
        started = time.monotonic()
        assert cache.cached("home", conn, lambda: {"de": "quien esperaba"}) == {"de": "quien esperaba"}
        assert time.monotonic() - started < 1
        release.set()
        assert slow.result() == {"de": "el lento"}


def test_a_failed_load_is_retried_by_the_next_caller(clock):
    conn, (compute, calls) = FakeConn(), _counter()

    def broken():
        raise RuntimeError("la consulta se cortó")

    with pytest.raises(RuntimeError):
        cache.cached("home", conn, broken)

    assert cache.cached("home", conn, compute) == {"vez": 1} and calls == [1]


def test_version_is_asked_at_most_once_per_window(clock):
    """Una búsqueda pide el conteo de 8 verticales: la versión se consulta una vez, no ocho."""
    conn, (compute, _) = FakeConn(), _counter()
    for vertical in range(8):
        cache.cached(f"docs:{vertical}", conn, compute)
    assert conn.asked == 1


def test_empty_catalog_has_version_zero(clock):
    assert cache.catalog_version(FakeConn(None)) == 0


def _fetcher():
    """`fetch(faltantes)` de `cached_many`: anota qué le pidieron y devuelve el largo de cada clave."""
    asked = []

    def fetch(keys):
        asked.append(list(keys))
        return {key: len(key) for key in keys}

    return fetch, asked


def test_many_fetches_only_what_is_missing(clock):
    conn, (fetch, asked) = FakeConn(), _fetcher()

    assert cache.cached_many("df:turbo", conn, ["papas", "frit"], fetch) == {"papas": 5, "frit": 4}
    assert cache.cached_many("df:turbo", conn, ["frit", "sal"], fetch) == {"frit": 4, "sal": 3}

    assert asked == [["papas", "frit"], ["sal"]]
    assert cache.cached_many("df:mall", conn, ["papas"], fetch) == {"papas": 5}  # cada prefijo es aparte
    assert asked[-1] == ["papas"]


def test_many_follows_the_catalog_version_and_the_ttl(clock):
    conn, (fetch, asked) = FakeConn(), _fetcher()
    cache.cached_many("df:turbo", conn, ["papas"], fetch)

    conn.run_id = 8  # corrida nueva
    clock.now += cache.VERSION_TTL_S + 1
    cache.cached_many("df:turbo", conn, ["papas"], fetch)
    clock.now += cache.DEFAULT_TTL_S + 1  # vence sin corrida
    cache.cached_many("df:turbo", conn, ["papas"], fetch)

    assert asked == [["papas"], ["papas"], ["papas"]]


def test_many_is_bounded_and_forgets_the_least_recently_used(clock, monkeypatch):
    """Las palabras que la gente busca no tienen fin: la caché guarda a lo más MANY_MAX y olvida la usada hace más
    tiempo."""
    monkeypatch.setattr(cache, "MANY_MAX", 3)
    conn, (fetch, asked) = FakeConn(), _fetcher()
    cache.cached_many("df", conn, ["a", "b", "c"], fetch)
    cache.cached_many("df", conn, ["a"], fetch)  # "a" pasa a ser la más reciente

    cache.cached_many("df", conn, ["d"], fetch)  # entra "d" y sale "b"
    cache.cached_many("df", conn, ["a", "c", "d"], fetch)
    cache.cached_many("df", conn, ["b"], fetch)

    assert asked == [["a", "b", "c"], ["d"], ["b"]]
    assert len(cache._many) == 3


def test_clear_also_forgets_many(clock):
    conn, (fetch, asked) = FakeConn(), _fetcher()
    cache.cached_many("df", conn, ["a"], fetch)
    cache.clear()
    cache.cached_many("df", conn, ["a"], fetch)

    assert asked == [["a"], ["a"]]


def _refresher():
    calls = []

    def refresh(conn):
        calls.append(conn)
        return {"renovado": len(calls)}

    return refresh, calls


def test_keep_warm_renews_what_is_about_to_expire_and_leaves_the_rest(clock):
    """Lo registrado con `refresh` se recalcula antes de vencer (WARM_AHEAD_S), y lo que acaba de calcularse, no."""
    conn = FakeConn()
    compute, _ = _counter()
    refresh, calls = _refresher()
    cache.cached("home", conn, compute, ttl_s=600, refresh=refresh)
    cache.cached("docs:licores", conn, compute, ttl_s=600)  # sin refresh: no se mantiene caliente
    assert cache.keep_warm(conn) == []  # recién calculado

    clock.now += 600 - cache.WARM_AHEAD_S
    assert cache.keep_warm(conn) == ["home"]
    assert calls == [conn]
    assert cache.cached("home", conn, compute, ttl_s=600, refresh=refresh) == {"renovado": 1}  # ya renovado: no vence
    clock.now += 10
    assert cache.cached("docs:licores", conn, compute, ttl_s=600) == {"vez": 2}  # este sí venció y se recalculó


def test_keep_warm_renews_everything_registered_after_a_new_run(clock):
    conn = FakeConn(run_id=7)
    compute, _ = _counter()
    refresh, calls = _refresher()
    cache.cached("home", conn, compute, refresh=refresh)
    conn.run_id = 8
    assert cache.keep_warm(conn) == ["home"]
    clock.now += cache.VERSION_TTL_S  # el request vuelve a preguntar la versión y ve la corrida nueva
    assert cache.cached("home", conn, compute, refresh=refresh) == {"renovado": 1}  # la versión nueva, sin recalcular
    assert calls == [conn]


def test_keep_warm_computes_what_was_registered_but_cleared(clock):
    """Tras `clear` (o si nunca se pidió) lo registrado no está: la pasada lo calcula."""
    conn = FakeConn()
    refresh, calls = _refresher()
    cache._warm["home"] = (refresh, 600)
    assert cache.keep_warm(conn) == ["home"]
    assert calls == [conn]


def test_a_refresh_that_fails_keeps_the_old_value_and_the_others_go_on(clock, caplog):
    conn = FakeConn()
    compute, _ = _counter()
    refresh, _ = _refresher()

    def broken(_conn):
        raise RuntimeError("la base no respondió")

    cache.cached("home", conn, compute, refresh=broken)
    cache.cached("deals:licores:24", conn, compute, refresh=refresh)
    clock.now += 600
    with caplog.at_level(logging.WARNING, logger="rappi_ia.catalog.cache"):
        assert cache.keep_warm(conn) == ["deals:licores:24"]
    assert "No se pudo renovar home" in caplog.text
    assert cache._values["home"][2] == {"vez": 1}  # lo de antes sigue (vencido: el próximo request lo recalcula)


def test_clear_also_forgets_what_was_registered(clock):
    refresh, _ = _refresher()
    cache.cached("home", FakeConn(), lambda: 1, refresh=refresh)
    cache.clear()
    assert cache._warm == {}
