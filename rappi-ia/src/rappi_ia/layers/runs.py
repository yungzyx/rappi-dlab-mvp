"""Linaje de las capas derivadas: cada corrida de `rappi-ia attributes|measures|…` queda en `layer_runs`."""

import hashlib
from functools import lru_cache
from pathlib import Path

from psycopg import Connection
from psycopg.types.json import Jsonb


def start_layer_run(conn: Connection, layer: str, rules_version: str, counts: dict | None = None) -> int:
    """Abre la corrida (`running`); `counts` deja algo a la vista desde el inicio (p. ej., la fuente del motor), por si
    no llega a terminar."""
    row = conn.execute(
        "INSERT INTO layer_runs (layer, rules_version, counts) VALUES (%s, %s, %s) RETURNING run_id",
        (layer, rules_version, Jsonb(counts or {})),
    ).fetchone()
    return row[0]


def finish_layer_run(conn: Connection, run_id: int, counts: dict, status: str = "done") -> None:
    conn.execute(
        "UPDATE layer_runs SET status = %s, counts = %s, finished_at = clock_timestamp() WHERE run_id = %s",
        (status, Jsonb(counts), run_id),
    )


def rules_version(version: str, *files: Path) -> str:
    """`version` más una huella del contenido de las reglas (TOML y código): dos corridas con la misma huella usaron
    exactamente las mismas reglas, aunque alguien olvide subir la fecha. Queda en caché por fecha y tamaño de cada
    archivo (el recálculo de segmentos después de cada pedido la pide)."""
    stamps = []
    for path in map(Path, files):
        stat = path.stat()
        stamps.append((path, stat.st_mtime_ns, stat.st_size))
    return _rules_version(version, tuple(stamps))


@lru_cache(maxsize=32)
def _rules_version(version: str, stamps: tuple[tuple[Path, int, int], ...]) -> str:
    digest = hashlib.sha256()
    for path, _mtime_ns, _size in stamps:
        digest.update(path.read_bytes())
    return f"{version}+{digest.hexdigest()[:8]}"
