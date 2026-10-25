"""Segmentos de usuario por comportamiento. Las reglas son datos (`concepts/segments.toml`): cada una combina piezas
genéricas y el motor no conoce segmentos por nombre.

Una señal (evento) calza una regla si cumple **alguna** pieza de contenido (concepto, grupo, atributo, marca, ocasión,
servicio, palabra de consulta; si la regla no tiene ninguna, basta el contexto) y **todas** las piezas de contexto
(vertical, hora, día, percentil de precio, descuento, tamaño del carro, modalidad, sugerencia, ciudad)."""

import logging
import re
import threading
import time
import tomllib
from collections import defaultdict
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import cache, lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
from psycopg import Connection
from psycopg.types.json import Jsonb
from rappi_scraper.storage.search import VERTICALS

from ..concepts.taxonomy import load_taxonomy
from .attributes import load_attribute_rules, phrase_key
from .runs import finish_layer_run, rules_version, start_layer_run

log = logging.getLogger(__name__)

RULES_FILE = Path(__file__).resolve().parents[1] / "concepts" / "segments.toml"
LOCAL_TZ = ZoneInfo("America/Santiago")  # las horas y los días de una regla son los de la persona
SIGNAL_EVENT_TYPES = ("search", "chat", "ask", "view_item", "cart_add", "service_shown", "service_opened")
MIN_CARTS_FOR_ABANDONMENT = 3
MIN_SUGGESTIONS_SHOWN = 5
MIN_BRANDED_LINES = 5
CONTENT_PIECES = ("concepts", "groups", "attributes", "brands", "occasions", "services", "query_words")
CONTEXT_PIECES = (
    *("verticals", "hours", "weekdays", "days_of_month", "price_percentile", "discount"),
    *("basket_size", "modality", "from_suggestion", "cities"),
)
EVENT_TYPES = frozenset(
    {
        *("app_open", "search", "chat", "ask", "view_store", "view_item", "cart_add", "cart_remove", "checkout_start"),
        *("order_placed", "suggestion_shown", "suggestion_accepted", "suggestion_dismissed", "recommendation_click"),
        *("service_shown", "service_opened", "order_line"),
    }
)
# Métricas por persona calculadas aparte (`user_metrics`): lo que no es una suma de eventos que calzan.
METRICS = frozenset(
    {
        *("dias_sin_pedido", "dias_desde_alta", "verticales_distintas", "tasa_abandono", "aceptacion_sugerencias"),
        *("pedidos_90d", "gasto_90d_percentil", "reactivado", "concentracion_marca", "conceptos_distintos_90d"),
        "ticket_creciente",
    }
)
FAMILIES = (
    *("dieta", "comida", "dulces", "bebidas", "hogar", "cuidado", "intereses"),
    *("momentos", "valor", "relacion", "servicios", "geografia"),
)
LEVELS = ("bajo", "medio", "alto")
MODALITIES = frozenset({"texto", "voz", "foto"})
# Se nombran por lo que la persona compra, nunca por la condición que se les supone; las vistas `capa` no exponen
# sus filas por usuario y sus agregados exigen k ≥ 5.
SENSITIVE_SEGMENTS = frozenset(
    {
        *("compra-sin-gluten", "compra-sin-lactosa", "compra-sin-azucar", "bajo-sodio", "alergia-frutos-secos"),
        *("mama-papa-bebe", "embarazo", "adulto-mayor", "salud-sexual", "farmacia-frecuente", "cuidado-cronico"),
        *("tabaco", "vapeo", "higiene-bebe"),  # `higiene-bebe` mira lo mismo que `mama-papa-bebe`
    }
)
_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_LIST_PIECES = ("concepts", "groups", "attributes", "brands", "occasions", "services", "query_words", "verticals")
_LIST_PIECES += ("modality", "cities")
_BASKET_KEYS = {"gte_items", "lte_items", "gte_amount"}


@dataclass(frozen=True)
class SegmentRule:
    id: str
    name: str
    family: str
    sensitive: bool
    description: str
    signals: dict
    events: dict[str, float]
    window_days: int
    half_life_days: float
    min_signals: int
    levels: dict[str, float]
    exclude: dict = field(default_factory=dict)
    metric: dict | None = None
    min_share: float = 0.0  # parte mínima de la actividad de la persona (en los tipos de evento de la regla) que calza


def load_segment_rules(path: Path | None = None) -> tuple[str, list[SegmentRule]]:
    """Las reglas leídas y validadas. Quedan en caché por ruta, fecha y tamaño del archivo (leerlas y validarlas
    toma ~0,7 s, y cada pedido recalcula los segmentos de su persona): si el archivo cambia, se vuelven a leer. La
    lista es compartida: no se modifica."""
    path = path or RULES_FILE
    stat = path.stat()
    return _load_segment_rules(path, stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=8)
