"""La evaluación del motor por fechas: se calcula el modelo con lo anterior a un corte y se mide contra lo que cada
persona pidió después, frente a líneas base. Usa las mismas funciones de `model.py` que el motor, sin rehacerlas.

Tres tramos: entrenar (todo hasta 56 días antes del final), validar (28 días) y probar (los últimos 28). Los pesos del
próximo vertical se eligen en validación (a = 1; b y c en una grilla, por nDCG) y las cifras que se informan son las de
prueba. El paso de la escalera fina (`combos.next_fine_step`) se mide contra la vertical que más se suma en la
población. Sobre datos simulados esto prueba la mecánica del motor, no su efecto.
"""

import math
import statistics
from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import pairwise

from ..offers import winback
from ..offers.guards import offerable_vertical
from .combos import OWN_SIGNALS_ONLY, fine_of, next_fine_step
from .data import Order, Signal
from .model import (
    DEFAULT_ORDER,
    DEFAULT_WEIGHTS,
    REPLENISH_MAX_CV,
    REPLENISH_MIN_ORDERS,
    affinity,
    combo_months,
    combo_stats,
    cross_sell,
    local_day,
    order_concepts,
    popularity,
    rank_verticals,
    replenishment,
    transitions,
)
from .predict import CURRENT_COMBO_DAYS, LAPSED_COMBO_DAYS
from .recommend import CROSS_SELL_LAMBDA, mix_scores

WINDOW_DAYS = 28
MIN_DAYS = 3 * WINDOW_DAYS
GRID_B = (0, 0.1, 0.3, 0.5, 1, 2)
GRID_C = (0, 0.05, 0.1, 0.3, 0.5, 1)
GRID_LAMBDA = (0, 0.5, 1, 2, 4)  # el empuje de las reglas sobre lo más pedido (`recommend.mix_scores`)
# Un λ mayor solo gana si suma al menos 5 aciertos en validación: menos es ruido y cambiaría la variante de la oferta
# cada semana.
LAMBDA_MIN_GAIN_HITS = 5
METHODS = ("orden_fijo", "popularidad", "afinidad", "transicion", "combinado")
METRICS = ("hit1", "hit3", "mrr", "ndcg")
CROSS_SELL_RECENT_DAYS = 30  # los conceptos de la persona que disparan reglas
TOP_K = 3
REPLENISH_TOLERANCE_DAYS = 7
SYNTHETIC_WARNING = "Datos simulados: esto prueba la mecánica del motor, no su efecto."
PROTOTYPE_WARNING = "Uso del MVP, pocas personas: no es evidencia."
NO_VALIDATION = "Sin personas para validar (nadie pidió antes y durante la validación): quedan los pesos anteriores."
# Lo que se lee en el informe; los ids quedan en el JSON de la corrida.
LABELS = {
    "orden_fijo": "Orden fijo",
    "popularidad": "Popularidad",
    "afinidad": "Solo afinidad",
    "transicion": "Solo transiciones",
    "combinado": "Combinado",
    "reglas": "Reglas aprendidas",
    "lo_mas_pedido": "Lo más pedido",
    "mezcla": "Mezcla",
    "escalera": "Paso de la escalera",
    "mas_sumada": "La vertical que más se suma",
}


@dataclass(frozen=True)
class Split:
    train_end: datetime
    valid_end: datetime
    test_end: datetime


def make_split(orders: list[Order]) -> Split | None:
    """Prueba = los últimos 28 días (hasta justo después del último pedido, para que entre); validación = los 28
    anteriores; entrenar = todo lo previo. `None` si los pedidos cubren menos de 84 días."""
    if not orders:
        return None
    first, last = min(o.ts for o in orders), max(o.ts for o in orders)
    if last - first < timedelta(days=MIN_DAYS):
        return None
    test_end = last + timedelta(microseconds=1)  # los tramos son semiabiertos: [inicio, fin)
    valid_end = test_end - timedelta(days=WINDOW_DAYS)
    return Split(valid_end - timedelta(days=WINDOW_DAYS), valid_end, test_end)


def rank_metrics(ranking: list[str], relevant: set[str] | frozenset[str]) -> dict:
    """Acierto@1, acierto@3, rango recíproco y nDCG binario sobre todo el ranking (los 8 verticales)."""
    positions = [i for i, v in enumerate(ranking) if v in relevant]
    if not positions:
        return {"hit1": 0, "hit3": 0, "mrr": 0.0, "ndcg": 0.0}
    dcg = sum(1 / math.log2(i + 2) for i in positions)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(relevant), len(ranking))))
    return {
        "hit1": int(positions[0] == 0),
        "hit3": int(positions[0] < 3),
        "mrr": 1 / (positions[0] + 1),
        "ndcg": dcg / ideal,
    }


# Lo anterior a un corte, sin volver a recorrer todo


class _History:
    """Pedidos y señales ordenados por fecha y, por persona, sus pedidos en orden: cortar en una fecha es un
    `bisect`."""

    def __init__(self, orders: list[Order], signals: list[Signal]):
        self.orders = sorted(orders, key=lambda o: (o.ts, o.order_id))
        self.order_ts = [o.ts for o in self.orders]
        self.signals = sorted(signals, key=lambda s: s.ts)
        self.signal_ts = [s.ts for s in self.signals]
        self.by_user: dict[str, list[Order]] = defaultdict(list)
        for o in self.orders:
            self.by_user[o.user_id].append(o)
        self.user_ts = {user: [o.ts for o in user_orders] for user, user_orders in self.by_user.items()}

    def orders_before(self, cut: datetime) -> list[Order]:
        return self.orders[: bisect_left(self.order_ts, cut)]

    def signals_before(self, cut: datetime) -> list[Signal]:
        return self.signals[: bisect_left(self.signal_ts, cut)]

    def user_orders(self, user: str, start: datetime | None, end: datetime) -> list[Order]:
        """Los pedidos de la persona en `[start, end)` (desde el primero si `start` es None)."""
        ts = self.user_ts[user]
        lo = 0 if start is None else bisect_left(ts, start)
        return self.by_user[user][lo : bisect_left(ts, end)]


