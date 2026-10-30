""" "Pedir por mí": cuánta autonomía le da la persona a Mochi para pedir (`agent_autonomy`, migración 049) y qué puede
pedir solo. Lo pidió el usuario el 25-10-2026, mirando el agente de la app de Rappi ("Revisar antes de enviar" o el
pedido automático en todas o algunas tiendas: docs/investigacion/app-rappi-2026-10-25.md), pero acotado
(docs/diseno-ia.md, "Pedir por mí"):

- Por defecto, "Revisar antes de pedir": Mochi arma el resumen y se paga en el checkout de siempre.
- "Pedir por mí": la persona elige tiendas de las que ya pidió (ninguna de Farmacia ni Licores) y un tope por pedido.
- Mochi solo pide "lo de siempre" (`usual`): los mismos productos y cantidades de su último pedido en esa tienda (modo
  propuesta), todos a la venta ahí con su precio vigente.
- Nunca alcohol, +18, Farmacia, bebé ni salud (las guardias de las ofertas, `offers/guards.py`, más la marca +18 y la
  vertical de la tienda); nunca por encima del tope (los productos a precio del catálogo; la app suma envío y servicio);
  nunca en una tienda cerrada según lo publicado (`catalog/hours.py`) ni bajo la compra mínima del catálogo
  (`catalog/terms.py`; la supuesta de la app la revisa la app). Si algo falla, revisa antes y dice por qué (`decide`).
- La app espera la ventana de "Deshacer pedido" antes de mandar el pedido, y `POST /orders` lo vuelve a revisar todo
  (`check_order`): solo entra si sigue siendo lo de siempre y pasa cada límite.
- Cada autopedido queda en su `order_placed` con origen `agent-autopedido` y una `basis` que dice que lo pidió el
  agente con permiso, con el tope y la regla (`basis`).
"""

from dataclasses import dataclass, field
from datetime import datetime

from psycopg import Connection
from rappi_scraper.storage.search import MIN_PRICE

from ..agent.tools import clp
from ..catalog import hours as catalog_hours
from ..catalog.stores import BIGINT_MAX, line_prices, product_card
from ..catalog.terms import store_terms
from ..concepts.taxonomy import load_taxonomy
from ..text import normalize
from .guards import (
    OFFER_BLOCKED_VERTICALS,
    alcohol_in_description,
    alcohol_in_name,
    alcohol_section,
    baby_in_name,
    is_offerable,
    unofferable_subverticals,
)

ORIGIN = "agent-autopedido"  # el origen del `order_placed` de un pedido que Mochi hizo solo
RULE = "lo-de-siempre"
MAX_STORES = 10  # como el CHECK de la migración 049
MIN_TOTAL, MAX_TOTAL = 1000, 200_000
DEFAULT_TOTAL = 20_000  # lo que la app propone al encenderlo (la persona lo cambia)
MAX_OPTIONS = 10  # tiendas de las que ya pidió que se ofrecen para elegir
# La acción que la recompra suma en una tienda elegida (api/agent.py): le pide a Mochi lo de siempre ahí.
ASK_LABEL = "Pide lo de siempre por mí"
ASK_TEXT = "Pide lo de siempre en {store}"

# Por qué Mochi no pide solo y deja revisar antes: código → texto ("Lo revisas tú: …").
REASONS = {
    "sin_permiso": "no me diste permiso para pedir por ti",
    "tienda_no_elegida": "no elegiste {store} para que pida por ti",
    "no_disponible": "{name} ya no está a la venta en {store}",
    "guardia": "lleva algo que no pido solo (alcohol, +18, farmacia, bebé o salud)",
    "cerrada": "{store} está cerrada ahora, según el horario que publicó",
    "minimo": "no llega a la compra mínima de {store} ({minimum})",
    "tope": "pasa tu tope de {cap} por pedido",
    "distinto": "ya no es lo de siempre",
    "calificacion": "calificaste mal un pedido de {store} hace poco",
}


class AutonomyError(ValueError):
    """Lo que se pidió guardar no vale (una tienda de la que no pidió, un tope fuera de rango): un 422."""


@dataclass(frozen=True)
class Autonomy:
    store_ids: tuple[int, ...]
    max_total: int


@dataclass
class Usual:
    """Lo de siempre en una tienda: su último pedido ahí con el precio de hoy."""

    store: dict  # id, name, vertical (código del backend)
    order_id: str
    lines: list[dict]  # [{product: Product.to_dict(), qty}] lo que sigue a la venta
    missing: list[str] = field(default_factory=list)  # nombres de lo que ya no está a la venta ahí

    @property
    def subtotal(self) -> int:
        return round(sum(line["product"]["price_value"] * line["qty"] for line in self.lines))