def _load_segment_rules(path: Path, _mtime_ns: int, _size: int) -> tuple[str, list[SegmentRule]]:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    defaults = raw.get("defaults", {})
    rules, seen = [], set()
    for entry in raw["segment"]:
        merged = {**defaults, **entry}
        rule = _build(merged)
        if rule.id in seen:
            raise ValueError(f"Segmento {rule.id}: id repetido")
        seen.add(rule.id)
        rules.append(rule)
    return raw["version"], rules


def _build(entry: dict) -> SegmentRule:
    seg = entry.get("id", "?")

    def fail(message: str):
        raise ValueError(f"Segmento {seg}: {message}")

    for key in ("id", "name", "family", "description", "window_days", "half_life_days", "min_signals", "levels"):
        if key not in entry:
            fail(f"falta `{key}`")
    if not _SLUG.match(seg):
        fail("el id debe ser un slug (minúsculas, números y guiones)")
    if entry["family"] not in FAMILIES:
        fail(f"familia desconocida `{entry['family']}`")
    signals, exclude, metric = entry.get("signals", {}), entry.get("exclude", {}), entry.get("metric")
    if bool(signals) == bool(metric):
        fail("debe tener `signals` o `metric`, y solo uno")
    _check_pieces(signals, fail, "signals")
    _check_pieces(exclude, fail, "exclude")
    events = {k: float(v) for k, v in entry.get("events", {}).items()}
    if signals and not events:
        fail("una regla con `signals` necesita `events`")
    if unknown := set(events) - EVENT_TYPES:
        fail(f"eventos desconocidos {sorted(unknown)}")
    if any(w <= 0 for w in events.values()):
        fail("el peso de un evento debe ser positivo")
    if metric is not None:
        _check_metric(metric, fail)
    min_share = float(entry.get("min_share", 0.0))
    if not 0 <= min_share <= 1:
        fail("`min_share` debe estar entre 0 y 1")
    levels = entry["levels"]
    values = [levels.get(level) for level in LEVELS]
    if list(levels) != list(LEVELS) or None in values:
        fail(f"`levels` debe traer {', '.join(LEVELS)} en ese orden")
    lower = bool(metric) and metric.get("stronger") == "lower"
    if min(values) <= 0 or values != sorted(set(values), reverse=lower):
        fail("`levels` debe ser positivo y estrictamente " + ("decrecientes" if lower else "creciente"))
    if int(entry["min_signals"]) < 1 or int(entry["window_days"]) < 1 or float(entry["half_life_days"]) <= 0:
        fail("min_signals y window_days deben ser ≥ 1 y half_life_days > 0")
    return SegmentRule(
        id=seg,
        name=entry["name"],
        family=entry["family"],
        sensitive=bool(entry.get("sensitive", False)),
        description=entry["description"],
        signals=signals,
        events=events,
        window_days=int(entry["window_days"]),
        half_life_days=float(entry["half_life_days"]),
        min_signals=int(entry["min_signals"]),
        levels={level: float(levels[level]) for level in LEVELS},
        exclude=exclude,
        metric=metric,
        min_share=min_share,
    )


def _check_pieces(pieces: dict, fail, where: str) -> None:
    taxonomy = load_taxonomy()
    attributes = {a.attribute_id for a in load_attribute_rules()[1]}
    if unknown := set(pieces) - {*CONTENT_PIECES, *CONTEXT_PIECES}:
        fail(f"`{where}` con piezas desconocidas {sorted(unknown)}")
    for key in _LIST_PIECES:
        if key in pieces and (not isinstance(pieces[key], list) or not pieces[key]):
            fail(f"`{where}.{key}` debe ser una lista no vacía")
    known = {
        "concepts": set(taxonomy.concepts),
        "groups": set(taxonomy.groups),
        "attributes": attributes,
        "occasions": set(taxonomy.occasions),
        "services": set(taxonomy.services),
        "verticals": set(VERTICALS),
        "modality": MODALITIES,
    }
    for key, valid in known.items():
        if missing := [v for v in pieces.get(key, ()) if v not in valid]:
            fail(f"`{where}.{key}` nombra algo que no existe: {missing}")
    if "hours" in pieces:
        hours = pieces["hours"]
        if not (
            isinstance(hours, list) and len(hours) == 2 and all(isinstance(h, int) and 0 <= h <= 23 for h in hours)
        ):
            fail(f"`{where}.hours` debe ser [desde, hasta] con horas de 0 a 23")
    for key, low, high in (("weekdays", 1, 7), ("days_of_month", 1, 31)):
        if key in pieces and not (
            isinstance(pieces[key], list)
            and pieces[key]
            and all(isinstance(d, int) and low <= d <= high for d in pieces[key])
        ):
            fail(f"`{where}.{key}` debe ser una lista de enteros entre {low} y {high}")
    if "price_percentile" in pieces:
        pp = pieces["price_percentile"]
        if not (isinstance(pp, dict) and pp and set(pp) <= {"gte", "lte"} and all(0 <= v <= 1 for v in pp.values())):
            fail(f"`{where}.price_percentile` debe ser {{ gte|lte = 0..1 }}")
    if "basket_size" in pieces:
        bs = pieces["basket_size"]
        if not (isinstance(bs, dict) and bs and set(bs) <= _BASKET_KEYS and all(v > 0 for v in bs.values())):
            fail(f"`{where}.basket_size` debe usar {sorted(_BASKET_KEYS)} con valores positivos")
    for key in ("discount", "from_suggestion"):
        if key in pieces and not isinstance(pieces[key], bool):
            fail(f"`{where}.{key}` debe ser true o false")