# Próximo vertical


@dataclass(frozen=True)
class _Case:
    affinity: dict[str, float]
    last_vertical: str
    relevant: frozenset[str]


@dataclass(frozen=True)
class _Window:
    cases: list[_Case]
    transitions: dict[str, dict[str, float]]
    popularity: dict[str, float]


def _window(history: _History, cut: datetime, end: datetime) -> _Window:
    """Lo que el motor sabría en `cut` (afinidad, transiciones y popularidad con lo anterior) y, para cada persona con
    pedidos antes y en `[cut, end)`, los verticales que pidió en ese tramo."""
    before = history.orders_before(cut)
    aff = affinity(history.signals_before(cut), cut)
    cases = []
    for user in sorted(history.by_user):
        past = history.user_orders(user, None, cut)
        future = history.user_orders(user, cut, end)
        if past and future:
            cases.append(_Case(aff.get(user, {}), past[-1].vertical, frozenset(o.vertical for o in future)))
    return _Window(cases, transitions(before), popularity(before, cut))


def _mean_metrics(rows: list[dict], people: int) -> dict:
    out = {m: sum(r[m] for r in rows) / people if people else 0.0 for m in METRICS}
    out["personas"] = people
    return out


def _method_metrics(window: _Window, method: str, weights: dict[str, float]) -> dict:
    """Las métricas medias de un método. La popularidad como línea base ordena los 8 por su cuota (sin la regla de
    Farmacia y Licores, que es del motor); afinidad, transición y combinado son `rank_verticals` con sus pesos."""
    method_weights = {
        "afinidad": {"afinidad": 1.0, "transicion": 0.0, "popularidad": 0.0},
        "transicion": {"afinidad": 0.0, "transicion": 1.0, "popularidad": 0.0},
        "combinado": weights,
    }
    by_popularity = sorted(DEFAULT_ORDER, key=lambda v: (-window.popularity.get(v, 0.0), DEFAULT_ORDER.index(v)))
    rows = []
    for case in window.cases:
        if method == "orden_fijo":
            ranking = list(DEFAULT_ORDER)
        elif method == "popularidad":
            ranking = by_popularity
        else:
            ranked = rank_verticals(
                case.affinity, case.last_vertical, window.transitions, window.popularity, method_weights[method]
            )
            ranking = [v for v, _score in ranked]
        rows.append(rank_metrics(ranking, case.relevant))
    return _mean_metrics(rows, len(window.cases))


def _next_vertical(window: _Window, weights: dict[str, float]) -> dict[str, dict]:
    return {method: _method_metrics(window, method, weights) for method in METHODS}


def evaluate_next_vertical(
    orders: list[Order], signals: list[Signal], cut: datetime, end: datetime, weights: dict[str, float]
) -> dict[str, dict]:
    """Por método (`METHODS`), acierto@1, acierto@3, MRR y nDCG medios sobre las personas con pedidos antes de `cut`
    y en `[cut, end)`; lo relevante son los verticales que pidió en ese tramo. `combinado` usa `weights`."""
    return _next_vertical(_window(_History(orders, signals), cut, end), weights)


def _tune(history: _History, split: Split) -> tuple[dict[str, float] | None, float | None, int]:
    """`(pesos, nDCG en validación, personas en validación)`; sin personas, `(None, None, 0)`."""
    window = _window(history, split.train_end, split.valid_end)
    if not window.cases:
        return None, None, 0
    best: tuple[float, dict[str, float]] | None = None
    for b in GRID_B:  # en orden creciente: ante un empate queda el primero (b más chico y, después, c más chico)
        for c in GRID_C:
            weights = {"afinidad": 1.0, "transicion": float(b), "popularidad": float(c)}
            # Redondeado: sin ruido de punto flotante en los empates.
            ndcg = round(_method_metrics(window, "combinado", weights)["ndcg"], 12)
            if best is None or ndcg > best[0]:
                best = (ndcg, weights)
    return best[1], best[0], len(window.cases)


def tune(orders: list[Order], signals: list[Signal], split: Split) -> dict[str, float] | None:
    """Los pesos del próximo vertical: a = 1 y el (b, c) de `GRID_B` × `GRID_C` con mejor nDCG en validación (lo
    anterior a `train_end` contra `[train_end, valid_end)`); ante un empate, los más chicos. `None` si nadie pidió
    antes y durante la validación (no hay con qué elegir)."""
    return _tune(_History(orders, signals), split)[0]


# Compra cruzada


def _precision(predictions: dict[str, list[tuple[str, str]]], bought: dict[str, set], people: int) -> dict:
    """Entre quienes tienen alguna predicción: `precision3` = aciertos / recomendaciones hechas (hasta 3) y
    `aciertos_sobre_3` = aciertos / 3, en promedio por persona."""
    with_prediction = [user for user, pairs in predictions.items() if pairs]
    hits = {u: len(set(predictions[u]) & bought[u]) for u in with_prediction}
    return {
        "precision3": statistics.fmean(hits[u] / len(predictions[u]) for u in with_prediction) if hits else 0.0,
        "aciertos_sobre_3": statistics.fmean(n / TOP_K for n in hits.values()) if hits else 0.0,
        "cobertura": len(with_prediction) / people if people else 0.0,
        "personas_con_prediccion": len(with_prediction),
    }


