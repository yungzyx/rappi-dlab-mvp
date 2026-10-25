"""«Para ti» dentro de una tienda: lo que esa tienda tiene vigente de los conceptos que más le interesan a la persona.

Es una recomendación que la persona no pidió, así que pasa por las guardias de las ofertas (`offers/guards.py`): nada
de Farmacia ni Licores, de una tienda Farmacia, Sex shop o Smoking shop, +18, bebé, salud ni un concepto sensible. El
interés es el perfil de la persona (`events.store.profile`, con decaimiento de 14 días); sin interés que calce no hay
pestaña. Solo lo pide la propuesta: «Rappi hoy» no enseña.
"""

from psycopg import Connection
from rappi_scraper.storage.search import MIN_PRICE

from ..concepts.taxonomy import load_taxonomy
from ..events import store as events
from ..offers.engine import _offerable_products
from ..offers.guards import is_offerable, offerable_vertical
from .stores import BIGINT_MAX, OWN_VERTICAL, product_card

FOR_YOU_PRODUCTS = 8
FOR_YOU_CONCEPTS = 6  # los intereses que más pesan, de los que salen los productos

_STORE = f"""
SELECT btrim(coalesce(b.name, s.name)), {OWN_VERTICAL}
FROM stores s LEFT JOIN brands b ON b.brand_id = s.brand_id
WHERE s.store_id = %(store_id)s"""

# Lo vigente de una tienda (en un pasillo, no agotado) de esos conceptos, un SKU por producto (el más barato).
_PRODUCTS = """
SELECT DISTINCT ON (ci.master_product_id) ci.master_product_id::text, ci.name, l.price, l.real_price,
       NULLIF(ci.image_url, ''), ci.presentation, ci.is_alcoholic OR ci.age_restricted, ic.concept_id
FROM store_products sp
JOIN item_concepts ic ON ic.entity_type = 'catalog_item' AND ic.entity_id = sp.master_product_id::text
JOIN catalog_items ci ON ci.master_product_id = sp.master_product_id
JOIN v_latest_offers l ON l.store_id = sp.store_id AND l.sku = sp.sku
JOIN aisles a ON a.store_id = sp.store_id AND a.aisle_id = sp.aisle_id AND a.parent_aisle_id IS NULL
WHERE sp.store_id = %(store_id)s AND ic.concept_id = ANY(%(concepts)s)
  AND l.current AND l.in_stock IS NOT FALSE AND l.price >= %(min_price)s
ORDER BY ci.master_product_id, l.price"""

# Los platos con precio de un restaurante de esos conceptos.
_DISHES = """
SELECT mi.item_id::text, mi.name, p.price, p.real_price, NULLIF(mi.image_url, ''), NULL, false, ic.concept_id
FROM menu_items mi
JOIN latest_menu_prices p ON p.item_id = mi.item_id
JOIN item_concepts ic ON ic.entity_type = 'menu_item' AND ic.entity_id = mi.item_id::text
WHERE mi.store_id = %(store_id)s AND ic.concept_id = ANY(%(concepts)s) AND p.price >= %(min_price)s"""


def store_for_you(conn: Connection, store_id: int, user_id: str) -> dict:
    """`{products, basis}`: hasta FOR_YOU_PRODUCTS productos (o platos) de la tienda, primero los del interés que más
    pesa y, dentro de él, del más barato al más caro. `basis` dice de qué intereses salen. Vacío si la tienda no existe,
    es de una vertical que no se ofrece o nada calza."""
    empty = {"products": [], "basis": []}
    if not 0 <= store_id <= BIGINT_MAX:
        return empty
    store = conn.execute(_STORE, {"store_id": store_id}).fetchone()
    if store is None or store[1] is None or not offerable_vertical(store[1]):
        return empty
    name, vertical = store
    taxonomy = load_taxonomy()
    interests = [
        c for c in events.profile(conn, user_id) if c in taxonomy.concepts and is_offerable(taxonomy.concepts[c])
    ][:FOR_YOU_CONCEPTS]
    if not interests:
        return empty
    restaurant = vertical == "restaurantes"
    rows = conn.execute(
        _DISHES if restaurant else _PRODUCTS, {"store_id": store_id, "concepts": interests, "min_price": MIN_PRICE}
    ).fetchall()
    entity_type = "menu_item" if restaurant else "catalog_item"
    cards = [product_card(row, vertical, name, store_id, taxonomy, entity_type).to_dict() for row in rows]
    cards = [c for c in _offerable_products(conn, cards) if c["price_value"] is not None]
    cards.sort(key=lambda c: (interests.index(c["concept"]), c["price_value"], c["id"]))
    chosen = cards[:FOR_YOU_PRODUCTS]
    used = [c for c in interests if any(p["concept"] == c for p in chosen)]
    return {
        "products": chosen,
        "basis": [{"kind": "interes", "id": concept, "source": "eventos:persona"} for concept in used],
    }
