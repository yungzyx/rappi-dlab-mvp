"""Tiendas y productos del catálogo con el precio vigente de cada tienda. Solo lectura, consultas parametrizadas.

Oferta vigente: la de la vista `v_latest_offers` (migración 032), la misma que usan el precio que muestra el agente
(`_with_prices`, agent/tools.py) y la búsqueda (`_OFFER_PRICES`, rappi_scraper/storage/search.py): el último precio de
la tienda para ese SKU es de la corrida `format_run_id` de su formato (`v_store_format_runs`, migración 019) o, en un
pasillo que esa corrida no pudo leer, de la bajada anterior de su formato; y `in_stock` no es `false`. Además, el
precio tiene que ser real (desde `MIN_PRICE`): uno de relleno cuenta como desconocido y el producto no se ofrece.

Una tienda se lista y se abre por sus ofertas vigentes que están en un pasillo (la página muestra los productos por
pasillo): así la cuenta de la tarjeta es la suma de sus pasillos, y una tienda sin pasillos no sale como una página
vacía. Eso deja fuera a las tiendas solo descubiertas (sin productos), a las sucursales cuya última descarga es anterior
a la de su formato y a las importadas de un CSV antiguo (sin `raw` ni pasillos).
"""

from psycopg import Connection
from rappi_scraper.storage.search import MIN_PRICE

from ..agent.tools import Product
from ..agent.verticals import LOGO_BASE_URL
from ..concepts.taxonomy import load_taxonomy
from .cache import cached

BIGINT_MAX = 2**63 - 1

# Farmacia no se empuja: no entra en «Cerca de ti» ni en las ofertas sin vertical. Restaurantes no vende productos del
# catálogo (tiene menús), así que tampoco es una tienda de «Cerca de ti».
# Lo que el agente no ofrece por su cuenta tiene su propia lista (offers/guards.py), que reutiliza
# NOT_PUSHED_SUBVERTICALS.
NOT_PUSHED_VERTICALS = ("farmacia", "restaurantes")
# Tampoco las tiendas que Rappi rotula con estos subverticales (store_verticals.subvertical), sea cual sea su vertical:
# en la base real, sex shops y smoking shops (tabaco, Ley 20.105) del mall y farmacias listadas entre los súper (Cruz
# Verde). Quien abre su vertical a propósito (Retail, Súper) sí las ve: la regla es de lo que la app propone sola.
NOT_PUSHED_SUBVERTICALS = ("Farmacia", "Sex shop", "Smoking shop")


def not_pushed_params() -> dict[str, list[str]]:
    """Los parámetros que pide el CTE `downloaded` sin vertical (`downloaded_cte(False)`)."""
    return {"not_pushed": list(NOT_PUSHED_VERTICALS), "not_pushed_subverticals": list(NOT_PUSHED_SUBVERTICALS)}


# Las ofertas vigentes de UNA tienda con su pasillo, una por producto del catálogo (la más barata, si la tienda lo tiene
# en dos SKU): `offers` es el CTE de la página de la tienda (`_STORE_PAGE`).
_STORE_OFFERS = """
offers AS (
    SELECT DISTINCT ON (sp.master_product_id) sp.master_product_id, a.aisle_id, a.name AS aisle, l.price, l.real_price
    FROM v_latest_offers l
    JOIN store_products sp ON sp.store_id = %(store_id)s AND sp.sku = l.sku
    JOIN aisles a ON a.store_id = %(store_id)s AND a.aisle_id = sp.aisle_id AND a.parent_aisle_id IS NULL
    WHERE l.store_id = %(store_id)s AND l.current AND sp.master_product_id IS NOT NULL AND l.in_stock IS NOT FALSE
      AND l.price >= %(min_price)s
    ORDER BY sp.master_product_id, l.price, sp.sku
)"""

# El vertical de la tienda `s`: el propio (su fila de store_verticals); los heredados de su formato, solo si no tiene.
OWN_VERTICAL = """(
    SELECT v.vertical FROM v_store_verticals v WHERE v.store_id = s.store_id
    ORDER BY EXISTS (SELECT 1 FROM store_verticals d WHERE d.store_id = v.store_id AND d.vertical = v.vertical) DESC,
             v.vertical
    LIMIT 1)"""

