"""El fixture `db` borra el esquema entero de la base de tests: nunca debe tocar otra que no sea `rappi_test`."""

import pytest
import requests

import conftest


def _must_not_connect(*args, **kwargs):
    raise AssertionError("se conectó para borrar una base que no es rappi_test")


@pytest.mark.parametrize("url", ["postgresql:///rappi", "postgresql:///rappi_ia_test"])
def test_the_db_fixture_refuses_any_database_but_rappi_test(monkeypatch, url):
    """Un DATABASE_URL_TEST exportado en la terminal gana sobre el .env (load_dotenv no lo pisa)."""
    monkeypatch.setenv("DATABASE_URL_TEST", url)
    db = conftest.db.__wrapped__
    monkeypatch.setitem(db.__globals__, "connect", _must_not_connect)

    with pytest.raises(pytest.fail.Exception, match="solo borran la base rappi_test"):
        next(db())


def test_no_test_can_reach_the_network():
    """Un test que se olvidó del cliente falso falla en vez de descargar de rappi.cl. (Aquí se prueba con un puerto
    local cerrado: sin el bloqueo sería un error de conexión, nunca una descarga real.)"""
    with pytest.raises(pytest.fail.Exception, match="sin red"):
        requests.Session().get("http://127.0.0.1:9/")
