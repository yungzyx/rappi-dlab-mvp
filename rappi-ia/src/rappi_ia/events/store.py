"""Registro de eventos de la app (prototipo) y perfil de intereses por concepto.

Privacidad (docs/diseno-ia.md §2): las consultas se guardan con datos personales redactados y se borran a los
90 días; los conceptos sensibles no entran al perfil; "Olvidar" borra los eventos, no solo el perfil.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from psycopg import Connection
from psycopg.types.json import Jsonb

from ..catalog.stores import line_prices
from ..concepts.matcher import KeywordMatcher
from ..concepts.taxonomy import load_taxonomy
from . import catalog_context, experiments

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
    "order_rated",  # la calificación de un pedido entregado (`payload.stars` y `payload.reasons`; el pedido, `cart_id`)
    "reorder",  # "Pídelo de nuevo": el carro con un pedido anterior (`payload.available` y `payload.unavailable`)
    "order_cancelled",  # la persona canceló un pedido (`payload.reason` y `.stage`; el pedido, `cart_id` y su tienda)
    "list_view",  # lo que una lista dejó a la vista (sus elementos en `app_event_items`; `position`, la mayor vista)
    "offer_withheld",  # una oferta de Mochi retenida al grupo de control (lo que habría mostrado, en `app_event_items`)
    # Mochi movió los accesos de la Home y dijo por qué (migración 052): el acceso que más subió en `vertical`, su lugar
    # nuevo en `position` y el de antes en `payload.antes`. No enseña al motor (motor/data.py: EVENT_KINDS).
    "vertical_reorder_shown",
    "agent_visibility",  # la persona ocultó a Mochi o lo trajo de vuelta (`payload.visible`; migración 052)
    # Se abrió el "¿Por qué?" de una oferta (migración 053): su origen, el concepto de la razón en `concept_id` y los
    # tipos de su `basis` en `payload.basis` (nunca el texto). No enseña al motor.
    "offer_why_open",
}
# Lo que el cliente puede mandar a /events: `order_placed` nace solo en /orders, con un pedido guardado detrás, y
# `offer_withheld`, solo en /agent/offer, que es quien decide retener la oferta.
CLIENT_EVENT_TYPES = EVENT_TYPES - {"order_placed", "offer_withheld"}
# Los eventos que traen elementos (`app_event_items`), y cuántos como mucho en uno.
ITEM_EVENT_TYPES = frozenset({"list_view", "offer_withheld"})
ITEM_ENTITY_TYPES = frozenset({"catalog_item", "menu_item", "store", "vertical"})
MAX_EVENT_ITEMS = 20
QUERY_RETENTION_DAYS = 90
IMPRESSION_RETENTION_DAYS = 90  # los elementos de las impresiones se borran como el texto de las consultas
# "¿Qué problema tuvo el pedido?" (con 3 estrellas o menos): los motivos que la app puede mandar en `order_rated`.
RATING_REASONS = frozenset({"tarde", "faltante", "mal_estado", "equivocado", "repartidor", "otro"})
LOW_RATING = 3  # 3 estrellas o menos es una calificación mala: pausa la recompra y el "volver" (offers/winback.py)
# "¿Por qué quieres cancelar?": los motivos que la app puede mandar en `order_cancelled`.
CANCEL_REASONS = frozenset({"direccion", "pago", "demora", "productos", "ya_no", "otro"})
# El momento del pedido en que se canceló: antes de que la tienda lo empiece (gratis), ya empezado (con un costo de
# ejemplo en la app) o programado y sin empezar.
CANCEL_STAGES = frozenset({"antes_de_tienda", "en_tienda", "programado"})
# Dónde estaba lo que se tocó, se vio o se agregó: el CHECK de `app_events.surface` (migración 043).
SURFACES = frozenset(
    {
        "home",
        "search",
        "store",
        "vertical",
        "restaurants",
        "turbo",
        "deals",
        "favorites",
        "list",
        "agent",
        "cart",
        "checkout",
        "tracking",
        "orders",
    }
)
ORIGIN = re.compile(r"[a-z0-9_-]{1,40}")  # el CHECK de `app_events.origin`
CLIENT_CLOCK_SKEW = timedelta(hours=24)  # una hora del cliente más lejos que esto de la llegada no se guarda
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
# Un nombre propio tras "me llamo" o "mi nombre es" (con mayúscula: "me llamo la atención" no es un nombre).
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
    # El sobre de la migración 043: id, hora y orden según la app, desde dónde y la respuesta de la API que lo originó.
    client_event_id: uuid.UUID | None = None
    client_ts: datetime | None = None
    seq: int | None = None
    surface: str | None = None
    origin: str | None = None
    position: int | None = None
    request_id: str | None = None
    # Los elementos de un `list_view` u `offer_withheld`: `{position, entity_type, entity_id, concept_id, vertical}`.
    items: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class SessionInfo:
    """Lo que la app cuenta de su sesión (`app_sessions`): versión, plataforma, modo y entrada."""

    app_version: str | None = None
    platform: str | None = None
    mode: str | None = None
    entry: str | None = None


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


def _origin(e: Event) -> str | None:
    """El origen del evento: la columna o, de un cliente de antes de la migración 043, `payload.origen` (solo si tiene
    la forma de un origen: lo demás queda en el payload, como siempre)."""
    if e.origin is not None:
        return e.origin
    legacy = e.payload.get("origen")
    return legacy if isinstance(legacy, str) and ORIGIN.fullmatch(legacy) else None


def _client_ts(e: Event, now: datetime) -> datetime | None:
    """La hora del cliente, si está a menos de `CLIENT_CLOCK_SKEW` de la llegada (o de `ts`, si el evento la trae): un
    reloj mal puesto no reordena la historia."""
    if e.client_ts is None:
        return None
    reference = e.ts or now
    client = e.client_ts if e.client_ts.tzinfo else e.client_ts.replace(tzinfo=UTC)
    return client if abs(client - reference) <= CLIENT_CLOCK_SKEW else None


def record(conn: Connection, events: list[Event], source: str = "prototype", session: SessionInfo | None = None) -> int:
    """Guarda eventos válidos (tipo conocido, concepto existente) y devuelve cuántos entraron. Cada persona del lote se
    crea una sola vez (un lote de la app trae hasta 200 eventos de una misma persona). Un evento con `client_event_id`
    que ya estaba (un lote reintentado) no entra otra vez. Cada sesión del lote queda en `app_sessions` con su primer
    evento (y `session`, lo que la app cuenta de ella: su modo es también la variante de `modo_app` de la persona, si
    aún no tenía). Los elementos de un `list_view` u `offer_withheld` van a `app_event_items`, y `view_store`,
    `view_item` y `cart_add` llevan el catálogo tal como estaba (`payload.catalogo`, events/catalog_context.py)."""
    unknown = next((e.type for e in events if e.type not in EVENT_TYPES), None)
    if unknown is not None:
        raise ValueError(f"Tipo de evento desconocido: {unknown}")
    surface = next((e.surface for e in events if e.surface is not None and e.surface not in SURFACES), None)
    if surface is not None:
        raise ValueError(f"Superficie desconocida: {surface}")
    for e in events:
        _check_items(e)
    ratings = [(e, _rating(e)) for e in events if e.type == "order_rated"]
    cancellations = [e for e in events if e.type == "order_cancelled" and _check_cancellation(e)]
    for user_id in dict.fromkeys(e.user_id for e in events):
        ensure_user(conn, user_id, source)
        if session is not None:
            experiments.assign_mode(conn, user_id, session.mode)
    known = _known_concepts(conn)
    catalog_context.pin(conn, events)
    now = datetime.now(UTC)
    rows = []
    starts: dict[tuple[str, str], datetime | None] = {}
    for e in events:
        client_ts = _client_ts(e, now)
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
                e.client_event_id,
                client_ts,
                e.seq,
                e.surface,
                _origin(e),
                e.position,
                e.request_id,
            )
        )
        start = client_ts or e.ts
        key = (e.user_id, e.session_id)
        if key not in starts or (start is not None and (starts[key] is None or start < starts[key])):
            starts[key] = start
    ids: list[int | None] = []
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO app_events (user_id, session_id, ts, type, vertical, concept_id, entity_type, entity_id,
                                       cart_id, query, modality, results, unmet, value, payload, source,
                                       client_event_id, client_ts, seq, surface, origin, position, request_id)
               VALUES (%s, %s, coalesce(%s, now()), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (user_id, client_event_id) WHERE client_event_id IS NOT NULL DO NOTHING
               RETURNING event_id""",
            rows,
            returning=True,
        )
        if rows:
            ids = _returned_ids(cur, len(rows))
    saved = sum(event_id is not None for event_id in ids)
    _record_items(conn, [(event_id, e) for event_id, e in zip(ids, events, strict=True) if event_id and e.items], known)
    _record_sessions(conn, starts, source, session or SessionInfo())
    _record_ratings(conn, [(e, stars, reasons, _client_ts(e, now) or e.ts or now) for e, (stars, reasons) in ratings])
    _record_cancellations(conn, [(e, _client_ts(e, now) or e.ts or now) for e in cancellations])
    return saved


