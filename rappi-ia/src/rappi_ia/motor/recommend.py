"""Compras cruzadas para una persona: lo más pedido de la población, empujado por las reglas que salen de lo que ella
pidió hace poco.

Las reglas solas acertaron menos que lo más pedido (16-10, antes de la etapa 5, con datos simulados en
`rappi_staging`: precisión@3 0,076 contra 0,124; las cifras vigentes, en `docs/resultados/motor-2026-10-16.md`): por
eso la base es la popularidad del par (concepto, vertical) y el lift de las reglas solo la sube. El peso del empuje (λ)
se elige en validación, como los demás pesos del motor (`motor.evaluate`), y queda en la corrida como
`lambda_cruzada`.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from psycopg import Connection

from .. import config
from ..concepts.taxonomy import load_taxonomy
from ..offers.guards import is_offerable, offerable_vertical
from .data import load_orders
from .predict import source_of

CROSS_SELL_LAMBDA = 1.0  # sin una corrida que lo haya elegido
RECENT_DAYS = 30  # los conceptos de la persona que disparan reglas, y lo que ya pidió y no se repite

Pair = tuple[str, str]  # (concepto, vertical)


def mix_scores(popular: dict[Pair, float], rules: dict[Pair, float], lam: float) -> dict[Pair, float]:
    """Puntaje = popularidad × (1 + λ × max(0, lift − 1)). `popular`: cuota de pedidos del par en la ventana; `rules`:
    el lift máximo de las reglas que llegan al par desde los conceptos de la persona. Un par sin popularidad no
    aparece (una regla no inventa lo que nadie pide)."""
    return {
        pair: share * (1 + lam * max(0.0, rules.get(pair, 1.0) - 1)) for pair, share in popular.items() if share > 0
    }


@dataclass(frozen=True)
class CrossPick:
    concept_id: str
    vertical: str
    score: float
    from_concept: str | None  # el concepto de la persona cuya regla llega al par (None: solo lo más pedido)
    lift: float | None


def latest_lambda(conn: Connection, source: str) -> float:
    """El λ de la última corrida `motor` terminada de esa fuente que lo tenga; `CROSS_SELL_LAMBDA` si no hay."""
    row = conn.execute(
        """SELECT counts->>'lambda_cruzada' FROM layer_runs
           WHERE layer = 'motor' AND status = 'done' AND counts->>'fuente' = %s AND counts ? 'lambda_cruzada'
           ORDER BY run_id DESC LIMIT 1""",
        (source,),
    ).fetchone()
    return float(row[0]) if row else CROSS_SELL_LAMBDA


def cross_picks(
    conn: Connection,
    user_id: str,
    verticals: Iterable[str] | None = None,
    population: str | None = None,
    k: int | None = 3,
    lam: float | None = None,
) -> list[CrossPick]:
    """Los `k` pares (concepto, vertical) que más conviene ofrecerle: los conceptos de sus pedidos `propuesta` de los
    últimos 30 días disparan las reglas de `cross_sell_rules` de la población, que se mezclan (`mix_scores`, con el λ
    de la última corrida) con lo más pedido de `trends`. Sin lo que ya pidió en ese vertical en esos 30 días, sin
    conceptos ni verticales que las guardias de ofertas no dejan proponer, y solo de `verticals` si se da. Sin pedidos
    recientes, es lo más pedido. `population` por defecto es `config.MOTOR_POBLACION`, leída al llamar; `k=None` los
    trae todos y `lam`, si quien llama ya lo leyó, evita volver a leer el λ."""
    population = population or config.MOTOR_POBLACION
    now = datetime.now(UTC)
    source = source_of(conn, user_id)
    since = now - timedelta(days=RECENT_DAYS)
    recent = [o for o in (load_orders(conn, source, user_id, since=since) if source else []) if o.ts <= now]
    had = {(line.concept_id, o.vertical) for o in recent for line in o.lines if line.concept_id is not None}
    concepts = sorted({c for c, _vertical in had})

    rules: dict[Pair, tuple[float, str]] = {}
    if concepts:
        for from_concept, to_concept, to_vertical, lift in conn.execute(
            """SELECT from_concept, to_concept, to_vertical, lift FROM cross_sell_rules
               WHERE data_source = %s AND from_concept = ANY(%s)""",
            (population, concepts),
        ):
            pair = (to_concept, to_vertical)
            # El de mayor lift; a igual lift, el primer concepto en orden alfabético (la razón no cambia entre veces).
            if pair not in rules or (-lift, from_concept) < (-rules[pair][0], rules[pair][1]):
                rules[pair] = (float(lift), from_concept)

    counts = conn.execute(
        "SELECT concept_id, vertical, orders_now FROM trends WHERE data_source = %s AND scope = 'concepto'",
        (population,),
    ).fetchall()
    total = sum(n for _c, _v, n in counts)
    if not total:
        return []
    allowed = set(verticals) if verticals is not None else None
    taxonomy = load_taxonomy().concepts
    popular = {
        (concept, vertical): n / total
        for concept, vertical, n in counts
        if (concept, vertical) not in had
        and (allowed is None or vertical in allowed)
        and offerable_vertical(vertical)
        and concept in taxonomy
        and is_offerable(taxonomy[concept])
    }
    lam = latest_lambda(conn, population) if lam is None else lam
    scores = mix_scores(popular, {pair: lift for pair, (lift, _c) in rules.items()}, lam)
    best = sorted(scores, key=lambda pair: (-scores[pair], pair))[:k]
    return [
        CrossPick(
            concept,
            vertical,
            scores[concept, vertical],
            rules[concept, vertical][1] if (concept, vertical) in rules else None,
            rules[concept, vertical][0] if (concept, vertical) in rules else None,
        )
        for concept, vertical in best
    ]
