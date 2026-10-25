"""`seed-demo` borra la base antes de sembrar: solo puede apuntar a una base de prueba."""

import pytest

from rappi_ia import cli
from rappi_ia.demo.seed import ensure_test_database, reset_test_database


def test_seed_demo_command_refuses_a_database_not_ending_in_test(capsys):
    with pytest.raises(SystemExit) as refused:
        ensure_test_database("postgresql://localhost/rappi")

    assert refused.value.code == 2
    message = capsys.readouterr().err
    assert "solo siembra una base de prueba" in message and message.strip().endswith("no rappi")


@pytest.mark.parametrize(
    "url",
    ["postgresql://localhost/rappi_ia_test", "postgresql://user:pw@localhost:5432/rappi_test?sslmode=disable"],
)
def test_ensure_test_database_accepts_names_ending_in_test(url):
    ensure_test_database(url)


def test_seed_demo_reads_the_test_url_and_never_opens_database_url(monkeypatch, capsys):
    """Si DATABASE_URL_TEST no es de prueba, el comando se detiene antes de abrir cualquier conexión."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/rappi")
    monkeypatch.setenv("DATABASE_URL_TEST", "postgresql://localhost/rappi_produccion")

    def no_connection(*args, **kwargs):
        raise AssertionError("seed-demo no debe conectarse a esta base")

    monkeypatch.setattr(cli, "connect", no_connection)

    with pytest.raises(SystemExit) as refused:
        cli.main(["seed-demo"])

    assert refused.value.code == 2
    assert "rappi_produccion" in capsys.readouterr().err


class FakeConnection:
    """Una conexión que dice estar en otra base y apunta todo lo que le piden."""

    def __init__(self, database):
        self.database = database
        self.statements = []

    def execute(self, query, *args):
        self.statements.append(query)
        return self

    def fetchone(self):
        return (self.database,)

    def commit(self):
        self.statements.append("COMMIT")


def test_reset_refuses_a_connection_to_a_database_not_ending_in_test(capsys):
    """`postgresql:///rappi_test?dbname=rappi` pasa la revisión del nombre de la URL, pero conecta a `rappi`."""
    conn = FakeConnection("rappi")

    with pytest.raises(SystemExit) as refused:
        reset_test_database(conn)

    assert refused.value.code == 2
    message = capsys.readouterr().err
    assert "solo siembra una base de prueba" in message and message.strip().endswith("no rappi")
    assert conn.statements == ["SELECT current_database()"]  # nada se borró
