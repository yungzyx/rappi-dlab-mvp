"""El fixture `db` borra el esquema entero de la base de tests: nunca debe tocar otra que no sea `rappi_test`."""

import pytest
import requests

import conftest


class _Connection:
    """Una conexión falsa a la base `name`: anota lo que se le pide y responde `current_database()`."""

    def __init__(self, name: str):
        self.name = name
        self.statements: list[str] = []

    def execute(self, statement, *args):
        self.statements.append(str(statement))
        return self

    def fetchone(self):
        return (self.name,)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.mark.parametrize(
    ("url", "database"),
    [
        ("postgresql:///rappi", "rappi"),
        ("postgresql:///rappi_ia_test", "rappi_ia_test"),
        # El texto termina en rappi_test, pero la conexión va a `rappi` (libpq toma el dbname de los parámetros).
        ("postgresql:///rappi?application_name=rappi_test", "rappi"),
        ("postgresql://u:clave-secreta@localhost/x?dbname=rappi&options=rappi_test", "rappi"),
    ],
)
def test_the_db_fixture_refuses_any_database_but_rappi_test(monkeypatch, url, database):
    """Un DATABASE_URL_TEST exportado en la terminal gana sobre el .env (load_dotenv no lo pisa). Lo que decide es la
    base a la que de verdad se conectó, no el texto de la URL; y el mensaje no repite la URL (puede traer una clave)."""
    monkeypatch.setenv("DATABASE_URL_TEST", url)
    conn = _Connection(database)
    db = conftest.db.__wrapped__
    monkeypatch.setitem(db.__globals__, "connect", lambda *args, **kwargs: conn)

    with pytest.raises(pytest.fail.Exception, match=f"solo borran la base rappi_test, no {database}$") as refused:
        next(db())

    assert not any("DROP" in statement for statement in conn.statements)
    assert "clave-secreta" not in str(refused.value)


def test_no_test_can_reach_the_network():
    """Un test que se olvidó del cliente falso falla en vez de descargar de rappi.cl. (Aquí se prueba con un puerto
    local cerrado: sin el bloqueo sería un error de conexión, nunca una descarga real.)"""
    with pytest.raises(pytest.fail.Exception, match="sin red"):
        requests.Session().get("http://127.0.0.1:9/")
