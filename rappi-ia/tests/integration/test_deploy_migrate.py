"""`rappi-ia deploy-migrate`: en un despliegue, migrar es un paso aparte que respalda antes (si hay algo que aplicar),
y, con `DB_API_ROLE`, da los permisos del rol de la API. En producción, ni la API ni los
objetivos de servidor migran al arrancar."""

import os
import subprocess
import threading
import time

import pytest
from psycopg.pq import TransactionStatus
from rappi_scraper.storage import db as scraper_db

from rappi_ia import cli
from rappi_ia.config import PROJECT_ROOT
from rappi_ia.db import connect

PROBE = "999_prueba.sql"


@pytest.fixture
def add_pending(tmp_path, monkeypatch):
    """Suma a las migraciones del repositorio una nueva sin aplicar, que crea la tabla `deploy_probe`."""
    monkeypatch.delenv("DB_API_ROLE", raising=False)

    def add(text: str = "CREATE TABLE deploy_probe (id int);") -> None:
        folder = tmp_path / "migrations"
        folder.mkdir()
        for path in scraper_db.MIGRATIONS_DIR.glob("*.sql"):
            (folder / path.name).symlink_to(path)
        (folder / PROBE).write_text(text, encoding="utf-8")
        monkeypatch.setattr(scraper_db, "MIGRATIONS_DIR", folder)

    return add


@pytest.fixture
def pending(add_pending):
    add_pending()


def _probe_exists(conn) -> bool:
    return conn.execute("SELECT to_regclass('deploy_probe')").fetchone()[0] is not None


def _applied(conn, name: str) -> bool:
    return conn.execute("SELECT count(*) FROM schema_migrations WHERE name = %s", (name,)).fetchone()[0] == 1


def test_deploy_migrate_backs_up_only_when_pending(db, add_pending, tmp_path, capsys):
    backups = []

    def backup():
        backups.append(_probe_exists(db))  # el respaldo va antes de migrar
        return tmp_path / "pre-migracion_prueba.dump"

    cli.deploy_migrate(db, backup)  # nada pendiente: no respalda
    assert backups == []
    assert "Sin migraciones pendientes" in capsys.readouterr().out

    add_pending()
    cli.deploy_migrate(db, backup)

    out = capsys.readouterr().out
    assert backups == [False]
    assert _probe_exists(db) and _applied(db, PROBE)
    assert "pre-migracion_prueba.dump" in out
    assert PROBE in out


def test_without_backup_flag_migrates_without_backing_up(db, pending, capsys):
    cli.deploy_migrate(db, None)

    assert _applied(db, PROBE)
    assert "sin respaldo" in capsys.readouterr().out


def test_failed_backup_blocks_migration(db, pending, capsys):
    def backup():
        raise RuntimeError("pg_dump falló con código 1")

    with pytest.raises(SystemExit) as stopped:
        cli.deploy_migrate(db, backup)

    assert stopped.value.code not in (0, None)
    assert "No se pudo respaldar la base (pg_dump falló con código 1): no migro." in str(stopped.value.code)
    assert not _probe_exists(db) and not _applied(db, PROBE)


def test_api_role_applies_the_grants_file(db, pending, tmp_path, monkeypatch, capsys):
    me = db.execute("SELECT current_user").fetchone()[0]
    grants = tmp_path / "grants.sql"
    grants.write_text("CREATE TABLE grants_probe (); GRANT SELECT ON grants_probe TO {api_role};", encoding="utf-8")
    monkeypatch.setenv("DB_API_ROLE", me)

    cli.deploy_migrate(db, None, grants_file=grants)

    acl = db.execute("SELECT relacl::text FROM pg_class WHERE relname = 'grants_probe'").fetchone()[0]
    assert acl is not None and me in acl
    assert f"Permisos del rol de la API ({me})" in capsys.readouterr().out


def test_api_role_without_grants_file_stops_before_migrating(db, pending, tmp_path, monkeypatch):
    monkeypatch.setenv("DB_API_ROLE", "rappi_api")
    missing = tmp_path / "no-existe.sql"

    with pytest.raises(SystemExit) as stopped:
        cli.deploy_migrate(db, lambda: pytest.fail("no respalda si no va a poder terminar"), grants_file=missing)

    assert "DB_API_ROLE" in str(stopped.value.code) and str(missing) in str(stopped.value.code)
    assert not _applied(db, PROBE)