@dataclass(frozen=True)
class Decision:
    allowed: bool  # Mochi lo pide solo
    code: str | None = None  # por qué no (REASONS), o None
    text: str | None = None


# ── El ajuste ────────────────────────────────────────────────────────────────
def load(conn: Connection, user_id: str | None) -> Autonomy | None:
    """El permiso de la persona, o None ("Revisar antes de pedir")."""
    if not user_id:
        return None
    row = conn.execute("SELECT store_ids, max_total FROM agent_autonomy WHERE user_id = %s", (user_id,)).fetchone()
    return Autonomy(tuple(row[0]), row[1]) if row else None


_ORDERED_STORES = """
SELECT l.store_id, btrim(coalesce(b.name, s.name)), o.vertical, max(o.ts)
FROM app_orders o
JOIN app_order_lines l USING (order_id)
JOIN stores s ON s.store_id = l.store_id
LEFT JOIN brands b ON b.brand_id = s.brand_id
WHERE o.user_id = %(user)s AND o.mode = 'propuesta' AND o.status = 'confirmado' AND l.store_id IS NOT NULL
  AND o.vertical <> ALL(%(blocked)s)
  AND NOT EXISTS (SELECT 1 FROM v_store_verticals v WHERE v.store_id = l.store_id AND v.vertical = ANY(%(blocked)s))
  AND NOT EXISTS (SELECT 1 FROM store_verticals v WHERE v.store_id = l.store_id AND v.subvertical = ANY(%(sub)s))
GROUP BY 1, 2, 3
ORDER BY 4 DESC, 1
LIMIT %(limit)s"""


def ordered_stores(conn: Connection, user_id: str) -> list[dict]:
    """Las tiendas de las que la persona ya pidió (modo propuesta) y que puede elegir, de la más reciente a la más
    antigua: `[{id, name, vertical}]`. Ninguna de Farmacia, Licores ni una tienda que Rappi rotula Farmacia, Sex shop o
    Smoking shop: ahí Mochi nunca pide solo."""
    rows = conn.execute(
        _ORDERED_STORES,
        {"user": user_id, "blocked": list(OFFER_BLOCKED_VERTICALS), "sub": unofferable_subverticals(), "limit": 50},
    ).fetchall()
    seen, stores = set(), []
    for store_id, name, vertical, _ in rows:  # una tienda con pedidos en dos verticales sale una vez
        if store_id not in seen:
            seen.add(store_id)
            stores.append({"id": store_id, "name": name, "vertical": vertical})
    return stores[:MAX_OPTIONS]


def save(conn: Connection, user_id: str, store_ids: list[int], max_total: int) -> Autonomy:
    """Enciende o cambia "Pedir por mí". Las tiendas tienen que ser de las que ya pidió (`ordered_stores`); la población
    es la de la persona. No hace commit."""
    wanted = list(dict.fromkeys(store_ids))
    if not wanted or len(wanted) > MAX_STORES:
        raise AutonomyError(f"Elige entre 1 y {MAX_STORES} tiendas")
    if not MIN_TOTAL <= max_total <= MAX_TOTAL:
        raise AutonomyError(f"El tope va entre {clp(MIN_TOTAL)} y {clp(MAX_TOTAL)}")
    allowed = {store["id"] for store in ordered_stores(conn, user_id)}
    if not set(wanted) <= allowed:
        raise AutonomyError("Solo puedes elegir tiendas donde ya pediste (y que no son Farmacia ni Licores)")
    conn.execute(
        """INSERT INTO agent_autonomy (user_id, store_ids, max_total, source)
           SELECT user_id, %(stores)s, %(cap)s, source FROM app_users WHERE user_id = %(user)s
           ON CONFLICT (user_id) DO UPDATE SET store_ids = EXCLUDED.store_ids, max_total = EXCLUDED.max_total,
                                                updated_at = now()""",
        {"user": user_id, "stores": wanted, "cap": max_total},
    )
    return Autonomy(tuple(wanted), max_total)


def turn_off(conn: Connection, user_id: str) -> bool:
    """Vuelve a "Revisar antes de pedir" (borra el permiso). No hace commit."""
    return conn.execute("DELETE FROM agent_autonomy WHERE user_id = %s", (user_id,)).rowcount > 0


