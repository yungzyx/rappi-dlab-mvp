"""Resumen por persona de una prueba con usuarios (`rappi-ia resumen-prueba`; guion en docs/prueba-usuarios.md).

Solo lee, y solo personas del prototipo (`source = 'prototype'`): una simulada nunca entra, aunque se pida su id. Del
"¿Por qué?" de cada oferta los eventos traen de qué sale (los tipos de su `basis`, en `payload.basis`, desde la
migración 053) y cuándo se abrió (`offer_why_open`), no su texto: puede traer lo que la persona escribió. Lo que la app
no guarda no sale aquí y lo anota el moderador: el texto exacto del "¿Por qué?" y los rechazos que no dejan
`suggestion_dismissed`.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from psycopg import Connection
from psycopg.rows import dict_row

from ..catalog.hours import TZ
from ..concepts.taxonomy import load_taxonomy
from ..offers.autonomy import ORIGIN as AUTO_ORDER_ORIGIN
from .multivertical import LABELS as VERTICAL_LABELS

# Las ofertas de Mochi: su origen es `agent-<momento>` o la fila "Para ti" de su tarjeta (`para-ti`). El origen vivía
# en `payload.origen` antes de la migración 043.
_ORIGIN = "coalesce(origin, payload ->> 'origen')"
_IS_OFFER = f"({_ORIGIN} LIKE 'agent-%%' OR {_ORIGIN} = 'para-ti')"
# Por qué la ofreció, según el momento (el origen sin `agent-`): la razón exacta que vio la persona no se guarda.
MOMENTS = {
    "plan": "un plan del día (una ocasión)",
    "carrito": "complemento de lo que agregó al carro",
    "checkout": "complemento antes de pagar",
    "sin_resultado": "lo más cercano a una búsqueda sin resultado",
    "proximo_pedido": "idea para el próximo pedido",
    "vertical_por_probar": "una vertical que todavía no prueba",
    "recompra": 'lo que suele repetir ("¿Repetimos?")',
    "volver": 'algo que dejó ("¿Volvemos a…?")',
    "ontop": "sumar de Turbo al pedido en curso",
    "perfil": "su perfil de gusto",
    "ask": "respuesta a lo que le pidió",
    "para-ti": '"Para ti" en su tarjeta (sus intereses o lo más pedido)',
}
# De qué sale el "¿Por qué?": los tipos de `reason.basis` (`payload.basis`). Uno que no esté aquí sale tal cual.
BASIS = {
    "pedido": "un pedido suyo",
    "pedidos": "sus pedidos",
    "recompra": "su ritmo de recompra",
    "volver": "algo que dejó de pedir",
    "vuelta": "una vertical que dejó",
    "busqueda": "lo que buscó",
    "carrito": "lo que lleva en el carro",
    "concepto": "sus intereses",
    "perfil": "su perfil de gusto",
    "ocasion": "el plan que eligió",
    "sin_pedidos": "una vertical sin pedidos suyos",
    "combinacion": "la tabla de combinaciones de Rappi",
    "compra_cruzada": "lo que se compra junto",
    "afinidad_vertical": "las verticales que más usa",
    "ofertas": "las ofertas del catálogo",
    "ontop": "sumar de Turbo al pedido en curso",
    "lo_mas_pedido": "lo más pedido",
}
ACCEPTED, DISMISSED, NO_ANSWER, WITHHELD = (
    "aceptada",
    "rechazada",
    "sin respuesta registrada",
    "retenida (grupo de control)",
)
# El botón con que se rechaza cada oferta en la app (`suggestion_dismissed`, con el origen `agent-<momento>`): sale
# junto a "rechazada". Un momento que no esté aquí sale "rechazada" a secas.
DISMISS_BUTTONS = {
    "carrito": "Ahora no",
    "vertical_por_probar": "Después",
    "recompra": "Después",
    "volver": "Después",
}
# El camino por el que llegó a una vertical sale del origen del evento (`origin`), no de la pantalla.
SEARCH_ORIGINS = ("resultados", "resultados-tiendas")
# Los botones "Ver …" de las ofertas de Mochi llevan a la vertical sin dejar `vertical_open`: si llegó por "otro"
# camino, se nombra la última oferta de Mochi de esa vertical mostrada hasta este tiempo antes, sin afirmar que llegó
# por ella.
OFFER_BEFORE = timedelta(minutes=30)
# Lo que cuenta como tocar una vertical, con lo que hizo ("order" es un pedido de `app_orders`).
TOUCHES = {
    "vertical_open": "abrió la vertical",
    "view_store": "vio una tienda",
    "view_item": "vio un producto",
    "cart_add": "agregó al carro",
    "order": "pidió",
}


@dataclass
class Participant:
    user_id: str
    created_at: datetime
    variants: dict[str, str]
    sessions: list[dict]
    searches: list[dict]
    offers: list[dict]
    accepted_products: int
    why_opened: list[dict]
    opened: list[dict]
    touches: list[dict]
    services: list[dict]
    visibility: list[dict]
    orders: list[dict]


def parse_since(text: str) -> datetime:
    """`AAAA-MM-DD` o `AAAA-MM-DDTHH:MM`; sin zona horaria, la hora de Santiago (una fecha sola, desde las 00:00)."""
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f'Fecha inválida: "{text}" (usa AAAA-MM-DD o AAAA-MM-DDTHH:MM)') from exc
    if len(text) == 10:
        moment = datetime.combine(date.fromisoformat(text), datetime.min.time())
    return moment if moment.tzinfo else moment.replace(tzinfo=TZ)


def select_users(conn: Connection, user_ids: list[str] | None = None, since: datetime | None = None) -> list[str]:
    """Las personas del prototipo pedidas por id (en ese orden), o las creadas desde `since` que tienen algún evento
    (sin eventos, solo abrieron la sesión). Una simulada o que no existe no sale, aunque se pida."""
    if user_ids is not None:
        rows = conn.execute(
            "SELECT user_id FROM app_users WHERE source = 'prototype' AND user_id = ANY(%s)", (user_ids,)
        ).fetchall()
        found = {row[0] for row in rows}
        return [u for u in dict.fromkeys(user_ids) if u in found]
    return [
        row[0]
        for row in conn.execute(
            """SELECT u.user_id FROM app_users u
               WHERE u.source = 'prototype' AND u.created_at >= %s
                 AND EXISTS (SELECT 1 FROM app_events e WHERE e.user_id = u.user_id AND e.source = 'prototype')
               ORDER BY u.created_at, u.user_id""",
            (since,),
        )
    ]


def _rows(conn: Connection, query: str, user_id: str) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, {"user": user_id})
        return cur.fetchall()


# Todas las consultas filtran `source = 'prototype'` además de la persona: nunca se mezcla con lo simulado.
_EVENTS = f"""SELECT coalesce(client_ts, ts) AS at, type, vertical, concept_id, query, results, unmet, payload,
                     {_ORIGIN} AS origin, surface
              FROM app_events WHERE user_id = %(user)s AND source = 'prototype'"""
_ORDER = " ORDER BY coalesce(client_ts, ts), seq NULLS LAST, event_id"


def _events(conn: Connection, user_id: str, types: tuple[str, ...], where: str = "") -> list[dict]:
    kinds = ", ".join(f"'{t}'" for t in types)
    return _rows(conn, f"{_EVENTS} AND type IN ({kinds}){where}{_ORDER}", user_id)


def load_participant(conn: Connection, user_id: str) -> Participant:
    created = conn.execute(
        "SELECT created_at FROM app_users WHERE user_id = %s AND source = 'prototype'", (user_id,)
    ).fetchone()
    if created is None:
        raise ValueError(f"{user_id} no es una persona del prototipo")
    variants = dict(
        conn.execute(
            """SELECT experiment_id, variant FROM experiment_assignments
               WHERE user_id = %s AND source = 'prototype' ORDER BY experiment_id""",
            (user_id,),
        ).fetchall()
    )
    sessions = _rows(
        conn,
        """SELECT e.session_id, coalesce(s.started_at, min(coalesce(e.client_ts, e.ts))) AS started,
                  max(coalesce(e.client_ts, e.ts)) AS ended, s.mode, count(*) AS events
           FROM app_events e
           LEFT JOIN app_sessions s ON s.user_id = e.user_id AND s.session_id = e.session_id AND s.source = 'prototype'
           WHERE e.user_id = %(user)s AND e.source = 'prototype'
           GROUP BY e.session_id, s.started_at, s.mode
           ORDER BY started""",
        user_id,
    )
    offer_events = _events(
        conn,
        user_id,
        ("suggestion_shown", "suggestion_accepted", "suggestion_dismissed", "offer_withheld"),
        f" AND {_IS_OFFER}",
    )
    orders = _rows(
        conn,
        """SELECT o.order_id, o.ts AS at, o.vertical, o.total, o.status, o.mode,
                  count(l.line_no) AS lines, count(l.line_no) FILTER (WHERE l.from_suggestion) AS from_offer,
                  (SELECT e.origin FROM app_events e
                   WHERE e.user_id = o.user_id AND e.type = 'order_placed' AND e.payload ->> 'order_id' = o.order_id
                   LIMIT 1) AS origin
           FROM app_orders o LEFT JOIN app_order_lines l USING (order_id)
           WHERE o.user_id = %(user)s AND o.source = 'prototype'
           GROUP BY o.order_id ORDER BY o.ts""",
        user_id,
    )
    return Participant(
        user_id=user_id,
        created_at=created[0],
        variants=variants,
        sessions=sessions,
        searches=_events(conn, user_id, ("search", "ask")),
        offers=_offers(offer_events),
        accepted_products=sum(e["type"] == "suggestion_accepted" for e in offer_events),
        why_opened=_events(conn, user_id, ("offer_why_open",)),
        opened=_events(conn, user_id, ("vertical_open",)),
        touches=_events(conn, user_id, ("view_store", "view_item", "cart_add"), " AND vertical IS NOT NULL"),
        services=_events(conn, user_id, ("service_opened",)),
        visibility=_events(conn, user_id, ("agent_visibility",)),
        orders=orders,
    )


def _offers(events: list[dict]) -> list[dict]:
    """Cada oferta mostrada (o retenida al grupo de control) con lo que pasó después: aceptada si se agregó algo de ella
    al carro, rechazada (con el botón de su momento) si la descartó; si no, sin respuesta registrada. Se reconocen por
    su origen, su concepto y su vertical, como las cuenta la app (prototipo-app/src/api/suggestions.js), y lo que pasó
    después llega hasta la siguiente vez que se mostró la misma: una aceptación no vale por dos mostradas."""
    offers = []
    for i, e in enumerate(events):
        if e["type"] not in ("suggestion_shown", "offer_withheld"):
            continue
        status = WITHHELD if e["type"] == "offer_withheld" else NO_ANSWER
        if e["type"] == "suggestion_shown":
            key = (e["origin"], e["concept_id"], e["vertical"])
            after = set()
            for x in events[i + 1 :]:
                if (x["origin"], x["concept_id"], x["vertical"]) != key:
                    continue
                if x["type"] == "suggestion_shown":
                    break
                after.add(x["type"])
            if "suggestion_accepted" in after:
                status = ACCEPTED
            elif "suggestion_dismissed" in after:
                button = DISMISS_BUTTONS.get(e["origin"].removeprefix("agent-"))
                status = f'{DISMISSED} ("{button}")' if button else DISMISSED
        offers.append({**e, "moment": e["origin"].removeprefix("agent-"), "status": status})
    return offers


def _time(at: datetime) -> str:
    return at.astimezone(TZ).strftime("%d-%m %H:%M")


def _datetime(at: datetime) -> str:
    return at.astimezone(TZ).strftime("%d-%m-%Y %H:%M")


def _minutes(span: timedelta) -> str:
    seconds = max(int(span.total_seconds()), 0)
    return f"{seconds // 60} min {seconds % 60:02d} s"


def _pesos(amount) -> str:
    return "$" + f"{int(amount):,}".replace(",", ".")


def _vertical(code: str | None) -> str:
    return VERTICAL_LABELS.get(code, code) if code else "sin vertical"


def _concept(concept_id: str | None) -> str:
    concept = load_taxonomy().concepts.get(concept_id) if concept_id else None
    return concept.name if concept else (concept_id or "sin concepto")


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _search_note(e: dict) -> str:
    notes = []
    if e["unmet"]:
        notes.append("sin resultado")
    fixed = e["payload"].get("corregida")
    if fixed:
        notes.append(f'corregida a "{_cell(fixed)}"')
    source = e["payload"].get("fuente")
    if source == "correccion":
        notes.append("buscó tal cual, sin la corrección")
    elif source in ("sugerencia", "reciente", "lo-mas-buscado"):
        notes.append(f"tocó una sugerencia ({source})")
    return "; ".join(notes)


def active_time(sessions: list[dict]) -> timedelta:
    """El tiempo cubierto por las sesiones (de su primer a su último evento), con las que se superponen (dos pestañas
    abiertas a la vez) contadas una sola vez."""
    total, end = timedelta(), None
    for s in sorted(sessions, key=lambda s: s["started"]):
        if end is None or s["started"] > end:
            total += s["ended"] - s["started"]
            end = s["ended"]
        elif s["ended"] > end:
            total += s["ended"] - end
            end = s["ended"]
    return total


def _sessions(p: Participant) -> list[str]:
    lines = [
        "## Sesiones",
        "",
        f"{len(p.sessions)} sesión(es), {_minutes(active_time(p.sessions))} en total (del primer al último evento de"
        " cada una; las que se superponen, una vez).",
        "",
        "| Inicio | Duración | Modo | Eventos |",
        "|---|---|---|---|",
    ]
    return lines + [
        f"| {_datetime(s['started'])} | {_minutes(s['ended'] - s['started'])} | {s['mode'] or 'sin dato'} "
        f"| {s['events']} |"
        for s in p.sessions
    ]


def _searches(p: Participant) -> list[str]:
    if not p.searches:
        return ["## Búsquedas", "", "Sin búsquedas."]
    unmet = sum(bool(e["unmet"]) for e in p.searches)
    fixed = sum(bool(e["payload"].get("corregida")) for e in p.searches)
    lines = [
        "## Búsquedas",
        "",
        f"{len(p.searches)} búsqueda(s): {unmet} sin resultado y {fixed} corregida(s) por un error de tipeo.",
        "",
        "| Hora | Dónde | Texto | Resultados | Nota |",
        "|---|---|---|---|---|",
    ]
    for e in p.searches:
        where = "buscador" if e["type"] == "search" else "Mochi"
        text = f'"{_cell(e["query"])}"' if e["query"] else "(texto no guardado)"
        results = "" if e["results"] is None else e["results"]
        lines.append(f"| {_time(e['at'])} | {where} | {text} | {results} | {_search_note(e)} |")
    return lines


def _basis(payload: dict) -> str:
    """De qué sale el "¿Por qué?" (`payload.basis`), o "—" si el evento no lo trae (anterior a la migración 053, o una
    oferta sin razón)."""
    kinds = payload.get("basis")
    if not isinstance(kinds, list) or not kinds:
        return "—"
    return _cell(", ".join(BASIS.get(str(kind), str(kind)) for kind in kinds))


def _offer_lines(p: Participant) -> list[str]:
    if not p.offers:
        return ["## Ofertas de Mochi", "", "Mochi no mostró ofertas."]
    statuses = [o["status"] for o in p.offers]
    counts = {status: statuses.count(status) for status in dict.fromkeys(statuses)}
    lines = [
        "## Ofertas de Mochi",
        "",
        f"{len(p.offers)} oferta(s): {', '.join(f'{n} {status}' for status, n in counts.items())}. Productos agregados"
        f" al carro desde una oferta: {p.accepted_products}.",
        "",
        'El motivo es el del momento en que Mochi la ofreció, y "De qué sale" son las fuentes de su "¿Por qué?": su'
        " texto exacto no se guarda (lo anota el moderador).",
        "",
        "| Hora | Momento | Motivo (según el momento) | De qué sale | Concepto | Vertical | Qué pasó |",
        "|---|---|---|---|---|---|---|",
    ]
    for o in p.offers:
        kind = o["payload"].get("kind")
        moment = f"{o['moment']} ({kind})" if kind else o["moment"]
        lines.append(
            f"| {_time(o['at'])} | {moment} | {MOMENTS.get(o['moment'], 'otro')} | {_basis(o['payload'])} "
            f"| {_concept(o['concept_id'])} "
            f"| {_vertical(o['vertical'])} | {o['status']} |"
        )
    return lines


def _why_lines(p: Participant) -> list[str]:
    title = ['## El "¿Por qué?" de las ofertas', ""]
    if not p.why_opened:
        return [*title, 'No abrió el "¿Por qué?" de ninguna oferta (sin eventos `offer_why_open`).']
    lines = [
        *title,
        f'Abrió el "¿Por qué?" {len(p.why_opened)} {"vez" if len(p.why_opened) == 1 else "veces"}.',
        "",
        "| Hora | Momento | De qué sale | Concepto |",
        "|---|---|---|---|",
    ]
    for e in p.why_opened:
        moment = (e["origin"] or "sin origen").removeprefix("agent-")
        concept = _concept(e["concept_id"]) if e["concept_id"] else "—"
        lines.append(f"| {_time(e['at'])} | {moment} | {_basis(e['payload'])} | {concept} |")
    return lines


def _path(e: dict) -> str:
    """Por qué camino llegó, según el origen del evento: Mochi (una oferta `agent-<momento>` o el "Para ti" de su
    tarjeta, no el de una tienda), el buscador, un acceso de la Home u otro (pantalla y origen tal cual)."""
    origin, surface = e.get("origin"), e.get("surface")
    if origin and origin.startswith("agent-"):
        return f"Mochi ({origin.removeprefix('agent-')})"
    if origin == "para-ti" and surface != "store":
        return "Mochi (para-ti)"
    if origin in SEARCH_ORIGINS:
        return "buscador"
    if e["type"] == "vertical_open" and surface == "home":
        return "acceso de la Home"
    if surface == "agent":
        return f"Mochi ({origin or 'sin origen'})"
    where = ", ".join(x for x in (surface, origin) if x)
    return f"otro ({where})" if where else "sin dato"


def _offer_before(p: Participant, e: dict) -> dict | None:
    """La última oferta de Mochi (`agent-<momento>`) de la vertical de `e` mostrada en los `OFFER_BEFORE` anteriores."""
    shown = [
        o
        for o in p.offers
        if o["type"] == "suggestion_shown"
        and o["origin"].startswith("agent-")
        and o["vertical"] == e["vertical"]
        and e["at"] - OFFER_BEFORE <= o["at"] <= e["at"]
    ]
    return max(shown, key=lambda o: o["at"], default=None)


def _journey_path(p: Participant, e: dict) -> str:
    """El camino de `_path`; si es "otro" o "sin dato", con la oferta de Mochi de esa vertical que vio justo antes."""
    path = _path(e)
    offer = _offer_before(p, e) if path.startswith(("otro", "sin dato")) else None
    if offer is None:
        return path
    return f"{path}; antes, oferta de Mochi ({offer['moment']}) de esa vertical a las {_time(offer['at'])[-5:]}"


def journey(p: Participant) -> list[dict]:
    """La primera vez que tocó cada vertical (la abrió, vio una tienda o un producto, agregó al carro o pidió), en
    orden: la primera es la vertical con que empezó y las demás, cada una nueva."""
    orders = [{**o, "type": "order"} for o in p.orders]
    seen: dict[str, dict] = {}
    for e in sorted((*p.opened, *p.touches, *orders), key=lambda e: e["at"]):
        if e["vertical"] and e["vertical"] not in seen:
            seen[e["vertical"]] = e
    return list(seen.values())


def _journey(p: Participant) -> list[str]:
    title = ["## Recorrido por verticales", ""]
    steps = journey(p)
    if not steps:
        return [
            *title,
            "No tocó ninguna vertical (sin `vertical_open`, `view_store`, `view_item`, `cart_add` ni pedidos).",
        ]
    other = "sí" if len(steps) > 1 else "no"
    lines = [
        *title,
        f"Tocó {len(steps)} vertical(es); empezó por {_vertical(steps[0]['vertical'])}. Llegó a otra vertical:"
        f" {other}.",
        "",
        'La primera vez que tocó cada una, con la hora de Santiago y el camino, que sale del origen del evento: "acceso'
        ' de la Home", "Mochi (momento)", "buscador" u "otro (pantalla, origen)"; "sin dato" si no trae ninguno. Los'
        ' botones "Ver …" de una oferta de Mochi no dejan origen: si en los 30 minutos anteriores vio una oferta de'
        ' Mochi de esa vertical, "otro" la nombra ("antes, oferta de Mochi…"), sin afirmar que llegó por ella.',
        "",
        "| Hora | Vertical | Qué hizo | Camino |",
        "|---|---|---|---|",
    ]
    for i, e in enumerate(steps):
        name = _vertical(e["vertical"]) + (" (la primera)" if i == 0 else "")
        lines.append(f"| {_time(e['at'])} | {name} | {TOUCHES[e['type']]} | {_cell(_journey_path(p, e))} |")
    return lines


def _verticals(p: Participant) -> list[str]:
    opened = list(dict.fromkeys(_vertical(e["vertical"]) for e in p.opened if e["vertical"]))
    others = sum(e["vertical"] is None for e in p.opened)
    if others:
        opened.append(f"{others} acceso(s) sin vertical del catálogo")
    services = list(dict.fromkeys(str(e["payload"]["servicio"]) for e in p.services if e["payload"].get("servicio")))
    ordered = list(dict.fromkeys(_vertical(o["vertical"]) for o in p.orders if o["status"] == "confirmado"))
    return [
        "## Verticales",
        "",
        f"- Abiertas (un acceso de la Home o un botón de Mochi): {', '.join(opened) or 'ninguna'}.",
        f"- Servicios abiertos: {', '.join(services) or 'ninguno'}.",
        f"- Con pedido (sin los cancelados): {', '.join(ordered) or 'ninguna'}.",
    ]


def _visibility(p: Participant) -> list[str]:
    if not p.visibility:
        return ["## Mochi a la vista", "", "Ocultó a Mochi: no (sin eventos `agent_visibility`)."]
    hid = any(e["payload"].get("visible") is False for e in p.visibility)
    return [
        "## Mochi a la vista",
        "",
        f"Ocultó a Mochi: {'sí' if hid else 'no'}.",
        "",
        *(
            f"- {_time(e['at'])}: {'lo trajo de vuelta' if e['payload'].get('visible') else 'lo ocultó'}"
            f" (desde {e['origin'] or 'sin origen'})"
            for e in p.visibility
        ),
    ]


def _orders(p: Participant) -> list[str]:
    if not p.orders:
        return ["## Pedidos", "", "Sin pedidos."]
    lines = [
        "## Pedidos",
        "",
        "| Hora | Vertical | Total | Líneas (de una oferta) | Modo | Estado | Quién pidió |",
        "|---|---|---|---|---|---|---|",
    ]
    for o in p.orders:
        who = "Mochi (Pedir por mí)" if o["origin"] == AUTO_ORDER_ORIGIN else "la persona"
        lines.append(
            f"| {_time(o['at'])} | {_vertical(o['vertical'])} | {_pesos(o['total'])} "
            f"| {o['lines']} ({o['from_offer']}) | {o['mode']} | {o['status']} | {who} |"
        )
    return lines


def render(p: Participant) -> str:
    variants = ", ".join(f"{k} = {v}" for k, v in p.variants.items()) or "ninguno"
    lines = [
        f"# Prueba con usuarios: `{p.user_id}`",
        "",
        f"Persona del prototipo creada el {_datetime(p.created_at)} (hora de Santiago). Resumen de `rappi-ia"
        " resumen-prueba`: solo lee la base y solo la población `prototype`. Describe lo que hizo esta persona; no mide"
        " retención ni efecto.",
        "",
        f"Experimentos: {variants}.",
    ]
    for section in (_sessions, _searches, _offer_lines, _why_lines, _journey, _verticals, _visibility, _orders):
        lines += ["", *section(p)]
    return "\n".join(lines) + "\n"


def write_reports(conn: Connection, user_ids: list[str], out_dir: Path) -> list[Path]:
    """Un Markdown por persona en `out_dir` (`<user_id>.md`, con lo que no es letra, número, guion o guion bajo
    cambiado por `_`). No escribe nada en la base."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for user_id in user_ids:
        path = out_dir / f"{re.sub(r'[^A-Za-z0-9_-]', '_', user_id)}.md"
        path.write_text(render(load_participant(conn, user_id)), encoding="utf-8")
        paths.append(path)
    return paths