def _pairs(orders: list[Order], sensitive: frozenset[str], skip_suggested: bool = False) -> set[tuple[str, str]]:
    return {(c, o.vertical) for o in orders for c in order_concepts(o, sensitive, skip_suggested)}


def evaluate_cross_sell(
    orders: list[Order], sensitive: frozenset[str], cut: datetime, end: datetime, lam: float = CROSS_SELL_LAMBDA
) -> dict:
    """Reglas aprendidas con lo anterior a `cut`; a cada persona con pedidos antes de `cut` y en `[cut, end)` (quien no
    vuelve no cuenta: si no, se mediría el abandono), las 3 (concepto, vertical) de mayor confianza entre las reglas
    de los conceptos que pidió en los 30 días previos, sin lo que ya pidió en ese vertical. Acierto si lo pide en
    `[cut, end)` sin que se lo sugieran (como al aprender las reglas). `precision3` = media de aciertos /
    predicciones entre quienes tienen alguna; `aciertos_sobre_3`, lo mismo dividido por 3; `cobertura` = la parte de
    las personas con alguna. Línea base `lo_mas_pedido`: los pares más pedidos de los 28 días previos, los mismos para
    todos (sin lo que la persona ya pidió). `mezcla`: lo más pedido empujado por el lift de las reglas de la persona
    (`recommend.mix_scores` con `lam`), con las mismas exclusiones y personas."""
    return _cross_sell(_cross_sell_window(_History(orders, []), sensitive, cut, end), lam)


@dataclass(frozen=True)
class _CrossSellWindow:
    people: list[str]
    had: dict[str, set[tuple[str, str]]]  # lo que pidió antes del corte: no se recomienda
    lifts: dict[str, dict[tuple[str, str], float]]  # lift máximo de las reglas desde sus conceptos recientes
    rules_pred: dict[str, list[tuple[str, str]]]
    bought: dict[str, set[tuple[str, str]]]
    popular: dict[tuple[str, str], float]  # cuota de pedidos de los 28 días previos
    by_popularity: list[tuple[str, str]]


def _cross_sell_window(history: _History, sensitive: frozenset[str], cut: datetime, end: datetime) -> _CrossSellWindow:
    """Lo que no depende de λ: reglas, popularidad, lo ya pedido y lo comprado de cada persona evaluada."""
    before = history.orders_before(cut)
    by_concept: dict[str, list] = defaultdict(list)
    for r in cross_sell(before, sensitive):
        by_concept[r.from_concept].append(r)
    recent_start = cut - timedelta(days=CROSS_SELL_RECENT_DAYS)
    counts = Counter(
        pair for o in before if o.ts >= cut - timedelta(days=WINDOW_DAYS) for pair in _pairs([o], sensitive)
    )
    total = sum(counts.values())
    popular = {pair: n / total for pair, n in counts.items()}
    window = _CrossSellWindow(
        people=[
            user
            for user in sorted(history.by_user)
            if history.user_orders(user, None, cut) and history.user_orders(user, cut, end)
        ],
        had={},
        lifts={},
        rules_pred={},
        bought={},
        popular=popular,
        by_popularity=sorted(counts, key=lambda p: (-counts[p], p)),
    )
    for user in window.people:
        past = history.user_orders(user, None, cut)
        had = _pairs(past, sensitive)
        recent = {c for o in past if o.ts >= recent_start for c in order_concepts(o, sensitive)}
        best: dict[tuple[str, str], tuple[float, float]] = {}
        lifts: dict[tuple[str, str], float] = {}
        for concept in recent:
            for r in by_concept.get(concept, ()):
                pair = (r.to_concept, r.to_vertical)
                lifts[pair] = max(lifts.get(pair, 0.0), r.lift)
                if pair not in had:
                    best[pair] = max(best.get(pair, (0.0, 0.0)), (r.confidence, r.lift))
        window.had[user] = had
        window.lifts[user] = lifts
        window.rules_pred[user] = sorted(best, key=lambda p: (-best[p][0], -best[p][1], p))[:TOP_K]
        window.bought[user] = _pairs(history.user_orders(user, cut, end), sensitive, skip_suggested=True)
    return window


def _top_popular(window: _CrossSellWindow, user: str, skip: set | dict = frozenset()) -> list[tuple[str, str]]:
    """Los 3 pares más pedidos que la persona no pidió (ni están en `skip`)."""
    out = []
    for pair in window.by_popularity:
        if pair not in window.had[user] and pair not in skip:
            out.append(pair)
            if len(out) == TOP_K:
                break
    return out


def _mixed_pred(window: _CrossSellWindow, lam: float) -> dict[str, list[tuple[str, str]]]:
    """Las 3 de `mix_scores` por persona, sin lo que ya pidió. Solo los pares con regla cambian de puntaje: el resto
    queda en su orden de popularidad, así que basta mezclar esos con los 3 más pedidos sin regla."""
    pred = {}
    for user in window.people:
        lifts = {p: lift for p, lift in window.lifts[user].items() if p not in window.had[user]}
        candidates = [p for p in lifts if p in window.popular] + _top_popular(window, user, lifts)
        scores = mix_scores({p: window.popular[p] for p in candidates}, lifts, lam)
        pred[user] = sorted(scores, key=lambda p: (-scores[p], p))[:TOP_K]
    return pred


def _cross_sell(window: _CrossSellWindow, lam: float) -> dict:
    people = len(window.people)
    baseline_pred = {user: _top_popular(window, user) for user in window.people}
    mixed_pred = _mixed_pred(window, lam)
    out = {"personas": people, **_precision(window.rules_pred, window.bought, people)}
    # Lo más pedido y la mezcla, también sobre las mismas personas que las reglas: así las precisiones se comparan
    # sobre la misma gente.
    with_rules = [u for u, pairs in window.rules_pred.items() if pairs]
    for key, pred in (("lo_mas_pedido", baseline_pred), ("mezcla", mixed_pred)):
        out[key] = _precision(pred, window.bought, people)
        same = {u: pred[u] for u in with_rules}
        out[key]["precision3_mismas_personas"] = _precision(same, window.bought, len(same))["precision3"]
    return out


