"""Conexión a Postgres y runner de migraciones (`storage/migrations/*.sql`, en orden).

Cada migración corre en su propia transacción, con `lock_timeout` (MIGRATE_LOCK_TIMEOUT, 10 s): si una tabla está
tomada, falla en vez de dejar en fila a todas sus consultas. Un `CHECK` nuevo sobre una tabla grande va en dos pasos,
`ADD CONSTRAINT … NOT VALID` y después `VALIDATE CONSTRAINT`: en uno solo, la tabla queda tomada (ni lecturas ni
escrituras) mientras se revisa entera; así, el primero no la lee y el segundo la lee sin bloquear las escrituras.
"""

import hashlib
import logging
import os
from pathlib import Path

import psycopg
from psycopg.pq import TransactionStatus

from .. import config  # carga .env antes de leer DATABASE_URL

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
# Clave de pg_advisory_lock (de sesión) que pone en fila a dos `migrate` a la vez (p. ej. dos despliegues, o un
# despliegue y la tarea semanal). No es la de search_documents (72_001).
MIGRATE_LOCK = 72_000


class PendingMigrations(RuntimeError):
    """La base no tiene todas las migraciones del repositorio (p. ej. tras un `git pull`)."""


# En producción (API_ENV=production) la tarea semanal no migra: solo revisa. Las migraciones las aplica el despliegue.
APPLIED_BY_DEPLOY = (
    "en producción las aplica el despliegue, que respalda la base antes: "
    "`docker compose -f deploy/docker-compose.yml --env-file /etc/rappi/rappi.env run --rm migrate` "
    "(docs/despliegue.md §4)"
)


def database_url(env_var: str = "DATABASE_URL") -> str:
    url = os.environ.get(env_var)
    if not url:
        raise RuntimeError(f"Falta {env_var} (ver .env.example)")
    return url


def connect(url: str | None = None) -> psycopg.Connection:
    """Con timeout al conectar y keepalives: la conexión del scraper vive días, y sin ellos una caída de red o un NAT
    que la olvida la dejaba colgada en vez de fallar."""
    return psycopg.connect(url or database_url(), connect_timeout=10, keepalives=1, keepalives_idle=60)


def _checksum(path: Path) -> str:
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


def _has_checksum_column(conn: psycopg.Connection) -> bool:
    return conn.execute(
        """SELECT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = 'schema_migrations'::regclass
                          AND attname = 'checksum' AND NOT attisdropped)"""
    ).fetchone()[0]


def _applied(conn: psycopg.Connection) -> dict[str, str | None]:
    """Nombre → md5 de las migraciones registradas. `to_jsonb(m)` lee el checksum aunque la columna todavía no exista
    (una base que no ha pasado por el `migrate` que la agrega)."""
    if conn.execute("SELECT to_regclass('schema_migrations')").fetchone()[0] is None:
        return {}
    return dict(conn.execute("SELECT name, to_jsonb(m) ->> 'checksum' FROM schema_migrations m").fetchall())


def migrate(conn: psycopg.Connection) -> list[str]:
    """Aplica las migraciones pendientes, cada una en su transacción. Devuelve los nombres aplicados.

    Toma el candado MIGRATE_LOCK durante toda la pasada: un segundo `migrate` espera al primero (sin límite) y después
    no encuentra nada pendiente. Registra el md5 de cada archivo; a las filas anteriores sin md5 se lo completa."""
    previous_timeout = conn.execute("SELECT current_setting('lock_timeout')").fetchone()[0]
    conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATE_LOCK,))
    try:
        conn.execute("SELECT set_config('lock_timeout', %s, false)", (config.MIGRATE_LOCK_TIMEOUT,))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        # Solo si falta: el ALTER pide ACCESS EXCLUSIVE aun con IF NOT EXISTS, y pg_dump tiene la tabla tomada (ACCESS
        # SHARE) todo el volcado: un `migrate` durante un respaldo fallaba a los 10 s aunque no hubiera nada pendiente.
        if not _has_checksum_column(conn):
            conn.execute("ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS checksum text")
        applied = _applied(conn)
        files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        for path in files:
            if path.name in applied and applied[path.name] is None:
                conn.execute("UPDATE schema_migrations SET checksum = %s WHERE name = %s", (_checksum(path), path.name))
        conn.commit()  # así cada `conn.transaction()` de abajo es una transacción propia, no un savepoint
        newly_applied = []
        for path in files:
            if path.name in applied:
                continue
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT INTO schema_migrations (name, checksum) VALUES (%s, %s)", (path.name, _checksum(path))
                )
            log.info("Migración aplicada: %s", path.name)
            newly_applied.append(path.name)
        conn.commit()
        return newly_applied
    finally:
        # Lo aplicado ya está confirmado: el candado se suelta después, y la sesión vuelve con su lock_timeout. Con la
        # conexión caída no hay nada que soltar (el candado muere con la sesión) y se ve el error original.
        if not conn.closed:
            if conn.info.transaction_status == TransactionStatus.INERROR:
                conn.rollback()
            conn.execute("SELECT set_config('lock_timeout', %s, false)", (previous_timeout,))
            conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATE_LOCK,))
            conn.commit()


def check_migrations(conn: psycopg.Connection, advice: str = "corre `rappi migrate` antes") -> None:
    """Falla si la base no tiene todas las migraciones del repositorio: el código puede depender de ellas (la vista de
    vigencia de la 019) y `refresh` descargaba todo antes de caerse al armar la búsqueda. `advice` dice qué hacer."""
    applied = _applied(conn)
    for name in changed_migrations(conn, applied):
        log.warning("La migración %s cambió después de aplicarse", name)
    pending = [path.name for path in sorted(MIGRATIONS_DIR.glob("*.sql")) if path.name not in applied]
    if pending:
        raise PendingMigrations(f"Hay migraciones pendientes ({', '.join(pending)}): {advice}.")


def changed_migrations(conn: psycopg.Connection, applied: dict[str, str | None] | None = None) -> list[str]:
    """Migraciones aplicadas cuyo archivo ya no tiene el md5 registrado: se editaron después de aplicarse, y `migrate`
    no las vuelve a correr (se registran por nombre). Las filas sin md5 todavía no cuentan."""
    applied = _applied(conn) if applied is None else applied
    return [
        path.name
        for path in sorted(MIGRATIONS_DIR.glob("*.sql"))
        if applied.get(path.name) is not None and applied[path.name] != _checksum(path)
    ]