def describe(conn: Connection, user_id: str) -> dict:
    """Lo que muestra el ajuste: `{modo, tiendas, tope, opciones: {tiendas, tope_min, tope_max, tope_sugerido}}`. Una
    tienda elegida que ya no se puede elegir (p. ej. tras "Olvidar" un concepto) sigue en `tiendas` y no en las
    opciones: la app la muestra para quitarla."""
    mine = load(conn, user_id)
    return {
        "modo": "pedir" if mine else "revisar",
        "tiendas": list(mine.store_ids) if mine else [],
        "tope": mine.max_total if mine else None,
        "opciones": {
            "tiendas": ordered_stores(conn, user_id),
            "tope_min": MIN_TOTAL,
            "tope_max": MAX_TOTAL,
            "tope_sugerido": DEFAULT_TOTAL,
        },
    }


# ── Lo de siempre ────────────────────────────────────────────────────────────
def find_ordered_store(conn: Connection, user_id: str, said: str | None) -> dict | None:
    """La tienda de las que ya pidió que nombró la persona ("en el súper Centro"): todas las palabras dichas están en su
    nombre. Sin nombre, la de su último pedido. La más reciente gana. Incluye las de Farmacia y Licores: así Mochi
    puede decir por qué ahí no pide solo."""
    rows = conn.execute(
        """SELECT l.store_id, btrim(coalesce(b.name, s.name)), o.vertical
           FROM app_orders o JOIN app_order_lines l USING (order_id)
           JOIN stores s ON s.store_id = l.store_id LEFT JOIN brands b ON b.brand_id = s.brand_id
           WHERE o.user_id = %s AND o.mode = 'propuesta' AND o.status = 'confirmado' AND l.store_id IS NOT NULL
           ORDER BY o.ts DESC, o.order_id DESC LIMIT 200""",
        (user_id,),
    ).fetchall()
    words = set(normalize(said or "").split()) - {"el", "la", "los", "las", "de", "del", "en"}
    for store_id, name, vertical in rows:
        if not words or words <= set(normalize(name).split()):
            return {"id": store_id, "name": name, "vertical": vertical}
    return None


_CATALOG_ITEMS = """
SELECT ci.master_product_id::text, ci.name, NULLIF(ci.image_url, ''), ci.presentation,
       ci.is_alcoholic OR ci.age_restricted, ic.concept_id
FROM catalog_items ci
LEFT JOIN item_concepts ic ON ic.entity_type = 'catalog_item' AND ic.entity_id = ci.master_product_id::text
WHERE ci.master_product_id = ANY(%s)"""
_MENU_ITEMS = """
SELECT mi.item_id::text, mi.name, NULLIF(mi.image_url, ''), ic.concept_id, ms.name, clean_html(mi.description)
FROM menu_items mi
LEFT JOIN menu_sections ms ON ms.store_id = mi.store_id AND ms.section_id = mi.section_id
LEFT JOIN item_concepts ic ON ic.entity_type = 'menu_item' AND ic.entity_id = mi.item_id::text
WHERE mi.item_id = ANY(%s)"""


def _valid(entity_id: str) -> bool:
    return entity_id.isascii() and entity_id.isdigit() and int(entity_id) <= BIGINT_MAX


def usual(conn: Connection, user_id: str, store: dict) -> Usual | None:
    """Lo de siempre en `store` (`find_ordered_store`): las líneas de su último pedido ahí (modo propuesta), cada una
    con su producto y el precio de hoy en esa tienda (`line_prices`, como "Pídelo de nuevo"). Lo que ya no está a la
    venta queda en `missing`. None si nunca pidió ahí."""
    rows = conn.execute(
        """SELECT o.order_id, l.entity_type, l.entity_id, l.qty
           FROM app_order_lines l JOIN app_orders o USING (order_id)
           WHERE o.order_id = (
               SELECT o2.order_id FROM app_orders o2 JOIN app_order_lines l2 USING (order_id)
               WHERE o2.user_id = %(user)s AND o2.mode = 'propuesta' AND o2.status = 'confirmado'
                 AND l2.store_id = %(store)s
               ORDER BY o2.ts DESC, o2.order_id DESC LIMIT 1)
             AND l.store_id = %(store)s
           ORDER BY l.line_no""",
        {"user": user_id, "store": store["id"]},
    ).fetchall()
    if not rows:
        return None
    order_id = rows[0][0]
    lines = [{"entity_type": kind, "entity_id": entity_id, "store_id": store["id"]} for _, kind, entity_id, _ in rows]
    prices = line_prices(conn, lines)
    details = _details(conn, [line for line in lines if _valid(line["entity_id"])])
    taxonomy = load_taxonomy()
    out = Usual(store, order_id, [])
    for (_, kind, entity_id, qty), price in zip(rows, prices, strict=True):
        detail = details.get((kind, entity_id))
        if detail is None or price is None or price < MIN_PRICE:
            out.missing.append(detail[1] if detail else "un producto")
            continue
        name, image, presentation, adult, concept, alcohol = detail[1:]
        row = (entity_id, name, price, None, image, presentation, adult or alcohol, concept)
        product = product_card(row, store["vertical"], store["name"], store["id"], taxonomy, kind).to_dict()
        out.lines.append({"product": product, "qty": int(qty)})
    return out