def _check_metric(metric: dict, fail) -> None:
    if metric.get("name") not in METRICS:
        fail(f"métrica desconocida `{metric.get('name')}`")
    if not ({"min", "max"} & set(metric)) or set(metric) - {"name", "min", "max", "stronger"}:
        fail("`metric` es { name, min?, max?, stronger? } con al menos un límite")
    if metric.get("stronger", "higher") not in ("higher", "lower"):
        fail("`metric.stronger` es `higher` (por defecto) o `lower`")
    if "min" in metric and "max" in metric and metric["min"] >= metric["max"]:
        fail("`metric.min` debe ser menor que `metric.max`")


@dataclass(frozen=True)
class Signal:
    """Un evento de una persona con lo que se sabe de su ítem: lo único que el motor mira."""

    ts: datetime
    type: str  # tipo de app_events o `order_line`
    concept: str | None
    group: str | None
    attributes: frozenset[str]
    vertical: str | None
    brand: str | None
    query: str | None
    modality: str | None
    price_percentile: float | None  # posición del precio entre los ítems de su concepto (0 a 1)
    discounted: bool
    basket_items: int | None
    basket_total: float | None
    from_suggestion: bool
    event_key: str  # identifica el evento: dos filas con la misma clave cuentan una sola vez
    city: str | None = None
    service: str | None = None
    unit_key: str | None = None  # la ocasión (sesión o pedido): `min_signals` cuenta ocasiones, no eventos


@dataclass(frozen=True)
class Membership:
    segment_id: str
    score: float
    level: str
    signals: int
    evidence: dict
    first_seen: datetime | None
    last_signal: datetime | None


def score_user(
    signals: list[Signal], metrics: dict[str, float], rules: list[SegmentRule], now: datetime
) -> list[Membership]:
    """Los segmentos de una persona. Puntaje = Σ peso(evento) × 0,5^(edad / vida media) sobre las señales de la
    ventana que calzan la regla y ninguna exclusión; sin `min_signals` señales distintas o bajo el primer umbral no
    hay segmento. Una regla con `metric` ignora los eventos: el valor de la métrica, en [min, max), decide."""
    found = []
    for rule in rules:
        member = _by_metric(rule, metrics) if rule.metric else _by_signals(rule, signals, now)
        if member:
            found.append(member)
    return found


def _lower_is_stronger(rule: SegmentRule) -> bool:
    return bool(rule.metric) and rule.metric.get("stronger") == "lower"


def _level(rule: SegmentRule, score: float) -> str | None:
    if _lower_is_stronger(rule):  # «nuevo», «activo», «gasto-bajo»: menos días o menos gasto es más fuerte
        reached = [level for level in LEVELS if score <= rule.levels[level]]
    else:
        reached = [level for level in LEVELS if score >= rule.levels[level]]
    return reached[-1] if reached else None


def _by_metric(rule: SegmentRule, metrics: dict[str, float]) -> Membership | None:
    value = metrics.get(rule.metric["name"])
    if value is None or value < rule.metric.get("min", float("-inf")) or value >= rule.metric.get("max", float("inf")):
        return None
    return Membership(
        rule.id, value, _level(rule, value) or LEVELS[0], 0, {"metric": rule.metric["name"], "value": value}, None, None
    )


def _by_signals(rule: SegmentRule, signals: list[Signal], now: datetime) -> Membership | None:
    window = rule.window_days * 86400
    taxonomy = load_taxonomy()
    counted: dict[str, tuple[Signal, float]] = {}
    seen: set[str] = set()
    activity = 0.0  # peso de todo lo que hizo la persona en los tipos que cuenta la regla, calce o no
    for signal in signals:
        age = max(0.0, (now - signal.ts).total_seconds())
        weight = rule.events.get(signal.type)
        if weight is None or age > window or signal.event_key in seen:
            continue
        seen.add(signal.event_key)
        points = weight * 0.5 ** (age / 86400 / rule.half_life_days)
        activity += points
        if _matches(signal, rule.signals, taxonomy) and not (rule.exclude and _matches(signal, rule.exclude, taxonomy)):
            counted[signal.event_key] = (signal, points)
    occasions = {signal.unit_key or signal.event_key for signal, _points in counted.values()}
    if len(occasions) < rule.min_signals:
        return None
    score = sum(points for _signal, points in counted.values())
    level = _level(rule, score)
    if level is None or (rule.min_share and score < rule.min_share * activity):
        return None
    seen_at = [signal.ts for signal, _points in counted.values()]
    evidence = _evidence(rule, counted.values())
    evidence["share"] = round(score / activity, 3)
    return Membership(rule.id, score, level, len(occasions), evidence, min(seen_at), max(seen_at))


