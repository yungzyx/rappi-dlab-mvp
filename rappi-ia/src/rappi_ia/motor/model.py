"""El modelo del motor multivertical como funciones puras: reciben pedidos y señales (`motor.data`) y devuelven lo que
se guarda en las tablas del motor. Sin acceso a la base.

Las fechas de calendario (meses, días de compra, ventanas de tendencias) son las de Santiago de Chile. Ningún concepto
sensible entra a compra cruzada, tendencias ni recompra; Farmacia y Licores solo suben por señales de la propia persona.
"""

import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

from rappi_ia.motor.combos import NONE_COMBO, OWN_SIGNALS_ONLY, combo_of_verticals, fine_of
from rappi_ia.motor.data import Order, Signal

TZ = ZoneInfo("America/Santiago")

# Afinidad: Σ peso × 0,5^(días/30) sobre las señales de los últimos 180 días.
AFFINITY_HALF_LIFE_DAYS = 30
AFFINITY_WINDOW_DAYS = 180
AFFINITY_WEIGHTS = {
    "order": 5.0,
    "cart_add": 1.5,
    "vertical_open": 1.0,
    "view_store": 1.0,
    "search": 0.5,
    "view_item": 0.3,
}
# Transiciones: suavizado de Laplace sobre los 8 verticales.
TRANSITION_ALPHA = 1.0
# Compra cruzada: B dentro de 14 días después de A, con al menos 10 personas y lift sobre 1,2.
CROSS_SELL_WINDOW_DAYS = 14
CROSS_SELL_MIN_USERS = 10
CROSS_SELL_MIN_LIFT = 1.2
# Tendencias: 4 semanas contra las 4 anteriores; el crecimiento divide por al menos 5 pedidos.
TREND_WINDOW_DAYS = 28
TREND_MIN_PREV = 5
TREND_TOP_PRODUCTS = 50
# Con las pocas personas del prototipo, un concepto o producto que pidió una sola no sale: la fila apuntaría a ella.
PROTOTYPE_MIN_USERS = 5
# Recompra: al menos 3 días de compra distintos e intervalos regulares.
REPLENISH_MIN_ORDERS = 3
REPLENISH_MAX_CV = 0.6

DEFAULT_ORDER = ("restaurantes", "turbo", "supermercado", "farmacia", "mall", "licores", "conveniencia", "chocolateria")
DEFAULT_WEIGHTS = {"afinidad": 1.0, "transicion": 0.3, "popularidad": 0.1}


def local_day(ts: datetime) -> date:
    return ts.astimezone(TZ).date()


def _month_of(ts: datetime) -> date:
    return local_day(ts).replace(day=1)


