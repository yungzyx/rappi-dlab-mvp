"""Abierto o cerrado según lo que Rappi publicó el día de la descarga, nunca el estado en vivo.

- Un restaurante trae su horario (`restaurant_details.schedules`: `[{day, open_time, close_time}]`, día en inglés y
  horas "HH:MM:SS"). Se compara con la hora local de Santiago: abre si la hora cae en un tramo del día de hoy. Si el
  horario publicado es de un solo día (la página muestra el del día en que se bajó), ese tramo vale para todos los
  días; si trae varios días y hoy no está, hoy está cerrado. Un tramo que pasa la medianoche (de 19:00 a 02:00) cuenta
  las dos partes.
- Una tienda solo trae cómo estaba al bajarla (`stores.raw`: `is_open` y `next_schedule`): no hay hora que comparar,
  así que se dice tal cual, como el estado publicado en la descarga.

`hours` siempre dice de dónde sale (`source`: `horario` o `descarga`): la app lo rotula así.
"""

import re
from datetime import datetime, time
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Santiago")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_TIME = re.compile(r"(\d{1,2}):(\d{2})")


def now_local() -> datetime:
    """La hora de Santiago (los tests la fijan)."""
    return datetime.now(TZ)


def _clock(text) -> time | None:
    match = _TIME.match(text) if isinstance(text, str) else None
    if match is None or int(match[1]) > 23 or int(match[2]) > 59:
        return None
    return time(int(match[1]), int(match[2]))


def _text(moment: time) -> str:
    return moment.strftime("%H:%M")


def normalize_schedule(schedules) -> list[dict]:
    """Los tramos válidos del horario publicado, `[{day, open, close}]` con horas "HH:MM", en el orden de la semana.
    Lo que no tiene día conocido u horas legibles se descarta."""
    spans = []
    for entry in schedules if isinstance(schedules, list) else []:
        if not isinstance(entry, dict) or entry.get("day") not in DAYS:
            continue
        opens, closes = _clock(entry.get("open_time")), _clock(entry.get("close_time"))
        if opens is not None and closes is not None:
            spans.append({"day": entry["day"], "open": _text(opens), "close": _text(closes)})
    return sorted(spans, key=lambda s: (DAYS.index(s["day"]), s["open"]))


def _spans_of(schedule: list[dict], day: str) -> list[tuple[time, time]]:
    """Los tramos de `day`: los suyos, o los del único día publicado (vale para todos)."""
    days = {s["day"] for s in schedule}
    chosen = day if day in days else (next(iter(days)) if len(days) == 1 else None)
    return [(_clock(s["open"]), _clock(s["close"])) for s in schedule if s["day"] == chosen]


def restaurant_hours(schedule: list[dict], now: datetime) -> dict:
    """`{source, open, closes_at, opens_at, opens_tomorrow, today}` de un horario ya normalizado a la hora `now`.
    Sin horario, `open` es None (no se sabe)."""
    if not schedule:
        return {
            "source": "horario",
            "open": None,
            "closes_at": None,
            "opens_at": None,
            "opens_tomorrow": False,
            "today": None,
        }
    today = DAYS[now.weekday()]
    tomorrow = DAYS[(now.weekday() + 1) % 7]
    yesterday = DAYS[(now.weekday() - 1) % 7]
    moment = now.time().replace(second=0, microsecond=0)
    spans = _spans_of(schedule, today)
    # Lo que queda de un tramo de ayer que pasó la medianoche.
    late = [(o, c) for o, c in _spans_of(schedule, yesterday) if c < o and moment < c]
    current = next(((o, c) for o, c in spans if (o <= moment < c if o < c else moment >= o)), None)
    current = current or (late[0] if late else None)
    later = sorted(o for o, _ in spans if o > moment)
    upcoming = later[0] if later else None
    if current is None and upcoming is None and (next_day := _spans_of(schedule, tomorrow)):
        upcoming, opens_tomorrow = min(o for o, _ in next_day), True
    else:
        opens_tomorrow = False
    return {
        "source": "horario",
        "open": current is not None,
        "closes_at": _text(current[1]) if current else None,
        "opens_at": _text(upcoming) if current is None and upcoming else None,
        "opens_tomorrow": current is None and opens_tomorrow,
        "today": ", ".join(f"{_text(o)}–{_text(c)}" for o, c in spans) or None,
    }


def day_spans(schedule: list[dict], now: datetime) -> dict:
    """Los tramos publicados de hoy y de mañana (`{hoy, manana}`, cada uno `[[abre, cierra]]` en "HH:MM"), para
    programar un pedido dentro del horario. Un tramo que pasa la medianoche cierra a las "24:00" de su día (lo de
    después es del día siguiente). Sin horario, las dos listas van vacías."""

    def spans(day: str) -> list[list[str]]:
        return [[_text(o), "24:00" if c <= o else _text(c)] for o, c in _spans_of(schedule, day)] if schedule else []

    return {"hoy": spans(DAYS[now.weekday()]), "manana": spans(DAYS[(now.weekday() + 1) % 7])}


def store_hours(raw: dict | None) -> dict | None:
    """Cómo estaba la tienda al bajarla (`raw.is_open`), con la hora a la que abría si Rappi la publicó
    (`raw.next_schedule`). None si la descarga no lo dice."""
    if not isinstance(raw, dict) or not isinstance(raw.get("is_open"), bool):
        return None
    following = raw.get("next_schedule")
    if isinstance(following, dict):
        following = following.get("open_time") or following.get("start_time")
    opens = _clock(following) if not raw["is_open"] else None
    return {
        "source": "descarga",
        "open": raw["is_open"],
        "closes_at": None,
        "opens_at": _text(opens) if opens else None,
        "opens_tomorrow": False,
        "today": None,
    }


def closed_last(cards: list[dict]) -> list[dict]:
    """Los cerrados al final, sin cambiar el orden dentro de cada grupo (lo que no se sabe va con los abiertos)."""
    return sorted(cards, key=lambda card: (card.get("hours") or {}).get("open") is False)
