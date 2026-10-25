"""Arma `search_documents` (uno por entidad y vertical) y permite buscar por texto dentro de un vertical.

El texto (`content`) no incluye precios: así un cambio de precio no obliga a regenerar el
embedding. Si el texto cambia (otro `content_hash`), el embedding guardado se invalida.
"""

from psycopg import Connection

from .repository import GONE_REASON

VERTICALS = ("supermercado", "conveniencia", "turbo", "mall", "farmacia", "licores", "chocolateria", "restaurantes")

# Bajo $10 no hay precio real en pesos chilenos: un plato a $0 o $1 es de relleno (su precio depende de las opciones
# que se elijan) y pasaba cualquier tope de precio. Se trata como precio desconocido.
MIN_PRICE = 10

# Clave de pg_advisory_xact_lock para reescribir search_documents. rappi-ia la toma antes de copiar vectores: sin
# ella, su UPDATE masivo y el upsert de abajo bloquean filas en distinto orden (deadlock). No sirve mirar
# scrape_runs: la corrida ya quedó 'done' cuando empieza esta reescritura.
SEARCH_DOCUMENTS_LOCK = 72_001

# Los documentos se arman primero en una tabla temporal y solo se escriben los que cambiaron: reescribir las
# ~300 mil filas en cada refresh insertaba cada una de nuevo en todos los índices (GIN y HNSW por partición).
_STAGE = """
CREATE TEMP TABLE staged_documents (
    vertical text, entity_type text, entity_id text, content text, metadata jsonb, content_hash text
) ON COMMIT DROP
"""

_UPSERT = """
INSERT INTO search_documents (vertical, entity_type, entity_id, content, metadata, content_hash)
SELECT vertical, entity_type, entity_id, content, metadata, content_hash FROM staged_documents
ON CONFLICT (vertical, entity_type, entity_id) DO UPDATE SET
    content = EXCLUDED.content,
    metadata = EXCLUDED.metadata,
    content_hash = EXCLUDED.content_hash,
    embedding = CASE WHEN search_documents.content_hash = EXCLUDED.content_hash
                     THEN search_documents.embedding END,
    embedding_model = CASE WHEN search_documents.content_hash = EXCLUDED.content_hash
                           THEN search_documents.embedding_model END,
    updated_at = now()
WHERE (search_documents.content_hash, search_documents.metadata)
      IS DISTINCT FROM (EXCLUDED.content_hash, EXCLUDED.metadata)
"""

_DELETE_STALE = """
DELETE FROM search_documents d
WHERE NOT EXISTS (SELECT 1 FROM staged_documents s
                  WHERE s.vertical = d.vertical AND s.entity_type = d.entity_type AND s.entity_id = d.entity_id)
"""

# Vigencia. Cada corrida baja una sucursal por formato de tienda (store_type) y una por cadena de restaurantes
# (brand_id), y no siempre la misma. Una oferta o un plato sigue vigente si su último precio es de la última corrida
# que bajó su formato o su cadena: así salen las sucursales viejas y lo que ya no se vende, y un formato que la última
# corrida no pudo bajar conserva su último dato. Un plato también sale si una corrida posterior ya no encontró su
# local o su cadena en Rappi (el motivo que anota pipeline/restaurants.py). Lo que no tiene ningún precio guardado
# no se descarta (no hay con qué compararlo).
# La vigencia de las ofertas está definida una sola vez, en la vista v_latest_offers (migración 032): la misma que usan
# la API y el agente en rappi-ia, con la excepción de los pasillos que la corrida no pudo leer. El último precio sale
# de latest_prices y latest_menu_prices (migración 032), sin ordenar todo el historial.
_OFFER_PRICES = """
CREATE TEMP TABLE offer_prices ON COMMIT DROP AS
SELECT store_id, sku, price, current FROM v_latest_offers
"""

_DISH_PRICES = f"""
CREATE TEMP TABLE dish_prices ON COMMIT DROP AS
WITH latest AS (
    SELECT lmp.item_id, lmp.price, lmp.real_price, lmp.run_id, lmp.scraped_at,
           mi.store_id, s.brand_id, COALESCE(s.brand_id::text, 'id:' || s.store_id) AS chain
    FROM latest_menu_prices lmp
    JOIN menu_items mi ON mi.item_id = lmp.item_id
    JOIN stores s ON s.store_id = mi.store_id
),
chain_run AS (
    SELECT DISTINCT ON (chain) chain, run_id FROM latest ORDER BY chain, scraped_at DESC, run_id DESC
),
gone AS (
    SELECT job_key, max(run_id) AS run_id
    FROM scrape_jobs
    WHERE job_type = 'restaurant' AND status = 'skipped' AND result->>'reason' = '{GONE_REASON}'
    GROUP BY job_key
)
SELECT l.item_id, l.price, l.real_price,
       l.run_id = c.run_id AND l.run_id >= GREATEST(gc.run_id, gr.run_id, 0) AS current
FROM latest l
JOIN chain_run c USING (chain)
LEFT JOIN gone gc ON gc.job_key = 'chain:' || l.brand_id
LEFT JOIN gone gr ON gr.job_key = 'rest:' || l.store_id
"""

