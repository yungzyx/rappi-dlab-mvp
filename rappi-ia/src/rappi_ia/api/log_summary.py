"""Resumen diario de la API (`rappi-ia resumen-api`): lo que dejó en su registro (`api/logs.py`) un día, y las
personas nuevas del prototipo de ese día. Lo corre cada mañana `deploy/macos/resumen.sh` en la demo desde un
Mac; solo lee el registro y la base.

Del registro cuenta las líneas de request (`MÉTODO /plantilla ESTADO N ms`): por ruta, cuántas, el promedio y el
máximo, y cuántas pasaron de SLOW_MS; y los errores 5xx con su `request_id`, para buscarlos en el registro. Las horas
son las del registro (las del equipo). `/live` y `/health` solo se registran cuando fallan, así que no inflan nada.

Las búsquedas de calentamiento de `deploy/macos/vigilante.sh` llevan un `request_id` que empieza con UPKEEP_PREFIX: se
cuentan aparte (cuántas y cuántas pasaron de SLOW_MS) y no entran a las rutas, los lentos ni los promedios; un 5xx
suyo sí va a los errores. Las personas nuevas salen de dos lados: los `POST /session 200` del registro (cada uno, una
persona nueva o un id viejo de la app que se reclama) y las filas de `app_users` de ese día que siguen en la base, que
pueden ser menos porque "Borrar mis datos" borra la fila. De la base también salen las veces que el prototipo
silenció a Mochi por hoy y las que lo ocultó ese día (`agent_visibility`; `agent_changes`).
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from psycopg import Connection

from ..catalog.hours import TZ

SLOW_MS = 1000
UPKEEP_PREFIX = "vigilante-"  # el X-Request-ID de las búsquedas de calentamiento de deploy/macos/vigilante.sh
LINE = re.compile(
    r"^(?P<day>\d{4}-\d\d-\d\d) (?P<time>\d\d:\d\d:\d\d),\d+ \w+ rappi_ia\.api\.logs \[(?P<request>[^\]]+)\] "
    r"(?P<method>[A-Z]+) (?P<route>.+) (?P<status>\d{3}) (?P<ms>\d+) ms$"
)


@dataclass
class Route:
    count: int = 0
    total_ms: int = 0
    max_ms: int = 0
    slow: int = 0


@dataclass
class Summary:
    day: date
    routes: dict[str, Route] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)  # "HH:MM:SS MÉTODO /ruta ESTADO (request_id …)"
    new_people: int | None = None
    upkeep: int = 0  # búsquedas del vigilante (no cuentan en `routes`)
    upkeep_slow: int = 0
    new_sessions: int = 0  # POST /session 200
    silenced: int | None = None  # veces que silenciaron a Mochi por hoy ese día (de la base)
    hidden: int | None = None  # veces que lo ocultaron ese día (de la base)

    @property
    def requests(self) -> int:
        return sum(r.count for r in self.routes.values())

    @property
    def slow(self) -> int:
        return sum(r.slow for r in self.routes.values())


def read_log(lines, day: date) -> Summary:
    """Las líneas de request de `day` (las demás se saltan)."""
    summary = Summary(day)
    wanted = day.isoformat()
    for line in lines:
        match = LINE.match(line.rstrip("\n"))
        if not match or match["day"] != wanted:
            continue
        key = f"{match['method']} {match['route']}"
        ms, status = int(match["ms"]), int(match["status"])
        if status >= 500:
            summary.errors.append(f"{match['time']} {key} {status} (request_id {match['request']})")
        if match["request"].startswith(UPKEEP_PREFIX):
            summary.upkeep += 1
            summary.upkeep_slow += ms > SLOW_MS
            continue
        summary.new_sessions += key == "POST /session" and status == 200
        route = summary.routes.setdefault(key, Route())
        route.count += 1
        route.total_ms += ms
        route.max_ms = max(route.max_ms, ms)
        route.slow += ms > SLOW_MS
    return summary


def read_logs(paths: list[Path], day: date) -> Summary:
    """Como `read_log`, juntando los archivos que existan (el registro y su copia rotada)."""
    summary = Summary(day)
    for path in paths:
        if not path.exists():
            continue
        with path.open(encoding="utf-8", errors="replace") as lines:
            part = read_log(lines, day)
        for key, route in part.routes.items():
            total = summary.routes.setdefault(key, Route())
            total.count += route.count
            total.total_ms += route.total_ms
            total.max_ms = max(total.max_ms, route.max_ms)
            total.slow += route.slow
        summary.errors += part.errors
        summary.upkeep += part.upkeep
        summary.upkeep_slow += part.upkeep_slow
        summary.new_sessions += part.new_sessions
    summary.errors.sort()
    return summary


def new_people(conn: Connection, day: date) -> int:
    """Personas del prototipo creadas ese día (hora de Chile)."""
    start = datetime.combine(day, datetime.min.time(), TZ)
    return conn.execute(
        "SELECT count(*) FROM app_users WHERE source = 'prototype' AND created_at >= %s AND created_at < %s",
        (start, start + timedelta(days=1)),
    ).fetchone()[0]


def agent_changes(conn: Connection, day: date) -> tuple[int, int]:
    """Las veces que el prototipo silenció a Mochi por hoy (`payload.quiet` true) y las que lo ocultó (`visible`
    false, sin `quiet`) ese día (hora de Chile)."""
    start = datetime.combine(day, datetime.min.time(), TZ)
    return conn.execute(
        """SELECT count(*) FILTER (WHERE payload -> 'quiet' = 'true'::jsonb),
                  count(*) FILTER (WHERE payload -> 'visible' = 'false'::jsonb AND NOT payload ? 'quiet')
           FROM app_events
           WHERE source = 'prototype' AND type = 'agent_visibility' AND ts >= %s AND ts < %s""",
        (start, start + timedelta(days=1)),
    ).fetchone()


def _times(value: int) -> str:
    return f"{_number(value)} {'vez' if value == 1 else 'veces'}"


def _number(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def render(summary: Summary) -> str:
    """El resumen en texto: la primera línea dice el día y la segunda, lo que importa (la que va en el aviso)."""
    lines = [
        f"Resumen de la API · {summary.day.strftime('%d-%m-%Y')}",
        f"{_number(summary.requests)} peticiones · {len(summary.errors)} errores 5xx · {summary.slow} sobre 1 s"
        f" · {summary.new_sessions} personas nuevas"
        + ("" if summary.new_people is None else f" ({summary.new_people} siguen en la base)"),
    ]
    if summary.silenced is not None and summary.hidden is not None:
        lines.append(f"Mochi: silenciado por hoy {_times(summary.silenced)} · ocultado {_times(summary.hidden)}")
    if summary.upkeep:
        lines.append(
            f"Mantención del vigilante (no cuenta arriba): {_number(summary.upkeep)} búsquedas"
            f" · {summary.upkeep_slow} sobre 1 s"
        )
    if summary.routes:
        lines += ["", "Por ruta (peticiones · promedio · máximo · sobre 1 s):"]
        ranked = sorted(summary.routes.items(), key=lambda kv: (-kv[1].count, kv[0]))
        for key, route in ranked:
            average = round(route.total_ms / route.count)
            lines.append(
                f"  {key}: {_number(route.count)} · {_number(average)} ms · {_number(route.max_ms)} ms · {route.slow}"
            )
    if summary.errors:
        lines += ["", "Errores 5xx (búscalos en el registro por su request_id):"]
        lines += [f"  {error}" for error in summary.errors]
    return "\n".join(lines) + "\n"
