"""Actualización completa: tiendas → restaurantes → búsqueda → reportes → respaldo.

Pensada para correr sola cada semana. Si una corrida anterior quedó a medias (se cortó
la luz, se durmió el equipo), la retoma en vez de empezar otra.
"""

import logging
from collections.abc import Callable
from pathlib import Path

from psycopg import Connection

from ..reporting import REPORTS_DIR, write_run_report
from ..scraping.client import DownloadStopped, RappiClient
from ..storage import repository
from ..storage.db import check_migrations
from ..storage.search import build_search_documents
from .restaurants import process_restaurant_jobs
from .stores import process_store_jobs

log = logging.getLogger(__name__)

JOB_TYPES = {"stores": "store_group", "restaurants": "restaurant"}

Discoverer = Callable[[Connection, int], int]  # (conn, run_id) -> jobs creados


def finish_and_report(
    conn: Connection, run_id: int, kind: str, reports_dir: Path = REPORTS_DIR, alert: str | None = None
) -> tuple[dict, Path]:
    """Cierra la corrida si no quedan pendientes y deja el reporte de calidad (DB + archivo)."""
    if not repository.pending_jobs(conn, run_id, JOB_TYPES[kind]):
        repository.finish_run(conn, run_id)
        log.info("Corrida %d terminada", run_id)
    report, path = write_run_report(conn, run_id, reports_dir, alert)
    log.info("Reporte guardado en %s", path)
    return report, path


def ensure_run(
    conn: Connection, kind: str, discover: Discoverer, on_failure: Callable[[int, Exception], None] | None = None
) -> int | None:
    """Retoma la corrida abierta de ese tipo o crea una nueva y descubre qué descargar.

    Si el descubrimiento falla, la corrida queda cerrada como fallida y el error sube; con `on_failure`, un error que no
    detenga la descarga (un posible bloqueo, robots.txt) se le pasa (con la corrida) y devuelve None."""
    run_id = repository.open_run(conn, kind)
    if run_id is not None:
        log.info("Retomando corrida %d (%s)", run_id, kind)
        return run_id
    run_id = repository.start_run(conn, kind, {"trigger": "refresh"})
    log.info("Corrida nueva %d (%s): descubriendo…", run_id, kind)
    try:
        discover(conn, run_id)
    except BaseException as exc:
        # Sin esto quedaría "en curso" con la cola a medias: la próxima vez se retomaría sin descubrir de nuevo
        # (y mientras tanto rappi-ia no embebe, porque cree que hay una descarga en curso).
        conn.rollback()
        repository.finish_run(conn, run_id, "failed")
        if isinstance(exc, DownloadStopped):
            exc.run_left_open = False
        if on_failure is None or not isinstance(exc, Exception) or isinstance(exc, DownloadStopped):
            raise
        on_failure(run_id, exc)
        return None
    return run_id


def refresh(
    conn: Connection,
    client: RappiClient,
    discover_stores: Discoverer,
    discover_restaurants: Discoverer,
    backup: Callable[[], Path] | None = None,
    reports_dir: Path = REPORTS_DIR,
    resume_only: bool = False,
    retry_stores: Discoverer | None = None,
) -> tuple[list[dict], bool]:
    """Corre la actualización completa y devuelve los reportes (tiendas, restaurantes) y si falló el respaldo. Si falló
    el descubrimiento de restaurantes, su reporte viene con estado 'failed' y la alerta (salvo un posible bloqueo, que
    sube como DownloadStopped, igual que una página que robots.txt no permite).

    Con `resume_only` solo retoma las corridas abiertas (p. ej. las que reabrió `retry-failed`) y nunca empieza una
    nueva: sin él, una corrida de restaurantes cerrada se volvería a bajar entera."""
    check_migrations(conn)  # antes de descargar: sin una migración nueva, fallaría recién al armar la búsqueda
    reports = []
    # Con restaurantes abiertos y tiendas cerradas, la actualización anterior se cortó después de terminar las tiendas
    # (apagado, corte de luz): se retoma en los restaurantes, sin volver a bajar tiendas.
    if repository.open_run(conn, "stores") is not None or (
        not resume_only and repository.open_run(conn, "restaurants") is None
    ):
        run_id = ensure_run(conn, "stores", discover_stores)
        _scrape(conn, run_id, lambda: process_store_jobs(conn, client, run_id), reports_dir)
        # Los listados que fallaron al descubrir (botillerías cerradas a las 03:00) se piden de nuevo ahora, horas
        # después, y lo que aparezca se baja en la misma corrida. Un bloqueo al pedirlos se trata como en la descarga.
        if retry_stores is not None and _scrape(conn, run_id, lambda: retry_stores(conn, run_id), reports_dir):
            _scrape(conn, run_id, lambda: process_store_jobs(conn, client, run_id), reports_dir)
        reports.append(finish_and_report(conn, run_id, "stores", reports_dir)[0])

    if not resume_only or repository.open_run(conn, "restaurants") is not None:

        def discovery_failed(failed_run: int, exc: Exception) -> None:
            # Un sitemap caído al final de días de tiendas no debe dejar esas tiendas fuera de la búsqueda una semana
            # más: la corrida queda cerrada como fallida (con el error en su reporte) y se sigue con búsqueda y
            # respaldo.
            log.exception("Descubrimiento de restaurantes fallido: no se actualizan esta vez")
            reports.append(write_run_report(conn, failed_run, reports_dir, f"{type(exc).__name__}: {exc}")[0])

        run_id = ensure_run(conn, "restaurants", discover_restaurants, on_failure=discovery_failed)
        if run_id is not None:
            _scrape(conn, run_id, lambda: process_restaurant_jobs(conn, client, run_id), reports_dir)
            reports.append(finish_and_report(conn, run_id, "restaurants", reports_dir)[0])

    # Cierra la transacción de lectura que abre `open_run` (con `resume_only`): si no, la búsqueda quedaría en un
    # savepoint sin guardar, `pg_dump` respaldaría los documentos viejos y un respaldo fallido (exit 3) la desharía.
    conn.commit()
    log.info("Documentos de búsqueda: %s", build_search_documents(conn))
    backup_failed = False
    if backup is not None:
        try:
            backup()
        except Exception:  # los respaldos anteriores siguen intactos; la capa de IA igual tiene que correr
            log.exception("Respaldo fallido: se conservan los anteriores")
            backup_failed = True
    return reports, backup_failed


def _scrape(conn: Connection, run_id: int, process: Callable[[], int | None], reports_dir: Path) -> int | None:
    """Corre `process` (la descarga o el nuevo pedido de los listados) y devuelve lo que devuelva. Ante un posible
    bloqueo o una página que robots.txt no permite, deja el reporte y la corrida abierta, aunque no le queden jobs
    pendientes (la próxima actualización la retoma y vuelve a pedir los listados), y no sigue: ni restaurantes, ni
    búsqueda, ni respaldo."""
    try:
        return process()
    except DownloadStopped as exc:
        log.error("Corrida %d detenida: %s", run_id, exc)
        log.info("Reporte guardado en %s", write_run_report(conn, run_id, reports_dir, alert=str(exc))[1])
        raise
