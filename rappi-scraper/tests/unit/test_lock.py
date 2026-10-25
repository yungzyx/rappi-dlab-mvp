import psycopg
import pytest

from rappi_scraper import cli, lock
from rappi_scraper.lock import DownloadInProgress, download_lock


def test_only_one_download_at_a_time(tmp_path):
    path = tmp_path / "scraper.lock"
    with download_lock(path), pytest.raises(DownloadInProgress), download_lock(path):
        pass
    with download_lock(path):  # al terminar, el candado queda libre
        pass


def test_download_commands_refuse_to_start_while_another_download_runs(tmp_path, monkeypatch):
    """Un scrape-stores a mano no se cruza con la tarea del domingo (el pgrep del script no lo veía)."""
    monkeypatch.setattr(lock, "LOCK_FILE", tmp_path / "scraper.lock")
    with download_lock(), pytest.raises(SystemExit, match="Ya hay una descarga en curso"):
        cli.main(["scrape-stores"])


@pytest.mark.parametrize(
    "fatal",
    [
        "sorry, too many clients already",
        "remaining connection slots are reserved for roles with the SUPERUSER attribute",
        "the database system is not yet accepting connections",
        "the database system is starting up",
    ],
)
def test_transient_fatal_keeps_the_file_lock(tmp_path, monkeypatch, caplog, fatal):
    """La base llena o reiniciándose no es una base que rechaza: la descarga del domingo sigue con el candado de archivo
    (y lo avisa) en vez de detenerse."""

    def connect(*args, **kwargs):
        raise psycopg.OperationalError(
            f'connection failed: connection to server at "127.0.0.1", port 5432 failed: FATAL:  {fatal}'
        )

    monkeypatch.setattr(lock.psycopg, "connect", connect)
    with download_lock(tmp_path / "scraper.lock", database_url="postgresql://127.0.0.1/rappi"):
        pass

    assert "solo con el candado de este equipo" in caplog.text
