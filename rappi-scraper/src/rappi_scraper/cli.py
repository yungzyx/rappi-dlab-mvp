"""CLI de la base de datos de contenido por vertical.

Flujo típico:
    rappi migrate
    rappi discover                          # tiendas por vertical + restaurantes
    rappi scrape-stores --vertical mall
    rappi scrape-restaurants
    rappi build-search
    rappi search "pañales" --vertical supermercado
    rappi retry-failed --kind stores        # reintentar jobs fallidos de la última corrida
    rappi refresh --resume-only             # y retomar solo lo reencolado (sin corridas nuevas)
    rappi report                            # reporte de calidad de la última corrida
    rappi refresh                           # todo lo anterior de una vez (pensado para correr semanal)
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from . import config
from .keep_awake import keep_awake
from .lock import DownloadInProgress, database_lock, file_lock
from .pipeline.discover import (
    VERTICAL_LISTINGS,
    city_locations,
    discover_restaurants,
    discover_stores,
    failed_listings,
)
from .pipeline.refresh import JOB_TYPES, finish_and_report, refresh
from .pipeline.restaurants import process_restaurant_jobs
from .pipeline.stores import process_store_jobs
from .reporting import render_markdown, write_run_report
from .scraping.client import DownloadStopped, PossibleBlock, RappiClient, RobotsDisallowed
from .storage import repository
from .storage.backup import backup_database
from .storage.db import APPLIED_BY_DEPLOY, PendingMigrations, check_migrations, connect, database_url, migrate
from .storage.export import export_catalog_csv
from .storage.search import VERTICALS, build_search_documents, search

log = logging.getLogger("rappi_scraper")

LOGS_DIR = config.DATA_DIR / "logs"
# Los logs de cada comando largo (`refresh_…log`, `backup_…log`) se borran pasadas estas semanas (LOG_RETENTION_WEEKS).
LOG_RETENTION_WEEKS = 8
# Log a archivo, equipo despierto y el candado de descargas: los que descargan de rappi.cl, y `backup`, que no debe
# correr junto al respaldo de `refresh` (se pisaban al rotar).
LONG_COMMANDS = {"discover", "scrape-stores", "scrape-restaurants", "refresh", "backup"}
# Códigos de salida de `refresh` que refresh-semanal.sh distingue:
# 3: terminó todo menos el respaldo; se anota («respaldo fallido») y sigue con la capa de IA.
BACKUP_FAILED_EXIT = 3
# 4: posible bloqueo; la corrida quedó abierta y la tarea semanal se detiene ahí.
POSSIBLE_BLOCK_EXIT = 4
# 5: los restaurantes no se actualizaron (falló su descubrimiento y no había una corrida anterior terminada de la que
# usar la lista), y tiendas, búsqueda y respaldo sí: sigue la capa de IA. Con un sitemap caído o bloqueado y esa lista,
# los restaurantes se bajan igual y sale con 0 (el reporte lo avisa).
RESTAURANTS_FAILED_EXIT = 5
# 6: las dos cosas, restaurantes sin actualizar y respaldo fallido: la tarea semanal anota ambas y sigue.
RESTAURANTS_AND_BACKUP_FAILED_EXIT = 6
# 7: robots.txt no permite una página (o no respondió); como con el 4, la corrida queda abierta y la tarea semanal se
# detiene ahí, hasta que alguien revise la regla.
ROBOTS_EXIT = 7
# Avisos que no cambian el código de salida: si la variable trae una ruta, `refresh` escribe ahí una marca fija por
# línea, y refresh-semanal.sh la anota en ultimo-estado.txt. La única por ahora: los restaurantes se bajaron con la
# lista de una corrida anterior porque el sitemap no respondió (sale con 0).
REFRESH_NOTES_ENV = "RAPPI_REFRESH_NOTES"
FALLBACK_NOTE = "restaurantes_con_lista_anterior"


def _run_id(conn, kind: str, args) -> int:
    """Reanuda la última corrida abierta de ese tipo, o crea una nueva con --new-run (y cierra la abierta como fallida:
    si quedara «en curso», `rappi-ia embed` no correría nunca)."""
    run_id = repository.open_run(conn, kind)
    if args.new_run and run_id is not None:
        repository.finish_run(conn, run_id, "failed")
        log.info("Corrida %d (%s) cerrada como fallida: se empieza otra", run_id, kind)
        run_id = None
    if run_id is None:
        run_id = repository.start_run(conn, kind, {})
        log.info("Corrida nueva %d (%s)", run_id, kind)
    else:
        log.info("Reanudando corrida %d (%s)", run_id, kind)
    return run_id


def _store_discoverer(client: RappiClient, verticals: list[str], city_filter: list[str] | None = None):
    """`run` descubre; `run.retry` vuelve a pedir solo los listados que fallaron (anotados en la corrida, así
    sobrevive a un corte) y devuelve cuántos grupos quedaron en la cola."""

    def cities() -> list[dict]:
        found = city_locations(client.get_json(config.STORES_METADATA_URL))
        return [c for c in found if not city_filter or any(x.lower() in c["city"].lower() for x in city_filter)]

    def run(conn, run_id: int) -> int:
        n = discover_stores(conn, client, run_id, verticals, cities())
        log.info("%d grupos de tiendas en la cola (corrida %d)", n, run_id)
        return n

    def retry(conn, run_id: int) -> int:
        pending = failed_listings(conn, run_id)
        if not pending:
            return 0
        log.info("Reintentando %d listados que fallaron al descubrir", len(pending))
        n = discover_stores(conn, client, run_id, verticals, cities(), only=pending)
        log.info("%d grupos de tiendas en la cola (%d listados siguen fallando)", n, len(failed_listings(conn, run_id)))
        return n

    run.retry = retry
    return run


def _restaurant_discoverer(client: RappiClient, max_chains: int | None = None, max_independents: int | None = None):
    def run(conn, run_id: int) -> int:
        n = discover_restaurants(conn, client, run_id, max_chains, max_independents)
        log.info("%d jobs de restaurantes en la cola (corrida %d)", n, run_id)
        return n

    return run


def cmd_discover(conn, args) -> None:
    client = RappiClient()
    if args.verticals != ["restaurantes"]:
        verticals = [v for v in args.verticals if v in VERTICAL_LISTINGS]
        _store_discoverer(client, verticals, args.cities)(conn, _run_id(conn, "stores", args))
    if "restaurantes" in args.verticals:
        _restaurant_discoverer(client, args.max_chains, args.max_independents)(conn, _run_id(conn, "restaurants", args))


def _finish_and_report(conn, run_id: int, kind: str) -> None:
    report, _ = finish_and_report(conn, run_id, kind)
    print(render_markdown(report))


def _scrape_or_stop(conn, run_id: int, kind: str, process) -> None:
    """Como `refresh`: ante un posible bloqueo o robots.txt deja el reporte con la alerta y un mensaje claro, no una
    traza."""
    try:
        process()
    except DownloadStopped as exc:
        report, _ = finish_and_report(conn, run_id, kind, alert=str(exc))
        print(render_markdown(report))
        raise SystemExit(
            f"Descarga detenida: {exc}. La corrida quedó abierta: retómala con el mismo comando más tarde."
        ) from exc
    _finish_and_report(conn, run_id, kind)


def cmd_refresh(conn, args) -> None:
    client = RappiClient()
    discover = _store_discoverer(client, list(VERTICAL_LISTINGS))
    try:
        reports, backup_failed = refresh(
            conn,
            client,
            discover,
            _restaurant_discoverer(client),
            retry_stores=discover.retry,
            backup=None if args.no_backup else lambda: backup_database(database_url()),
            resume_only=args.resume_only,
        )
    except DownloadStopped as exc:
        if exc.run_left_open:
            state = "El reporte está en data/reports/; la corrida quedó abierta y la próxima actualización la retoma."
        else:  # al descubrir: la corrida se cerró y no hay qué retomar
            state = "Fue al descubrir: la corrida se cerró como fallida y la próxima actualización empieza otra."
        if isinstance(exc, RobotsDisallowed):  # la próxima vuelve a pedir lo mismo: alguien tiene que decidir antes
            state += " Si robots.txt sigue sin permitir esa página, la próxima se detendrá en el mismo lugar."
        print(f"Descarga detenida: {exc}. {state}", file=sys.stderr)
        raise SystemExit(POSSIBLE_BLOCK_EXIT if isinstance(exc, PossibleBlock) else ROBOTS_EXIT) from exc
    for report in reports:
        print(render_markdown(report))
    _write_refresh_notes(reports)
    restaurants_failed = any(r["status"] == "failed" for r in reports)
    if restaurants_failed and backup_failed:
        raise SystemExit(RESTAURANTS_AND_BACKUP_FAILED_EXIT)
    if restaurants_failed:
        raise SystemExit(RESTAURANTS_FAILED_EXIT)
    if backup_failed:
        raise SystemExit(BACKUP_FAILED_EXIT)


def _write_refresh_notes(reports: list[dict]) -> None:
    path = os.environ.get(REFRESH_NOTES_ENV)
    notes = [FALLBACK_NOTE for report in reports if report.get("fallback_list")]
    if path and notes:
        try:
            Path(path).write_text("".join(f"{note}\n" for note in notes), encoding="utf-8")
        except OSError as exc:  # solo es un aviso: la descarga ya terminó y el reporte lo dice
            log.warning("No pude escribir los avisos en %s (%s): ultimo-estado.txt no los anotará", path, exc)


def cmd_backup(conn, args) -> None:
    print(backup_database(database_url()))


def cmd_scrape_stores(conn, args) -> None:
    run_id = repository.open_run(conn, "stores")
    if run_id is None:
        raise SystemExit("No hay corrida de tiendas abierta: ejecuta primero `discover`.")
    client = RappiClient()
    _scrape_or_stop(
        conn,
        run_id,
        "stores",
        lambda: process_store_jobs(conn, client, run_id, args.vertical, args.limit, args.max_aisles),
    )


def cmd_scrape_restaurants(conn, args) -> None:
    run_id = repository.open_run(conn, "restaurants")
    if run_id is None:
        raise SystemExit("No hay corrida de restaurantes abierta: ejecuta `discover --verticals restaurantes`.")
    client = RappiClient()
    _scrape_or_stop(conn, run_id, "restaurants", lambda: process_restaurant_jobs(conn, client, run_id, args.limit))


def cmd_retry_failed(conn, args) -> None:
    run_id = repository.latest_run(conn, args.kind)
    if run_id is None:
        raise SystemExit(f"No hay corridas de tipo {args.kind}.")
    requeued = repository.requeue_failed(conn, run_id, args.max_attempts)
    if requeued:
        repository.reopen_run(conn, run_id)
    command = "scrape-stores" if args.kind == "stores" else "scrape-restaurants"
    print(f"{len(requeued)} jobs fallidos vuelven a la cola (corrida {run_id}). Siguiente: rappi {command}")


def cmd_report(conn, args) -> None:
    run_id = args.run or repository.latest_run(conn, args.kind)
    if run_id is None:
        raise SystemExit("No hay corridas para reportar.")
    report, path = write_run_report(conn, run_id)
    print(render_markdown(report))
    print(f"Guardado en {path}")


def cmd_status(conn, args) -> None:
    print("corrida\ttipo\testado\tjobs\tcantidad")
    for row in repository.run_status(conn):
        print(*row, sep="\t")
    print()
    columns, rows = repository.vertical_summary(conn)
    print(*columns, sep="\t")
    for row in rows:
        print(*row, sep="\t")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Base de datos de contenido de Rappi Chile por vertical")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("migrate", help="Aplicar migraciones pendientes")
    p.add_argument(
        "--solo-revisar",
        action="store_true",
        help="No aplica nada: falla si falta una (la tarea semanal en producción; las aplica el despliegue)",
    )

    p = sub.add_parser("discover", help="Descubrir tiendas por vertical y restaurantes; crea la cola")
    p.add_argument(
        "--verticals",
        nargs="+",
        default=[*VERTICAL_LISTINGS, "restaurantes"],
        choices=[*VERTICAL_LISTINGS, "restaurantes"],
    )
    p.add_argument("--cities", nargs="+", help="Limitar ciudades (coincidencia parcial)")
    p.add_argument(
        "--max-chains", type=int, help="Máximo de cadenas de restaurantes (pruebas; también con la lista de respaldo)"
    )
    p.add_argument(
        "--max-independents",
        type=int,
        help="Máximo de restaurantes independientes (pruebas; también con la lista de respaldo)",
    )
    p.add_argument("--new-run", action="store_true", help="Empezar corrida nueva en vez de reanudar")

    p = sub.add_parser("scrape-stores", help="Procesar la cola de tiendas")
    p.add_argument("--vertical", choices=[v for v in VERTICALS if v != "restaurantes"])
    p.add_argument("--limit", type=int)
    p.add_argument("--max-aisles", type=int, help="Máximo de pasillos por tienda (pruebas)")

    p = sub.add_parser("scrape-restaurants", help="Procesar la cola de restaurantes")
    p.add_argument("--limit", type=int)

    sub.add_parser("build-search", help="Regenerar documentos de búsqueda por vertical")

    p = sub.add_parser("search", help="Buscar por texto dentro de un vertical")
    p.add_argument("query")
    p.add_argument("--vertical", required=True, choices=VERTICALS)
    p.add_argument("--limit", type=int, default=10)

    p = sub.add_parser("export-csv", help="Exportar catálogo por vertical a CSV")
    p.add_argument("--output", type=Path, default=config.EXPORT_DIR / "catalogo_por_vertical.csv")

    sub.add_parser("status", help="Estado de corridas y resumen por vertical")

    p = sub.add_parser("refresh", help="Actualización completa: tiendas, restaurantes, búsqueda, reportes y respaldo")
    p.add_argument("--no-backup", action="store_true", help="No respaldar la base al final")
    p.add_argument(
        "--resume-only",
        action="store_true",
        help="Solo retomar las corridas abiertas (p. ej. tras retry-failed), sin empezar corridas nuevas",
    )

    sub.add_parser("backup", help="Respaldar la base en data/backups/ (conserva los últimos 4)")

    p = sub.add_parser("retry-failed", help="Reencolar los jobs fallidos de la última corrida")
    p.add_argument("--kind", choices=list(JOB_TYPES), default="stores")
    p.add_argument("--max-attempts", type=int, default=4, help="Solo jobs con menos intentos que esto")

    p = sub.add_parser("report", help="Reporte de calidad de una corrida")
    p.add_argument("--run", type=int, help="ID de corrida (por defecto, la última del tipo)")
    p.add_argument("--kind", choices=list(JOB_TYPES), default="stores")
    return parser


COMMANDS = {
    "discover": cmd_discover,
    "scrape-stores": cmd_scrape_stores,
    "scrape-restaurants": cmd_scrape_restaurants,
    "status": cmd_status,
    "retry-failed": cmd_retry_failed,
    "report": cmd_report,
    "refresh": cmd_refresh,
    "backup": cmd_backup,
}


def prune_old_logs(logs_dir: Path) -> list[Path]:
    """Borra los `<comando>_<fecha>.log` con más de LOG_RETENTION_WEEKS semanas (mínimo 1). Los de launchd
    (`launchd.*.log`, los rota refresh-semanal.sh) y ultimo-estado.txt no son de un comando y quedan. Nunca hace fallar
    el comando: un valor mal escrito usa el de siempre y un log que otro proceso borró en el camino se salta."""
    try:
        weeks = max(1, int(os.environ.get("LOG_RETENTION_WEEKS") or LOG_RETENTION_WEEKS))
    except ValueError:
        log.warning("LOG_RETENTION_WEEKS no es un número de semanas: uso %d.", LOG_RETENTION_WEEKS)
        weeks = LOG_RETENTION_WEEKS
    cutoff = time.time() - weeks * 7 * 86400
    removed = []
    for path in logs_dir.glob("*_*.log"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed.append(path)
        except OSError as exc:
            log.warning("No pude borrar el log antiguo %s (%s): sigo.", path.name, type(exc).__name__)
    return removed


def _setup_logging(command: str) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if command in LONG_COMMANDS:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOGS_DIR / f"{command}_{datetime.now():%Y%m%d-%H%M%S}.log"
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S", handlers=handlers
    )
    if command in LONG_COMMANDS:
        log.info("Log en %s", log_path)
        prune_old_logs(LOGS_DIR)  # después de configurar el log: sus avisos quedan en el archivo


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        if args.command in LONG_COMMANDS:  # una a la vez (sin el candado de archivo, ni log)
            with file_lock():
                _setup_logging(args.command)  # antes del candado de la base: su aviso queda en el log
                with database_lock(), keep_awake(), connect() as conn:
                    COMMANDS[args.command](conn, args)
        else:
            _setup_logging(args.command)
            _run_simple(args)
    except (DownloadInProgress, PendingMigrations) as exc:
        raise SystemExit(str(exc)) from exc
    except DownloadStopped as exc:  # al descubrir, fuera de `refresh`: un mensaje y no una traza
        raise SystemExit(f"Descarga detenida: {exc}.") from exc
    except KeyboardInterrupt:
        log.warning("Interrumpido. Lo avanzado quedó guardado: retoma con el mismo comando.")
        sys.exit(130)


def _run_simple(args) -> None:
    with connect() as conn:
        if args.command in COMMANDS:
            COMMANDS[args.command](conn, args)
        elif args.command == "migrate" and args.solo_revisar:
            check_migrations(conn, APPLIED_BY_DEPLOY)
            print("Migraciones al día.")
        elif args.command == "migrate":
            print("Aplicadas:", migrate(conn) or "ninguna (al día)")
        elif args.command == "build-search":
            check_migrations(conn)
            print(build_search_documents(conn))
        elif args.command == "search":
            for hit in search(conn, args.vertical, args.query, args.limit):
                print(f"{hit['rank']:.3f}  [{hit['entity_type']}] {hit['content'][:110]}")
                print("       ", json.dumps(hit["metadata"], ensure_ascii=False)[:160])
        elif args.command == "export-csv":
            print(export_catalog_csv(conn, args.output))


if __name__ == "__main__":
    main()
