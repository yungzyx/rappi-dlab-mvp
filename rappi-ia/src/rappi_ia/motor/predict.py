"""La predicción del motor para una persona: el próximo vertical, su combinación de este mes y el paso que más retención
suma: la vertical del catálogo (o, si ya usa todas las que se pueden ofrecer, RappiFavor o RappiTravel) con la que más
sube su retención esperada (`combos.next_fine_step`).

Lee solo las filas de la persona y las tablas chicas de la población (transiciones, tendencias por vertical,
combinaciones, la última corrida); nunca recorre todos los pedidos en el momento de responder. La afinidad se calcula en
vivo con las señales de la propia persona, así que siempre está al día.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from psycopg import Connection

from .. import config
from ..offers.guards import offerable_vertical
from .combos import (
    LEARNED_RETENTION_MIN_USERS,
    NONE_COMBO,
    SERVICE_COMBO,
    SERVICES,
    Step,
    combo_of_verticals,
    fine_of,
    load_combos,
    next_fine_step,
)
from .data import load_signals
from .model import DEFAULT_WEIGHTS, OWN_SIGNALS_ONLY, affinity, rank_verticals

CURRENT_COMBO_DAYS = 30
LAPSED_COMBO_DAYS = 90  # sin pedidos en 30 días, la combinación es la de los últimos 90


@dataclass(frozen=True)
class VerticalScore:
    """El puntaje de un vertical y sus tres piezas, antes de los pesos: afinidad normalizada (suma 1 entre los
    verticales de la persona), P(vertical | último vertical) y cuota de pedidos recientes de la población. Farmacia y
    Licores llevan 0 en las dos últimas: solo suben por lo propio."""

    vertical: str
    score: float
    affinity: float
    transition: float
    popularity: float


def latest_weights(conn: Connection, source: str) -> dict[str, float]:
    """Los pesos de la última corrida `motor` terminada de esa fuente; `DEFAULT_WEIGHTS` si no hay."""
    row = conn.execute(
        """SELECT counts->'pesos' FROM layer_runs
           WHERE layer = 'motor' AND status = 'done' AND counts->>'fuente' = %s AND counts ? 'pesos'
           ORDER BY run_id DESC LIMIT 1""",
        (source,),
    ).fetchone()
    return {k: float(v) for k, v in row[0].items()} if row else dict(DEFAULT_WEIGHTS)


def next_verticals(
    conn: Connection, user_id: str | None, population: str | None = None, now: datetime | None = None
) -> list[VerticalScore]:
    """Los 8 verticales en el orden en que conviene ofrecérselos a la persona (`model.rank_verticals`). `population`
    por defecto es `config.MOTOR_POBLACION`, leída al llamar."""
    population = population or config.MOTOR_POBLACION
    now = now or datetime.now(UTC)
    aff: dict[str, float] = {}
    last_vertical = None
    source = source_of(conn, user_id) if user_id else None
    if source is not None:
        signals = [s for s in load_signals(conn, source, user_id) if s.ts <= now]
        aff = affinity(signals, now).get(user_id, {})
        last_vertical = next((s.vertical for s in reversed(signals) if s.kind == "order"), None)
    trans = {}
    if last_vertical is not None:
        rows = conn.execute(
            "SELECT to_vertical, prob FROM vertical_transitions WHERE data_source = %s AND from_vertical = %s",
            (population, last_vertical),
        ).fetchall()
        trans = {last_vertical: {to: float(prob) for to, prob in rows}}
    recent = dict(
        conn.execute(
            "SELECT vertical, orders_now FROM trends WHERE data_source = %s AND scope = 'vertical'", (population,)
        ).fetchall()
    )
    total_recent = sum(recent.values())
    pop = {v: n / total_recent for v, n in recent.items()} if total_recent else {}
    total_aff = sum(aff.values())
    out = []
    for vertical, score in rank_verticals(aff, last_vertical, trans, pop, latest_weights(conn, population)):
        own_only = vertical in OWN_SIGNALS_ONLY
        out.append(
            VerticalScore(
                vertical=vertical,
                score=score,
                affinity=aff.get(vertical, 0.0) / total_aff if total_aff else 0.0,
                transition=0.0 if own_only else trans.get(last_vertical, {}).get(vertical, 0.0),
                popularity=0.0 if own_only else pop.get(vertical, 0.0),
            )
        )
    return out


def current_fine(conn: Connection, user_id: str, now: datetime | None = None) -> str:
    """La combinación fina de la persona: las verticales de sus pedidos `propuesta` de los últimos 30 días y los
    servicios que abrió en ese tiempo (`service_opened`, salvo en «Rappi hoy»). Sin pedidos en 30 días, los de 90
    (`LAPSED_COMBO_DAYS`); sin pedidos en 90, «ninguna»: abrir un servicio sin pedir no arma una combinación."""
    now = now or datetime.now(UTC)
    by_service = {payload: service for service, payload in load_combos().services.items()}
    for days in (CURRENT_COMBO_DAYS, LAPSED_COMBO_DAYS):
        since = now - timedelta(days=days)
        verticals = [
            v
            for (v,) in conn.execute(
                """SELECT DISTINCT vertical FROM app_orders
                   WHERE user_id = %s AND mode = 'propuesta' AND ts > %s AND ts <= %s""",
                (user_id, since, now),
            )
        ]
        if verticals:
            opened = conn.execute(
                """SELECT DISTINCT payload ->> 'servicio' FROM app_events
                   WHERE user_id = %s AND type = 'service_opened' AND ts > %s AND ts <= %s
                     AND coalesce(payload ->> 'mode', '') <> 'actual'""",
                (user_id, since, now),
            ).fetchall()
            return fine_of(verticals, [by_service[s] for (s,) in opened if s in by_service])
    return NONE_COMBO


def target_step(conn: Connection, user_id: str, population: str | None = None) -> Step | None:
    """El paso que más retención le suma a la persona (`combos.next_fine_step`) desde su combinación fina
    (`current_fine`), con la retención de Rappi mezclada con la aprendida (gruesa y fina) en `combo_stats` de la
    población. Los candidatos son las verticales que el agente puede ofrecer, en el orden de `next_verticals` de la
    persona (que desempata), y al final los servicios; `None` si no hay paso."""
    population = population or config.MOTOR_POBLACION
    fine = current_fine(conn, user_id)
    if fine == NONE_COMBO:
        return None
    ranked = [s.vertical for s in next_verticals(conn, user_id, population)]
    candidates = [v for v in ranked if offerable_vertical(v) and v not in OWN_SIGNALS_ONLY] + list(SERVICES)
    learned_coarse = _learned_retention(conn, population)
    learned_fine = _learned_fine_retention(conn, population)
    return next_fine_step(fine, candidates, learned_coarse, learned_fine)


def step_signal(conn: Connection, step: Step, population: str | None = None) -> dict:
    """La señal `combinacion` de un paso (`target_step`) para la `basis` de una oferta: «<actual>→<objetivo>», con sus
    combinaciones finas sin Farmacia ni Licores (cuentan en el paso, pero la base no los nombra). Su fuente parte de la
    tabla de Rappi («rappi»), suma «+supuesto» si pesó el supuesto propio del rendimiento decreciente y
    «+poblacion:<fuente>» si pesó la retención aprendida de la población (gruesa o fina, con al menos
    `LEARNED_RETENTION_MIN_USERS` personas) en la combinación actual o en la objetivo."""
    population = population or config.MOTOR_POBLACION
    coarse = _learned_retention(conn, population)
    fine = _learned_fine_retention(conn, population)
    enough = LEARNED_RETENTION_MIN_USERS
    weighed = any(
        fine.get(combo, (0, 0.0))[0] >= enough or coarse.get(_coarse_of(combo), (0, 0.0))[0] >= enough
        for combo in (step.current, step.target)
    )
    source = "rappi" + ("+supuesto" if step.used_assumption else "") + (f"+poblacion:{population}" if weighed else "")
    return {"kind": "combinacion", "id": f"{_nameable(step.current)}→{_nameable(step.target)}", "source": source}


def _nameable(fine: str) -> str:
    """La combinación fina sin las verticales que el agente no propone por su cuenta (`OWN_SIGNALS_ONLY`: Farmacia y
    Licores): la `basis` de una oferta no las nombra, aunque la persona haya pedido ahí y cuenten en su combinación."""
    if fine == NONE_COMBO:
        return fine
    return "+".join(m for m in fine.split("+") if m not in OWN_SIGNALS_ONLY) or NONE_COMBO


def _coarse_of(fine: str) -> str | None:
    """La combinación gruesa de la que parte la retención de una fina: la de sus verticales del catálogo; solo
    servicios, «favor» si está RappiFavor (RappiTravel solo no tiene fila)."""
    members = [] if fine == NONE_COMBO else fine.split("+")
    catalog = [m for m in members if m not in SERVICES]
    if catalog or not members:
        return combo_of_verticals(catalog)
    return SERVICE_COMBO if SERVICE_COMBO in members else None


def _learned_retention(conn: Connection, population: str) -> dict[str, tuple[int, float]]:
    """combinación → (personas, retención M+1) aprendidas en `combo_stats` (nivel grueso) de la población."""
    return {
        combo: (n, float(retention))
        for combo, n, retention in conn.execute(
            """SELECT combo, retention_n, retention_m1 FROM combo_stats
               WHERE data_source = %s AND nivel = 'grueso' AND retention_m1 IS NOT NULL""",
            (population,),
        )
    }


def _learned_fine_retention(conn: Connection, population: str) -> dict[str, tuple[int, float]]:
    """combinación fina → (personas, retención M+1) aprendidas en `combo_stats` (nivel fino) de la población."""
    return {
        combo: (n, float(retention))
        for combo, n, retention in conn.execute(
            """SELECT combo, retention_n, retention_m1 FROM combo_stats
               WHERE data_source = %s AND nivel = 'fino' AND retention_m1 IS NOT NULL""",
            (population,),
        )
    }


def source_of(conn: Connection, user_id: str) -> str | None:
    row = conn.execute("SELECT source FROM app_users WHERE user_id = %s", (user_id,)).fetchone()
    return row[0] if row else None