@cache
def _sensitive_names() -> tuple[frozenset[str], frozenset[str]]:
    """(conceptos, atributos) que mira algún segmento sensible o que la taxonomía marca como sensibles."""
    taxonomy = load_taxonomy()
    concepts = {c.id for c in taxonomy.concepts.values() if c.sensitive}
    attributes: set[str] = set()
    for rule in load_segment_rules()[1]:
        if rule.sensitive:
            concepts |= set(rule.signals.get("concepts", ()))
            attributes |= set(rule.signals.get("attributes", ()))
            for group in rule.signals.get("groups", ()):
                concepts |= {c.id for c in taxonomy.concepts.values() if c.parent == group}
    return frozenset(concepts), frozenset(attributes)


def _evidence(rule: SegmentRule, counted) -> dict:
    """Los 3 conceptos o atributos que más aportan al puntaje. La evidencia de un segmento común no nombra lo que mira
    un segmento sensible: `capa.user_segments` oculta los sensibles, y «cazaofertas» listaba los pañales comprados."""
    hidden_concepts, hidden_attributes = ((), ()) if rule.sensitive else _sensitive_names()
    by_item: dict[tuple[str, str], float] = defaultdict(float)
    named = set(rule.signals.get("attributes", ()))
    for signal, points in counted:
        if signal.concept and signal.concept not in hidden_concepts:
            by_item[("concepto", signal.concept)] += points
        for attribute in (signal.attributes & named) - set(hidden_attributes):
            by_item[("atributo", attribute)] += points
    top = sorted(by_item.items(), key=lambda item: (-item[1], item[0]))[:3]
    return {"top": [{"kind": kind, "id": ident, "score": round(points, 3)} for (kind, ident), points in top]}


def _matches(signal: Signal, pieces: dict, taxonomy) -> bool:
    """Alguna pieza de contenido (si la regla trae) y todas las de contexto."""
    content = [key for key in CONTENT_PIECES if key in pieces]
    if content and not any(_content_hit(signal, key, pieces[key], taxonomy) for key in content):
        return False
    return all(_context_hit(signal, key, pieces[key]) for key in CONTEXT_PIECES if key in pieces)


def _content_hit(signal: Signal, key: str, wanted: list[str], taxonomy) -> bool:
    if key == "concepts":
        return signal.concept in wanted
    if key == "groups":
        return signal.group in wanted
    if key == "attributes":
        return bool(signal.attributes & set(wanted))
    if key == "brands":
        return signal.brand in wanted
    if key == "services":
        return signal.service in wanted
    if key == "occasions":
        return any(signal.concept in taxonomy.occasions[o].concepts for o in wanted)
    return signal.query is not None and any(_has_phrase(signal.query, phrase) for phrase in wanted)


def _has_phrase(text: str, phrase: str) -> bool:
    words, target = _words(text), _words(phrase)
    return any(words[i : i + len(target)] == target for i in range(len(words) - len(target) + 1))


@lru_cache(maxsize=20_000)
def _words(text: str) -> tuple[str, ...]:
    """Las palabras normalizadas y sin plural de una consulta o de una frase de regla (`phrase_key`), con memoria: una
    corrida compara cada consulta con cada frase de cada regla (millones de veces los mismos textos) y normalizarlos
    era el 94 % de su tiempo."""
    return phrase_key(text)


def _context_hit(signal: Signal, key: str, wanted) -> bool:
    if key == "verticals":
        return signal.vertical in wanted
    if key == "cities":
        return signal.city in wanted
    if key == "modality":
        return signal.modality in wanted
    if key == "hours":
        start, end = wanted
        hour = signal.ts.hour
        return start <= hour <= end if start <= end else hour >= start or hour <= end
    if key == "weekdays":
        return signal.ts.isoweekday() in wanted
    if key == "days_of_month":
        return signal.ts.day in wanted
    if key == "discount":
        return signal.discounted == wanted
    if key == "from_suggestion":
        return signal.from_suggestion == wanted
    if key == "price_percentile":
        value = signal.price_percentile
        return value is not None and value >= wanted.get("gte", 0) and value <= wanted.get("lte", 1)
    items, total = signal.basket_items, signal.basket_total  # basket_size
    return (
        ("gte_items" not in wanted or (items is not None and items >= wanted["gte_items"]))
        and ("lte_items" not in wanted or (items is not None and items <= wanted["lte_items"]))
        and ("gte_amount" not in wanted or (total is not None and total >= wanted["gte_amount"]))
    )


