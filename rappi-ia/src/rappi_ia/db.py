"""Conexión a Postgres. El esquema y sus migraciones son de rappi-scraper (un solo historial para toda la base).

`migrate` toma un candado de Postgres: dos a la vez se ponen en fila. En producción (API_ENV=production) solo migra
`rappi-ia deploy-migrate`, que respalda antes; ni la API ni `make serve` migran al arrancar."""

import os

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from rappi_scraper.storage import db as scraper_db
from rappi_scraper.storage.db import changed_migrations, database_url, migrate

from . import config  # carga .env antes de leer DATABASE_URL
from .catalog.hours import TZ

__all__ = [
    "TIMEZONE_OPTIONS",
    "changed_migrations",
    "connect",
    "database_url",
    "migrate",
    "pending_migrations",
    "set_index_build_memory",
    "timezone_options",
]

# La hora de Chile en cada conexión: `date_trunc('day'|'week', ts)` y `::date` sobre timestamptz (el panel) siguen la
# zona de la sesión, y un Postgres en UTC (el de deploy/ o el del CI) cortaría la semana el domingo a las 21:00.
TIMEZONE_OPTIONS = f"-c TimeZone={TZ.key}"


def timezone_options(conninfo: str) -> str:
    """Las `options` de libpq para `conninfo`: las que ya trae (p. ej. `?options=-c random_page_cost=4` en la URL) o,
    si la URL no trae, las de `PGOPTIONS`, más la hora de Chile, salvo que ya fijen una zona. Van como argumento de
    psycopg, que pisa las de la URL y `PGOPTIONS`: por eso se juntan aquí."""
    current = conninfo_to_dict(conninfo).get("options") or os.environ.get("PGOPTIONS", "")
    if "timezone" in current.lower():
        return current
    return f"{current} {TIMEZONE_OPTIONS}".strip()


def connect(url: str | None = None, **options) -> psycopg.Connection:
    """`options` van a psycopg.connect (p. ej. `connect_timeout`). Sin `options` de libpq, la sesión va en la hora
    de Chile (`timezone_options`)."""
    url = url or database_url()
    options.setdefault("options", timezone_options(url))
    return psycopg.connect(url, **options)


def pending_migrations(conn: psycopg.Connection) -> list[str]:
    """Migraciones del repositorio que la base aún no tiene, en orden (la misma regla de `migrate`: por nombre)."""
    applied: set[str] = set()
    if conn.execute("SELECT to_regclass('schema_migrations')").fetchone()[0] is not None:
        applied = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}
    return [path.name for path in sorted(scraper_db.MIGRATIONS_DIR.glob("*.sql")) if path.name not in applied]


def set_index_build_memory(conn: psycopg.Connection) -> None:
    """Memoria para construir un índice HNSW, solo en la transacción en curso (SET LOCAL: al terminarla vuelve sola
    al valor normal). Va justo antes del CREATE INDEX, sin commit entre medio."""
    memory = sql.Literal(config.HNSW_MAINTENANCE_WORK_MEM)
    conn.execute(sql.SQL("SET LOCAL maintenance_work_mem = {}").format(memory))