def test_no_open_transaction_while_backing_up(db, pending):
    """pg_dump tiene las tablas tomadas (ACCESS SHARE) todo el volcado: la sesión que va a migrar no le suma una
    transacción abierta."""
    states = []

    def backup():
        states.append(db.info.transaction_status)
        return "respaldo.dump"

    cli.deploy_migrate(db, backup)

    assert states == [TransactionStatus.IDLE]


def test_two_deploys_at_once_back_up_once(db, add_pending, test_url, capsys):
    """El segundo espera al primero (el candado de `migrate`) y ya no encuentra nada que respaldar ni aplicar: nunca
    escriben dos respaldos a la vez."""
    add_pending()
    start = threading.Barrier(2)
    backups, errors = [], []

    def backup():
        backups.append(time.monotonic())
        time.sleep(0.5)
        return "respaldo.dump"

    def deploy():
        try:
            with connect(test_url) as conn:
                start.wait()
                cli.deploy_migrate(conn, backup)
        except BaseException as exc:  # el test quiere ver cualquier error de los hilos (también SystemExit)
            errors.append(exc)

    threads = [threading.Thread(target=deploy) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    assert errors == []
    assert len(backups) == 1
    assert _applied(db, PROBE)


def test_busy_table_stops_with_a_clear_message(db, add_pending, test_url, monkeypatch):
    add_pending("ALTER TABLE menu_items ADD COLUMN prueba int;")
    monkeypatch.setattr(scraper_db.config, "MIGRATE_LOCK_TIMEOUT", "300ms")
    with connect(test_url) as other:
        other.execute("LOCK TABLE menu_items IN ROW EXCLUSIVE MODE")
        with pytest.raises(SystemExit) as stopped:
            cli.deploy_migrate(db, None)
        other.rollback()

    assert stopped.value.code == (
        "Una tabla está ocupada; la migración no se aplicó. Intenta de nuevo en unos minutos."
    )
    assert not _applied(db, PROBE)


def test_plain_migrate_on_a_busy_table_stops_with_the_same_message(db, add_pending, test_url, monkeypatch):
    """`rappi-ia migrate` (el de `make mvp`) con una tabla ocupada: el mismo mensaje que deploy-migrate, sin traza."""
    add_pending("ALTER TABLE menu_items ADD COLUMN prueba int;")
    monkeypatch.setattr(scraper_db.config, "MIGRATE_LOCK_TIMEOUT", "300ms")
    with connect(test_url) as other:
        other.execute("LOCK TABLE menu_items IN ROW EXCLUSIVE MODE")
        with pytest.raises(SystemExit) as stopped:
            cli.cmd_migrate(db, cli.build_parser().parse_args(["migrate"]))
        other.rollback()

    assert stopped.value.code == (
        "Una tabla está ocupada; la migración no se aplicó. Intenta de nuevo en unos minutos."
    )
    assert not _applied(db, PROBE)


def test_check_only_migrate_stops_on_pending_and_points_to_the_deploy(db, pending, capsys):
    """`rappi-ia migrate --solo-revisar` (post-refresh en producción) no migra sin respaldo: se detiene y remite al
    despliegue."""
    with pytest.raises(SystemExit) as stopped:
        cli.cmd_migrate(db, cli.build_parser().parse_args(["migrate", "--solo-revisar"]))

    assert PROBE in stopped.value.code and "run --rm migrate" in stopped.value.code
    assert not _applied(db, PROBE)


def test_check_only_migrate_passes_when_up_to_date(db, capsys):
    cli.cmd_migrate(db, cli.build_parser().parse_args(["migrate", "--solo-revisar"]))

    assert "al día" in capsys.readouterr().out


def test_failed_migration_stops_naming_the_file(db, add_pending):
    add_pending("SELECT 1/0;")

    with pytest.raises(SystemExit) as stopped:
        cli.deploy_migrate(db, None)

    assert isinstance(stopped.value.code, str) and PROBE in stopped.value.code
    assert "Traceback" not in stopped.value.code
    assert not _applied(db, PROBE)


def _dry_run(target: str, **env) -> str:
    environment = {k: v for k, v in os.environ.items() if k != "API_ENV"} | env
    return subprocess.run(
        ["make", "-n", "-C", str(PROJECT_ROOT), target], capture_output=True, text=True, check=True, env=environment
    ).stdout


@pytest.mark.parametrize("target", ["serve", "serve-lan"])
def test_production_start_does_not_migrate(target, tmp_path):
    production = _dry_run(target, API_ENV="production")
    assert "uvicorn" in production
    for step in ("check-migrations", "rappi_ia migrate"):
        assert step not in production

    dotenv = tmp_path / ".env"
    dotenv.write_text('API_ENV="production"\n', encoding="utf-8")
    assert "rappi_ia migrate" not in _dry_run(target, DOTENV=str(dotenv))  # también si va en .env

    local = _dry_run(target, API_ENV="local", DOTENV=str(tmp_path / "sin-env"))  # en local siguen migrando
    assert local.index("rappi_ia check-migrations") < local.index("rappi_ia migrate") < local.index("uvicorn")


def test_post_refresh_in_production_only_checks_migrations(tmp_path):
    """La tarea semanal en el servidor no migra sin respaldo: post-refresh solo revisa (lo aplica deploy-migrate)."""
    production = _dry_run("post-refresh", API_ENV="production")
    assert "rappi_ia migrate --solo-revisar" in production
    assert "rappi_ia migrate\n" not in production

    local = _dry_run("post-refresh", API_ENV="local", DOTENV=str(tmp_path / "sin-env"))
    assert "rappi_ia migrate\n" in local and "--solo-revisar" not in local


def test_grants_file_lets_the_api_role_write_only_its_tables(db):
    """El `deploy/db/grants.sql` de verdad, sobre el esquema de verdad: el rol de la API lee todo, escribe solo los
    datos de las personas y no puede borrar tablas ni crearlas. Todo en una transacción que se deshace (los roles
    también)."""
    from psycopg import errors, sql

    conn = db
    role = "rappi_api_prueba"
    for name in ("rappi_owner", role):  # rappi_owner: el dueño de ALTER DEFAULT PRIVILEGES (en el servidor ya existe)
        if conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,)).fetchone() is None:
            conn.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(name)))
    # Un permiso de más (de antes, o puesto a mano) desaparece; aplicarlo dos veces da lo mismo (cada despliegue).
    conn.execute(sql.SQL("GRANT INSERT, UPDATE, DELETE ON stores TO {}").format(sql.Identifier(role)))
    grants = sql.SQL(cli.GRANTS_FILE.read_text(encoding="utf-8")).format(api_role=sql.Identifier(role))
    conn.execute(grants)
    conn.execute(grants)
    conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))

    conn.execute("SELECT count(*) FROM search_documents")
    conn.execute("SELECT count(*) FROM capa.item_attributes")
    conn.execute("INSERT INTO app_users (user_id, source) VALUES ('proto-permisos', 'prototype')")
    conn.execute(  # usa la secuencia de app_events
        "INSERT INTO app_events (user_id, session_id, type, source)"
        " VALUES ('proto-permisos', 's', 'search', 'prototype')"
    )
    conn.execute(  # afinidad y recompra son datos de la persona: la API las escribe; las del motor, no
        "INSERT INTO user_vertical_affinity (user_id, vertical, score, orders, signals)"
        " VALUES ('proto-permisos', 'turbo', 1, 0, 1)"
    )
    conn.execute("SELECT count(*) FROM capa.combo_stats")
    for forbidden in (
        "INSERT INTO combo_steps (data_source, from_combo, to_combo, users, prob) VALUES ('synthetic', 'a', 'b', 1, 1)",
        "DROP TABLE app_events",
        "DELETE FROM stores",
        "TRUNCATE app_users",
        "CREATE TABLE intrusa ()",
    ):
        with pytest.raises(errors.InsufficientPrivilege), conn.transaction():
            conn.execute(forbidden)
    conn.rollback()