# Los precios se agregan una sola vez por (producto, vertical) en CTEs; hacerlo con un
# LATERAL por producto recalculaba el último precio de todo el historial en cada fila.
CATALOG_DOCS = """
WITH offers AS (
    SELECT sp.store_id, sp.master_product_id, op.price, op.store_id IS NOT NULL AS priced
    FROM store_products sp
    LEFT JOIN offer_prices op ON op.store_id = sp.store_id AND op.sku = sp.sku
    WHERE sp.master_product_id IS NOT NULL AND op.current IS NOT FALSE
),
-- Como v_item_verticals, pero solo con las ofertas vigentes.
item_verticals AS (
    SELECT o.master_product_id, vsv.vertical,
           array_agg(DISTINCT vsv.subvertical) FILTER (WHERE vsv.subvertical IS NOT NULL) AS subverticals,
           count(DISTINCT o.store_id) AS stores
    FROM offers o
    JOIN v_store_verticals vsv ON vsv.store_id = o.store_id
    GROUP BY o.master_product_id, vsv.vertical
),
store_vertical AS (SELECT DISTINCT store_id, vertical FROM v_store_verticals),
-- Rappi marca los medicamentos con receta: el agente no los muestra cuando se habla de síntomas.
prescription AS (
    SELECT master_product_id FROM store_products
    WHERE master_product_id IS NOT NULL AND raw->>'requires_medical_prescription' = 'true'
    GROUP BY master_product_id
),
prices AS (
    SELECT o.master_product_id, sv.vertical,
           min(o.price) AS precio_min, max(o.price) AS precio_max,
           array_agg(DISTINCT COALESCE(b.name, s.name)) AS cadenas
    FROM offers o
    JOIN store_vertical sv ON sv.store_id = o.store_id
    JOIN stores s ON s.store_id = o.store_id
    LEFT JOIN brands b ON b.brand_id = s.brand_id
    WHERE o.priced
    GROUP BY o.master_product_id, sv.vertical
)
INSERT INTO staged_documents (vertical, entity_type, entity_id, content, metadata, content_hash)
SELECT iv.vertical, 'catalog_item', ci.master_product_id::text, d.content,
       jsonb_strip_nulls(jsonb_build_object(
           'master_product_id', ci.master_product_id, 'categoria', c.name, 'marca', NULLIF(ci.trademark, ''),
           'subverticales', iv.subverticals, 'tiendas', iv.stores, 'cadenas', p.cadenas,
           'precio_min', p.precio_min, 'precio_max', p.precio_max, 'imagen', NULLIF(ci.image_url, ''),
           'alcohol', ci.is_alcoholic, 'restriccion_edad', ci.age_restricted,
           'receta', CASE WHEN rx.master_product_id IS NOT NULL THEN true END)),
       md5(d.content)
FROM item_verticals iv
JOIN catalog_items ci USING (master_product_id)
LEFT JOIN categories c USING (category_id)
CROSS JOIN LATERAL (SELECT concat_ws('. ', clean_html(ci.name), 'Marca: ' || NULLIF(ci.trademark, ''),
                                     NULLIF(ci.presentation, ''), 'Categoría: ' || c.name,
                                     NULLIF(NULLIF(clean_html(ci.description), ''), ci.name)) AS content) d
LEFT JOIN prices p ON p.master_product_id = iv.master_product_id AND p.vertical = iv.vertical
LEFT JOIN prescription rx ON rx.master_product_id = iv.master_product_id
"""

MENU_DOCS = f"""
INSERT INTO staged_documents (vertical, entity_type, entity_id, content, metadata, content_hash)
SELECT 'restaurantes', 'menu_item', mi.item_id::text, d.content,
       jsonb_strip_nulls(jsonb_build_object(
           'store_id', s.store_id, 'restaurante', s.name, 'cadena', b.name, 'ciudad', NULLIF(s.city, ''),
           'cocinas', cu.cocinas, 'precio', CASE WHEN mp.price >= {MIN_PRICE} THEN mp.price END,
           'precio_normal', mp.real_price,
           'popular', mi.is_popular, 'imagen', NULLIF(mi.image_url, ''))),
       md5(d.content)
FROM menu_items mi
JOIN stores s ON s.store_id = mi.store_id
LEFT JOIN brands b ON b.brand_id = s.brand_id
LEFT JOIN menu_sections ms ON ms.store_id = mi.store_id AND ms.section_id = mi.section_id
LEFT JOIN LATERAL (SELECT string_agg(cuisine, ', ' ORDER BY cuisine) AS cocinas
                   FROM restaurant_cuisines rc WHERE rc.store_id = s.store_id) cu ON true
LEFT JOIN dish_prices mp ON mp.item_id = mi.item_id
CROSS JOIN LATERAL (SELECT concat_ws('. ', clean_html(mi.name), NULLIF(NULLIF(clean_html(mi.description), ''), mi.name),
                                     'Sección: ' || ms.name,
                                     'Restaurante: ' || s.name, 'Cocina: ' || cu.cocinas) AS content) d
WHERE mp.current IS NOT FALSE
"""