def _returned_ids(cur, n: int) -> list[int | None]:
    """El `event_id` de cada fila de un `executemany(..., returning=True)`, en orden: None para la que no entró (un
    reintento de un evento que ya estaba)."""
    ids: list[int | None] = []
    while True:
        row = cur.fetchone()
        ids.append(row[0] if row else None)
        if not cur.nextset():
            break
    return ids if len(ids) == n else ids + [None] * (n - len(ids))


def _check_items(e: Event) -> None:
    """Solo `list_view` y `offer_withheld` traen elementos, hasta MAX_EVENT_ITEMS, cada uno con su lugar y un tipo
    conocido. Uno que no cumple rechaza el lote, como un tipo desconocido. Dos en el mismo lugar no: queda el primero
    (`_record_items`), y el lote, con sus eventos de carro, no se pierde por una impresión."""
    if not e.items:
        return
    if e.type not in ITEM_EVENT_TYPES:
        raise ValueError(f"El evento {e.type} no lleva elementos")
    if len(e.items) > MAX_EVENT_ITEMS:
        raise ValueError(f"Demasiados elementos en un evento: {len(e.items)}")
    positions = [item.get("position") for item in e.items]
    if any(not isinstance(p, int) or isinstance(p, bool) or not 0 <= p <= 999 for p in positions):
        raise ValueError("Posición de un elemento inválida")
    if any(item.get("entity_type") not in ITEM_ENTITY_TYPES or not item.get("entity_id") for item in e.items):
        raise ValueError("Elemento sin tipo o sin id")


