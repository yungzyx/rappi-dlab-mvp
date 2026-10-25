"""Lo que el motor lee de la base: pedidos con sus líneas y señales de afinidad, siempre de una sola fuente.

`synthetic` y `prototype` nunca se mezclan: cada función filtra la fuente de la persona, del pedido y del evento. Lo que
pasa en «Rappi hoy» no enseña: solo entran pedidos `mode = 'propuesta'` y ningún evento con `payload.mode = 'actual'`.
"""

from dataclasses import dataclass
from datetime import datetime

from psycopg import Connection

# Tipo de evento → clase de señal (las claves de `model.AFFINITY_WEIGHTS`, salvo «order», que sale de los pedidos).
EVENT_KINDS = ("cart_add", "vertical_open", "view_store", "search", "view_item")


@dataclass(frozen=True)
class Line:
    concept_id: str | None
    entity_type: str
    entity_id: str
    from_suggestion: bool


@dataclass(frozen=True)
class Order:
    user_id: str
    order_id: str
    cart_id: str | None
    ts: datetime
    vertical: str
    total: float
    lines: tuple[Line, ...]


@dataclass(frozen=True)
class Signal:
    user_id: str
    ts: datetime
    kind: str
    vertical: str


def _filters(
    source: str, user_id: str | list[str] | None, before: datetime | None, table: str, since: datetime | None = None
) -> tuple[str, list]:
    """Las condiciones comunes: fuente de la persona y del registro, persona (o lista de personas) y cortes de tiempo
    opcionales."""
    sql = f"u.source = %s AND {table}.source = %s"
    params: list = [source, source]
    if isinstance(user_id, list):
        sql += f" AND {table}.user_id = ANY(%s)"
        params.append(user_id)
    elif user_id is not None:
        sql += f" AND {table}.user_id = %s"
        params.append(user_id)
    if before is not None:
        sql += f" AND {table}.ts < %s"
        params.append(before)
    if since is not None:
        sql += f" AND {table}.ts > %s"
        params.append(since)
    return sql, params


def load_orders(
    conn: Connection,
    source: str,
    user_id: str | list[str] | None = None,
    before: datetime | None = None,
    since: datetime | None = None,
) -> list[Order]:
    """Los pedidos `propuesta` de la fuente (de una persona o de una lista, anteriores a `before` y posteriores a
    `since`, si se piden), en orden de `ts`."""
    where, params = _filters(source, user_id, before, "o", since)
    rows = conn.execute(
        f"""SELECT o.order_id, o.user_id, o.cart_id, o.ts, o.vertical, o.total,
                   l.concept_id, l.entity_type, l.entity_id, l.from_suggestion
            FROM app_orders o
            JOIN app_users u USING (user_id)
            LEFT JOIN app_order_lines l USING (order_id)
            WHERE o.mode = 'propuesta' AND {where}
            ORDER BY o.ts, o.order_id, l.line_no""",
        params,
    ).fetchall()
    heads: dict[str, tuple] = {}
    lines: dict[str, list[Line]] = {}
    for order_id, user, cart_id, ts, vertical, total, concept_id, entity_type, entity_id, suggested in rows:
        if order_id not in heads:
            heads[order_id] = (user, order_id, cart_id, ts, vertical, float(total))
            lines[order_id] = []
        if entity_type is not None:
            lines[order_id].append(Line(concept_id, entity_type, entity_id, suggested))
    return [Order(*head, tuple(lines[order_id])) for order_id, head in heads.items()]


def load_signals(
    conn: Connection,
    source: str,
    user_id: str | list[str] | None = None,
    before: datetime | None = None,
    orders: list[Order] | None = None,
) -> list[Signal]:
    """Las señales de afinidad de la fuente en orden de `ts`: cada pedido `propuesta` (`kind="order"`) y los eventos
    con vertical de `EVENT_KINDS`, sin los hechos en «Rappi hoy». `orders`: lo que da `load_orders` con la misma fuente,
    personas y `before`, si quien llama ya lo leyó (así no se lee dos veces)."""
    if orders is None:
        orders = load_orders(conn, source, user_id, before)
    signals = [Signal(o.user_id, o.ts, "order", o.vertical) for o in orders]
    where, params = _filters(source, user_id, before, "e")
    rows = conn.execute(
        f"""SELECT e.user_id, e.ts, e.type, e.vertical
            FROM app_events e
            JOIN app_users u USING (user_id)
            WHERE e.type = ANY(%s) AND e.vertical IS NOT NULL
              AND e.payload->>'mode' IS DISTINCT FROM 'actual' AND {where}
            ORDER BY e.ts, e.event_id""",
        [list(EVENT_KINDS), *params],
    ).fetchall()
    signals += [Signal(*row) for row in rows]
    signals.sort(key=lambda s: s.ts)  # estable: a igual hora, el pedido va antes que el evento
    return signals


def sensitive_concepts(conn: Connection) -> frozenset[str]:
    """Los conceptos sensibles: nunca entran a compra cruzada, tendencias de concepto ni recompra."""
    return frozenset(r[0] for r in conn.execute("SELECT concept_id FROM concepts WHERE sensitive"))