STORE_DOCS = """
INSERT INTO staged_documents (vertical, entity_type, entity_id, content, metadata, content_hash)
SELECT DISTINCT ON (vsv.vertical, s.store_id)
       vsv.vertical, 'store', s.store_id::text, d.content,
       jsonb_strip_nulls(jsonb_build_object(
           'store_id', s.store_id, 'cadena', b.name, 'ciudad', NULLIF(s.city, ''),
           'subvertical', COALESCE(vsv.subvertical, NULLIF(s.sub_group, '')), 'path', s.path)),
       md5(d.content)
FROM stores s
JOIN v_store_verticals vsv ON vsv.store_id = s.store_id
LEFT JOIN brands b ON b.brand_id = s.brand_id
LEFT JOIN LATERAL (SELECT string_agg(cuisine, ', ' ORDER BY cuisine) AS cocinas
                   FROM restaurant_cuisines rc WHERE rc.store_id = s.store_id) cu ON true
LEFT JOIN LATERAL (SELECT string_agg(a.name, ', ' ORDER BY a.product_count_declared DESC NULLS LAST) AS pasillos
                   FROM aisles a WHERE a.store_id = s.store_id AND a.parent_aisle_id IS NULL) pa ON true
CROSS JOIN LATERAL (SELECT concat_ws('. ', s.name, 'Marca: ' || b.name,
                                     'Tipo: ' || COALESCE(vsv.subvertical, NULLIF(s.sub_group, '')),
                                     'Cocina: ' || cu.cocinas, 'Pasillos: ' || pa.pasillos,
                                     'Ciudad: ' || NULLIF(s.city, '')) AS content) d
WHERE EXISTS (SELECT 1 FROM store_products sp
              LEFT JOIN offer_prices op ON op.store_id = sp.store_id AND op.sku = sp.sku
              WHERE sp.store_id = s.store_id AND op.current IS NOT FALSE)
   OR EXISTS (SELECT 1 FROM menu_items mi LEFT JOIN dish_prices mp ON mp.item_id = mi.item_id
              WHERE mi.store_id = s.store_id AND mp.current IS NOT FALSE)
ORDER BY vsv.vertical, s.store_id, vsv.subvertical NULLS LAST
"""


def build_search_documents(conn: Connection) -> dict[str, int]:
    """Regenera los documentos a partir de las tablas núcleo. Devuelve documentos armados por tipo, cuántos se
    escribieron (nuevos o con otro texto, precio o metadatos) y cuántos se borraron (ya no existen)."""
    counts = {}
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (SEARCH_DOCUMENTS_LOCK,))
        conn.execute("DROP TABLE IF EXISTS pg_temp.staged_documents, pg_temp.offer_prices, pg_temp.dish_prices")
        conn.execute(_STAGE)
        conn.execute(_OFFER_PRICES)
        conn.execute(_DISH_PRICES)
        conn.execute("ANALYZE offer_prices, dish_prices")
        for name, sql in (("catalog_item", CATALOG_DOCS), ("menu_item", MENU_DOCS), ("store", STORE_DOCS)):
            counts[name] = conn.execute(sql).rowcount
        conn.execute("ANALYZE staged_documents")
        counts["escritos"] = conn.execute(_UPSERT).rowcount
        counts["eliminados"] = conn.execute(_DELETE_STALE).rowcount
        # El vocabulario con que rappi-ia corrige errores de tipeo sale de estos mismos documentos (migración 041).
        conn.execute("SELECT refresh_search_vocabulary()")
        # Estadísticas al día: /health de la API estima con ellas cuántos documentos hay, y el planificador también.
        conn.execute("ANALYZE search_documents, search_vocabulary")
    return counts


def search(conn: Connection, vertical: str, query: str, limit: int = 10) -> list[dict]:
    """Búsqueda por texto (español) **dentro de un solo vertical**."""
    if vertical not in VERTICALS:
        raise ValueError(f"Vertical desconocido: {vertical!r}. Opciones: {', '.join(VERTICALS)}")
    rows = conn.execute(
        """
        SELECT entity_type, entity_id, content, metadata, ts_rank(tsv, q) AS rank
        FROM search_documents, websearch_to_tsquery('spanish', %s) q
        WHERE vertical = %s AND tsv @@ q
        ORDER BY rank DESC
        LIMIT %s
        """,
        (query, vertical, limit),
    ).fetchall()
    return [{"entity_type": r[0], "entity_id": r[1], "content": r[2], "metadata": r[3], "rank": r[4]} for r in rows]
