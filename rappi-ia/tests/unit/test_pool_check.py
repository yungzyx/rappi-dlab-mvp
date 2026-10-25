"""`deps.checked`, la revisión de una conexión antes de entregarla, con un pool falso: si Postgres la cortó, además de
descartarla se revisan todas las libres en otro hilo (una sola revisión a la vez), así tras un reinicio de Postgres el
request siguiente no encuentra las muertas una a una."""

import threading

import pytest
from psycopg import OperationalError

from rappi_ia.api import deps


class FakePool:
    """Cuenta las revisiones (`check`); la primera espera a `release` para ver que no se lanza otra encima."""

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.checks = 0
        self.started = threading.Event()
        self.release = threading.Event()
        self.done = threading.Event()

    def check(self):
        self.checks += 1
        self.started.set()
        self.release.wait(timeout=5)
        self.done.set()
        if self.error:
            raise self.error


def broken(conn):
    raise OperationalError("server closed the connection unexpectedly")


def healthy(conn):
    return None


def eventually(condition) -> bool:
    """Lo que pasa en el hilo de la revisión, con un tope de 5 s."""
    for _ in range(500):
        if condition():
            return True
        threading.Event().wait(0.01)
    return False


def test_a_healthy_connection_does_not_check_the_pool():
    pool = FakePool()

    deps.checked(pool, object(), check=healthy)

    assert pool.checks == 0 and not pool.started.wait(timeout=0.1)


def test_a_broken_connection_checks_the_whole_pool_once():
    pool = FakePool()

    with pytest.raises(OperationalError):  # el pool la descarta y entrega otra
        deps.checked(pool, object(), check=broken)
    assert pool.started.wait(timeout=5)
    with pytest.raises(OperationalError):  # otra muerta mientras se revisa: no lanza otra revisión
        deps.checked(pool, object(), check=broken)
    pool.release.set()
    assert eventually(lambda: not deps._pool_check_lock(pool).locked())  # terminó: la próxima vez se revisa de nuevo

    assert pool.checks == 1


def test_a_failed_pool_check_is_logged_and_the_next_cut_checks_again(caplog):
    pool = FakePool(error=RuntimeError("the pool is closed"))
    pool.release.set()

    with pytest.raises(OperationalError):
        deps.checked(pool, object(), check=broken)
    assert eventually(lambda: "No se pudo revisar el pool" in caplog.text and not deps._pool_check_lock(pool).locked())
    with pytest.raises(OperationalError):
        deps.checked(pool, object(), check=broken)

    assert eventually(lambda: pool.checks == 2)


def test_each_pool_has_its_own_check():
    """Dos pools (los tests abren varios): la revisión de uno no tapa la del otro."""
    first, second = FakePool(), FakePool()

    for pool in (first, second):
        with pytest.raises(OperationalError):
            deps.checked(pool, object(), check=broken)
    assert first.started.wait(timeout=5) and second.started.wait(timeout=5)
    first.release.set()
    second.release.set()
    assert eventually(lambda: not deps._pool_check_lock(first).locked() and not deps._pool_check_lock(second).locked())


def test_a_thread_that_cannot_start_releases_the_lock_and_keeps_the_original_error(monkeypatch, caplog):
    pool = FakePool()

    class NoThreads:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(deps.threading, "Thread", NoThreads)
    with pytest.raises(OperationalError, match="server closed"):
        deps.checked(pool, object(), check=broken)

    assert not deps._pool_check_lock(pool).locked()  # el próximo corte vuelve a intentarlo
    assert "No se pudo lanzar la revisión" in caplog.text
    assert pool.checks == 0