# La página de una tienda en una sola consulta (`offers` se calcula una vez): su tarjeta, sus pasillos con ofertas
# vigentes, el pasillo elegido y una página de sus productos.
# - Un producto de un subpasillo trae también el id de su pasillo, así que los subpasillos no aparecen aparte. Rappi no
#   guarda la posición de los pasillos y su id no es un orden (en la base real Turbo abría en «Autopartes», con un
#   puñado de productos): primero el de más ofertas vigentes, y con las mismas, el id.
# - El pasillo elegido es el pedido (`%(aisle_id)s`, si la tienda lo tiene) o, sin pedir uno (`%(first)s`), el primero.
# - Los productos van por nombre (y por id, que desempata nombres repetidos: sin eso, una página podría repetir o
#   saltarse productos).
_STORE_PAGE = f"""
WITH {_STORE_OFFERS},
aisle_list AS (
    SELECT aisle_id, btrim(aisle) AS name, count(*) AS products FROM offers GROUP BY aisle_id, aisle
),
chosen AS (
    SELECT aisle_id FROM aisle_list
    WHERE %(first)s OR aisle_id = %(aisle_id)s
    ORDER BY products DESC, aisle_id
    LIMIT 1
),
page AS (
    SELECT ci.master_product_id AS mid, ci.master_product_id::text AS id, ci.name, o.price, o.real_price,
           NULLIF(ci.image_url, '') AS image, ci.presentation, ci.is_alcoholic OR ci.age_restricted AS adult,
           ic.concept_id
    FROM offers o
    JOIN chosen USING (aisle_id)
    JOIN catalog_items ci ON ci.master_product_id = o.master_product_id
    LEFT JOIN item_concepts ic ON ic.entity_type = 'catalog_item' AND ic.entity_id = ci.master_product_id::text
    ORDER BY ci.name, ci.master_product_id
    LIMIT %(limit)s OFFSET %(offset)s
)
SELECT s.store_id, btrim(coalesce(b.name, s.name)), s.raw->>'image', s.raw->>'eta_value',
       (SELECT count(*) FROM offers), {OWN_VERTICAL},
       (SELECT json_agg(json_build_array(aisle_id, name, products) ORDER BY products DESC, aisle_id) FROM aisle_list),
       (SELECT aisle_id FROM chosen),
       (SELECT json_agg(json_build_array(id, name, price, real_price, image, presentation, adult, concept_id)
                        ORDER BY name, mid)
        FROM page)
FROM stores s
LEFT JOIN brands b ON b.brand_id = s.brand_id
WHERE s.store_id = %(store_id)s"""

# Las ofertas vigentes de la tienda `d` (una fila con `store_id`), por su último precio `ps` (v_latest_offers), con su
# producto `sp` y su pasillo `a`. Es la regla de _STORE_OFFERS, _CATALOG_DETAIL y _with_prices dicha desde las tiendas:
# la usan las tarjetas de una vertical, «Cerca de ti» y las ofertas (rappi_ia/catalog/). Va tras un SELECT que elige
# columnas de `ps` y `sp`, dentro de un LATERAL o de un EXISTS.
CURRENT_OFFERS = """
FROM v_latest_offers ps
JOIN store_products sp ON sp.store_id = ps.store_id AND sp.sku = ps.sku
JOIN aisles a ON a.store_id = sp.store_id AND a.aisle_id = sp.aisle_id AND a.parent_aisle_id IS NULL
WHERE ps.store_id = d.store_id AND ps.current AND sp.master_product_id IS NOT NULL
  AND ps.in_stock IS NOT FALSE AND ps.price >= %(min_price)s"""

# Las tiendas descargadas por última vez en su formato (`downloaded`, con `store_id` y `format_run_id`): las de una
# vertical (`%(vertical)s`) o, sin vertical, las que tienen alguna que se empuje (`%(not_pushed)s` son las que no) y
# ningún subvertical que no se empuje (`%(not_pushed_subverticals)s`, solo los propios de la tienda).
# Una unión positiva con v_store_verticals: `NOT EXISTS` la leía entera (tres veces más lento). Con `history`, cada una
# dice si tiene precios de corridas anteriores (`has_history`); sin ellos no hay baja de precio que buscar, y saberlo
# cuesta recorrer los precios de las tiendas grandes.
_DOWNLOADED = """
downloaded AS MATERIALIZED (
    SELECT DISTINCT f.store_id, f.format_run_id{history}
    FROM v_store_format_runs f
    JOIN v_store_verticals v ON v.store_id = f.store_id AND {scope}{unpushed}
)"""
_NOT_PUSHED_SUBVERTICAL = """
    WHERE NOT EXISTS (SELECT 1 FROM store_verticals own
                      WHERE own.store_id = f.store_id AND own.subvertical = ANY(%(not_pushed_subverticals)s))"""
