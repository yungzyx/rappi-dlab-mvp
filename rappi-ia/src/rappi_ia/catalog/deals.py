"""Ofertas: productos con una baja de precio real o con una rebaja de la tienda, en una oferta vigente. Solo lectura,
consultas parametrizadas.

Una oferta es una oferta vigente de una tienda que se abre (la regla de `stores.CURRENT_OFFERS`) con un precio de
antes mayor que el actual:

- si la tienda marca un precio de lista (`real_price`) por encima del actual (`discount_pct` > 0), ese es el de
  antes: es el que la tarjeta del producto en su tienda ya muestra;
- si no, el precio anterior de la misma tienda cuando bajó (`v_price_changes`, con `diferencia` negativa en la
  corrida de la oferta). Una baja seguida de una subida, o un precio que no cambió, no cuenta.

Un descuento de más de `MAX_DISCOUNT_PCT` (60 %) no es una rebaja: en la base real son precios de lista por kilo contra
precios por unidad (fruta a granel con -90 %), y esas ofertas no salen.

El precio, el de antes, la tienda y su vertical son de una misma oferta. Un producto en varias tiendas sale una vez, con
la oferta de mayor descuento.

Una oferta se propone sin que nadie la pida, así que sigue la regla del agente: un producto de concepto sensible
(`sensitive` en la taxonomía: medicamentos, salud y bienestar sexual, tabaco, vapeo) no sale en ninguna vertical.
Sin vertical, tampoco las tiendas que no se empujan (`stores.NOT_PUSHED_*`).
"""

from psycopg import Connection
from rappi_scraper.storage.search import MIN_PRICE

from ..agent.tools import Product
from ..concepts.taxonomy import load_taxonomy, sensitive_concepts
from .cache import cached
from .stores import CURRENT_OFFERS, OWN_VERTICAL, downloaded_cte, not_pushed_params, product_card

MAX_DISCOUNT_PCT = 60

# Primero se buscan las filas que cambiaron en la corrida de cada tienda (las que la tienda rebajó y las que bajaron de
# precio) y solo a ellas se les aplica la regla de oferta vigente: aplicarla a todas las filas de todas las tiendas
# (140.000 en la base real) tarda varias veces más. El precio anterior es el del snapshot anterior del mismo SKU en la
# tienda, que es la definición de v_price_changes (`lag` por tienda y SKU); se busca por el índice (store_id, sku,
# scraped_at) solo para las filas de la corrida, porque la ventana de la vista no se puede acotar a unas tiendas sin
# recorrer casi todo el historial. Un test compara ambas.
# Una oferta rescatada de un pasillo omitido (v_latest_offers) no es candidata a oferta, a propósito: su precio es de
# la corrida anterior, no cambió en la corrida de su formato.
_DEALS = f"""
WITH {{downloaded}},
changed AS MATERIALIZED (
    SELECT x.store_id, x.format_run_id, x.sku, x.before
    FROM (
        SELECT d.store_id, d.format_run_id, cur.sku, cur.price, cur.real_price, prev.price AS prev_price,
               CASE WHEN cur.real_price > cur.price THEN cur.real_price ELSE prev.price END AS before
        FROM downloaded d
        CROSS JOIN LATERAL (
            SELECT c.sku, c.price, c.real_price, c.scraped_at, c.run_id
            FROM price_snapshots c WHERE c.run_id = d.format_run_id AND c.store_id = d.store_id
        ) cur
        LEFT JOIN LATERAL (
            SELECT p.price FROM price_snapshots p
            WHERE p.store_id = d.store_id AND p.sku = cur.sku AND p.scraped_at < cur.scraped_at
              AND d.has_history AND NOT coalesce(cur.real_price > cur.price, false)
            ORDER BY p.scraped_at DESC
            LIMIT 1
        ) prev ON true
    ) x
    WHERE (x.real_price > x.price OR x.prev_price > x.price)
      AND x.price * 100 >= x.before * (100 - %(max_discount)s)
),
offers AS (
    SELECT d.store_id, o.master_product_id, o.price, d.before
    FROM changed d
    CROSS JOIN LATERAL (
        SELECT sp.master_product_id, ps.price
        {CURRENT_OFFERS}
          AND ps.sku = d.sku
    ) o
),
best AS (
    SELECT DISTINCT ON (master_product_id) master_product_id, store_id, price, before
    FROM offers
    ORDER BY master_product_id, 1 - price / before DESC, price, store_id
),
top AS (
    SELECT * FROM best
    WHERE NOT EXISTS (SELECT 1 FROM item_concepts ic
                      WHERE ic.entity_type = 'catalog_item' AND ic.entity_id = best.master_product_id::text
                        AND ic.concept_id = ANY(%(sensitive)s))
    ORDER BY 1 - price / before DESC, master_product_id LIMIT %(limit)s
)
SELECT ci.master_product_id::text, ci.name, t.price, t.before, btrim(coalesce(b.name, s.name)), t.store_id,
       NULLIF(ci.image_url, ''), ci.presentation, ci.is_alcoholic OR ci.age_restricted, ic.concept_id,
       {{vertical}}
FROM top t
JOIN catalog_items ci ON ci.master_product_id = t.master_product_id
JOIN stores s ON s.store_id = t.store_id
LEFT JOIN brands b ON b.brand_id = s.brand_id
LEFT JOIN item_concepts ic ON ic.entity_type = 'catalog_item' AND ic.entity_id = ci.master_product_id::text
ORDER BY 1 - t.price / t.before DESC, ci.master_product_id"""


def deals(conn: Connection, vertical: str | None = None, limit: int = 24) -> list[dict]:
    """Los productos que bajaron de precio (o que su tienda rebajó), del mayor descuento al menor, de una vertical si
    se pide. Sin vertical, no entran las tiendas que no se empujan (farmacia, sex shops, smoking shops). Ninguno es de
    un concepto sensible. Restaurantes no vende productos del catálogo: no tiene ofertas. Sale de la caché del
    catálogo (catalog/cache.py)."""
    if vertical == "restaurantes":
        return []
    return cached(f"deals:{vertical}:{limit}", conn, lambda: _deals(conn, vertical, limit))


def _deals(conn: Connection, vertical: str | None, limit: int) -> list[dict]:
    sql = _DEALS.format(
        downloaded=downloaded_cte(vertical is not None, history=True),
        vertical=OWN_VERTICAL if vertical is None else "%(vertical)s",
    )
    params = {
        "vertical": vertical,
        **not_pushed_params(),
        "sensitive": sorted(sensitive_concepts()),
        "min_price": MIN_PRICE,
        "limit": limit,
        "max_discount": MAX_DISCOUNT_PCT,
    }
    taxonomy = load_taxonomy()
    products: list[Product] = []
    for id_, name, price, before, store, store_id, image, presentation, adult, concept, own in conn.execute(
        sql, params
    ):
        # `before` va como precio de lista: `Product.to_dict` calcula el descuento y lo deja si es mayor que el precio.
        products.append(
            product_card(
                (id_, name, price, before, image, presentation, adult, concept), own, store, store_id, taxonomy
            )
        )
    return [product.to_dict() for product in products]