# ── cálculo en la base ──

_SIGNALS_SQL = """
WITH raw AS (
    -- Solo lo que dice un concepto: «Rappi hoy» le quita el concepto al evento (y marca payload.mode = 'actual') y
    -- sus pedidos van con mode = 'actual', y «Olvidar» un concepto se lo quita a las líneas de pedido; sin concepto no
    -- hay huella de gusto.
    SELECT e.user_id, 'e' || e.event_id AS event_key, e.session_id AS unit_key, e.ts, e.type, e.concept_id,
           e.vertical, e.query, e.modality, e.entity_type, e.entity_id,
           coalesce(e.payload ->> 'from_suggestion', '') = 'true' AS from_suggestion,
           e.payload ->> 'servicio' AS service, NULL::bigint AS basket_items, NULL::numeric AS basket_total
    FROM app_events e
    WHERE e.source = %(source)s AND e.type = ANY(%(types)s) AND (%(user)s::text IS NULL OR e.user_id = %(user)s)
      AND coalesce(e.payload ->> 'mode', '') <> 'actual'
      AND (e.concept_id IS NOT NULL OR e.payload ? 'servicio')
    UNION ALL
    SELECT o.user_id, 'l' || o.order_id || ':' || l.line_no, coalesce(o.session_id, o.order_id), o.ts, 'order_line',
           l.concept_id, o.vertical, NULL, NULL, l.entity_type, l.entity_id, l.from_suggestion, NULL,
           sum(l.qty) OVER (PARTITION BY l.order_id), o.total
    FROM app_order_lines l JOIN app_orders o USING (order_id)
    WHERE o.source = %(source)s AND o.mode = 'propuesta' AND l.concept_id IS NOT NULL
      AND (%(user)s::text IS NULL OR o.user_id = %(user)s)
),
needed AS (SELECT DISTINCT concept_id FROM raw WHERE concept_id IS NOT NULL),
ranked AS (  -- posición del precio entre los ítems de su concepto en esa vertical (un ítem puede estar en varias)
    SELECT sd.vertical, sd.entity_type, sd.entity_id,
           percent_rank() OVER (PARTITION BY ic.concept_id, sd.vertical ORDER BY sd.price_min) AS pct
    FROM search_documents sd
    JOIN item_concepts ic ON ic.entity_type = sd.entity_type AND ic.entity_id = sd.entity_id
    WHERE sd.price_min IS NOT NULL AND ic.concept_id IN (SELECT concept_id FROM needed)
)
SELECT r.user_id, u.city, r.event_key, r.ts, r.type, r.concept_id, c.parent_id, r.vertical, r.query, r.modality,
       r.from_suggestion, r.service, r.basket_items, r.basket_total, ib.brand_key, rk.pct,
       coalesce((SELECT array_agg(ia.attribute_id) FROM item_attributes ia
                 WHERE ia.entity_type = r.entity_type AND ia.entity_id = r.entity_id), '{}') AS attributes,
       r.unit_key
FROM raw r
JOIN app_users u ON u.user_id = r.user_id
LEFT JOIN concepts c ON c.concept_id = r.concept_id
LEFT JOIN item_brands ib ON ib.entity_type = r.entity_type AND ib.entity_id = r.entity_id
LEFT JOIN ranked rk ON rk.vertical = r.vertical AND rk.entity_type = r.entity_type AND rk.entity_id = r.entity_id
"""


def load_signals(conn: Connection, source: str, user_id: str | None = None) -> dict[str, list[Signal]]:
    """Los eventos de cada persona de esa fuente (nunca mezcla fuentes) como señales: búsquedas, consultas, vistas,
    carros, servicios y líneas de pedido, con el concepto, los atributos y la marca de su ítem y la posición de su
    precio entre los ítems de su concepto. «Con descuento» es el descuento que el ítem tiene ahora."""
    rows = conn.execute(_SIGNALS_SQL, {"source": source, "user": user_id, "types": list(SIGNAL_EVENT_TYPES)})
    signals: dict[str, list[Signal]] = defaultdict(list)
    for row in rows:
        user, city, key, ts, kind, concept, group, vertical, query, modality = row[:10]
        suggested, service, items, total, brand, pct, attributes, unit = row[10:]
        signals[user].append(
            Signal(
                ts=ts.astimezone(LOCAL_TZ),
                type=kind,
                concept=concept,
                group=group,
                attributes=frozenset(attributes),
                vertical=vertical,
                brand=brand,
                query=query,
                modality=modality,
                price_percentile=pct,
                discounted="con-descuento" in attributes,
                basket_items=int(items) if items is not None else None,
                basket_total=float(total) if total is not None else None,
                from_suggestion=suggested,
                event_key=key,
                city=city,
                service=service,
                unit_key=unit,
            )
        )
    return dict(signals)


