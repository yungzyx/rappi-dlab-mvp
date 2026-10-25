"""El candado de descargas también vive en la base: dos contenedores o dos equipos sobre la misma base (cada uno con su
propio archivo de candado) no descargan a la vez de rappi.cl."""

import logging
from contextlib import nullcontext

import pytest
from psycopg.conninfo import make_conninfo

from rappi_scraper import cli, lock
from rappi_scraper.lock import DOWNLOAD_LOCK, DownloadInProgress, DownloadLockRefused, download_lock
from rappi_scraper.storage.db import connect, database_url
from rappi_scraper.storage.search import SEARCH_DOCUMENTS_LOCK


def test_download_lock_also_takes_pg_lock(db, tmp_path):
    url = database_url("DATABASE_URL_TEST")
    with download_lock(tmp_path / "equipo-a.lock", database_url=url):
        with (
            pytest.raises(DownloadInProgress, match=r"en otro proceso o equipo"),
            download_lock(tmp_path / "equipo-b.lock", database_url=url),
        ):
            pass
        with download_lock(tmp_path / "equipo-b.lock"):  # el intento fallido soltó su archivo
            pass

    with connect(url) as other:  # al terminar, la base queda libre
        assert other.execute("SELECT pg_try_advisory_lock(%s)", (DOWNLOAD_LOCK,)).fetchone()[0]
        other.execute("SELECT pg_advisory_unlock(%s)", (DOWNLOAD_LOCK,))


def test_download_lock_leaves_search_documents_free(db, tmp_path):
    """`rappi refresh` arma la búsqueda dentro de su propio candado de descarga: con la misma clave se esperaría a sí
    mismo para siempre."""
    url = database_url("DATABASE_URL_TEST")
    with download_lock(tmp_path / "scraper.lock", database_url=url), connect(url) as other:
        assert other.execute("SELECT pg_try_advisory_xact_lock(%s)", (SEARCH_DOCUMENTS_LOCK,)).fetchone()[0]


def test_download_lock_without_database_keeps_the_file_lock(tmp_path, caplog):
    """Una descarga local con Postgres caído sigue con el candado de archivo y lo dice."""
    path = tmp_path / "scraper.lock"
    with (
        download_lock(path, database_url="postgresql://127.0.0.1:9/sin_base"),
        pytest.raises(DownloadInProgress),
        download_lock(path),
    ):
        pass

    assert "solo con el candado de este equipo" in caplog.text


def test_download_lock_refused_by_the_database_stops(db, tmp_path):
    """Una base que responde pero no deja entrar (clave o rol equivocados) no es «base caída»: no se descarga sin saber
    si hay otra descarga."""
    url = make_conninfo(database_url("DATABASE_URL_TEST"), user="rol_que_no_existe")
    with (
        pytest.raises(DownloadLockRefused, match="rechazó la conexión del candado"),
        download_lock(tmp_path / "scraper.lock", database_url=url),
    ):
        pass
    with download_lock(tmp_path / "scraper.lock"):  # el archivo quedó libre
        pass


def test_database_lock_warning_reaches_the_command_log(tmp_path, monkeypatch):
    """El aviso de «base caída» sale después de configurar el log del comando: queda en su archivo."""
    monkeypatch.setattr(lock, "LOCK_FILE", tmp_path / "scraper.lock")
    monkeypatch.setattr(cli, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(cli, "connect", lambda: nullcontext(None))
    monkeypatch.setitem(cli.COMMANDS, "backup", lambda conn, args: None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://127.0.0.1:9/sin_base")
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    root.handlers[:] = []  # sin los de pytest, basicConfig instala los del comando (consola y archivo)
    try:
        cli.main(["backup"])
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers[:] = handlers
        root.setLevel(level)

    (log_file,) = (tmp_path / "logs").glob("backup_*.log")
    assert "solo con el candado de este equipo" in log_file.read_text(encoding="utf-8")
