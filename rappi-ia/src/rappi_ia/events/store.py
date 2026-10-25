"""Registro de eventos de la app (prototipo) y perfil de intereses por concepto.

Privacidad (docs/diseno-ia.md §2): las consultas se guardan con datos personales redactados y se borran a los
90 días; los conceptos sensibles no entran al perfil; "Olvidar" borra los eventos, no solo el perfil.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from psycopg import Connection
from psycopg.types.json import Jsonb

from ..catalog.stores import offer_price, store_prices
from ..concepts.matcher import KeywordMatcher
from ..concepts.taxonomy import load_taxonomy

EVENT_TYPES = {
    "app_open",
    "search",
    "chat",  # tipo anterior de `ask`: los clientes y los datos viejos lo siguen mandando
    "ask",
    "view_store",
    "view_item",
    "cart_add",
    "cart_remove",
    "checkout_start",
    "order_placed",
    "suggestion_shown",
    "suggestion_accepted",
    "suggestion_dismissed",
    "recommendation_click",
    "service_shown",  # el agente ofreció un servicio sin catálogo (payload.servicio)
    "service_opened",  # se tocó el botón que abre ese servicio
    "vertical_open",  # se abrió un vertical desde la Home (en el campo `vertical`); alimenta la afinidad del motor
}
# Lo que el cliente puede mandar a /events: `order_placed` nace solo en /orders, con un pedido guardado detrás.
CLIENT_EVENT_TYPES = EVENT_TYPES - {"order_placed"}
QUERY_RETENTION_DAYS = 90
HALF_LIFE_DAYS = 14  # el interés se reduce a la mitad cada 2 semanas sin actividad
# Solo señales positivas del propio usuario. Lo que el agente mostró (suggestion_shown), lo que rechazó
# (suggestion_dismissed) o sacó del carro (cart_remove) no suma interés.
WEIGHTS = {
    "order_placed": 5.0,
    "cart_add": 3.0,
    "suggestion_accepted": 3.0,
    "view_item": 1.5,
    "view_store": 1.0,
    "search": 1.0,
    "chat": 1.0,
    "ask": 1.0,
    "recommendation_click": 2.0,
}

_DASH = "[-‐‑‒–—]"
_EMAIL = re.compile(r"[\w.+-]+\s?@\s?[\w-]+(?:\.[\w-]+)+")
_RUT = re.compile(r"(?<!\d)(\d{1,2})[.\s]?(\d{3})[.\s]?(\d{3})\s*" + _DASH + r"\s*([\dkK])(?!\w)")
_CARD = re.compile(r"(?<!\d)(?:\d[\s-]?){12,18}\d(?!\d)")
# Teléfono chileno: celular 9 + 8 dígitos o fijo (código de área + 7-8 dígitos), con +56 opcional.
_PHONE = re.compile(
    r"(?<![\d$])(?:\+?\s?56[\s.-]*)?(?:9[\s.-]*\d{4}[\s.-]*\d{4}|\d{1,2}[\s.-]*\d{3,4}[\s.-]*\d{4})(?!\d)"
)
_STREET_TYPES = r"(?:calle|av(?:da)?\.?|avenida|pasaje|psje\.?|pje\.?|camino|ruta)"
_TAIL = r"(?:\s*(?:depto|dpto|departamento|of|oficina|casa)\.?\s*\w+)?"
_ADDRESS = re.compile(
    r"\b" + _STREET_TYPES + r"\s+(?P<name>[^\d,;\n]{2,40}?)\s*(?:n[°º]\.?\s*|#\s*)?\d{1,5}\b" + _TAIL,
    re.IGNORECASE,
)
# Sin tipo de calle: solo con una frase que anuncia la dirección ("vivo en Los Leones 123").
_ADDRESS_CONTEXT = re.compile(
    r"(?P<intro>vivo en|mi direcci[oó]n(?: es)?|despacho a|entregar en|env[ií]a(?:lo)? a|manda(?:lo)? a|estoy en"
    r"|queda en)\s+[^\d,;\n]{2,40}?\s*"
    r"(?:n[°º]\.?\s*|#\s*)?\d{1,5}\b" + _TAIL,
    re.IGNORECASE,
)
# Un nombre propio tras «me llamo» o «mi nombre es» (con mayúscula: «me llamo la atención» no es un nombre).
_NAME = re.compile(r"(?P<intro>me llamo|mi nombre es)\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+){0,2}")
_NOT_A_STREET = {"para", "de", "la", "el", "los", "las", "con", "sin", "y", "a", "en", "por", "que", "un", "una"}


def _rut_valid(body: str, check: str) -> bool:
    total, factor = 0, 2
    for digit in reversed(body):
        total += int(digit) * factor
        factor = 2 if factor == 7 else factor + 1
    expected = 11 - total % 11
    return check.upper() == {10: "K", 11: "0"}.get(expected, str(expected))


def _luhn(number: str) -> bool:
    digits = [int(d) for d in re.sub(r"\D", "", number)]
    doubled = [d if i % 2 == 0 else (d * 2 - 9 if d * 2 > 9 else d * 2) for i, d in enumerate(reversed(digits))]
    return 13 <= len(digits) <= 19 and sum(doubled) % 10 == 0


def _street(match: re.Match) -> str:
    """ "calle para 4" no es una dirección: el nombre de la calle debe tener alguna palabra que no sea de relleno."""
    return "[dirección]" if set(match.group("name").lower().split()) - _NOT_A_STREET else match.group(0)


def redact(text: str | None) -> str | None:
    """Quita correo, RUT (válido), tarjetas (Luhn), teléfonos chilenos, nombres y direcciones antes de guardar una
    consulta."""
    if text is None:
        return None
    text = _EMAIL.sub("[correo]", text)
    text = _RUT.sub(lambda m: "[rut]" if _rut_valid("".join(m.groups()[:3]), m.group(4)) else m.group(0), text)
    text = _CARD.sub(lambda m: "[tarjeta]" if _luhn(m.group(0)) else m.group(0), text)
    text = _PHONE.sub("[teléfono]", text)
    text = _ADDRESS.sub(_street, text)
    text = _NAME.sub(lambda m: f"{m.group('intro')} [nombre]", text)
    return _ADDRESS_CONTEXT.sub(lambda m: f"{m.group('intro')} [dirección]", text)


@dataclass
class Event:
    user_id: str
    session_id: str
    type: str
    ts: datetime | None = None
    vertical: str | None = None
    concept_id: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    cart_id: str | None = None
    query: str | None = None
    modality: str | None = None
    results: int | None = None
    unmet: bool | None = None
    value: float | None = None
    payload: dict = field(default_factory=dict)


def ensure_user(conn: Connection, user_id: str, source: str = "prototype", **extra) -> None:
    """Crea el usuario si no existe. Un id de otra fuente no se puede usar: con la API abierta a la red, el prototipo
    podía colgarles eventos a los usuarios simulados (ids correlativos). Una persona del prototipo que se crea aquí
    llegó con su token (la API lo exige): queda con `token_issued_at`, así nadie la reclama como id viejo."""
    row = conn.execute(
        """INSERT INTO app_users (user_id, source, segment, city, consent_notifications, token_issued_at)
           VALUES (%s, %s, %s, %s, %s, CASE WHEN %s = 'prototype' THEN now() END)
           ON CONFLICT (user_id) DO UPDATE SET source = app_users.source
           RETURNING source""",
        (user_id, source, extra.get("segment"), extra.get("city"), extra.get("consent", False), source),
    ).fetchone()
    if row[0] != source:
        raise ValueError(f"El usuario {user_id} es de otra fuente")


def _known_concepts(conn: Connection) -> set[str]:
    """Conceptos sembrados en la base: los que acepta la llave foránea. Uno nuevo de taxonomy.toml que aún no se
    siembra (`rappi-ia concepts`) se guarda como desconocido en vez de tumbar el registro."""
    return {row[0] for row in conn.execute("SELECT concept_id FROM concepts")}


def record(conn: Connection, events: list[Event], source: str = "prototype") -> int:
    """Guarda eventos válidos (tipo conocido, concepto existente) y devuelve cuántos. Cada persona del lote se crea una
    sola vez (un lote de la app trae hasta 200 eventos de una misma persona)."""
    unknown = next((e.type for e in events if e.type not in EVENT_TYPES), None)
    if unknown is not None:
        raise ValueError(f"Tipo de evento desconocido: {unknown}")
    for user_id in dict.fromkeys(e.user_id for e in events):
        ensure_user(conn, user_id, source)
    known = _known_concepts(conn)
    rows = []
    for e in events:
        rows.append(
            (
                e.user_id,
                e.session_id,
                e.ts,
                e.type,
                e.vertical,
                e.concept_id if e.concept_id in known else None,
                e.entity_type,
                e.entity_id,
                e.cart_id,
                redact(e.query),
                e.modality,
                e.results,
                e.unmet,
                e.value,
                Jsonb(e.payload),
                source,
            )
        )
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO app_events (user_id, session_id, ts, type, vertical, concept_id, entity_type, entity_id,
                                       cart_id, query, modality, results, unmet, value, payload, source)
               VALUES (%s, %s, coalesce(%s, now()), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            rows,
        )
    return len(rows)


def record_order(
    conn: Connection,
    user_id: str,
    session_id: str,
    cart_id: str,
    vertical: str,
    lines: list[dict],
    source: str = "prototype",
    ts: datetime | None = None,
    mode: str = "propuesta",
) -> str:
    """Pedido + líneas (producto o plato) + evento `order_placed`. Los precios de `lines` se guardan tal cual: la API
    los pone antes con `catalog_prices`. Un pedido en modo `actual` («Rappi hoy») no entra al perfil."""
    order_id = f"ord-{uuid.uuid4().hex[:12]}"
    total = sum(float(line.get("unit_price") or 0) * int(line.get("qty", 1)) for line in lines)
    ensure_user(conn, user_id, source)
    conn.execute(
        """INSERT INTO app_orders (order_id, user_id, session_id, cart_id, ts, vertical, total, source, mode)
           VALUES (%s, %s, %s, %s, coalesce(%s, now()), %s, %s, %s, %s)""",
        (order_id, user_id, session_id, cart_id, ts, vertical, total, source, mode),
    )
    known = _known_concepts(conn)
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO app_order_lines (order_id, line_no, entity_type, entity_id, concept_id, qty, unit_price,
                                            from_suggestion)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            [
                (
                    order_id,
                    i,
                    line["entity_type"],
                    line["entity_id"],
                    # En «Rappi hoy» no se aprende: la línea no guarda concepto, como los eventos de ese modo.
                    line.get("concept_id") if mode == "propuesta" and line.get("concept_id") in known else None,
                    int(line.get("qty", 1)),
                    line.get("unit_price"),
                    bool(line.get("from_suggestion")),
                )
                for i, line in enumerate(lines, start=1)
            ],
        )
    record(
        conn,
        [
            Event(
                user_id,
                session_id,
                "order_placed",
                ts=ts,
                vertical=vertical,
                cart_id=cart_id,
                value=total,
                payload={"order_id": order_id, "lines": len(lines)},
            )
        ],
        source,
    )
    return order_id


def catalog_prices(conn: Connection, lines: list[dict]) -> tuple[list[dict], int]:
    """Las líneas de un pedido del cliente con el precio vigente del catálogo en su tienda (`offer_price`): el que
    manda el cliente no se usa, porque el total alimenta segmentos y métricas. Devuelve las líneas con precio y cuántas
    se omitieron (agotadas, de una tienda que no las vende o que no están en el catálogo). Los productos con tienda (lo
    normal) salen en una sola consulta; un plato o un producto sin tienda, uno por uno."""
    in_store = [
        i for i, line in enumerate(lines) if line["entity_type"] == "catalog_item" and line.get("store_id") is not None
    ]
    in_store_prices = store_prices(conn, [(lines[i]["entity_id"], lines[i]["store_id"]) for i in in_store])
    known = dict(zip(in_store, in_store_prices, strict=True))
    priced = []
    for i, line in enumerate(lines):
        if i in known:
            price = known[i]
        else:
            price = offer_price(conn, line["entity_type"], line["entity_id"], line.get("store_id"))
        if price is not None:
            priced.append({**line, "unit_price": price})
    return priced, len(lines) - len(priced)


def profile(conn: Connection, user_id: str, now: datetime | None = None) -> dict[str, float]:
    """Interés por concepto con decaimiento exponencial (vida media 14 días). Sin conceptos sensibles."""
    sensitive = [c.id for c in load_taxonomy().concepts.values() if c.sensitive]
    rows = conn.execute(
        """SELECT concept_id, type, extract(epoch FROM (coalesce(%(now)s, now()) - ts)) / 86400.0 AS days
           FROM app_events
           WHERE user_id = %(user)s AND concept_id IS NOT NULL AND concept_id <> ALL(%(sensitive)s)
             AND type = ANY(%(types)s)""",
        {"now": now, "user": user_id, "sensitive": sensitive, "types": list(WEIGHTS)},
    ).fetchall()
    scores: dict[str, float] = {}
    for concept_id, event_type, days in rows:
        weight = WEIGHTS[event_type] * 0.5 ** (max(float(days), 0) / HALF_LIFE_DAYS)
        scores[concept_id] = scores.get(concept_id, 0.0) + weight
    return {c: round(s, 3) for c, s in sorted(scores.items(), key=lambda kv: -kv[1]) if s >= 0.05}


def forget(conn: Connection, user_id: str, concept_id: str | None = None) -> int:
    """'Olvidar' (docs/diseno-ia.md §2). Sin concepto: borra al usuario entero (eventos, pedidos y líneas en
    cascada). Con concepto: borra sus eventos de ese concepto, lo quita de sus líneas de pedido y borra el texto de
    las consultas que lo nombran. Devuelve cuántos registros se borraron o anonimizaron."""
    if conn.execute(
        "SELECT 1 FROM app_users WHERE user_id = %s AND source <> 'prototype'", (user_id,)
    ).fetchone():  # «Olvidar» es del prototipo: nunca borra usuarios simulados
        return 0
    from ..layers.segments import build_segments, lock_user_segments

    lock_user_segments(conn, user_id)  # espera un recálculo de segmentos en curso (después de un pedido)
    if concept_id is None:
        events = conn.execute("SELECT count(*) FROM app_events WHERE user_id = %s", (user_id,)).fetchone()[0]
        orders = conn.execute("SELECT count(*) FROM app_orders WHERE user_id = %s", (user_id,)).fetchone()[0]
        conn.execute("DELETE FROM app_users WHERE user_id = %s", (user_id,))
        return events + orders
    deleted = conn.execute(
        "DELETE FROM app_events WHERE user_id = %s AND concept_id = %s", (user_id, concept_id)
    ).rowcount
    deleted += conn.execute(
        """UPDATE app_order_lines l SET concept_id = NULL FROM app_orders o
           WHERE o.order_id = l.order_id AND o.user_id = %s AND l.concept_id = %s""",
        (user_id, concept_id),
    ).rowcount
    concept = load_taxonomy().concepts.get(concept_id)
    if concept is not None:
        matcher = KeywordMatcher((concept.id, kw) for kw in (concept.name, *concept.keywords, *concept.query_keywords))
        rows = conn.execute(
            "SELECT event_id, query FROM app_events WHERE user_id = %s AND query IS NOT NULL", (user_id,)
        ).fetchall()
        mentions = [event_id for event_id, query in rows if matcher.best(query)]
        if mentions:
            deleted += conn.execute("UPDATE app_events SET query = NULL WHERE event_id = ANY(%s)", (mentions,)).rowcount
    # Sus segmentos se recalculan sin lo que olvidó.
    # La historia semanal también dice «tenía este segmento»: tras olvidar un concepto no queda nada anterior.
    conn.execute("DELETE FROM user_segment_history WHERE user_id = %s", (user_id,))
    build_segments(conn, "prototype", user_id, commit=False)
    return deleted


def purge_inactive_users(conn: Connection, days: int) -> int:
    """Borra a las personas del prototipo sin actividad en `days` días: sin eventos ni pedidos en
    ese tiempo, y creadas antes (con sus eventos, pedidos y segmentos, en cascada). Los usuarios simulados no se tocan.
    Devuelve cuántas."""
    return conn.execute(
        """WITH cutoff AS (SELECT now() - make_interval(days => %s) AS ts)
           DELETE FROM app_users u USING cutoff
           WHERE u.source = 'prototype' AND u.created_at < cutoff.ts
             AND NOT EXISTS (SELECT 1 FROM app_events e WHERE e.user_id = u.user_id AND e.ts >= cutoff.ts)
             AND NOT EXISTS (SELECT 1 FROM app_orders o WHERE o.user_id = u.user_id AND o.ts >= cutoff.ts)""",
        (days,),
    ).rowcount


def purge_old_queries(conn: Connection, days: int = QUERY_RETENTION_DAYS) -> int:
    """Borra el texto de consultas más antiguas que `days` (quedan los agregados por concepto)."""
    return conn.execute(
        "UPDATE app_events SET query = NULL WHERE query IS NOT NULL AND ts < now() - make_interval(days => %s)",
        (days,),
    ).rowcount
