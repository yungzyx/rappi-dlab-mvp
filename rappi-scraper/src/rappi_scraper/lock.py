"""Una descarga a la vez contra rappi.cl, para todos los comandos del scraper que descargan.

Un candado de archivo (`flock`) y no un PID: el sistema lo suelta solo si el proceso muere, incluso por un apagado,
y lo ven también los comandos lanzados a mano, que el `pgrep` de la tarea semanal no alcanzaba a ver.

Con DATABASE_URL, además un candado en la base (`pg_try_advisory_lock`, de sesión, en una conexión propia que dura lo
que la descarga): dos contenedores o dos equipos sobre la misma base, cada uno con su archivo, tampoco descargan a la
vez. Si la base no responde, la descarga sigue solo con el archivo y lo avisa.
"""

import fcntl
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg

from .config import DATA_DIR

log = logging.getLogger(__name__)

LOCK_FILE = DATA_DIR / "scraper.lock"
# Clave del candado de descargas en la base. No es la de `migrate` (72_000) ni la de search_documents (72_001):
# `rappi refresh` arma la búsqueda dentro de su descarga y, con la misma clave, se esperaría a sí mismo.
DOWNLOAD_LOCK = 72_002


class DownloadInProgress(RuntimeError):
    """Otra descarga (otra terminal, la tarea semanal, otro contenedor u otro equipo) tiene el candado."""


class DownloadLockRefused(DownloadInProgress):
    """La base respondió pero no dejó entrar (clave, rol o base equivocados): no se puede comprobar que no haya otra
    descarga en curso, así que no se descarga."""


# Con estos FATAL la base está, pero todavía no o ya no atiende: se trata como caída (sigue el candado de archivo).
_TRANSIENT_FATAL = (
    "too many connections",
    "too many clients already",
    "remaining connection slots are reserved",
    "starting up",
    "shutting down",
    "not yet accepting connections",
    "in recovery mode",
)


@contextmanager
def download_lock(path: Path | None = None, database_url: str | None = None) -> Iterator[None]:
    """El candado de archivo y el de la base, juntos."""
    with file_lock(path), database_lock(database_url):
        yield


@contextmanager
def file_lock(path: Path | None = None) -> Iterator[None]:
    path = path or LOCK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DownloadInProgress(
                "Ya hay una descarga en curso contra rappi.cl (otra terminal o la tarea semanal): espera a que termine."
            ) from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


@contextmanager
def database_lock(database_url: str | None = None) -> Iterator[None]:
    """El candado en la base de DATABASE_URL (o `database_url`). Sin URL no hace nada. Si la base no responde, avisa y
    sigue (queda el candado de archivo); si responde y rechaza la conexión, falla."""
    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        yield
        return
    try:
        conn = psycopg.connect(url, autocommit=True, connect_timeout=10, keepalives=1, keepalives_idle=60)
    except psycopg.OperationalError as exc:
        message = str(exc)
        if "FATAL:" in message and not any(reason in message for reason in _TRANSIENT_FATAL):
            detail = message.split("FATAL:", 1)[1].strip().splitlines()[0]
            raise DownloadLockRefused(
                f"La base rechazó la conexión del candado de descargas ({detail}): revisa DATABASE_URL. No descargo."
            ) from None
        log.warning(
            "No pude conectar a la base para el candado de descargas (%s): sigo solo con el candado de este equipo.",
            type(exc).__name__,
        )
        yield
        return
    with conn:  # cerrar la conexión suelta el candado, también si se cortó durante la descarga
        if not conn.execute("SELECT pg_try_advisory_lock(%s)", (DOWNLOAD_LOCK,)).fetchone()[0]:
            raise DownloadInProgress("Ya hay una descarga en curso (en otro proceso o equipo).")
        yield