def _tune_lambda(history: _History, sensitive: frozenset[str], split: Split) -> tuple[float | None, float | None, int]:
    """`(λ, precisión@3 de la mezcla en validación, personas en validación)`; sin personas, `(None, None, 0)`."""
    window = _cross_sell_window(history, sensitive, split.train_end, split.valid_end)
    if not window.people:
        return None, None, 0
    best: tuple[int, float, float] | None = None  # (aciertos, λ, precisión@3)
    for lam in GRID_LAMBDA:  # en orden creciente: si no suma LAMBDA_MIN_GAIN_HITS aciertos, queda el menor
        pred = _mixed_pred(window, lam)
        hits = sum(len(set(pairs) & window.bought[user]) for user, pairs in pred.items())
        if best is None or hits >= best[0] + LAMBDA_MIN_GAIN_HITS:
            best = (hits, float(lam), _precision(pred, window.bought, len(window.people))["precision3"])
    return best[1], best[2], len(window.people)


def tune_lambda(orders: list[Order], sensitive: frozenset[str], split: Split) -> float | None:
    """El λ de la mezcla: el de `GRID_LAMBDA` con más aciertos en validación (reglas y popularidad con lo anterior a
    `train_end`, aciertos en `[train_end, valid_end)`); uno mayor reemplaza al elegido solo si lo supera en al menos
    `LAMBDA_MIN_GAIN_HITS` aciertos, así que en un empate o casi empate queda el menor. `None` si nadie pidió antes y
    durante la validación."""
    return _tune_lambda(_History(orders, []), sensitive, split)[0]


# Recompra


def evaluate_replenishment(orders: list[Order], sensitive: frozenset[str], cut: datetime, end: datetime) -> dict:
    """La recompra calculada con lo anterior a `cut`, para las predicciones que vencen en `[cut, end)`: el error es la
    distancia en días entre el día previsto y la primera compra del concepto desde `cut`; si no lo compró, es un fallo.
    `error_mediano_dias` (sobre las que compraron), `acierto_7_dias` (error ≤ 7 sobre todas) y `n`.

    Líneas base, medidas igual: `mediana_poblacional` (las mismas predicciones, con el día previsto a la mediana de los
    intervalos del concepto en toda la población antes de `cut`; `solo_intervalo_propio`, `solo_mediana` y su McNemar
    exacto `p_mcnemar`), `regla_simple` (3 días de compra o más, sin filtro de variación, con esa mediana) y
    `sin_filtro_cv` (el intervalo propio sin `REPLENISH_MAX_CV`: la cobertura que cuesta el filtro)."""
    return _replenishment(_History(orders, []), sensitive, cut, end)


def _concept_days(orders: list[Order], sensitive: frozenset[str]) -> dict[tuple[str, str], list[date]]:
    """`(persona, concepto) → días de compra distintos, en orden`, como los cuenta `model.replenishment`."""
    days: dict[tuple[str, str], set[date]] = defaultdict(set)
    for o in orders:
        for concept in order_concepts(o, sensitive):
            days[o.user_id, concept].add(local_day(o.ts))
    return {key: sorted(d) for key, d in days.items()}


def _intervals(days: list[date]) -> list[int]:
    return [(b - a).days for a, b in pairwise(days)]


def _first_bought(history: _History, sensitive: frozenset[str], cut: datetime, end: datetime) -> dict:
    """`(persona, concepto) → el primer día que lo compró en [cut, end)`."""
    first: dict[tuple[str, str], date] = {}
    for o in history.orders[bisect_left(history.order_ts, cut) : bisect_left(history.order_ts, end)]:
        for concept in order_concepts(o, sensitive):
            first.setdefault((o.user_id, concept), local_day(o.ts))
    return first


def _due_metrics(due: dict[tuple[str, str], date], bought: dict[tuple[str, str], date]) -> tuple[dict, set]:
    """Las métricas de unas predicciones `(persona, concepto) → día previsto` y cuáles aciertan (error ≤ 7 días)."""
    errors = {key: abs((bought[key] - day).days) for key, day in due.items() if key in bought}
    hits = {key for key, e in errors.items() if e <= REPLENISH_TOLERANCE_DAYS}
    metrics = {
        "n": len(due),
        "compraron": len(errors) / len(due) if due else 0.0,
        "error_mediano_dias": statistics.median(errors.values()) if errors else None,
        "acierto_7_dias": len(hits) / len(due) if due else 0.0,
    }
    return metrics, hits