def _details(conn: Connection, lines: list[dict]) -> dict[tuple[str, str], tuple]:
    """(tipo, id) → (id, nombre, imagen, presentación, +18, concepto, alcohol). En un plato, "alcohol" es lo que las
    guardias leen en su sección o su descripción (un plato no trae marca +18)."""
    out: dict[tuple[str, str], tuple] = {}
    catalog = [int(line["entity_id"]) for line in lines if line["entity_type"] == "catalog_item"]
    dishes = [int(line["entity_id"]) for line in lines if line["entity_type"] == "menu_item"]
    if catalog:
        for id_, name, image, presentation, adult, concept in conn.execute(_CATALOG_ITEMS, (catalog,)):
            out[("catalog_item", id_)] = (id_, name, image, presentation, bool(adult), concept, False)
    if dishes:
        for id_, name, image, concept, section, description in conn.execute(_MENU_ITEMS, (dishes,)):
            alcohol = alcohol_section(section) or alcohol_in_description(description, concept, section)
            out[("menu_item", id_)] = (id_, name, image, None, False, concept, alcohol)
    return out


def _guarded(conn: Connection, found: Usual) -> bool:
    """Si lo de siempre lleva algo que Mochi nunca pide solo: la vertical o la tienda (Farmacia, Licores, o una que
    Rappi rotula Farmacia, Sex shop o Smoking shop) o una línea +18, con un nombre que dice alcohol o bebé, o de un
    concepto que el agente no ofrece (bebé, salud, sensible)."""
    store_id = found.store["id"]
    blocked = list(OFFER_BLOCKED_VERTICALS)
    if (
        found.store["vertical"] in blocked
        or conn.execute(
            """SELECT EXISTS (SELECT 1 FROM v_store_verticals WHERE store_id = %(s)s AND vertical = ANY(%(v)s))
               OR EXISTS (SELECT 1 FROM store_verticals WHERE store_id = %(s)s AND subvertical = ANY(%(sub)s))""",
            {"s": store_id, "v": blocked, "sub": unofferable_subverticals()},
        ).fetchone()[0]
    ):
        return True
    concepts = load_taxonomy().concepts
    for line in found.lines:
        product = line["product"]
        kind = product["entity_type"]
        if product["age_restricted"] or alcohol_in_name(kind, product["name"], product["concept"]):
            return True
        if baby_in_name(kind, product["name"]):
            return True
        concept = concepts.get(product["concept"]) if product["concept"] else None
        if concept is not None and not is_offerable(concept):
            return True
    return False


def _closed(conn: Connection, store: dict, now: datetime | None = None) -> bool:
    """Si la tienda está cerrada según lo publicado: el horario de un restaurante a la hora de Santiago, o cómo estaba
    una tienda al bajarla (`catalog/hours.py`). Sin dato no cuenta como cerrada (el catálogo no sabe el estado en vivo:
    lo diría la app de Rappi)."""
    row = conn.execute(
        """SELECT s.raw, d.schedules FROM stores s LEFT JOIN restaurant_details d ON d.store_id = s.store_id
           WHERE s.store_id = %s""",
        (store["id"],),
    ).fetchone()
    if row is None:
        return False
    raw, schedules = row
    if store["vertical"] == "restaurantes":
        state = catalog_hours.restaurant_hours(
            catalog_hours.normalize_schedule(schedules), now or catalog_hours.now_local()
        )
    else:
        state = catalog_hours.store_hours(raw)
    return (state or {}).get("open") is False