# `{only}` es el filtro por persona (vacío para toda la fuente): va dentro de cada consulta, donde se leen sus filas.
_ORDERS_90 = "FROM app_orders o WHERE o.source = %(source)s AND o.ts >= %(now)s - interval '90 days'{only}"
_METRIC_SQL = {
    "dias_sin_pedido": """SELECT user_id, extract(epoch FROM %(now)s - max(ts)) / 86400 FROM app_orders
                          WHERE source = %(source)s{only} GROUP BY 1""",
    "dias_desde_alta": """SELECT u.user_id,
                                 greatest(0, extract(epoch FROM %(now)s - least(u.created_at, min(e.ts))) / 86400)
                          FROM app_users u JOIN app_events e ON e.user_id = u.user_id
                          WHERE u.source = %(source)s{only_u} GROUP BY u.user_id, u.created_at""",
    "verticales_distintas": f"SELECT o.user_id, count(DISTINCT o.vertical) {_ORDERS_90} GROUP BY 1",
    "pedidos_90d": f"SELECT o.user_id, count(*) {_ORDERS_90} GROUP BY 1",
    "tasa_abandono": """SELECT s.user_id, 1 - count(o.cart_id)::float / count(*)
                        FROM (SELECT DISTINCT user_id, cart_id FROM app_events
                              WHERE source = %(source)s AND type = 'cart_add' AND cart_id IS NOT NULL
                                AND ts >= %(now)s - interval '90 days'{only}) s
                        LEFT JOIN app_orders o ON o.user_id = s.user_id AND o.cart_id = s.cart_id
                        GROUP BY 1 HAVING count(*) >= %(min_carts)s""",
    "aceptacion_sugerencias": """SELECT user_id, count(*) FILTER (WHERE type = 'suggestion_accepted')::float
                                        / count(*) FILTER (WHERE type = 'suggestion_shown')
                                 FROM app_events
                                 WHERE source = %(source)s AND ts >= %(now)s - interval '90 days'{only}
                                 GROUP BY 1
                                 HAVING count(*) FILTER (WHERE type = 'suggestion_shown') >= %(min_shown)s""",
    # Dos pedidos con la misma hora se ordenan por order_id: sin eso, cuál es el último dependía del plan.
    "reactivado": """SELECT user_id, CASE WHEN ts >= %(now)s - interval '30 days' AND gap >= interval '60 days'
                                          THEN 1 ELSE 0 END
                     FROM (SELECT user_id, ts, ts - lag(ts) OVER w AS gap,
                                  row_number() OVER (PARTITION BY user_id ORDER BY ts DESC, order_id DESC) AS rn
                           FROM app_orders WHERE source = %(source)s AND ts <= %(now)s{only}
                           WINDOW w AS (PARTITION BY user_id ORDER BY ts, order_id)) t
                     WHERE rn = 1 AND gap IS NOT NULL""",
    "concentracion_marca": """SELECT user_id, max(n)::float / sum(n) FROM (
                                 SELECT o.user_id, ib.brand_key, sum(l.qty) AS n
                                 FROM app_order_lines l JOIN app_orders o USING (order_id)
                                 JOIN item_brands ib ON ib.entity_type = l.entity_type AND ib.entity_id = l.entity_id
                                 WHERE o.source = %(source)s AND o.mode = 'propuesta'
                                   AND o.ts >= %(now)s - interval '90 days'{only}
                                 GROUP BY 1, 2) t
                              GROUP BY 1 HAVING sum(n) >= %(min_lines)s""",
    "conceptos_distintos_90d": """SELECT user_id, count(DISTINCT concept_id) FROM (
                                     SELECT o.user_id, l.concept_id
                                     FROM app_order_lines l JOIN app_orders o USING (order_id)
                                     WHERE o.source = %(source)s AND o.ts >= %(now)s - interval '90 days'{only}
                                     UNION ALL
                                     SELECT user_id, concept_id FROM app_events
                                     WHERE source = %(source)s AND type IN ('view_item', 'cart_add', 'search')
                                       AND ts >= %(now)s - interval '90 days'{only}) t
                                  WHERE concept_id IS NOT NULL GROUP BY 1""",
    "ticket_creciente": """SELECT user_id, avg(total) FILTER (WHERE ts >= %(now)s - interval '45 days')
                                         / avg(total) FILTER (WHERE ts < %(now)s - interval '45 days')
                           FROM app_orders
                           WHERE source = %(source)s AND ts >= %(now)s - interval '90 days'{only}
                           GROUP BY 1 HAVING count(*) FILTER (WHERE ts >= %(now)s - interval '45 days') >= 2
                                         AND count(*) FILTER (WHERE ts < %(now)s - interval '45 days') >= 2""",
}
# El gasto de 90 días de cada persona; su percentil se mide contra toda la fuente.
_SPEND_90 = f"SELECT o.user_id, sum(o.total) AS spent {_ORDERS_90} GROUP BY 1"
_SPEND_PERCENTILE = f"SELECT user_id, percent_rank() OVER (ORDER BY spent) FROM ({_SPEND_90}) t"
# El gasto de toda la fuente para el percentil de una persona, leído una vez al día: fuente → (día, gasto por persona).
_SOURCE_SPEND: dict[str, tuple[date, dict[str, Decimal]]] = {}
_SOURCE_SPEND_LOCK = threading.Lock()