_HAS_HISTORY = """,
           EXISTS (SELECT 1 FROM price_snapshots e
                   WHERE e.store_id = f.store_id AND e.run_id < f.format_run_id) AS has_history"""


def downloaded_cte(in_vertical: bool, history: bool = False) -> str:
    """El CTE `downloaded` de una vertical (parámetro `vertical`) o de las que se empujan (`not_pushed_params`)."""
    return _DOWNLOADED.format(
        scope="v.vertical = %(vertical)s" if in_vertical else "v.vertical <> ALL(%(not_pushed)s)",
        unpushed="" if in_vertical else _NOT_PUSHED_SUBVERTICAL,
        history=_HAS_HISTORY if history else "",
    )


# Una tarjeta por formato (store_type) del vertical: la sucursal que la última corrida de su formato bajó. Si hubiera
# varias en esa corrida, la de más ofertas. Las tarjetas se cortan antes de unir con tiendas y marcas. El LATERAL hace
# que el plan busque por llave en vez de leer price_snapshots entero (el plan sin él tardaba el doble).
_VERTICAL_STORES = f"""
WITH downloaded AS MATERIALIZED (
    SELECT f.store_id, f.format, f.format_run_id
    FROM v_store_format_runs f
    JOIN v_store_verticals v ON v.store_id = f.store_id AND v.vertical = %(vertical)s
    WHERE EXISTS (SELECT 1 FROM aisles a WHERE a.store_id = f.store_id AND a.parent_aisle_id IS NULL)  -- sin pasillos
),
offers AS (
    SELECT d.format, d.store_id, o.master_product_id
    FROM downloaded d
    CROSS JOIN LATERAL (SELECT sp.master_product_id {CURRENT_OFFERS}) o
),
counted AS (
    SELECT format, store_id, count(DISTINCT master_product_id) AS products FROM offers GROUP BY format, store_id
),
one_per_format AS (
    SELECT DISTINCT ON (format) store_id, products FROM counted ORDER BY format, products DESC, store_id
),
top AS (
    SELECT store_id, products FROM one_per_format ORDER BY products DESC, store_id LIMIT %(limit)s
)
SELECT s.store_id, btrim(coalesce(b.name, s.name)), s.raw->>'image', s.raw->>'eta_value', t.products
FROM top t
JOIN stores s ON s.store_id = t.store_id
LEFT JOIN brands b ON b.brand_id = s.brand_id
ORDER BY t.products DESC, s.store_id"""

# El producto del catálogo con su oferta vigente más barata entre las tiendas que se abren con este producto en un
# pasillo (como en /catalog/stores): el precio, el precio anterior y la tienda son de esa misma oferta. Sin ninguna
# tienda que se abra, la oferta más barata de todas, con el id de tienda nulo.
_CATALOG_DETAIL = f"""
WITH offers AS (
    SELECT l.store_id, l.price, l.real_price,
           EXISTS (SELECT 1 FROM aisles a
                   WHERE a.store_id = l.store_id AND a.aisle_id = sp.aisle_id AND a.parent_aisle_id IS NULL) AS openable
    FROM store_products sp
    JOIN v_latest_offers l ON l.store_id = sp.store_id AND l.sku = sp.sku
    WHERE sp.master_product_id = %(id)s AND l.current AND l.in_stock IS NOT FALSE AND l.price >= %(min_price)s
),
chosen AS (SELECT * FROM offers ORDER BY openable DESC, price, store_id LIMIT 1)
SELECT ci.master_product_id::text, ci.name, c.price, c.real_price, btrim(coalesce(b.name, s.name)),
       CASE WHEN c.openable THEN c.store_id END,
       NULLIF(ci.image_url, ''), ci.presentation, ci.is_alcoholic OR ci.age_restricted, ic.concept_id,
       {OWN_VERTICAL}
FROM chosen c
JOIN catalog_items ci ON ci.master_product_id = %(id)s
JOIN stores s ON s.store_id = c.store_id
LEFT JOIN brands b ON b.brand_id = s.brand_id
LEFT JOIN item_concepts ic ON ic.entity_type = 'catalog_item' AND ic.entity_id = ci.master_product_id::text"""