def decide(
    conn: Connection,
    user_id: str,
    mine: Autonomy | None,
    found: Usual,
    now: datetime | None = None,
    lines: list[dict] | None = None,
) -> Decision:
    """Si Mochi pide solo lo de siempre (`found`) o lo deja para revisar antes, con el primer límite que falla. Con
    `lines` (las de un pedido que llega a la API), además tiene que ser lo de siempre tal cual. Una tienda que la
    persona calificó mal hace poco (`winback.paused`, la misma pausa de la recompra y el "volver") se revisa antes."""
    store = found.store
    if mine is None:
        return _review("sin_permiso")
    if store["id"] not in mine.store_ids:
        return _review("tienda_no_elegida", store=store["name"])
    if found.missing:
        return _review("no_disponible", name=found.missing[0], store=store["name"])
    if lines is not None and _shape(lines) != _shape([_line(line) for line in found.lines]):
        return _review("distinto")
    from .winback import paused  # import diferido: winback importa agent.grouped_search, que importa este módulo

    if store["id"] in paused(conn, user_id).stores:
        return _review("calificacion", store=store["name"])
    if _guarded(conn, found):
        return _review("guardia")
    if _closed(conn, store, now):
        return _review("cerrada", store=store["name"])
    terms = next(iter(store_terms(conn, [store["id"]])), {})
    minimum = terms.get("min_order")
    if minimum is not None and found.subtotal < minimum:
        return _review("minimo", store=store["name"], minimum=clp(minimum))
    if found.subtotal > mine.max_total:
        return _review("tope", cap=clp(mine.max_total))
    return Decision(True)


def _review(code: str, **values: str) -> Decision:
    return Decision(False, code, REASONS[code].format(**values))


def _line(line: dict) -> dict:
    product = line["product"]
    return {"entity_type": product["entity_type"], "entity_id": product["entity_id"], "qty": line["qty"]}


def _shape(lines: list[dict]) -> list[tuple[str, str, int]]:
    return sorted((line["entity_type"], str(line["entity_id"]), int(line.get("qty", 1))) for line in lines)


def basis(mine: Autonomy, found: Usual) -> list[dict]:
    """Por qué pidió solo: el permiso de la persona en esa tienda, su tope y la regla (lo de siempre)."""
    return [
        {"kind": "permiso", "id": "pedir-por-mi", "source": "persona"},
        {"kind": "tienda", "id": str(found.store["id"]), "source": "persona"},
        {"kind": "tope", "id": str(mine.max_total), "source": "persona"},
        {"kind": "regla", "id": RULE, "source": "pedidos"},
    ]


def plan(conn: Connection, user_id: str, said: str | None, now: datetime | None = None) -> dict | None:
    """Lo que Mochi arma con "pide lo de siempre en X": `{modo, tienda, lineas, subtotal, tope, motivo, codigo, basis}`
    (`modo` "pedir" si lo pide solo, "revisar" si no). None si no encuentra la tienda o nunca pidió ahí."""
    store = find_ordered_store(conn, user_id, said)
    found = usual(conn, user_id, store) if store else None
    if found is None:
        return None
    mine = load(conn, user_id)
    decision = decide(conn, user_id, mine, found, now)
    return {
        "modo": "pedir" if decision.allowed else "revisar",
        "tienda": store,
        "lineas": found.lines,
        "subtotal": found.subtotal,
        "tope": mine.max_total if mine else None,
        "codigo": decision.code,
        "motivo": decision.text,
        "basis": basis(mine, found) if decision.allowed else [],
    }


def check_order(conn: Connection, user_id: str, store_id: int | None, lines: list[dict]) -> tuple[Decision, list]:
    """Lo que revisa `POST /orders` de un autopedido, ya pasada la ventana de deshacer: el mismo `decide` con lo de
    siempre de hoy y las líneas que llegan. Devuelve la decisión y la `basis` (vacía si no pasa)."""
    store = None
    if store_id is not None:
        row = conn.execute(
            """SELECT o.vertical, btrim(coalesce(b.name, s.name))
               FROM app_orders o JOIN app_order_lines l USING (order_id)
               JOIN stores s ON s.store_id = l.store_id LEFT JOIN brands b ON b.brand_id = s.brand_id
               WHERE o.user_id = %s AND o.mode = 'propuesta' AND o.status = 'confirmado' AND l.store_id = %s
               ORDER BY o.ts DESC LIMIT 1""",
            (user_id, store_id),
        ).fetchone()
        store = {"id": store_id, "name": row[1], "vertical": row[0]} if row else None
    found = usual(conn, user_id, store) if store else None
    if found is None:
        return _review("distinto"), []
    mine = load(conn, user_id)
    decision = decide(conn, user_id, mine, found, lines=lines)
    return decision, basis(mine, found) if decision.allowed else []