def _next_month(month: date) -> date:
    return date(month.year + month.month // 12, month.month % 12 + 1, 1)


# Afinidad


def affinity(signals: Iterable[Signal], now: datetime) -> dict[str, dict[str, float]]:
    """`persona → vertical → puntaje`: cada señal pesa su peso por 0,5 elevado a (días de antigüedad / 30). Las
    señales de más de 180 días o posteriores a `now` no cuentan; solo vuelven verticales con puntaje."""
    scores: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for s in signals:
        age = (now - s.ts).total_seconds() / 86400
        if age < 0 or age > AFFINITY_WINDOW_DAYS:
            continue
        scores[s.user_id][s.vertical] += AFFINITY_WEIGHTS[s.kind] * 0.5 ** (age / AFFINITY_HALF_LIFE_DAYS)
    return {user: dict(row) for user, row in scores.items()}  # todos los pesos son positivos: solo puntajes > 0


# Transiciones


def _by_user(orders: Iterable[Order]) -> dict[str, list[Order]]:
    out: dict[str, list[Order]] = defaultdict(list)
    for o in orders:
        out[o.user_id].append(o)
    for user_orders in out.values():
        user_orders.sort(key=lambda o: (o.ts, o.order_id))
    return out


def transition_counts(orders: Iterable[Order]) -> dict[str, Counter]:
    """`desde → hacia → veces`: pedidos consecutivos de la misma persona. Un carro repartido en dos verticales (dos
    pedidos con el mismo `cart_id`) no es transición."""
    counts: dict[str, Counter] = defaultdict(Counter)
    for user_orders in _by_user(orders).values():
        for a, b in pairwise(user_orders):
            if a.cart_id is not None and a.cart_id == b.cart_id:
                continue
            counts[a.vertical][b.vertical] += 1
    return dict(counts)


def transitions(orders: Iterable[Order]) -> dict[str, dict[str, float]]:
    """P(próximo vertical | último), con suavizado de Laplace sobre los 8 verticales; solo los verticales de partida
    que tienen algún paso."""
    k = len(DEFAULT_ORDER)
    out = {}
    for start, row in transition_counts(orders).items():
        total = sum(row.values())
        out[start] = {v: (row[v] + TRANSITION_ALPHA) / (total + k * TRANSITION_ALPHA) for v in DEFAULT_ORDER}
    return out


# Combinaciones


@dataclass(frozen=True)
class ComboMonth:
    user_id: str
    month: date
    combo: str
    orders: int
    spend: float
    retained: bool | None  # algún pedido en M+1; None si los datos no cubren M+1 completo


def combo_months(orders: Iterable[Order], fine: bool = False) -> list[ComboMonth]:
    """Una fila por persona y mes calendario con pedidos: la combinación usada, pedidos, gasto y si volvió a pedir el
    mes siguiente. La combinación es de grupos (`rest+turbo`); con `fine`, de verticales una por una
    (`restaurantes+turbo+mall`). Solo cuentan los verticales de los pedidos: los servicios no tienen pedidos."""
    orders = list(orders)
    if not orders:
        return []
    data_end = max(o.ts for o in orders)
    groups: dict[tuple[str, date], list[Order]] = defaultdict(list)
    for o in orders:
        groups[o.user_id, _month_of(o.ts)].append(o)
    out = []
    for (user, month), month_orders in sorted(groups.items()):
        following = _next_month(month)
        last_instant = datetime.combine(_next_month(following), datetime.min.time(), TZ) - timedelta(microseconds=1)
        retained = None if data_end < last_instant else (user, following) in groups
        out.append(
            ComboMonth(
                user_id=user,
                month=month,
                combo=(fine_of if fine else combo_of_verticals)(o.vertical for o in month_orders),
                orders=len(month_orders),
                spend=sum(o.total for o in month_orders),
                retained=retained,
            )
        )
    return out


def combo_stats(months: list[ComboMonth]) -> dict[str, dict]:
    """La tabla de Rappi medida con los datos propios, por combinación: personas-mes, % de personas-mes y de pedidos
    (0 a 100), pedidos y gasto por persona-mes, y retención M+1 sobre los meses con M+1 completo (`retention_n`)."""
    total_months = len(months)
    total_orders = sum(m.orders for m in months)
    by_combo: dict[str, list[ComboMonth]] = defaultdict(list)
    for m in months:
        by_combo[m.combo].append(m)
    out = {}
    for combo, rows in by_combo.items():
        n, orders = len(rows), sum(m.orders for m in rows)
        known = [m.retained for m in rows if m.retained is not None]
        out[combo] = {
            "user_months": n,
            "pct_users": 100 * n / total_months,
            "pct_orders": 100 * orders / total_orders if total_orders else 0.0,
            "orders_per_user": orders / n,
            "retention_m1": sum(known) / len(known) if known else None,
            "retention_n": len(known),
            "spend_per_user": sum(m.spend for m in rows) / n,
        }
    return out


def combo_steps(months: list[ComboMonth]) -> dict[tuple[str, str], tuple[int, float]]:
    """`(combinación en M, combinación en M+1) → (personas-mes, probabilidad)`, sobre los meses con M+1 completo; quien
    no vuelve pasa a «ninguna»."""
    combo_at = {(m.user_id, m.month): m.combo for m in months}
    counts: dict[str, Counter] = defaultdict(Counter)
    for m in months:
        if m.retained is None:
            continue
        target = combo_at[m.user_id, _next_month(m.month)] if m.retained else NONE_COMBO
        counts[m.combo][target] += 1
    out = {}
    for start, row in counts.items():
        total = sum(row.values())
        for target, n in row.items():
            out[start, target] = (n, n / total)
    return out


# Compra cruzada


@dataclass(frozen=True)
class Rule:
    from_concept: str
    from_vertical: str
    to_concept: str
    to_vertical: str
    users_from: int
    users_both: int
    confidence: float
    lift: float


def order_concepts(order: Order, sensitive: frozenset[str], skip_suggested: bool = False) -> set[str]:
    return {
        line.concept_id
        for line in order.lines
        if line.concept_id is not None
        and line.concept_id not in sensitive
        and not (skip_suggested and line.from_suggestion)
    }


def cross_sell(orders: Iterable[Order], sensitive: frozenset[str]) -> list[Rule]:
    """Quien pide el concepto A en el vertical X y, dentro de los 14 días siguientes, el concepto B en otro vertical Y.
    Confianza = personas con los dos / personas con A en X; lift = confianza / fracción de las personas que piden B en
    Y. Las líneas de B que vienen de una sugerencia no cuentan; tampoco los conceptos sensibles. Solo reglas con al
    menos 10 personas y lift sobre 1,2."""
    window = timedelta(days=CROSS_SELL_WINDOW_DAYS)
    users_from: Counter = Counter()
    users_to: Counter = Counter()
    users_both: Counter = Counter()
    by_user = _by_user(orders)
    for user_orders in by_user.values():
        as_from = [order_concepts(o, sensitive) for o in user_orders]
        as_to = [order_concepts(o, sensitive, skip_suggested=True) for o in user_orders]
        froms, tos, both = set(), set(), set()
        for i, a in enumerate(user_orders):
            froms |= {(c, a.vertical) for c in as_from[i]}
            tos |= {(c, a.vertical) for c in as_to[i]}
            for j in range(i + 1, len(user_orders)):
                b = user_orders[j]
                if b.ts - a.ts > window:
                    break
                if b.ts == a.ts or b.vertical == a.vertical:
                    continue
                if a.cart_id is not None and a.cart_id == b.cart_id:  # un carro repartido en verticales: misma compra
                    continue
                both |= {(c, a.vertical, to, b.vertical) for c in as_from[i] for to in as_to[j]}
        users_from.update(froms)
        users_to.update(tos)
        users_both.update(both)
    population = len(by_user)
    rules = []
    for (a, x, b, y), n in users_both.items():
        if n < CROSS_SELL_MIN_USERS:
            continue
        confidence = n / users_from[a, x]
        lift = confidence / (users_to[b, y] / population)
        if lift > CROSS_SELL_MIN_LIFT:
            rules.append(Rule(a, x, b, y, users_from[a, x], n, confidence, lift))
    rules.sort(key=lambda r: (r.from_concept, -r.confidence, r.from_vertical, r.to_concept, r.to_vertical))
    return rules


# Tendencias


@dataclass(frozen=True)
class TrendRow:
    scope: str  # vertical, concepto o producto
    vertical: str
    item_key: str
    concept_id: str | None
    entity_type: str | None
    entity_id: str | None
    orders_now: int
    orders_prev: int
    users_now: int
    growth: float
    rank: int


def trends(orders: Iterable[Order], window_end: date, sensitive: frozenset[str], min_users: int = 0) -> list[TrendRow]:
    """Lo más pedido y lo que sube en las 4 semanas que terminan en `window_end` (incluido) contra las 4 anteriores:
    por vertical, por concepto (sin sensibles) y por producto (los 50 más pedidos de cada vertical, sin los de un
    concepto sensible). Pedidos y personas distintas; `growth` = (ahora − antes) / max(antes, 5); `rank` por pedidos
    recientes dentro de cada alcance y vertical. Lo que no tiene pedidos recientes no sale, y con `min_users` tampoco
    los conceptos y productos que pidieron menos personas (los verticales, que son agregados, siempre salen)."""
    now_start = window_end - timedelta(days=TREND_WINDOW_DAYS - 1)
    prev_start = now_start - timedelta(days=TREND_WINDOW_DAYS)
    # (alcance, vertical, clave) → {"now": pedidos, "prev": pedidos, "users": personas recientes}
    stats: dict[tuple[str, str, str], dict[str, set]] = defaultdict(
        lambda: {"now": set(), "prev": set(), "users": set()}
    )
    meta: dict[tuple[str, str, str], tuple[str | None, str | None, str | None]] = {}
    for o in orders:
        day = local_day(o.ts)
        if now_start <= day <= window_end:
            window = "now"
        elif prev_start <= day < now_start:
            window = "prev"
        else:
            continue
        keys = {("vertical", o.vertical, o.vertical): (None, None, None)}
        for line in o.lines:
            if line.concept_id in sensitive:
                continue
            if line.concept_id is not None:
                keys.setdefault(("concepto", o.vertical, line.concept_id), (line.concept_id, None, None))
            product = ("producto", o.vertical, f"{line.entity_type}:{line.entity_id}")
            keys.setdefault(product, (line.concept_id, line.entity_type, line.entity_id))
        for key, info in keys.items():
            stats[key][window].add(o.order_id)
            if window == "now":
                stats[key]["users"].add(o.user_id)
            if key not in meta or (
                meta[key][0] is None and info[0] is not None
            ):  # el concepto, si alguna línea lo trae
                meta[key] = info
    groups: dict[tuple[str, str], list[tuple[str, int, int, int]]] = defaultdict(list)
    for (scope, vertical, item), s in stats.items():
        if s["now"] and (scope == "vertical" or len(s["users"]) >= min_users):
            groups[scope, vertical].append((item, len(s["now"]), len(s["prev"]), len(s["users"])))
    out = []
    for (scope, vertical), items in sorted(groups.items()):
        items.sort(key=lambda t: (-t[1], -t[3], t[0]))
        if scope == "producto":
            items = items[:TREND_TOP_PRODUCTS]
        for rank, (item, now, prev, users) in enumerate(items, start=1):
            concept_id, entity_type, entity_id = meta[scope, vertical, item]
            growth = (now - prev) / max(prev, TREND_MIN_PREV)
            out.append(
                TrendRow(scope, vertical, item, concept_id, entity_type, entity_id, now, prev, users, growth, rank)
            )
    return out


# Recompra


@dataclass(frozen=True)
class Replenish:
    user_id: str
    concept_id: str
    vertical: str
    orders: int  # días de compra distintos
    interval_days: float  # mediana de los intervalos
    cv: float  # desviación / media de los intervalos
    last_ts: datetime
    due_on: date


def replenishment(orders: Iterable[Order], sensitive: frozenset[str]) -> list[Replenish]:
    """Por persona y concepto (sin sensibles), con al menos 3 días de compra distintos (dos pedidos el mismo día
    cuentan uno): intervalo mediano entre días, su coeficiente de variación (solo los regulares, ≤ 0,6) y el día en que
    le toca de nuevo. El vertical es donde más lo pide (empate: el más reciente)."""
    bought: dict[tuple[str, str], list[Order]] = defaultdict(list)
    for o in sorted(orders, key=lambda o: (o.ts, o.order_id)):
        for concept in order_concepts(o, sensitive):
            bought[o.user_id, concept].append(o)
    out = []
    for (user, concept), concept_orders in sorted(bought.items()):
        days = sorted({local_day(o.ts) for o in concept_orders})
        if len(days) < REPLENISH_MIN_ORDERS:
            continue
        intervals = [(b - a).days for a, b in pairwise(days)]
        mean = statistics.fmean(intervals)
        cv = statistics.pstdev(intervals) / mean if len(set(intervals)) > 1 else 0.0
        if cv > REPLENISH_MAX_CV:
            continue
        median = statistics.median(intervals)
        per_vertical = Counter(o.vertical for o in concept_orders)
        last_seen = {o.vertical: i for i, o in enumerate(concept_orders)}
        vertical = max(per_vertical, key=lambda v: (per_vertical[v], last_seen[v]))
        out.append(
            Replenish(
                user_id=user,
                concept_id=concept,
                vertical=vertical,
                orders=len(days),
                interval_days=float(median),
                cv=cv,
                last_ts=concept_orders[-1].ts,
                # `round` redondea al par (17,5 → 18, 14,5 → 14) a propósito: sin sesgo hacia arriba ni hacia abajo.
                due_on=days[-1] + timedelta(days=round(median)),
            )
        )
    return out


# Popularidad y ranking


def popularity(orders: Iterable[Order], now: datetime) -> dict[str, float]:
    """La cuota de pedidos de cada vertical en los 28 días que terminan en `now`."""
    start = now - timedelta(days=TREND_WINDOW_DAYS)
    counts = Counter(o.vertical for o in orders if start < o.ts <= now)
    total = sum(counts.values())
    return {v: n / total for v, n in counts.items()} if total else {}


def rank_verticals(
    aff: dict[str, float],
    last_vertical: str | None,
    trans: dict[str, dict[str, float]],
    pop: dict[str, float],
    weights: dict[str, float],
) -> list[tuple[str, float]]:
    """Los 8 verticales ordenados por a × afinidad (normalizada a suma 1) + b × P(v | último vertical) + c ×
    popularidad. Farmacia y Licores solo suben por la afinidad de la persona (b = c = 0 para ellos). Los empates siguen
    `DEFAULT_ORDER`."""
    total_aff = sum(aff.values())
    from_last = trans.get(last_vertical, {}) if last_vertical else {}
    scored = []
    for v in DEFAULT_ORDER:
        score = weights["afinidad"] * (aff.get(v, 0.0) / total_aff if total_aff else 0.0)
        if v not in OWN_SIGNALS_ONLY:
            score += weights["transicion"] * from_last.get(v, 0.0) + weights["popularidad"] * pop.get(v, 0.0)
        scored.append((v, score))
    return sorted(scored, key=lambda t: (-t[1], DEFAULT_ORDER.index(t[0])))