def user_metrics(
    conn: Connection, source: str, user_id: str | None = None, now: datetime | None = None
) -> dict[str, dict[str, float]]:
    """Métricas por persona que no son una suma de eventos que calzan (días sin pedido, verticales distintas, tasa de
    abandono…). Sin datos suficientes la métrica falta, y sin la métrica no hay segmento. Con `user_id`, cada consulta
    lee solo las filas de esa persona; el percentil de gasto la compara con el gasto de toda la fuente, que se lee una
    vez al día (`_spend_percentile`)."""
    params = {
        "user": user_id,
        "source": source,
        "now": now or datetime.now(LOCAL_TZ),
        "min_carts": MIN_CARTS_FOR_ABANDONMENT,
        "min_shown": MIN_SUGGESTIONS_SHOWN,
        "min_lines": MIN_BRANDED_LINES,
    }
    only = {"only": "", "only_u": ""}
    if user_id is not None:
        only = {"only": " AND user_id = %(user)s", "only_u": " AND u.user_id = %(user)s"}
    metrics: dict[str, dict[str, float]] = defaultdict(dict)
    for name, sql in _METRIC_SQL.items():
        for user, value in conn.execute(sql.format(**only), params).fetchall():
            if value is not None:
                metrics[user][name] = float(value)
    if user_id is None:
        percentiles = conn.execute(_SPEND_PERCENTILE.format(only=""), params).fetchall()
    else:
        percentiles = _spend_percentile(conn, params)
    for user, value in percentiles:
        metrics[user]["gasto_90d_percentil"] = float(value)
    return dict(metrics)


def _spend_percentile(conn: Connection, params: dict) -> list[tuple[str, float]]:
    """El percentil de gasto de una persona (`percent_rank`, como para toda la fuente): su gasto se lee siempre; el de
    las demás, una vez al día por fuente. Sin pedidos en 90 días no tiene."""
    mine = conn.execute(_SPEND_90.format(only=" AND o.user_id = %(user)s"), params).fetchone()
    if mine is None:
        return []
    user, spent = mine
    source, day = params["source"], params["now"].astimezone(LOCAL_TZ).date()
    with _SOURCE_SPEND_LOCK:
        known = _SOURCE_SPEND.get(source)
    if known is None or known[0] != day:
        known = (day, dict(conn.execute(_SPEND_90.format(only=""), params).fetchall()))
        with _SOURCE_SPEND_LOCK:
            _SOURCE_SPEND[source] = known
    others = [value for other, value in known[1].items() if other != user]
    below = sum(1 for value in others if value < spent)
    return [(user, below / len(others) if others else 0.0)]


def forget_source_spend() -> None:
    """Olvida el gasto por fuente guardado para el percentil (los tests: cada uno recrea la base)."""
    with _SOURCE_SPEND_LOCK:
        _SOURCE_SPEND.clear()


def _monday(now: datetime):
    local = now.astimezone(LOCAL_TZ).date()
    return local - timedelta(days=local.weekday())