def _record_items(conn: Connection, saved: list[tuple[int, Event]], known: set[str]) -> None:
    """Los elementos de cada `list_view` u `offer_withheld` que entró. En "Rappi hoy" (`payload.mode = 'actual'`) van
    sin concepto, como sus eventos: ese modo no enseña."""
    rows = [
        (
            event_id,
            item["position"],
            item["entity_type"],
            str(item["entity_id"])[:64],
            item.get("concept_id") if e.payload.get("mode") != "actual" and item.get("concept_id") in known else None,
            item.get("vertical"),
        )
        for event_id, e in saved
        for item in e.items
    ]
    if rows:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO app_event_items (event_id, position, entity_type, entity_id, concept_id, vertical)
                   VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (event_id, position) DO NOTHING""",
                rows,
            )


def _rating(e: Event) -> tuple[int, list[str]]:
    """Las estrellas (1 a 5) y los motivos de un `order_rated`. Unas estrellas que no lo son, un motivo desconocido o un
    evento sin su pedido (`cart_id`) rechazan el lote, como un tipo desconocido."""
    stars, reasons = e.payload.get("stars"), e.payload.get("reasons", [])
    if not isinstance(stars, int) or isinstance(stars, bool) or not 1 <= stars <= 5:
        raise ValueError(f"Calificación inválida: {stars!r}")
    if not isinstance(reasons, list) or any(r not in RATING_REASONS for r in reasons):
        raise ValueError(f"Motivo de calificación desconocido: {reasons!r}")
    if not e.cart_id:
        raise ValueError("Una calificación necesita el pedido (cart_id)")
    _store_of(e)
    return stars, list(dict.fromkeys(reasons))


def _store_of(e: Event) -> int | None:
    """La tienda del pedido de un evento (`payload.store_id`), o None. Una que no es un id rechaza el lote."""
    store_id = e.payload.get("store_id")
    if store_id is not None and (not isinstance(store_id, int) or isinstance(store_id, bool) or store_id < 0):
        raise ValueError(f"Tienda inválida: {store_id!r}")
    return store_id


# El pedido de un evento: el de su carro y su tienda (un carro con dos tiendas son dos pedidos; `payload.store_id`, si
# viene, elige el de la tienda) o, sin tienda, el de su vertical. Sin tienda ni vertical, todos los del carro.
_ORDER_OF_EVENT = """user_id = %(user)s AND cart_id = %(cart)s
    AND (%(store)s::bigint IS NULL OR EXISTS (SELECT 1 FROM app_order_lines l
                                              WHERE l.order_id = app_orders.order_id AND l.store_id = %(store)s))
    AND (%(store)s::bigint IS NOT NULL OR %(vertical)s::text IS NULL OR vertical = %(vertical)s)"""


def _order_of_event(e: Event) -> dict:
    return {"user": e.user_id, "cart": e.cart_id, "store": _store_of(e), "vertical": e.vertical}


def _record_ratings(conn: Connection, ratings: list[tuple[Event, int, list[str], datetime]]) -> None:
    """Cada calificación queda en el pedido de su carro y su tienda (`_ORDER_OF_EVENT`). Las de "Rappi hoy"
    (`payload.mode = 'actual'`) no: ese modo no enseña, y la calificación pausa la recompra. Un pedido cancelado no se
    califica: no llegó."""
    rows = [
        {"stars": stars, "reasons": reasons, "at": rated_at, **_order_of_event(e)}
        for e, stars, reasons, rated_at in ratings
        if e.payload.get("mode") != "actual"
    ]
    if rows:
        with conn.cursor() as cur:
            cur.executemany(
                f"""UPDATE app_orders SET rating = %(stars)s, rating_reasons = %(reasons)s, rated_at = %(at)s
                    WHERE status = 'confirmado' AND {_ORDER_OF_EVENT}""",
                rows,
            )


def _check_cancellation(e: Event) -> bool:
    """Un `order_cancelled` necesita su pedido (`cart_id`), un motivo y una etapa conocidos y, si trae tienda, un id.
    Uno que no cumple rechaza el lote, como un tipo desconocido."""
    if not e.cart_id:
        raise ValueError("Una cancelación necesita el pedido (cart_id)")
    if e.payload.get("reason") not in CANCEL_REASONS:
        raise ValueError(f"Motivo de cancelación desconocido: {e.payload.get('reason')!r}")
    if e.payload.get("stage") not in CANCEL_STAGES:
        raise ValueError(f"Etapa de cancelación desconocida: {e.payload.get('stage')!r}")
    _store_of(e)
    return True


def _record_cancellations(conn: Connection, cancellations: list[tuple[Event, datetime]]) -> None:
    """Cada cancelación deja cancelado el pedido de su carro y su tienda (`_ORDER_OF_EVENT`), en los dos modos: es lo
    que pasó con el pedido. Un pedido ya cancelado no cambia (un reintento no mueve la hora)."""
    rows = [{"reason": e.payload["reason"], "at": at, **_order_of_event(e)} for e, at in cancellations]
    if rows:
        with conn.cursor() as cur:
            cur.executemany(
                f"""UPDATE app_orders SET status = 'cancelado', cancelled_at = %(at)s, cancel_reason = %(reason)s
                    WHERE status = 'confirmado' AND {_ORDER_OF_EVENT}""",
                rows,
            )


def _record_sessions(
    conn: Connection, starts: dict[tuple[str, str], datetime | None], source: str, info: SessionInfo
) -> None:
    """Una fila de `app_sessions` por sesión: la crea su primer evento y los siguientes solo completan lo que faltaba
    (un evento del servidor, como `ask`, no trae la versión de la app) y adelantan el inicio si llegó un evento
    anterior. `variants` es el eco de los experimentos: las variantes de la persona cuando nació la sesión."""
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO app_sessions (user_id, session_id, started_at, app_version, platform, mode, entry, source,
                                         variants)
               VALUES (%s, %s, coalesce(%s, now()), %s, %s, %s, %s, %s,
                       (SELECT jsonb_object_agg(experiment_id, variant) FROM experiment_assignments
                        WHERE user_id = %s))
               ON CONFLICT (user_id, session_id) DO UPDATE SET
                   started_at = least(app_sessions.started_at, EXCLUDED.started_at),
                   app_version = coalesce(app_sessions.app_version, EXCLUDED.app_version),
                   platform = coalesce(app_sessions.platform, EXCLUDED.platform),
                   mode = coalesce(app_sessions.mode, EXCLUDED.mode),
                   entry = coalesce(app_sessions.entry, EXCLUDED.entry),
                   variants = coalesce(app_sessions.variants, EXCLUDED.variants)""",
            [
                (user_id, session_id, start, info.app_version, info.platform, info.mode, info.entry, source, user_id)
                for (user_id, session_id), start in starts.items()
            ],
        )


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
    pro: bool | None = None,
    placed: dict | None = None,
    scheduled_for: datetime | None = None,
    delivery_type: str | None = None,
) -> str:
    """Pedido + líneas (producto o plato) + evento `order_placed`. Los precios de `lines` se guardan tal cual: la API
    los pone antes con `catalog_prices`. Un pedido en modo `actual` ("Rappi hoy") no entra al perfil. `pro`: si la
    persona es Rappi Pro según la app (`app_users.pro`); `None` no lo cambia. `placed`: el sobre del `order_placed`
    (`surface`, `origin`, `request_id`) y lo que suma a su payload (`payload`), como en un pedido que Mochi hizo solo
    (offers/autonomy.py). `scheduled_for`: el inicio de la franja si se programó; `delivery_type`: basica, sin_prisa o
    prioritaria. Cada línea puede traer su preferencia de sustitución (`substitution`)."""
    order_id = f"ord-{uuid.uuid4().hex[:12]}"
    total = sum(float(line.get("unit_price") or 0) * int(line.get("qty", 1)) for line in lines)
    ensure_user(conn, user_id, source)
    if pro is not None:
        conn.execute("UPDATE app_users SET pro = %s WHERE user_id = %s", (pro, user_id))
    conn.execute(
        """INSERT INTO app_orders (order_id, user_id, session_id, cart_id, ts, vertical, total, source, mode,
                                   scheduled_for, delivery_type)
           VALUES (%s, %s, %s, %s, coalesce(%s, now()), %s, %s, %s, %s, %s, %s)""",
        (order_id, user_id, session_id, cart_id, ts, vertical, total, source, mode, scheduled_for, delivery_type),
    )
    known = _known_concepts(conn)
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO app_order_lines (order_id, line_no, entity_type, entity_id, concept_id, qty, unit_price,
                                            from_suggestion, store_id, substitution)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            [
                (
                    order_id,
                    i,
                    line["entity_type"],
                    line["entity_id"],
                    # En "Rappi hoy" no se aprende: la línea no guarda concepto, como los eventos de ese modo.
                    line.get("concept_id") if mode == "propuesta" and line.get("concept_id") in known else None,
                    int(line.get("qty", 1)),
                    line.get("unit_price"),
                    bool(line.get("from_suggestion")),
                    line.get("store_id"),
                    line.get("substitution"),
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
                payload={"order_id": order_id, "lines": len(lines), **(placed or {}).get("payload", {})},
                **{k: v for k, v in (placed or {}).items() if k in ("surface", "origin", "request_id")},
            )
        ],
        source,
    )
    return order_id


