"""La mantención de la caché del catálogo (api/prewarm.py: `keep_catalog_warm`): la Home primero, una pasada por
ciclo, con su propia conexión, y nunca lanza."""

import logging
import threading

import psycopg

from rappi_ia.api import prewarm
from rappi_ia.catalog import cache


class FakeConn:
    def __init__(self):
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append(sql)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _stop_after(calls: list, n: int, stop: threading.Event):
    def passes(conn):
        calls.append(conn)
        if len(calls) >= n:
            stop.set()
        return ["home"] if len(calls) == 1 else []

    return passes


def test_keep_catalog_warm_computes_the_home_first_and_then_one_pass_per_cycle(monkeypatch, caplog):
    conns = []

    def connect(*args, **kwargs):
        assert kwargs["application_name"] == "rappi-ia-mantencion" and kwargs["autocommit"]
        conns.append(FakeConn())
        return conns[-1]

    monkeypatch.setattr(psycopg, "connect", connect)
    homes, passes, stop = [], [], threading.Event()
    monkeypatch.setattr("rappi_ia.catalog.home.home", lambda conn: homes.append(conn))
    monkeypatch.setattr(cache, "keep_warm", _stop_after(passes, 2, stop))
    monkeypatch.setattr(cache, "WARM_EVERY_S", 0)

    with caplog.at_level(logging.INFO, logger="rappi_ia.api.prewarm"):
        prewarm.keep_catalog_warm(url="postgresql:///falsa", stop=stop)

    assert homes == [conns[0]]  # la Home una sola vez, en la primera pasada
    assert passes == conns and len(conns) == 2  # una conexión nueva por pasada, y se cierra
    assert all("statement_timeout" in c.statements[0] for c in conns)
    assert "Caché del catálogo renovada: home" in caplog.text


def test_keep_catalog_warm_with_the_database_down_only_warns_and_retries(monkeypatch, caplog):
    attempts, stop = [], threading.Event()

    def connect(*args, **kwargs):
        attempts.append(1)
        if len(attempts) >= 2:
            stop.set()
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setattr(cache, "WARM_EVERY_S", 0)
    with caplog.at_level(logging.WARNING, logger="rappi_ia.api.prewarm"):
        prewarm.keep_catalog_warm(url="postgresql:///falsa", stop=stop)
    assert len(attempts) == 2
    assert "No se pudo mantener caliente la caché del catálogo" in caplog.text


def test_start_runs_the_prewarm_and_then_the_upkeep_and_stop_ends_it(monkeypatch):
    order = []
    monkeypatch.setattr(prewarm.config, "API_PREWARM", True)
    monkeypatch.setattr(prewarm, "prewarm_search_indexes", lambda: order.append("precarga"))
    monkeypatch.setattr(prewarm, "keep_catalog_warm", lambda stop: order.append(("mantencion", stop)))
    thread = prewarm.start()
    thread.join(5)
    assert order[0] == "precarga" and order[1][0] == "mantencion"
    assert order[1][1] is prewarm._stop and not prewarm._stop.is_set()
    prewarm.stop()
    assert prewarm._stop.is_set()