def build_segments(
    conn: Connection,
    source: str = "synthetic",
    user_id: str | None = None,
    now: datetime | None = None,
    commit: bool = True,
) -> dict:
    """Recalcula los segmentos de las personas de una fuente (o de una sola) y guarda la foto de la semana. Reemplaza
    las filas `regla` de ese alcance; lo `curado` no se toca y las otras fuentes tampoco. Solo la corrida de toda la
    fuente queda en `layer_runs`: la de una persona corre después de cada pedido y sumaba una fila por pedido (sus
    filas quedan sin `run_id`)."""
    now = now or datetime.now(LOCAL_TZ)
    version, rules = load_segment_rules()
    version = rules_version(version, RULES_FILE, Path(__file__))
    run = start_layer_run(conn, "segments", version) if user_id is None else None
    if user_id is None or not _definitions_current(conn, version, rules):
        _seed_definitions(conn, version, rules)
    signals = load_signals(conn, source, user_id)
    metrics = user_metrics(conn, source, user_id, now)
    users = sorted(set(signals) | set(metrics))
    found = {user: score_user(signals.get(user, []), metrics.get(user, {}), rules, now) for user in users}
    scope = "AND u.user_id = %(user)s" if user_id else ""
    params = {"source": source, "user": user_id, "week": _monday(now)}
    conn.execute(
        f"""DELETE FROM user_segments s USING app_users u
            WHERE s.user_id = u.user_id AND u.source = %(source)s AND s.source = 'regla' {scope}""",
        params,
    )
    conn.execute(
        f"""DELETE FROM user_segment_history h USING app_users u
            WHERE h.user_id = u.user_id AND u.source = %(source)s AND h.week = %(week)s {scope}""",
        params,
    )
    rows = [(user, m) for user, memberships in found.items() for m in memberships]
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO user_segments (user_id, segment_id, score, level, signals, evidence, first_seen,
                                          last_signal, source, run_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'regla', %s)
               ON CONFLICT (user_id, segment_id) DO NOTHING""",  # lo curado (misma clave) gana
            [(u, m.segment_id, m.score, m.level, m.signals, Jsonb(m.evidence), m.first_seen, m.last_signal, run)
             for u, m in rows],
        )  # fmt: skip
        cur.executemany(
            """INSERT INTO user_segment_history (week, user_id, segment_id, score, level)
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT (week, user_id, segment_id) DO NOTHING""",
            [(params["week"], u, m.segment_id, m.score, m.level) for u, m in rows],
        )
    counts = {
        "usuarios": len(users),
        "con_segmento": sum(1 for memberships in found.values() if memberships),
        "filas": len(rows),
        "segmentos": len({m.segment_id for _u, m in rows}),
    }
    if run is not None:
        finish_layer_run(conn, run, counts)
    if commit:
        conn.commit()
        conn.execute("ANALYZE user_segments")
    log.info("Segmentos (%s): %s", source, counts)
    return counts


def lock_user_segments(conn: Connection, user_id: str) -> None:
    """El candado por persona (advisory, hasta el fin de la transacción) que comparten el recálculo después de un
    pedido y «Olvidar»: nunca recalculan sus segmentos a la vez."""
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('segments:' || %s))", (user_id,))


def recalculate_user_segments(connector: Callable[[], AbstractContextManager[Connection]], user_id: str) -> None:
    """Los segmentos de una persona del prototipo después de un pedido, en segundo plano y con su propia conexión.

    Un candado por persona (advisory, de la transacción) pone en fila dos recálculos seguidos: el segundo espera al
    primero y ve todo lo guardado. Si la persona ya no está (la olvidaron antes de que esto corriera), no hace nada.
    Un error queda en el log y no llega a quien hizo el pedido, que ya tiene su respuesta."""
    start = time.perf_counter()
    try:
        with connector() as conn:
            lock_user_segments(conn, user_id)
            known = conn.execute(
                "SELECT 1 FROM app_users WHERE user_id = %s AND source = 'prototype'", (user_id,)
            ).fetchone()
            if known is None:
                conn.rollback()
                return
            build_segments(conn, "prototype", user_id, commit=False)
            conn.commit()  # suelta el candado; sin ANALYZE por pedido
    except psycopg.Error as exc:
        # El texto de Postgres puede traer la fila (`Key (user_id)=(…)`): solo la clase y el sqlstate, sin traza.
        log.warning(
            "No se pudieron recalcular los segmentos después de un pedido: %s (sqlstate %s)",
            type(exc).__name__,
            exc.sqlstate,
        )
        return
    except Exception:
        log.warning("No se pudieron recalcular los segmentos después de un pedido", exc_info=True)
        return
    log.info("Segmentos recalculados en %.0f ms", (time.perf_counter() - start) * 1000)  # sin el id de la persona


def _definitions_current(conn: Connection, version: str, rules: list[SegmentRule]) -> bool:
    """`segment_defs` tiene justo estas reglas, sembradas con esta versión (fecha y huella): el recálculo de una
    persona, que corre después de cada pedido, no las vuelve a escribir."""
    current, total = conn.execute(
        "SELECT count(*) FILTER (WHERE rules_version = %s AND segment_id = ANY(%s)), count(*) FROM segment_defs",
        (version, [r.id for r in rules]),
    ).fetchone()
    return current == total == len(rules)


def _seed_definitions(conn: Connection, version: str, rules: list[SegmentRule]) -> None:
    for r in rules:
        conn.execute(
            """INSERT INTO segment_defs (segment_id, name, family, sensitive, description, rule, rules_version)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (segment_id) DO UPDATE SET name = EXCLUDED.name, family = EXCLUDED.family,
                 sensitive = EXCLUDED.sensitive, description = EXCLUDED.description, rule = EXCLUDED.rule,
                 rules_version = EXCLUDED.rules_version""",
            (r.id, r.name, r.family, r.sensitive, r.description, Jsonb(asdict(r)), version),
        )
    conn.execute("DELETE FROM segment_defs WHERE segment_id <> ALL(%s)", ([r.id for r in rules],))
