"""«¿Volvemos a…?» (el momento `volver` de `POST /agent/offer`): a quién le toca una invitación a volver a pedir algo
que pedía con ritmo y dejó de pedir. Complementa a la recompra («¿Repetimos?»), que solo ofrece lo que toca ahora: las
dos ventanas no se tocan.

Quién califica (con el día `today` de Santiago):
- **Un concepto** de su tabla `replenishment` (el motor la recalcula con sus pedidos `propuesta`; ya sin sensibles)
  atrasado más de un intervalo, justo lo que la recompra deja de ofrecer (`repeat_due`), con su último pedido hace
  entre `LAPSE_MIN_DAYS` y `LAPSE_MAX_DAYS` días.
- **Una vertical** donde pidió al menos `VERTICAL_MIN_DAYS` días distintos y no pide hace más de
  `VERTICAL_LAPSE_DAYS` días (y no más de `LAPSE_MAX_DAYS`), mientras sigue pidiendo en otra en esos días.

Solo conceptos que el agente propone por su cuenta y verticales que ofrece (nunca Farmacia ni Licores), con pantalla en
la app. Por persona, primero los conceptos (el hábito más fuerte: más días de compra, después el menos atrasado
respecto de su ritmo) y después las verticales (más días con pedido, después la más reciente).

Para no insistir (`available`): la pausa es por persona. Si en los últimos `COOLDOWN_DAYS` días se le mostró una
invitación, solo puede volver esa misma (si sigue calificando) y ninguna otra; una invitación descartada
`MAX_DISMISSALS` veces después de su último pedido de eso no se ofrece más. Cuenta lo que registra la app con el origen
`agent-volver` (`payload.kind` dice si es de un concepto o de una vertical); lo hecho en «Rappi hoy» no cuenta.

`reach` estima a cuántas personas de una fuente les tocaría, para el panel: con datos simulados no es evidencia.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from psycopg import Connection

from ..agent.grouped_search import SCREEN_VERTICALS
from ..concepts.taxonomy import load_taxonomy
from ..motor.model import TZ
from .guards import is_offerable, offerable_vertical

REPEAT_AHEAD_DAYS = 2  # la recompra se ofrece desde 2 días antes del día en que le toca
LAPSE_MIN_DAYS = 14  # menos que esto no es haber dejado de pedir, aunque el ritmo sea diario
LAPSE_MAX_DAYS = 90  # más que esto ya es otra persona: no se le recuerda lo de hace meses
VERTICAL_LAPSE_DAYS = 30  # una vertical sin pedidos en más de un mes (la combinación del motor mira 30 días)
VERTICAL_MIN_DAYS = 3  # días distintos con pedido en la vertical: como la recompra, un ritmo y no una vez
COOLDOWN_DAYS = 7  # la misma invitación no se repite antes
MAX_DISMISSALS = 2  # descartada estas veces después de su último pedido de eso, no se ofrece más
ORIGIN = "agent-volver"  # `payload.origen` de lo que la app registra de esta oferta
# La señal de la `basis` de cada tipo de invitación, que la app también manda en `payload.kind` de sus eventos.
BASIS_KINDS = {"concepto": "volver", "vertical": "vuelta"}


@dataclass(frozen=True)
class Lapse:
    user_id: str
    kind: str  # "concepto" o "vertical"
    key: str  # el concepto o la vertical
    vertical: str  # donde se ofrece
    days: int  # días desde su último pedido de eso
    orders: int  # días distintos con pedido de eso
    interval: int | None  # cada cuántos días lo pedía (solo los conceptos)
    last_ts: datetime


def repeat_due(due_on: date, interval_days: float, today: date) -> bool:
    """Si a una fila de `replenishment` le toca la recompra: desde `REPEAT_AHEAD_DAYS` días antes del día en que le toca
    hasta un intervalo después."""
    late = today - timedelta(days=round(interval_days))
    return late <= due_on <= today + timedelta(days=REPEAT_AHEAD_DAYS)


def _offerable_concept(concept_id: str, vertical: str | None) -> bool:
    concept = load_taxonomy().concepts.get(concept_id)
    return concept is not None and is_offerable(concept) and _offerable_vertical(vertical)


def _offerable_vertical(vertical: str | None) -> bool:
    return vertical is not None and offerable_vertical(vertical) and vertical in SCREEN_VERTICALS


def _who(user_id: str | None, source: str | None, alias: str) -> tuple[str, list]:
    """La condición de persona (una) o de fuente (todas las suyas)."""
    if user_id is not None:
        return f"{alias}.user_id = %s", [user_id]
    return "u.source = %s", [source]


def _concept_lapses(conn: Connection, today: date, user_id: str | None, source: str | None) -> list[Lapse]:
    where, params = _who(user_id, source, "r")
    rows = conn.execute(
        f"""SELECT r.user_id, r.concept_id, r.vertical, r.orders, r.interval_days, r.last_ts, r.due_on
            FROM replenishment r JOIN app_users u USING (user_id)
            WHERE r.vertical IS NOT NULL AND {where}""",
        params,
    ).fetchall()
    out = []
    for user, concept_id, vertical, orders, interval, last_ts, due_on in rows:
        days = (today - last_ts.astimezone(TZ).date()).days
        late = due_on < today - timedelta(days=round(interval))  # lo que la recompra ya no ofrece
        if late and LAPSE_MIN_DAYS <= days <= LAPSE_MAX_DAYS and _offerable_concept(concept_id, vertical):
            out.append(Lapse(user, "concepto", concept_id, vertical, days, orders, round(interval), last_ts))
    return out


def _vertical_lapses(conn: Connection, today: date, user_id: str | None, source: str | None) -> list[Lapse]:
    """Las verticales que dejó (`propuesta`, de la fuente de la persona). Los pedidos posteriores a `today` (la
    referencia del panel en datos simulados) no cuentan."""
    where, params = _who(user_id, source, "o")
    end = datetime.combine(today + timedelta(days=1), datetime.min.time(), TZ)
    rows = conn.execute(
        f"""SELECT o.user_id, o.vertical, count(DISTINCT timezone(%s, o.ts)::date), max(o.ts)
            FROM app_orders o JOIN app_users u USING (user_id)
            WHERE o.mode = 'propuesta' AND o.source = u.source AND o.ts < %s AND {where}
            GROUP BY 1, 2""",
        [TZ.key, end, *params],
    ).fetchall()
    by_user: dict[str, list[tuple[str, int, datetime, int]]] = defaultdict(list)
    for user, vertical, orders, last_ts in rows:
        by_user[user].append((vertical, orders, last_ts, (today - last_ts.astimezone(TZ).date()).days))
    out = []
    for user, verticals in by_user.items():
        active = {v for v, _, _, days in verticals if days <= VERTICAL_LAPSE_DAYS}
        for vertical, orders, last_ts, days in verticals:
            if (
                VERTICAL_LAPSE_DAYS < days <= LAPSE_MAX_DAYS
                and orders >= VERTICAL_MIN_DAYS
                and active - {vertical}
                and _offerable_vertical(vertical)
            ):
                out.append(Lapse(user, "vertical", vertical, vertical, days, orders, None, last_ts))
    return out


def _rank(lapse: Lapse) -> tuple:
    """Primero los conceptos (más días de compra, y el menos atrasado respecto de su ritmo); después las verticales
    (más días con pedido, y la más reciente). El id desempata."""
    if lapse.kind == "concepto":
        return (0, -lapse.orders, lapse.days / max(lapse.interval or 1, 1), lapse.key)
    return (1, -lapse.orders, lapse.days, lapse.key)


def lapses(
    conn: Connection, today: date, *, user_id: str | None = None, source: str | None = None
) -> dict[str, list[Lapse]]:
    """persona → sus invitaciones posibles, en orden (`_rank`), de una persona (`user_id`) o de todas las de una fuente
    (`source`). Sin mirar lo ya mostrado ni descartado (`available`)."""
    found: dict[str, list[Lapse]] = defaultdict(list)
    for lapse in [*_concept_lapses(conn, today, user_id, source), *_vertical_lapses(conn, today, user_id, source)]:
        found[lapse.user_id].append(lapse)
    return {user: sorted(items, key=_rank) for user, items in found.items()}


def _same(lapse: Lapse, kind: str | None, concept: str | None, vertical: str | None) -> bool:
    """Si un evento de la app es de esta invitación: la de un concepto lleva su concepto (y `payload.kind` «volver» o
    nada); la de una vertical, `payload.kind` «vuelta» y su vertical. Así una invitación de concepto en el súper no
    cuenta como la del súper."""
    if lapse.kind == "concepto":
        return kind != BASIS_KINDS["vertical"] and concept == lapse.key
    return kind == BASIS_KINDS["vertical"] and vertical == lapse.key


def available(conn: Connection, user_id: str, candidates: list[Lapse], now: datetime | None = None) -> list[Lapse]:
    """Las invitaciones de `candidates` (en su orden) que se pueden mostrar ahora:
    - sin las de un concepto que la persona volvió a pedir después de su fila de `replenishment` (el motor la recalcula
      en segundo plano después del pedido);
    - sin las descartadas `MAX_DISMISSALS` veces después de su último pedido de eso;
    - la pausa es por persona: si en los últimos `COOLDOWN_DAYS` días se le mostró una, solo esa, si sigue calificando
      (y si no, ninguna).
    Cuentan los eventos con origen `agent-volver`; los de «Rappi hoy» (`payload.mode = 'actual'`) no."""
    if not candidates:
        return []
    now = now or datetime.now(UTC)
    concepts = [lapse.key for lapse in candidates if lapse.kind == "concepto"]
    ordered = dict(
        conn.execute(
            """SELECT l.concept_id, max(o.ts) FROM app_order_lines l JOIN app_orders o USING (order_id)
               WHERE o.user_id = %s AND o.mode = 'propuesta' AND l.concept_id = ANY(%s) GROUP BY 1""",
            (user_id, concepts),
        ).fetchall()
    )
    rows = conn.execute(
        """SELECT type, payload ->> 'kind', concept_id, vertical, ts FROM app_events
           WHERE user_id = %s AND type IN ('suggestion_shown', 'suggestion_dismissed')
             AND payload ->> 'origen' = %s AND payload ->> 'mode' IS DISTINCT FROM 'actual'
           ORDER BY ts DESC, event_id DESC""",
        (user_id, ORIGIN),
    ).fetchall()
    open_ = [
        lapse
        for lapse in candidates
        if not (lapse.kind == "concepto" and ordered.get(lapse.key, lapse.last_ts) > lapse.last_ts)
        and sum(
            kind == "suggestion_dismissed" and ts > lapse.last_ts and _same(lapse, payload_kind, concept, vertical)
            for kind, payload_kind, concept, vertical, ts in rows
        )
        < MAX_DISMISSALS
    ]
    recent = next((r for r in rows if r[0] == "suggestion_shown" and r[4] > now - timedelta(days=COOLDOWN_DAYS)), None)
    if recent is None:
        return open_
    return [lapse for lapse in open_ if _same(lapse, *recent[1:4])][:1]


def reference_day(conn: Connection, source: str) -> date | None:
    """El día con que se mide una fuente: el del último pedido simulado (los datos simulados terminan en una fecha
    pasada, como en `motor.build`) u hoy en el prototipo. None si la fuente simulada no tiene pedidos."""
    if source == "prototype":
        return datetime.now(TZ).date()
    last = conn.execute("SELECT max(ts) FROM app_orders WHERE source = %s AND mode = 'propuesta'", (source,)).fetchone()
    return last[0].astimezone(TZ).date() if last[0] else None


def reach(conn: Connection, source: str) -> dict:
    """A cuántas personas de la fuente les tocaría «¿Volvemos a…?» el día de referencia (`reference_day`), por el tipo
    de su primera invitación, y a cuántas la recompra, para comparar. Quien tiene recompra no cuenta como que califica
    (la Home le muestra la recompra). Sin productos ni lo ya mostrado: es quién califica, no a quién se le mostró."""
    today = reference_day(conn, source)
    people = conn.execute(
        "SELECT count(DISTINCT user_id) FROM app_orders WHERE source = %s AND mode = 'propuesta'", (source,)
    ).fetchone()[0]
    found = lapses(conn, today, source=source) if today else {}
    repeat = set()
    if today:
        for user, concept_id, vertical, interval, due_on in conn.execute(
            """SELECT r.user_id, r.concept_id, r.vertical, r.interval_days, r.due_on
               FROM replenishment r JOIN app_users u USING (user_id) WHERE u.source = %s""",
            (source,),
        ):
            if repeat_due(due_on, interval, today) and _offerable_concept(concept_id, vertical):
                repeat.add(user)
    # A quien le toca la recompra, la Home le muestra «¿Repetimos?» y no esta invitación: no califica.
    first = [items[0].kind for user, items in found.items() if user not in repeat]
    return {
        "dia": today.isoformat() if today and source != "prototype" else None,
        "personas": people,
        "califican": len(first),
        "por_concepto": first.count("concepto"),
        "por_vertical": first.count("vertical"),
        "recompra": len(repeat),
    }
