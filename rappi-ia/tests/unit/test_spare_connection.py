"""`deps.spare_connection`, la conexión extra de la búsqueda en varias verticales, con un pool falso y el turno de
verdad (`ConcurrencyCap`): si el pool no la entrega a tiempo o falla al prepararla, da None y suelta el turno antes de
que siga la búsqueda; y nunca toma la reserva del pool que queda para los demás requests."""

import logging
from contextlib import contextmanager

import anyio
import anyio.to_thread
import pytest
from psycopg import OperationalError
from psycopg_pool import PoolTimeout

from rappi_ia.api import deps
from rappi_ia.api.limits import ConcurrencyCap

POOL_SIZE = 4


class FakeConn:
    def __init__(self, fail: bool = False):
        self.fail = fail

    def execute(self, *args, **kwargs):
        if self.fail:
            raise OperationalError("server closed the connection unexpectedly")
        return self

    def commit(self):
        pass


class FakePool:
    """`connection()` como el de psycopg_pool: entrega una conexión, o lanza lo que se le diga."""

    def __init__(self, error: Exception | None = None, fail_on_use: bool = False):
        self.error = error
        self.fail_on_use = fail_on_use
        self.out = 0

    @contextmanager
    def connection(self, timeout=None):
        if self.error is not None:
            raise self.error
        self.out += 1
        try:
            yield FakeConn(self.fail_on_use)
        finally:
            self.out -= 1


def in_endpoint(monkeypatch, pool: FakePool, body):
    """Corre `body(gate)` en un hilo de anyio (como el endpoint), con el turno de la conexión del request ya tomado."""
    results = []

    async def main():
        gate = ConcurrencyCap("conexiones", POOL_SIZE, wait_s=3.0)
        monkeypatch.setattr(deps, "_gate", gate)
        monkeypatch.setattr(deps, "_pool", pool)
        await gate.acquire()  # la conexión del request
        try:
            results.append(await anyio.to_thread.run_sync(body, gate))
        finally:
            gate.release()

    anyio.run(main)
    return results[0]


def test_a_pool_timeout_gives_none_and_frees_the_turn_before_the_search_goes_on(monkeypatch):
    """El pool no entrega una conexión en SPARE_WAIT_S (se achicó por inactividad y está creando una, o Postgres anda
    lento): el turno no queda tomado mientras la búsqueda sigue en serie."""

    def body(gate):
        before = gate.slots.value
        with deps.spare_connection() as conn:
            during = gate.slots.value
        return conn, before, during, gate.slots.value

    conn, before, during, after = in_endpoint(monkeypatch, FakePool(PoolTimeout("couldn't get a connection")), body)

    assert conn is None
    assert during == before == after == POOL_SIZE - 1


def test_another_database_error_also_falls_back_and_frees_the_turn(monkeypatch, caplog):
    """Un error al preparar la conexión (fijar su statement_timeout) no tumba la búsqueda: esa vertical va en serie."""
    pool = FakePool(fail_on_use=True)

    def body(gate):
        before = gate.slots.value
        with deps.spare_connection() as conn:
            during = gate.slots.value
        return conn, before, during

    with caplog.at_level(logging.WARNING, logger="rappi_ia.api.deps"):
        conn, before, during = in_endpoint(monkeypatch, pool, body)

    assert conn is None and during == before and pool.out == 0
    assert "server closed the connection" in caplog.text


def test_spares_never_take_the_reserve_of_the_pool(monkeypatch):
    """Con 4 conexiones y una del request, la búsqueda toma una extra (quedan 2, la reserva) y la siguiente no: /health
    o una búsqueda nueva no esperan a que terminen las búsquedas en paralelo."""
    pool = FakePool()

    def body(gate):
        with deps.spare_connection() as first, deps.spare_connection() as second:
            return first is not None, second, gate.slots.value

    got_first, second, free = in_endpoint(monkeypatch, pool, body)

    assert deps.spare_reserve(POOL_SIZE) == 2
    assert got_first and second is None
    assert free == 2


def test_a_spare_gives_back_its_connection_and_then_its_turn(monkeypatch):
    pool = FakePool()

    def body(gate):
        with deps.spare_connection() as conn:
            inside = (conn is not None, pool.out, gate.slots.value)
        return inside, pool.out, gate.slots.value

    (got, out_inside, free_inside), out_after, free_after = in_endpoint(monkeypatch, pool, body)

    assert got and out_inside == 1 and free_inside == POOL_SIZE - 2
    assert out_after == 0 and free_after == POOL_SIZE - 1


@pytest.mark.parametrize(("size", "reserve"), [(1, 0), (2, 1), (4, 2), (10, 5)])
def test_the_reserve_is_half_the_pool(size, reserve):
    assert deps.spare_reserve(size) == reserve
