"""`rappi-ia doctor`: explica en español por qué la base no está lista antes de levantar el MVP."""

import pytest
from psycopg.conninfo import make_conninfo

from rappi_ia import cli
from rappi_ia.db import connect
from rappi_ia.demo import doctor
from rappi_ia.demo.doctor import check_database
from rappi_ia.demo.seed import seed_demo

UNREACHABLE_URL = "postgresql://localhost:1/nada"


def test_doctor_explains_unreachable_postgres():
    ready, message = check_database(UNREACHABLE_URL)

    assert ready is False
    assert message.startswith("No puedo conectar con Postgres")
    assert "docs/instalacion.md" in message


def test_doctor_explains_a_missing_database(test_url):
    """Postgres arriba pero sin la base: el consejo no es «revisa que esté corriendo»."""
    missing = make_conninfo(test_url, dbname="rappi_no_existe_prueba")

    ready, message = check_database(missing)

    assert ready is False
    assert message.startswith("La base rappi_no_existe_prueba no existe")
    assert "créala y carga un respaldo (docs/instalacion.md, sección 3)" in message
    assert "revisa que esté corriendo" not in message


def test_doctor_explains_empty_catalog(db, test_url):
    ready, message = check_database(test_url)

    assert ready is False
    assert "La base no tiene catálogo" in message
    assert "docs/instalacion.md" in message


def test_doctor_explains_missing_tables(db, test_url):
    """Una base recién creada, sin migrar: no hay `search_documents` y no debe salir un traceback."""
    db.execute("DROP TABLE search_documents CASCADE")
    db.commit()

    ready, message = check_database(test_url)

    assert ready is False
    assert "La base no tiene catálogo" in message
    assert "rappi-ia migrate" in message


def test_doctor_accepts_seeded_database(db, test_url):
    seed_demo(db)

    ready, message = check_database(test_url)

    assert ready is True
    assert "Base lista" in message
    assert "8 verticales" in message
    documents = db.execute("SELECT count(*) FROM search_documents").fetchone()[0]
    assert f"{documents} documentos" in message


def test_doctor_opens_the_database_read_only(db, test_url, monkeypatch):
    """Corre contra la base real: la abre de solo lectura, así que no puede escribirle ni por error."""
    seed_demo(db)
    opened = []

    def spy(url, **options):
        conn = connect(url, **options)
        opened.append(conn)
        return conn

    monkeypatch.setattr(doctor, "connect", spy)

    ready, _ = check_database(test_url)

    assert ready is True
    assert [conn.read_only for conn in opened] == [True]
    assert opened[0].closed


def test_doctor_command_exits_0_when_ready(db, test_url, monkeypatch, capsys):
    seed_demo(db)
    monkeypatch.setenv("DATABASE_URL", test_url)

    cli.main(["doctor"])  # termina sin SystemExit

    assert "Base lista" in capsys.readouterr().out


def test_doctor_command_exits_1_when_empty(db, test_url, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", test_url)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["doctor"])

    assert exit_info.value.code == 1
    assert "La base no tiene catálogo" in capsys.readouterr().out


def test_doctor_command_exits_1_when_postgres_is_down(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_URL)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["doctor"])

    assert exit_info.value.code == 1
    assert capsys.readouterr().out.startswith("No puedo conectar con Postgres")