def catalog_prices(conn: Connection, lines: list[dict]) -> tuple[list[dict], int]:
    """Las líneas de un pedido del cliente con el precio vigente del catálogo en su tienda (`line_prices`): el que
    manda el cliente no se usa, porque el total alimenta segmentos y métricas. Devuelve las líneas con precio y cuántas
    se omitieron (agotadas, de una tienda que no las vende o que no están en el catálogo)."""
    priced = [
        {**line, "unit_price": price}
        for line, price in zip(lines, line_prices(conn, lines), strict=True)
        if price is not None
    ]
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
    ).fetchone():  # "Olvidar" es del prototipo: nunca borra usuarios simulados
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
    # Lo que se le mostró de ese concepto en una lista (sus impresiones), aunque la lista sea de varios.
    deleted += conn.execute(
        """DELETE FROM app_event_items i USING app_events e
           WHERE e.event_id = i.event_id AND e.user_id = %s AND i.concept_id = %s""",
        (user_id, concept_id),
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
    # La historia semanal también dice "tenía este segmento": tras olvidar un concepto no queda nada anterior.
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


def purge_old_impressions(conn: Connection, days: int = IMPRESSION_RETENTION_DAYS) -> int:
    """Borra los elementos de las impresiones (`app_event_items`) de eventos más antiguos que `days`: es la tabla que
    más crece. Queda el evento (`list_view` con su lista, pantalla y mayor posición vista). Devuelve cuántos borró."""
    return conn.execute(
        """DELETE FROM app_event_items i USING app_events e
           WHERE e.event_id = i.event_id AND e.ts < now() - make_interval(days => %s)""",
        (days,),
    ).rowcount