# Un plato con su último precio (`latest_menu_prices`, desempatado por corrida; como lo muestra el agente).
_MENU_DETAIL = """
SELECT mi.item_id::text, mi.name, mp.price, mp.real_price, s.name, s.store_id, NULLIF(mi.image_url, ''), ic.concept_id
FROM menu_items mi
JOIN stores s ON s.store_id = mi.store_id
LEFT JOIN latest_menu_prices mp ON mp.item_id = mi.item_id
LEFT JOIN item_concepts ic ON ic.entity_type = 'menu_item' AND ic.entity_id = mi.item_id::text
WHERE mi.item_id = %(id)s"""


# El precio vigente de productos del catálogo, cada uno en SU tienda: su oferta vigente por SKU, no agotada (la regla
# de _CATALOG_DETAIL, sin pedir pasillo); si la tienda lo tiene en dos SKU, el más barato. Una sola consulta para todas
# las líneas de un pedido: `n` es la posición de cada par (producto, tienda), y uno sin oferta vigente no sale.
_STORE_PRICES = """
SELECT x.n, min(l.price)
FROM unnest(%(ids)s::bigint[], %(stores)s::bigint[]) WITH ORDINALITY x(id, store_id, n)
JOIN store_products sp ON sp.store_id = x.store_id AND sp.master_product_id = x.id
JOIN v_latest_offers l ON l.store_id = sp.store_id AND l.sku = sp.sku
WHERE l.current AND l.in_stock IS NOT FALSE AND l.price >= %(min_price)s
GROUP BY x.n"""


def store_prices(conn: Connection, wanted: list[tuple[str, int]]) -> list[float | None]:
    """El precio vigente de cada producto del catálogo (`entity_id`) en su tienda, en el orden de `wanted`, con una
    sola consulta. `None` si no hay oferta vigente o el id no es válido."""
    valid = [
        (i, int(entity_id), store_id)
        for i, (entity_id, store_id) in enumerate(wanted)
        if entity_id.isascii() and entity_id.isdigit() and int(entity_id) <= BIGINT_MAX and 0 <= store_id <= BIGINT_MAX
    ]
    prices: list[float | None] = [None] * len(wanted)
    if not valid:
        return prices
    rows = conn.execute(
        _STORE_PRICES,
        {"ids": [item_id for _, item_id, _ in valid], "stores": [s for _, _, s in valid], "min_price": MIN_PRICE},
    )
    for n, price in rows:
        prices[valid[n - 1][0]] = float(price)
    return prices


def offer_price(conn: Connection, entity_type: str, entity_id: str, store_id: int | None) -> float | None:
    """El precio vigente de una línea de pedido: el de su tienda (`store_id`, de donde la persona lo agregó: entre
    tiendas el precio cambia) o, sin tienda, el de la ficha del producto (la oferta más barata). Un plato es de un solo
    restaurante: con otra tienda no tiene precio. `None` si no hay oferta vigente."""
    if entity_type == "catalog_item" and store_id is not None:
        return store_prices(conn, [(entity_id, store_id)])[0]
    detail = product_detail(conn, entity_type, entity_id)
    if detail is None or (entity_type == "menu_item" and store_id is not None and detail["store_id"] != store_id):
        return None
    return detail["price_value"]


def vertical_stores(conn: Connection, vertical: str, limit: int = 30) -> list[dict]:
    """Una tarjeta por formato de tienda del vertical, de más a menos ofertas vigentes. Restaurantes no entra: sus
    locales no venden productos del catálogo (tienen menú). Sale de la caché del catálogo (catalog/cache.py)."""
    if vertical == "restaurantes":
        return []

    def compute() -> list[dict]:
        rows = conn.execute(_VERTICAL_STORES, {"vertical": vertical, "min_price": MIN_PRICE, "limit": limit})
        return [store_card(store_id, name, image, eta, count, vertical) for store_id, name, image, eta, count in rows]

    return cached(f"vertical_stores:{vertical}:{limit}", conn, compute)


