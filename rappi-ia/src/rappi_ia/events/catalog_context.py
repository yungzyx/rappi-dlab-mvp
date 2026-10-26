"""El catálogo tal como estaba al registrar un evento (docs/capa-de-datos.md): precio, oferta y si la tienda estaba
abierta, fijados en `payload.catalogo` de `view_store`, `view_item` y `cart_add`.

El precio cambia entre descargas: reconstruirlo después daría el de la descarga siguiente, no el que vio la persona.
Sale de las mismas fuentes que el resto de la API: la oferta vigente de `v_latest_offers` en su tienda (la más barata
si la tienda lo tiene en dos SKU; sin tienda, la de la ficha del producto) y el último precio de `latest_menu_prices`
para un plato. Abierta o cerrada es la de la descarga (`catalog/hours.py`): el horario publicado de un restaurante a la
hora de Santiago, o cómo estaba la tienda al bajarla; `horario` dice cuál de las dos.

`payload.catalogo` lo pone siempre el servidor: uno que mande la app se reemplaza. Lo que no se sabe no va.
"""

from psycopg import Connection
from rappi_scraper.storage.search import MIN_PRICE

from ..catalog import hours as clock
from ..catalog.stores import BIGINT_MAX

CONTEXT_TYPES = frozenset({"view_store", "view_item", "cart_add"})
KEY = "catalogo"

_STORE_OFFERS = """
SELECT DISTINCT ON (x.n) x.n, l.price, l.real_price, l.discount_pct
FROM unnest(%(ids)s::bigint[], %(stores)s::bigint[]) WITH ORDINALITY x(id, store_id, n)
JOIN store_products sp ON sp.store_id = x.store_id AND sp.master_product_id = x.id
JOIN v_latest_offers l ON l.store_id = sp.store_id AND l.sku = sp.sku
WHERE l.current AND l.in_stock IS NOT FALSE AND l.price >= %(min_price)s
ORDER BY x.n, l.price, sp.sku"""

# Sin tienda, la oferta vigente más barata del producto, como la ficha (`product_detail`): primero las tiendas que se
# abren con él en un pasillo (y entonces la tienda es esa), si no, cualquiera (sin tienda). El lote, en una consulta.
_CHEAPEST = """
SELECT DISTINCT ON (x.n) x.n, l.price, l.real_price, CASE WHEN o.openable THEN l.store_id END
FROM unnest(%(ids)s::bigint[]) WITH ORDINALITY x(id, n)
JOIN store_products sp ON sp.master_product_id = x.id
JOIN v_latest_offers l ON l.store_id = sp.store_id AND l.sku = sp.sku
CROSS JOIN LATERAL (
    SELECT EXISTS (SELECT 1 FROM aisles a
                   WHERE a.store_id = l.store_id AND a.aisle_id = sp.aisle_id AND a.parent_aisle_id IS NULL) AS openable
) o
WHERE l.current AND l.in_stock IS NOT FALSE AND l.price >= %(min_price)s
ORDER BY x.n, o.openable DESC, l.price, l.store_id"""

_DISHES = """
SELECT mi.item_id, mi.store_id, mp.price, mp.real_price, mp.discount_pct, mp.is_available
FROM menu_items mi LEFT JOIN latest_menu_prices mp ON mp.item_id = mi.item_id
WHERE mi.item_id = ANY(%s)"""

_STORES = """
SELECT s.store_id, jsonb_build_object('is_open', s.raw -> 'is_open', 'next_schedule', s.raw -> 'next_schedule'),
       d.schedules
FROM stores s LEFT JOIN restaurant_details d ON d.store_id = s.store_id
WHERE s.store_id = ANY(%s)"""


def _id(value) -> int | None:
    """Un id numérico del catálogo, o None (lo que no tiene esa forma no se busca)."""
    text = str(value) if value is not None else ""
    return int(text) if text.isascii() and text.isdigit() and int(text) <= BIGINT_MAX else None


def _price(price, real, discount) -> dict:
    """Precio, precio de lista (solo si es mayor: hay oferta) y descuento, en pesos enteros."""
    if price is None or float(price) < MIN_PRICE:
        return {}
    out = {"precio": round(float(price))}
    if real is not None and float(real) > float(price):
        out["precio_lista"] = round(float(real))
        if discount:
            out["descuento_pct"] = round(float(discount))
    return out


def _open(raw: dict | None, schedules, now) -> dict:
    """Abierta o cerrada según la descarga, con su fuente (`horario` o `descarga`); vacío si no se sabe."""
    schedule = clock.normalize_schedule(schedules)
    hours = clock.restaurant_hours(schedule, now) if schedule else clock.store_hours(raw)
    if hours is None or hours["open"] is None:
        return {}
    return {"abierta": hours["open"], "horario": hours["source"]}


def pin(conn: Connection, events: list, now=None) -> None:
    """Pone `payload.catalogo` en cada `view_store`, `view_item` y `cart_add` de `events` (los modifica). La tienda de
    un producto es `payload.store_id` (la manda la app); sin ella, la de su oferta vigente más barata."""
    wanted = [e for e in events if e.type in CONTEXT_TYPES]
    if not wanted:
        return
    now = now or clock.now_local()
    found: dict[int, dict] = {}  # índice en `wanted` → contexto
    store_of: dict[int, int] = {}  # índice → tienda cuyo estado se busca
    in_store = []  # (índice, producto, tienda)
    anywhere = []  # (índice, producto): sin tienda, la oferta más barata
    dishes = []  # (índice, plato)
    for i, e in enumerate(wanted):
        e.payload.pop(KEY, None)
        entity = _id(e.entity_id)
        store = _id(e.payload.get("store_id"))
        if e.entity_type == "store" and entity is not None:
            store_of[i] = entity
        elif e.entity_type == "catalog_item" and entity is not None:
            if store is not None:
                in_store.append((i, entity, store))
                store_of[i] = store
            else:
                anywhere.append((i, entity))
        elif e.entity_type == "menu_item" and entity is not None:
            dishes.append((i, entity))
    if in_store:
        rows = conn.execute(
            _STORE_OFFERS,
            {"ids": [p for _, p, _ in in_store], "stores": [s for _, _, s in in_store], "min_price": MIN_PRICE},
        )
        for n, price, real, discount in rows:
            found[in_store[n - 1][0]] = _price(price, real, discount)
    if anywhere:
        rows = conn.execute(_CHEAPEST, {"ids": [p for _, p in anywhere], "min_price": MIN_PRICE})
        for n, price, real, store_id in rows:
            i = anywhere[n - 1][0]
            found[i] = _price(price, real, None)
            if store_id is not None:
                store_of[i] = store_id
    if dishes:
        by_dish = {row[0]: row for row in conn.execute(_DISHES, ([d for _, d in dishes],))}
        for i, dish in dishes:
            if (row := by_dish.get(dish)) is not None:
                _, store_id, price, real, discount, available = row
                found[i] = _price(price, real, discount) | ({"disponible": available} if available is not None else {})
                store_of[i] = store_id
    if store_of:
        states = {
            store_id: _open(raw, schedules, now)
            for store_id, raw, schedules in conn.execute(_STORES, (sorted(set(store_of.values())),))
        }
        for i, store_id in store_of.items():
            found[i] = found.get(i, {}) | states.get(store_id, {})
    for i, e in enumerate(wanted):
        if found.get(i):
            e.payload[KEY] = found[i]
