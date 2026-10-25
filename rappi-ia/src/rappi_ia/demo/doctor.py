"""Chequeos de la base antes de levantar el MVP: `rappi-ia doctor` y `rappi-ia check-migrations`. Solo leen."""

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

import psycopg

from ..config import PROJECT_ROOT
from ..db import changed_migrations, connect, pending_migrations

# La base con los datos descargados: no se le aplican migraciones desde una rama sin fusionar.
PROTECTED_DATABASE = "rappi"


def _connection_problem(exc: psycopg.Error) -> str:
    """Qué decir cuando no se pudo abrir la conexión: Postgres caído o la base que no existe piden cosas distintas."""
    text = str(exc).strip()
    missing = re.search(r'database "([^"]+)" does not exist', text)
    if missing:
        return f"La base {missing.group(1)} no existe: créala y carga un respaldo (docs/instalacion.md, sección 3)."
    reason = (text.splitlines() or [type(exc).__name__])[0]
    return (
        f"No puedo conectar con Postgres ({reason}). Revisa que esté corriendo y que DATABASE_URL apunte "
        "a la base rappi (ver docs/instalacion.md)."
    )


def check_database(url: str) -> tuple[bool, str]:
    """Devuelve si la base está lista y un mensaje en español que dice qué falta o qué hay."""
    try:
        conn = connect(url, connect_timeout=3)
    except psycopg.Error as exc:
        return False, _connection_problem(exc)
    with conn:
        conn.read_only = True
        try:
            rows = conn.execute("SELECT vertical, count(*) FROM search_documents GROUP BY vertical").fetchall()
        except psycopg.errors.UndefinedTable:
            return False, (
                "La base no tiene catálogo: faltan las tablas. Corre `rappi-ia migrate` y carga el catálogo "
                "(ver docs/instalacion.md, sección 3)."
            )
    if not rows:
        return False, (
            "La base no tiene catálogo: no hay documentos de búsqueda. Restaura un respaldo o descarga el "
            "catálogo y arma la búsqueda (ver docs/instalacion.md, sección 3)."
        )
    documents = sum(count for _, count in rows)
    return True, f"Base lista: {documents} documentos en {len(rows)} verticales"


def head_is_merged(repo: Path = PROJECT_ROOT) -> bool | None:
    """¿El código que corre está contenido en origin/main? `None` si git no puede decirlo (sin git, fuera de un
    repositorio o sin origin/main): ahí no hay cómo saber que es una rama, y no se frena a quien no la usa."""
    command = ["git", "-C", str(repo), "merge-base", "--is-ancestor", "HEAD", "origin/main"]
    try:
        done = subprocess.run(command, capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return {0: True, 1: False}.get(done.returncode)


def _refusal(database: str, pending: list[str]) -> str:
    names = "\n".join(f"  - {name}" for name in pending)
    return (
        f"Hay migraciones pendientes en la base {database} y este código todavía no está en origin/main:\n"
        f"{names}\n"
        "Las migraciones se registran por nombre de archivo: si una de rama se aplica y después se edita, nunca se "
        "vuelve a aplicar. Por eso no las aplico en la base real. Para seguir:\n"
        "  - prueba en una copia (con la API detenida): `createdb -T rappi rappi_staging` y "
        "`DATABASE_URL=postgresql:///rappi_staging make mvp`;\n"
        "  - o fuérzalo a sabiendas: `MIGRATE=1 make mvp` (o `MIGRATE=1 make serve`)."
    )


def check_pending_migrations(
    url: str, *, force: bool = False, merged: Callable[[], bool | None] | None = None
) -> tuple[bool, str]:
    """¿Se pueden aplicar ya las migraciones pendientes? Solo lee; `migrate` es el que escribe.

    Se niega (False y un mensaje que las lista y dice cómo seguir) si hay pendientes en la base protegida (`rappi`) y el
    código no está en origin/main. `force` (la variable MIGRATE=1) y cualquier otra base (p. ej. una copia
    `rappi_staging`) las dejan pasar; sin pendientes, el mensaje queda vacío. Antes avisa (sin frenar) de cada migración
    aplicada cuyo archivo cambió después."""
    try:
        conn = connect(url, connect_timeout=3)
    except psycopg.Error as exc:
        return False, _connection_problem(exc)
    with conn:
        conn.read_only = True
        pending = pending_migrations(conn)
        changed = changed_migrations(conn)
        database = conn.info.dbname
    notes = [f"La migración {name} cambió después de aplicarse" for name in changed]
    if not pending:
        return True, "\n".join(notes)
    if database == PROTECTED_DATABASE and not force and (merged or head_is_merged)() is False:
        return False, "\n".join([*notes, _refusal(database, pending)])
    return True, "\n".join([*notes, f"Migraciones pendientes en {database} (se aplican ahora): {', '.join(pending)}"])