def _replenishment(history: _History, sensitive: frozenset[str], cut: datetime, end: datetime) -> dict:
    first_day, last_day = local_day(cut), local_day(end)
    before = history.orders_before(cut)
    bought = _first_bought(history, sensitive, cut, end)
    days = _concept_days(before, sensitive)
    pooled: dict[str, list[int]] = defaultdict(list)
    for (_user, concept), d in days.items():
        pooled[concept] += _intervals(d)
    population = {concept: statistics.median(v) for concept, v in pooled.items() if v}

    def by_population(key: tuple[str, str]) -> date:
        return days[key][-1] + timedelta(days=round(population[key[1]]))

    def in_test(due: dict[tuple[str, str], date]) -> dict[tuple[str, str], date]:
        return {key: day for key, day in due.items() if first_day <= day < last_day}

    motor = {
        (r.user_id, r.concept_id): r.due_on
        for r in replenishment(before, sensitive)
        if first_day <= r.due_on < last_day
    }
    rhythm = [key for key, d in days.items() if len(d) >= REPLENISH_MIN_ORDERS]
    out, own_hits = _due_metrics(motor, bought)
    same, base_hits = _due_metrics({key: by_population(key) for key in motor}, bought)
    only_own, only_base = len(own_hits - base_hits), len(base_hits - own_hits)
    out["mediana_poblacional"] = {
        **same,
        "solo_intervalo_propio": only_own,
        "solo_mediana": only_base,
        "p_mcnemar": _mcnemar_exact(only_own, only_base),
    }
    out["regla_simple"] = _due_metrics(in_test({key: by_population(key) for key in rhythm}), bought)[0]
    own_interval = {
        key: days[key][-1] + timedelta(days=round(statistics.median(_intervals(days[key])))) for key in rhythm
    }
    out["sin_filtro_cv"] = _due_metrics(in_test(own_interval), bought)[0]
    return out


# "¿Volvemos a…?"


def evaluate_winback(orders: list[Order], sensitive: frozenset[str], cut: datetime, end: datetime) -> dict:
    """Quién calificaba para "¿Volvemos a…?" (`offers.winback`) el día de `cut`, con lo anterior, y qué parte vuelve al
    concepto o a la vertical en `[cut, end)`, contra lo que tenía el mismo atraso y no calificaba. Sin lo ya mostrado ni
    descartado (como `winback.reach`: es quién califica). Por tipo de invitación:
    - `concepto`: conceptos que la persona pidió hace entre `LAPSE_MIN_DAYS` y `LAPSE_MAX_DAYS` días. Califica el de su
      recompra atrasado más de un intervalo; no califican los que no tienen recompra (menos de 3 días de compra o
      irregulares). Los que tienen recompra y no están atrasados quedan fuera: les toca "¿Repetimos?" o todavía nada.
    - `vertical`: verticales sin pedidos hace más de `VERTICAL_LAPSE_DAYS` días (y no más de `LAPSE_MAX_DAYS`). Califica
      la de al menos `VERTICAL_MIN_DAYS` días con pedido mientras pide en otra; las demás no califican.
    Solo conceptos y verticales que Mochi ofrece. `vuelven_mismo_atraso` pondera lo que no califica por semana de
    atraso con la mezcla de semanas de lo que califica (`None` si no comparten ninguna)."""
    return _winback(_History(orders, []), sensitive, cut, end)


