"""`migrate` con candado y checksum: dos a la vez no chocan, un DDL que espera una fila tomada falla rápido y una
migración editada después de aplicarse se nota."""

import logging
import threading
import time

import psycopg
import pytest

from rappi_scraper import cli
from rappi_scraper.storage import db as db_module
from rappi_scraper.storage.db import MIGRATIONS_DIR, check_migrations, connect, database_url, migrate


@pytest.fixture
def empty(db):
    """`rappi_test` sin nada: ni tablas ni `schema_migrations`."""
    db.execute("DROP SCHEMA IF EXISTS capa CASCADE")
    db.execute("DROP SCHEMA public CASCADE")
    db.execute("CREATE SCHEMA public")
    db.commit()
    return db


@pytest.fixture
def extra_migration(tmp_path, monkeypatch):
    """Las migraciones del repositorio más una nueva (`999_prueba.sql`) con el SQL que se le pase."""

    def add(text: str) -> str:
        for path in MIGRATIONS_DIR.glob("*.sql"):
            (tmp_path / path.name).symlink_to(path)
        (tmp_path / "999_prueba.sql").write_text(text, encoding="utf-8")
        monkeypatch.setattr(db_module, "MIGRATIONS_DIR", tmp_path)
        return "999_prueba.sql"

    return add


def test_concurrent_migrate_applies_each_file_once(empty):
    url = database_url("DATABASE_URL_TEST")
    start = threading.Barrier(2)
    results, errors = [], []

    def run():
        try:
            with connect(url) as conn:
                start.wait()
                results.append(migrate(conn))
        except Exception as exc:  # el test quiere ver cualquier error de los hilos
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    files = sorted(path.name for path in MIGRATIONS_DIR.glob("*.sql"))
    assert errors == []
    assert sorted(results, key=len) == [[], files]  # uno aplica todo; el otro espera y no encuentra nada pendiente
    rows = empty.execute("SELECT name, checksum FROM schema_migrations ORDER BY name").fetchall()
    assert [name for name, _ in rows] == files
    assert all(checksum for _, checksum in rows)


def test_migration_behind_row_lock_fails_fast(db, extra_migration, monkeypatch):
    name = extra_migration("ALTER TABLE menu_items ADD COLUMN prueba int;")
    monkeypatch.setattr(db_module.config, "MIGRATE_LOCK_TIMEOUT", "300ms")
    with connect(database_url("DATABASE_URL_TEST")) as other:
        other.execute("LOCK TABLE menu_items IN ROW EXCLUSIVE MODE")  # lo que toma un UPDATE abierto
        started = time.monotonic()
        with pytest.raises(psycopg.errors.LockNotAvailable):
            migrate(db)
        elapsed = time.monotonic() - started
        other.rollback()

    assert elapsed < 5
    assert db.execute("SELECT count(*) FROM schema_migrations WHERE name = %s", (name,)).fetchone()[0] == 0
    assert db.execute("SHOW lock_timeout").fetchone()[0] == "0"  # devuelve la sesión como la recibió
    assert migrate(db) == [name]  # soltó el candado: con la fila libre, la siguiente pasada la aplica


def test_checksum_mismatch_warns(db, caplog):
    first = sorted(MIGRATIONS_DIR.glob("*.sql"))[0].name
    db.execute("UPDATE schema_migrations SET checksum = NULL WHERE name <> %s", (first,))
    db.execute("UPDATE schema_migrations SET checksum = 'otro' WHERE name = %s", (first,))
    db.commit()

    with caplog.at_level(logging.WARNING):
        migrate(db)  # completa las filas viejas sin checksum, sin aviso
        assert caplog.records == []
        check_migrations(db)

    assert [r.getMessage() for r in caplog.records] == [f"La migración {first} cambió después de aplicarse"]
    missing = db.execute("SELECT count(*) FROM schema_migrations WHERE checksum IS NULL").fetchone()[0]
    assert missing == 0


def test_migrate_with_nothing_pending_does_not_wait_for_a_dump(db, monkeypatch):
    """pg_dump tiene ACCESS SHARE sobre schema_migrations todo el volcado: `migrate` sin nada pendiente no la altera."""
    monkeypatch.setattr(db_module.config, "MIGRATE_LOCK_TIMEOUT", "300ms")
    with connect(database_url("DATABASE_URL_TEST")) as dump:
        dump.execute("SELECT count(*) FROM schema_migrations")  # transacción abierta, como la de pg_dump
        assert migrate(db) == []
        dump.rollback()


def test_backfill_and_each_migration_commit_on_their_own(db, extra_migration):
    """Completar los checksum viejos no deja abierta una transacción que convierta a cada migración en un savepoint: si
    la conexión se cae en una migración, las anteriores y el relleno ya quedaron confirmados."""
    db.execute("UPDATE schema_migrations SET checksum = NULL")
    db.commit()
    extra_migration("CREATE TABLE prueba_ok (id int);")
    (db_module.MIGRATIONS_DIR / "999_zz_corte.sql").write_text(
        "SELECT pg_terminate_backend(pg_backend_pid());", encoding="utf-8"
    )

    with pytest.raises(psycopg.OperationalError):
        migrate(db)

    with connect(database_url("DATABASE_URL_TEST")) as other:
        assert other.execute("SELECT to_regclass('prueba_ok')").fetchone()[0] is not None
        assert other.execute("SELECT count(*) FROM schema_migrations WHERE checksum IS NULL").fetchone()[0] == 0


def test_check_only_lists_the_pending_ones_and_points_to_the_deploy(db, extra_migration, monkeypatch, capsys):
    """`rappi migrate --solo-revisar` (la tarea semanal en producción) no aplica nada: si falta una migración se detiene
    y dice que la aplica el despliegue, que respalda antes."""
    monkeypatch.setenv("DATABASE_URL", database_url("DATABASE_URL_TEST"))
    cli.main(["migrate", "--solo-revisar"])
    assert "al día" in capsys.readouterr().out

    name = extra_migration("CREATE TABLE prueba (id int);")
    with pytest.raises(SystemExit) as stopped:
        cli.main(["migrate", "--solo-revisar"])

    assert name in stopped.value.code and "run --rm migrate" in stopped.value.code
    assert db.execute("SELECT to_regclass('prueba')").fetchone()[0] is None


def test_the_unused_image_embeddings_table_is_gone(db):
    """La 010 la creó para vectores de fotos que nunca se usaron; la 042 la borra."""
    assert db.execute("SELECT to_regclass('image_embeddings')").fetchone()[0] is None
    applied = db.execute("SELECT count(*) FROM schema_migrations WHERE name = '042_sin_image_embeddings.sql'")
    assert applied.fetchone()[0] == 1
