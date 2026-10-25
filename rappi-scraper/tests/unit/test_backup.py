import os
import subprocess

import pytest

from rappi_scraper import cli, lock
from rappi_scraper.lock import download_lock
from rappi_scraper.storage import backup


def _touch(path, mtime):
    path.write_bytes(b"x")
    os.utime(path, (mtime, mtime))


def test_rotate_backups_keeps_newest(tmp_path):
    for i in range(6):
        _touch(tmp_path / f"rappi_2026090{i}.dump", mtime=1_000 + i)
    (tmp_path / "otro.txt").write_text("no se toca")

    removed = backup.rotate_backups(tmp_path, keep=4)

    assert sorted(p.name for p in removed) == ["rappi_20260900.dump", "rappi_20260901.dump"]
    assert sorted(p.name for p in tmp_path.glob("rappi_*.dump")) == [f"rappi_2026090{i}.dump" for i in range(2, 6)]
    assert (tmp_path / "otro.txt").exists()


def test_backups_before_migrating_rotate_apart_from_the_weekly_ones(monkeypatch, tmp_path):
    """Los de `rappi-ia deploy-migrate` llevan otro prefijo: varios despliegues seguidos no expulsan los semanales, y
    uno que coincida con el de `refresh` nunca escribe el mismo archivo."""
    for i in range(4):
        _touch(tmp_path / f"rappi_2026090{i}.dump", mtime=1_000 + i)
    for i in range(4):
        _touch(tmp_path / f"pre-migracion_2026090{i}.dump", mtime=2_000 + i)
    _fake_tools(monkeypatch)

    path = backup.backup_database("postgresql:///rappi", backups_dir=tmp_path, keep=4, prefix="pre-migracion")

    assert path.name.startswith("pre-migracion_")
    assert len(list(tmp_path.glob("rappi_*.dump"))) == 4
    assert not (tmp_path / "pre-migracion_20260900.dump").exists()
    assert len(list(tmp_path.glob("pre-migracion_*.dump"))) == 4


def test_find_pg_dump_prefers_env(monkeypatch, tmp_path):
    fake = tmp_path / "pg_dump"
    fake.write_text("")
    monkeypatch.setenv("PG_DUMP", str(fake))
    assert backup.find_pg_dump() == str(fake)


def test_find_pg_dump_errors_when_missing(monkeypatch):
    monkeypatch.delenv("PG_DUMP", raising=False)
    monkeypatch.setattr(backup.shutil, "which", lambda _name: None)
    monkeypatch.setattr(backup, "_PG_DUMP_CANDIDATES", ("/no/existe/pg_dump",))
    with pytest.raises(RuntimeError):
        backup.find_pg_dump()


def _fake_tools(monkeypatch, dump_fails=False, list_fails=False):
    """pg_dump escribe el archivo (a medias si falla); pg_restore --list lo valida."""
    calls = []

    def fake_run(cmd, check, **kwargs):
        calls.append(cmd)
        calls.append(kwargs.get("env") or {})
        if cmd[0].endswith("pg_dump"):
            target = next(a for a in cmd if a.startswith("--file=")).removeprefix("--file=")
            with open(target, "wb") as f:
                f.write(b"PGDMP a medias")
            if dump_fails:
                raise subprocess.CalledProcessError(2, cmd)
        elif list_fails:
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(backup, "find_pg_dump", lambda: "/bin/pg_dump")
    monkeypatch.setattr(backup.subprocess, "run", fake_run)
    return calls


def test_backup_database_runs_pg_dump_and_rotates(monkeypatch, tmp_path):
    calls = _fake_tools(monkeypatch)

    path = backup.backup_database("postgresql:///rappi", backups_dir=tmp_path, keep=4)

    assert path.exists() and path.name.startswith("rappi_") and path.suffix == ".dump"
    assert calls[0][:3] == ["/bin/pg_dump", "--format=custom", "--no-owner"]
    assert "--dbname=dbname=rappi" in calls[0]
    assert calls[2][:2] == ["/bin/pg_restore", "--list"]  # se valida antes de darlo por bueno
    assert list(tmp_path.glob("*.part")) == []


@pytest.mark.parametrize("failure", ["dump_fails", "list_fails"])
def test_a_broken_dump_never_replaces_a_good_one(monkeypatch, tmp_path, failure):
    """Un pg_dump cortado (disco lleno, corte de luz) o ilegible no cuenta como respaldo ni expulsa uno sano."""
    for i in range(4):
        _touch(tmp_path / f"rappi_2026090{i}.dump", mtime=1_000 + i)
    _fake_tools(monkeypatch, **{failure: True})

    with pytest.raises(RuntimeError, match="falló con código"):
        backup.backup_database("postgresql:///rappi", backups_dir=tmp_path, keep=4)

    assert sorted(p.name for p in tmp_path.iterdir()) == [f"rappi_2026090{i}.dump" for i in range(4)]


def test_backup_password_not_in_args_nor_error(monkeypatch, tmp_path):
    """Con la clave en la URL, `ps` la mostraba durante el volcado y el error (con el argv) la dejaba en los logs."""
    calls = _fake_tools(monkeypatch, dump_fails=True)

    with pytest.raises(RuntimeError) as failure:
        backup.backup_database("postgresql://usuario:secreto@db.example:6543/rappi", backups_dir=tmp_path)

    cmd, env = calls[0], calls[1]
    assert not any("secreto" in arg for arg in cmd)
    assert {"--host=db.example", "--port=6543", "--username=usuario", "--dbname=dbname=rappi"} <= set(cmd)
    assert env["PGPASSWORD"] == "secreto"
    assert str(failure.value) == "pg_dump falló con código 2"
    assert failure.value.__cause__ is None and failure.value.__suppress_context__  # sin el argv encadenado


def test_backup_takes_download_lock(monkeypatch, tmp_path):
    """Un `rappi backup` a mano no corre junto al respaldo de la tarea semanal (se pisaban al rotar)."""
    monkeypatch.setattr(lock, "LOCK_FILE", tmp_path / "scraper.lock")
    monkeypatch.setattr(cli, "backup_database", lambda url: pytest.fail("no debería respaldar"))
    with download_lock(), pytest.raises(SystemExit, match="Ya hay una descarga en curso"):
        cli.main(["backup"])