def store_page(
    conn: Connection, store_id: int, aisle_id: int | None = None, page: int = 1, page_size: int = 24
) -> dict | None:
    """La tienda con sus pasillos y una página de los productos de uno (el primero, si no se pide uno). `None` si la
    tienda no existe o no tiene ofertas vigentes. Con un pasillo que la tienda no tiene (o sin ofertas), `aisle` es
    `None` y no hay productos."""
    if not 0 <= store_id <= BIGINT_MAX:
        return None
    params = {
        "store_id": store_id,
        "min_price": MIN_PRICE,
        "first": aisle_id is None,
        "aisle_id": aisle_id,
        "limit": page_size + 1,  # una más de las que se piden: así se sabe si hay otra página sin contar
        "offset": (page - 1) * page_size,
    }
    row = conn.execute(_STORE_PAGE, params).fetchone()
    if row is None or row[4] == 0:
        return None
    store = store_card(*row[:6])
    aisles = [{"id": id_, "name": name, "products": count} for id_, name, count in row[6] or []]
    chosen = next((a for a in aisles if a["id"] == row[7]), None)
    taxonomy = load_taxonomy()
    products = [product_card(p, store["vertical"], store["name"], store_id, taxonomy) for p in row[8] or []]
    return {
        "store": store,
        "aisles": aisles,
        "aisle": chosen,
        "products": [p.to_dict() for p in products[:page_size]],
        "page": page,
        "has_more": len(products) > page_size,
    }


def product_detail(conn: Connection, entity_type: str, entity_id: str) -> dict | None:
    """Un producto del catálogo con su oferta vigente más barata, o un plato con su último precio. `None` si no existe
    o no tiene precio. Si alguna tienda que se abre lo vende (con el producto en un pasillo), el precio, el precio
    anterior, la tienda y `store_id` son los de la oferta vigente más barata de esas tiendas; si no, los de la oferta
    vigente más barata de todas (una tienda sin pasillos, importada de un CSV antiguo) y `store_id` es `None`."""
    item_id = int(entity_id) if entity_id.isascii() and entity_id.isdigit() else None
    if item_id is None or item_id > BIGINT_MAX:
        return None
    taxonomy = load_taxonomy()
    if entity_type == "catalog_item":
        row = conn.execute(_CATALOG_DETAIL, {"id": item_id, "min_price": MIN_PRICE}).fetchone()
        if row is None:
            return None
        id_, name, price, real, store, store_id, image, presentation, adult, concept, vertical = row
        product = product_card(
            (id_, name, price, real, image, presentation, adult, concept), vertical, store, store_id, taxonomy
        )
    elif entity_type == "menu_item":
        row = conn.execute(_MENU_DETAIL, {"id": item_id}).fetchone()
        if row is None:
            return None
        id_, name, price, real, store, store_id, image, concept = row
        product = product_card(
            (id_, name, price, real, image, None, False, concept),
            "restaurantes",
            store,
            store_id,
            taxonomy,
            entity_type,
        )
    else:
        return None
    return product.to_dict() if product.price_value is not None else None


def store_card(
    store_id: int, name: str, image: str | None, eta: str | None, products: int, vertical: str | None
) -> dict:
    return {
        "id": store_id,
        "name": name,
        "logo": LOGO_BASE_URL + image if image else None,
        "eta": _eta_text(eta),
        "products": products,
        "vertical": vertical,
    }


def _eta_text(value: str | None) -> str | None:
    """«25 min» a partir de los minutos que Rappi guarda en la tienda; sin minutos (o en 0), nada."""
    try:
        minutes = round(float(value)) if value else 0
    except (ValueError, OverflowError):  # texto que no es un número, o uno infinito
        return None
    return f"{minutes} min" if minutes > 0 else None


def product_card(
    row, vertical: str | None, store: str, store_id: int | None, taxonomy, entity_type: str = "catalog_item"
):
    """El `Product` de una fila (id, nombre, precio, precio antes, imagen, presentación, +18 por producto, concepto).
    Un precio de relleno ($0, $1) cuenta como desconocido, igual que en `_with_prices`."""
    entity_id, name, price, real, image, presentation, adult, concept_id = row
    concept = taxonomy.concepts.get(concept_id) if concept_id else None
    return Product(
        id=f"{'cat' if entity_type == 'catalog_item' else 'menu'}-{entity_id}",
        entity_type=entity_type,
        entity_id=entity_id,
        name=name,
        vertical=vertical,
        concept=concept_id,
        price_value=float(price) if price is not None and price >= MIN_PRICE else None,
        before_value=float(real) if real is not None else None,
        store=store,
        img=image,
        age_restricted=bool(adult) or bool(concept and concept.age_restricted),
        store_id=store_id,
        presentation=presentation or None,
    )