def _return_rates(qualify: list[tuple[int, bool]], others: list[tuple[int, bool]]) -> dict:
    """`(días de atraso, volvió)` de lo que califica y de lo que no, con la tasa de lo que no califica ajustada a las
    semanas de atraso de lo que califica."""
    by_week: dict[int, list[bool]] = defaultdict(list)
    for days, back in others:
        by_week[days // 7].append(back)
    weeks = Counter(days // 7 for days, _back in qualify if days // 7 in by_week)
    total = sum(weeks.values())
    return {
        "califican": len(qualify),
        "vuelven": sum(back for _days, back in qualify) / len(qualify) if qualify else 0.0,
        "no_califican": len(others),
        "vuelven_no_califican": sum(back for _days, back in others) / len(others) if others else 0.0,
        "vuelven_mismo_atraso": (
            sum(n * statistics.fmean(by_week[week]) for week, n in weeks.items()) / total if total else None
        ),
    }


def _winback(history: _History, sensitive: frozenset[str], cut: datetime, end: datetime) -> dict:
    today = local_day(cut)
    before = history.orders_before(cut)
    after = history.orders[bisect_left(history.order_ts, cut) : bisect_left(history.order_ts, end)]
    rhythm = {(r.user_id, r.concept_id): r for r in replenishment(before, sensitive)}
    last_vertical = {(o.user_id, c): o.vertical for o in before for c in order_concepts(o, sensitive)}
    back_concepts = {(o.user_id, c) for o in after for c in order_concepts(o, sensitive)}
    concept_q, concept_others = [], []
    for key, d in _concept_days(before, sensitive).items():
        days = (today - d[-1]).days
        r = rhythm.get(key)
        lapsed = winback.LAPSE_MIN_DAYS <= days <= winback.LAPSE_MAX_DAYS
        if not lapsed or not winback._offerable_concept(key[1], r.vertical if r else last_vertical[key]):
            continue
        case = (days, key in back_concepts)
        if r is None:
            concept_others.append(case)
        elif r.due_on < today - timedelta(days=round(r.interval_days)):  # como `winback._concept_lapses`
            concept_q.append(case)
    vertical_days: dict[tuple[str, str], set[date]] = defaultdict(set)
    for o in before:
        vertical_days[o.user_id, o.vertical].add(local_day(o.ts))
    active = defaultdict(set)
    for (user, vertical), d in vertical_days.items():
        if (today - max(d)).days <= winback.VERTICAL_LAPSE_DAYS:
            active[user].add(vertical)
    back_verticals = {(o.user_id, o.vertical) for o in after}
    vertical_q, vertical_others = [], []
    for (user, vertical), d in vertical_days.items():
        days = (today - max(d)).days
        lapsed = winback.VERTICAL_LAPSE_DAYS < days <= winback.LAPSE_MAX_DAYS
        if not lapsed or not winback._offerable_vertical(vertical):
            continue
        case = (days, (user, vertical) in back_verticals)
        qualifies = len(d) >= winback.VERTICAL_MIN_DAYS and active[user] - {vertical}  # como `winback._vertical_lapses`
        (vertical_q if qualifies else vertical_others).append(case)
    return {
        "concepto": _return_rates(concept_q, concept_others),
        "vertical": _return_rates(vertical_q, vertical_others),
    }


# Paso de la escalera fina


def _additions(history: _History, cut: datetime, end: datetime) -> dict[str, tuple[frozenset[str], frozenset[str]]]:
    """`persona → (verticales de su combinación en el corte, verticales que suma en [cut, end))` para quien suma alguna.
    La combinación es la de `predict.current_fine` en el corte, pero armada solo con los pedidos (sin servicios): los
    últimos 30 días y, sin pedidos, los últimos 90; sin pedidos en 90 días no hay combinación (la oferta es la de
    siempre). Solo cuentan las verticales que
    la escalera puede proponer: Farmacia y Licores no son paso, así que sumarlas no cuenta."""
    out = {}
    for user in sorted(history.by_user):
        recent = history.user_orders(user, cut - timedelta(days=CURRENT_COMBO_DAYS), cut) or history.user_orders(
            user, cut - timedelta(days=LAPSED_COMBO_DAYS), cut
        )
        if not recent:
            continue
        have = frozenset(o.vertical for o in recent)
        added = frozenset(
            o.vertical
            for o in history.user_orders(user, cut, end)
            if o.vertical not in have and _proposable(o.vertical)
        )
        if added:
            out[user] = (have, added)
    return out


def _proposable(vertical: str) -> bool:
    return offerable_vertical(vertical) and vertical not in OWN_SIGNALS_ONLY


def _learned(orders: list[Order], fine: bool) -> dict[str, tuple[int, float]]:
    """La retención aprendida `combinación → (personas, retención)` con los pedidos dados, como la guarda el motor."""
    return {
        combo: (s["retention_n"], s["retention_m1"])
        for combo, s in combo_stats(combo_months(orders, fine=fine)).items()
        if s["retention_m1"] is not None
    }


def evaluate_step(
    orders: list[Order], signals: list[Signal], cut: datetime, end: datetime, weights: dict[str, float]
) -> dict:
    """El paso de la escalera fina calculado en `cut` contra lo que la persona sumó en `[cut, end)`. Entran quienes
    tienen combinación en el corte y suman alguna vertical nueva que la escalera puede proponer (ni Farmacia ni
    Licores). `escalera`: acierto@1 de `next_fine_step` (con la retención de Rappi, el supuesto y lo aprendido de los
    pedidos anteriores al corte; candidatos del catálogo en el orden de `rank_verticals` con `weights`); sin paso
    cuenta como fallo y `con_paso` dice cuántas lo tienen. `mas_sumada`: la vertical que más personas sumaron en un
    tramo igual de largo antes del corte, entre las que la persona no tiene."""
    return _step(_History(orders, signals), cut, end, weights)


def _step(history: _History, cut: datetime, end: datetime, weights: dict[str, float]) -> dict:
    before = history.orders_before(cut)
    learned_coarse, learned_fine = _learned(before, fine=False), _learned(before, fine=True)
    aff = affinity(history.signals_before(cut), cut)
    trans, pop = transitions(before), popularity(before, cut)
    # La línea base: cuántas personas sumaron cada vertical en el tramo anterior (de igual largo que la prueba).
    added_before = Counter(v for _have, added in _additions(history, cut - (end - cut), cut).values() for v in added)
    most_added = sorted(DEFAULT_ORDER, key=lambda v: (-added_before[v], DEFAULT_ORDER.index(v)))
    cases = _additions(history, cut, end)
    ladder_hits = baseline_hits = with_step = only_ladder = only_base = 0
    for user, (have, added) in cases.items():
        last = history.user_orders(user, None, cut)[-1].vertical
        ranked = rank_verticals(aff.get(user, {}), last, trans, pop, weights)
        candidates = [v for v, _score in ranked if _proposable(v)]
        step = next_fine_step(fine_of(have), candidates, learned_coarse, learned_fine)
        with_step += step is not None
        ladder_hit = step is not None and step.vertical in added
        baseline = next((v for v in most_added if v not in have and _proposable(v)), None)
        baseline_hit = baseline in added
        ladder_hits += ladder_hit
        baseline_hits += baseline_hit
        only_ladder += ladder_hit and not baseline_hit
        only_base += baseline_hit and not ladder_hit
    people = len(cases)
    return {
        "personas": people,
        "con_paso": with_step,
        "escalera": ladder_hits / people if people else 0.0,
        "mas_sumada": baseline_hits / people if people else 0.0,
        "solo_paso": only_ladder,
        "solo_base": only_base,
        "p_mcnemar": _mcnemar_exact(only_ladder, only_base),
    }


def _mcnemar_exact(b: int, c: int) -> float:
    """p bilateral de McNemar exacto con los pares discordantes (`b`: solo acierta el paso; `c`: solo la línea base):
    con n = b + c, la binomial(n, 1/2) del menor de los dos. Las personas en que los dos aciertan o fallan no dicen
    cuál es mejor. 1.0 sin pares discordantes."""
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2**n)


# Todo junto


def _rounded(value):
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    return value


def evaluate(
    orders: list[Order],
    signals: list[Signal],
    sensitive: frozenset[str],
    previous_weights: dict[str, float] | None = None,
    previous_lambda: float | None = None,
) -> dict | None:
    """Elige los pesos y el λ de la mezcla en validación y mide en prueba el próximo vertical, la compra cruzada, la
    recompra, "¿Volvemos a…?" y el paso de la escalera fina. `None` si no hay 84 días de datos. Si nadie se puede
    validar, quedan `previous_weights` (por defecto `DEFAULT_WEIGHTS`) y `previous_lambda` (por defecto
    `CROSS_SELL_LAMBDA`), y `validacion.aviso` lo dice. Un diccionario serializable a JSON (fechas ISO, cifras con 4
    decimales)."""
    split = make_split(orders)
    if split is None:
        return None
    history = _History(orders, signals)
    weights, valid_ndcg, valid_people = _tune(history, split)
    # Las personas en validación son las mismas: pedidos antes de `train_end` y en `[train_end, valid_end)`.
    lam, valid_precision, _people = _tune_lambda(history, sensitive, split)
    validation = {"personas": valid_people, "ndcg_combinado": valid_ndcg, "precision3_mezcla": valid_precision}
    if weights is None:
        weights = dict(previous_weights or DEFAULT_WEIGHTS)
        validation["aviso"] = NO_VALIDATION
    if lam is None:
        lam = CROSS_SELL_LAMBDA if previous_lambda is None else float(previous_lambda)
    test = _window(history, split.valid_end, split.test_end)
    return _rounded(
        {
            "tramos": {
                "entrenar_hasta": split.train_end.isoformat(),
                "validar_hasta": split.valid_end.isoformat(),
                "probar_hasta": split.test_end.isoformat(),
            },
            "pesos": weights,
            "lambda_cruzada": lam,
            "validacion": validation,
            "proximo_vertical": _next_vertical(test, weights),
            "compra_cruzada": _cross_sell(_cross_sell_window(history, sensitive, split.valid_end, split.test_end), lam),
            "recompra": _replenishment(history, sensitive, split.valid_end, split.test_end),
            "volver": _winback(history, sensitive, split.valid_end, split.test_end),
            "paso": _step(history, split.valid_end, split.test_end, weights),
        }
    )


def _fmt(value) -> str:
    return "—" if value is None else f"{value:.3f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)


def _title(source: str) -> list[str]:
    lines = [f"# Evaluación del motor multivertical ({source})", ""]
    if source == "synthetic":
        lines += [f"> **{SYNTHETIC_WARNING}**", ""]
    elif source == "prototype":
        lines += [f"> **{PROTOTYPE_WARNING}**", ""]
    return lines


def _replenishment_verdict(rp: dict) -> list[str]:
    """Si el intervalo propio gana a la mediana de la población (McNemar en las mismas predicciones) y la cobertura
    que cuesta el filtro de variación."""
    same, no_cv = rp["mediana_poblacional"], rp["sin_filtro_cv"]
    own, base, p = same["solo_intervalo_propio"], same["solo_mediana"], same["p_mcnemar"]
    if p >= 0.05:
        verdict = "con p ≥ 0,05 la diferencia es ruido"
    else:
        verdict = "gana el intervalo propio" if own > base else "gana la mediana de la población"
    p_value = f"{p:.2f}".replace(".", ",")
    coverage = f"{round(100 * rp['n'] / no_cv['n'])} %" if no_cv["n"] else "—"
    return [
        f"En las mismas {rp['n']} predicciones, solo acierta el intervalo propio: {own}; solo la mediana de la "
        f"población: {base} (McNemar exacto p = {p_value}): {verdict}. El filtro de variación deja "
        f"{rp['n']} de las {no_cv['n']} predicciones del intervalo propio (cobertura {coverage}); la regla simple "
        f"hace {rp['regla_simple']['n']}.",
    ]


def report(results: dict, source: str) -> str:
    """El informe en markdown, en español."""
    lines = _title(source)
    t, w, v = results["tramos"], results["pesos"], results["validacion"]
    lines += [
        f"Tramos por fecha: entrenar hasta {t['entrenar_hasta'][:10]}, validar hasta {t['validar_hasta'][:10]} y "
        f"probar hasta {t['probar_hasta'][:10]} (28 días cada uno de los dos últimos).",
        "",
        "## Pesos",
        "",
    ]
    if "aviso" in v:
        lines += [f"**{v['aviso']}**", ""]
    else:
        lines += ["Con a = 1, (b, c) de la grilla con mejor nDCG en validación; ante un empate, los más chicos.", ""]
    lines += [
        "| Afinidad | Transición | Popularidad | Personas en validación | nDCG en validación |",
        "|---:|---:|---:|---:|---:|",
        f"| {_fmt(w['afinidad'])} | {_fmt(w['transicion'])} | {_fmt(w['popularidad'])} | {v['personas']} | "
        f"{_fmt(v['ndcg_combinado'])} |",
        "",
    ]
    nv = results["proximo_vertical"]
    lines += [
        f"## Próximo vertical (prueba, {nv['combinado']['personas']} personas)",
        "",
        "Personas con pedidos antes y durante la prueba; lo relevante: los verticales que pidió en esos 28 días.",
        "",
        "| Método | Acierto@1 | Acierto@3 | MRR | nDCG@8 |",
        "|---|---:|---:|---:|---:|",
        *(f"| {LABELS[m]} | " + " | ".join(_fmt(nv[m][k]) for k in METRICS) + " |" for m in METHODS),
        "",
    ]
    cs = results["compra_cruzada"]
    base, mix = cs["lo_mas_pedido"], cs["mezcla"]
    grid = ", ".join(_fmt(float(x)) for x in GRID_LAMBDA[:-1]) + f" y {_fmt(float(GRID_LAMBDA[-1]))}"
    chosen = (
        "el de la corrida anterior: nadie para validar"
        if "aviso" in v
        else f"de {grid}, el de más aciertos en validación (precisión@3 {_fmt(v['precision3_mezcla'])}); uno mayor "
        f"gana solo con {LAMBDA_MIN_GAIN_HITS} aciertos más"
    )
    lines += [
        f"## Compra cruzada (prueba, {cs['personas']} personas)",
        "",
        "Personas con pedidos antes y durante la prueba. Precisión@3 = aciertos / recomendaciones hechas (hasta 3);",
        "aciertos / 3 divide siempre por 3. Las dos, en promedio entre quienes tienen alguna recomendación. Un acierto",
        "es pedir ese concepto en ese vertical durante la prueba, sin que se lo sugieran. La mezcla es lo más pedido",
        "empujado por el lift de las reglas que salen de lo que la persona pidió hace poco: popularidad × (1 + λ ×",
        f"(lift − 1)), con λ = {_fmt(results['lambda_cruzada'])}: {chosen}.",
        "",
        "| Método | Precisión@3 | Aciertos / 3 | Cobertura | Personas con recomendación |",
        "|---|---:|---:|---:|---:|",
        *(
            f"| {LABELS[key]} | {_fmt(m['precision3'])} | {_fmt(m['aciertos_sobre_3'])} | {_fmt(m['cobertura'])} | "
            f"{m['personas_con_prediccion']} |"
            for key, m in (("reglas", cs), ("lo_mas_pedido", base), ("mezcla", mix))
        ),
        "",
        "Sobre las mismas personas que tienen reglas, precisión@3: lo más pedido "
        f"{_fmt(base['precision3_mismas_personas'])} y la mezcla {_fmt(mix['precision3_mismas_personas'])}.",
        "",
    ]
    rp = results["recompra"]
    lines += [
        "## Recompra (prueba)",
        "",
        'Predicciones que vencen durante la prueba. "Compraron": la parte en que la persona volvió a comprar el',
        "concepto en la prueba; las demás cuentan como fallo en el acierto ±7 días. El error mediano es solo sobre las",
        "que compraron.",
        "",
        "Líneas base, medidas igual: la mediana de los intervalos del concepto en toda la población antes de la",
        "prueba (en las mismas predicciones, y con la regla simple: 3 días de compra o más, sin filtro de variación);",
        "y el intervalo propio sin el filtro de variación (coeficiente ≤ "
        f"{str(REPLENISH_MAX_CV).replace('.', ',')}), para ver cuánta cobertura cuesta.",
        "",
        "| Método | Predicciones | Compraron | Error mediano (días) | Acierto ±7 días |",
        "|---|---:|---:|---:|---:|",
        *(
            f"| {label} | {m['n']} | {_fmt(m['compraron'])} | {_fmt(m['error_mediano_dias'])} | "
            f"{_fmt(m['acierto_7_dias'])} |"
            for label, m in (
                ("Intervalo propio (el motor)", rp),
                ("Mediana de la población, mismas predicciones", rp["mediana_poblacional"]),
                ("Regla simple con la mediana de la población", rp["regla_simple"]),
                ("Intervalo propio sin filtro de variación", rp["sin_filtro_cv"]),
            )
        ),
        "",
        *_replenishment_verdict(rp),
        "",
    ]
    wb = results["volver"]
    lines += [
        "## ¿Volvemos a…? (prueba)",
        "",
        "Quién calificaba para la invitación el día en que empieza la prueba (con lo anterior, sin lo ya mostrado ni",
        "descartado) y qué parte vuelve a pedir ese concepto o en esa vertical en los",
        f"{WINDOW_DAYS} días de la prueba, contra lo que tenía el mismo atraso y no calificaba: conceptos sin",
        "recompra (menos de 3 días de compra o irregulares) y verticales con menos días de pedido o sin pedidos en",
        "otra. La última columna pondera lo que no califica por semana de atraso como lo que califica.",
        "",
        "| Invitación | Califican | Vuelven | No califican | Vuelven sin calificar | Sin calificar, mismo atraso |",
        "|---|---:|---:|---:|---:|---:|",
        *(
            f"| {label} | {m['califican']} | {_fmt(m['vuelven'])} | {m['no_califican']} | "
            f"{_fmt(m['vuelven_no_califican'])} | {_fmt(m['vuelven_mismo_atraso'])} |"
            for label, m in (("Concepto", wb["concepto"]), ("Vertical", wb["vertical"]))
        ),
        "",
        ("Simulado: el generador no simula esta invitación. " if source == "synthetic" else "")
        + "Sin grupo al que no se le ofrezca, esto dice si la regla elige lo que vuelve, no el efecto de invitar.",
        "",
    ]
    step = results.get("paso")  # las corridas anteriores a la escalera fina no lo tienen
    if step is not None:
        p_value = f"{step['p_mcnemar']:.2f}".replace(".", ",")
        lines += [
            f"## Paso de la escalera (prueba, {step['personas']} personas)",
            "",
            "Personas con pedidos en los 90 días antes de la prueba que suman en ella una vertical que no estaba en su",
            "combinación (30 días; sin pedidos, 90). Farmacia y Licores no cuentan: la escalera nunca las propone.",
            "Acierto@1: la vertical propuesta es una de las que sumó. El paso se calcula con lo anterior a la prueba",
            f"(tabla de Rappi, supuesto propio y retención aprendida); {step['con_paso']} personas tienen paso y, sin",
            "paso, es un fallo. La línea base propone la vertical que más personas sumaron en los 28 días anteriores.",
            "",
            "| Método | Acierto@1 |",
            "|---|---:|",
            *(f"| {LABELS[key]} | {_fmt(step[key])} |" for key in ("escalera", "mas_sumada")),
            "",
            f"Solo acierta el paso: {step['solo_paso']}; solo la línea base: {step['solo_base']} (McNemar exacto p = "
            f"{p_value}). Con p ≥ 0,05 la diferencia es ruido.",
            "",
        ]
    return "\n".join(lines)


def not_evaluated(source: str, reason: str, weights: dict[str, float], when: str) -> str:
    """El informe de una corrida que no se evaluó: así uno viejo nunca parece el de la última corrida."""
    lines = _title(source)
    lines += [f"La última corrida del motor ({when}) no se evaluó: {reason}.", "", f"Pesos en uso: {weights}.", ""]
    return "\n".join(lines)
