"""Procesa una lista de jobs de la cola: progreso, aislamiento de errores y una pasada de reintento."""

import logging
from collections.abc import Callable

import psycopg
from psycopg import Connection

from .. import config
from ..scraping.client import DownloadStopped, PossibleBlock, RestaurantGone, StoreUnavailable
from ..storage import repository
from .progress import Progress

log = logging.getLogger(__name__)

JobResult = tuple[str, dict | None, str | None]  # (status, result, error)

# Fallos en los que rappi.cl sí respondió (no hay sucursal, no hay menú): no son señal de bloqueo.
NO_BRANCH_AVAILABLE = "ninguna sucursal disponible"
NO_BRANCH_WITH_MENU = "ninguna sucursal con menú"
GONE_MID_CRAWL = "sucursal no disponible a mitad del recorrido"
SITE_ANSWERED = {NO_BRANCH_AVAILABLE, NO_BRANCH_WITH_MENU, GONE_MID_CRAWL}


def _process(
    conn: Connection,
    run_id: int,
    jobs: list[dict],
    handler: Callable[[dict], JobResult],
    describe: Callable[[dict], str],
    log_every: int,
) -> None:
    progress = Progress(len(jobs))
    streak: list[str] = []  # jobs seguidos que fallaron sin respuesta útil de rappi.cl
    for i, job in enumerate(jobs):
        if i % log_every == 0 or i == len(jobs) - 1:
            log.info("%s %s", progress.label(i), describe(job))
        try:
            status, result, error = handler(job)
            site_answered = status != "failed" or error in SITE_ANSWERED
        except DownloadStopped:
            # Un posible bloqueo (demasiados requests rechazados seguidos) o una página que robots.txt no permite: este
            # job queda pendiente y los fallidos de la racha vuelven a la cola, como cuando la racha es de jobs.
            _rollback(conn)
            repository.requeue_failed(conn, run_id, config.MAX_BLOCKED_JOB_ATTEMPTS, streak)
            raise
        except Exception as exc:  # un dato inesperado no debe detener una corrida de horas
            _rollback(conn)  # deja la conexión usable si el error vino de la base
            log.exception("  job %s falló", job["job_key"])
            status, result, error = "failed", None, f"{type(exc).__name__}: {exc}"
            site_answered = isinstance(exc, StoreUnavailable | RestaurantGone)
        _mark_job(conn, run_id, job["job_key"], status, result, error)
        streak = [] if site_answered else [*streak, job["job_key"]]
        # Esos fallos los causó el bloqueo, no el job: vuelven a la cola para la próxima actualización, con un tope más
        # alto que el normal (un job de la pasada de reintento, o de un bloqueo anterior, ya llegó a ese). Si ninguno
        # vuelve (todos agotaron ese tope), es un error fijo de esos jobs y la corrida sigue; la racha no se vacía, así
        # que un bloqueo real justo después la detiene al primer fallo.
        if len(streak) >= config.MAX_CONSECUTIVE_FAILURES and repository.requeue_failed(
            conn, run_id, config.MAX_BLOCKED_JOB_ATTEMPTS, streak
        ):
            raise PossibleBlock(f"posible bloqueo: {len(streak)} fallos consecutivos (último: {error})")


def _rollback(conn: Connection) -> None:
    """Como `conn.rollback()`, pero sin reventar si la conexión se cayó (el error claro lo da `_mark_job`)."""
    try:
        conn.rollback()
    except psycopg.OperationalError:
        log.warning("  no se pudo deshacer la transacción: la conexión con la base se cayó")


def _mark_job(conn: Connection, run_id: int, job_key: str, status: str, result: dict | None, error: str | None) -> None:
    """Anota el job; ante un error pasajero de la base (un timeout, un bloqueo) reintenta una vez. Una conexión caída
    no se puede retomar a mitad de la corrida (el resto del proceso usa la misma): se detiene con un mensaje claro, y
    la corrida queda abierta para retomarla con el mismo comando."""
    try:
        repository.mark_job(conn, run_id, job_key, status, result, error)
        return
    except psycopg.OperationalError as exc:
        if conn.closed or conn.broken:
            raise psycopg.OperationalError(
                "Se perdió la conexión con la base: la corrida quedó abierta, retómala con el mismo comando"
            ) from exc
        log.warning("  error de la base al anotar el job %s (%s): se reintenta", job_key, exc)
        _rollback(conn)
    repository.mark_job(conn, run_id, job_key, status, result, error)


def process_with_retry(
    conn: Connection,
    run_id: int,
    jobs: list[dict],
    handler: Callable[[dict], JobResult],
    describe: Callable[[dict], str] = lambda job: job["job_key"],
    log_every: int = 1,
) -> None:
    """Procesa los jobs y, al final, reintenta una vez los que fallaron (errores transitorios de Rappi).

    Lanza `PossibleBlock` si demasiados jobs seguidos fallan sin respuesta útil, y deja subir un `DownloadStopped` del
    cliente: los que quedan siguen pendientes.
    """
    _process(conn, run_id, jobs, handler, describe, log_every)
    retry_keys = set(repository.requeue_failed(conn, run_id, config.MAX_JOB_ATTEMPTS, [j["job_key"] for j in jobs]))
    if not retry_keys:
        return
    log.info("Reintentando %d jobs fallidos", len(retry_keys))
    _process(conn, run_id, [j for j in jobs if j["job_key"] in retry_keys], handler, describe, log_every)
