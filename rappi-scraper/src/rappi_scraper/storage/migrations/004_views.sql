-- Vistas de análisis.

-- Verticales de cada tienda: los propios más los de otras sucursales del mismo formato
-- (se scrapea una sucursal por formato, pero la marca puede figurar en varios verticales).
CREATE VIEW v_store_verticals AS
SELECT sv.store_id, sv.vertical, sv.subvertical
FROM store_verticals sv
UNION
SELECT s.store_id, sv.vertical, sv.subvertical
FROM stores s
JOIN stores other ON other.store_type = s.store_type
JOIN store_verticals sv ON sv.store_id = other.store_id
WHERE s.store_type IS NOT NULL;

CREATE VIEW v_latest_prices AS
SELECT DISTINCT ON (ps.store_id, ps.sku)
       ps.store_id, ps.sku, ps.price, ps.real_price, ps.discount_pct, ps.pum,
       ps.in_stock, ps.run_id, ps.scraped_at
FROM price_snapshots ps
ORDER BY ps.store_id, ps.sku, ps.scraped_at DESC;

-- Qué productos del catálogo hay en cada vertical.
CREATE VIEW v_item_verticals AS
SELECT sp.master_product_id,
       vsv.vertical,
       array_agg(DISTINCT vsv.subvertical) FILTER (WHERE vsv.subvertical IS NOT NULL) AS subverticals,
       count(DISTINCT sp.store_id) AS stores
FROM store_products sp
JOIN v_store_verticals vsv ON vsv.store_id = sp.store_id
WHERE sp.master_product_id IS NOT NULL
GROUP BY sp.master_product_id, vsv.vertical;

CREATE VIEW v_vertical_summary AS
SELECT v.code AS vertical,
       (SELECT count(DISTINCT store_id) FROM v_store_verticals x WHERE x.vertical = v.code) AS tiendas_descubiertas,
       (SELECT count(DISTINCT sp.store_id) FROM store_products sp
          JOIN v_store_verticals x ON x.store_id = sp.store_id WHERE x.vertical = v.code) AS tiendas_scrapeadas,
       (SELECT count(*) FROM v_item_verticals iv WHERE iv.vertical = v.code) AS productos_unicos,
       (SELECT count(DISTINCT ci.trademark) FROM v_item_verticals iv
          JOIN catalog_items ci USING (master_product_id)
          WHERE iv.vertical = v.code AND ci.trademark <> '') AS marcas,
       (SELECT count(DISTINCT ci.category_id) FROM v_item_verticals iv
          JOIN catalog_items ci USING (master_product_id) WHERE iv.vertical = v.code) AS categorias,
       (SELECT count(*) FROM menu_items mi
          JOIN store_verticals x ON x.store_id = mi.store_id AND x.vertical = v.code) AS platos
FROM verticals v;

CREATE VIEW v_cross_vertical_items AS
SELECT ci.master_product_id, ci.name, ci.trademark,
       array_agg(iv.vertical ORDER BY iv.vertical) AS verticales,
       count(*) AS n_verticales
FROM v_item_verticals iv
JOIN catalog_items ci USING (master_product_id)
GROUP BY ci.master_product_id, ci.name, ci.trademark
HAVING count(*) > 1;

-- Mismo producto en distintas tiendas, con el último precio conocido.
CREATE VIEW v_price_compare AS
SELECT ci.master_product_id, ci.name AS producto, ci.presentation,
       b.name AS cadena, s.store_id, s.name AS tienda, s.city,
       lp.price, lp.real_price, lp.discount_pct, lp.in_stock, lp.scraped_at
FROM catalog_items ci
JOIN store_products sp USING (master_product_id)
JOIN stores s ON s.store_id = sp.store_id
LEFT JOIN brands b ON b.brand_id = s.brand_id
JOIN v_latest_prices lp ON lp.store_id = sp.store_id AND lp.sku = sp.sku;

-- Productos declarados vs obtenidos por sub-pasillo (tope de 24 en páginas públicas).
CREATE VIEW v_coverage AS
SELECT a.store_id, s.name AS tienda, parent.name AS pasillo, a.name AS sub_pasillo,
       a.product_count_declared AS declarados,
       count(sp.sku) AS obtenidos
FROM aisles a
JOIN stores s ON s.store_id = a.store_id
LEFT JOIN aisles parent ON parent.store_id = a.store_id AND parent.aisle_id = a.parent_aisle_id
LEFT JOIN store_products sp ON sp.store_id = a.store_id AND sp.sub_aisle_id = a.aisle_id
WHERE a.parent_aisle_id IS NOT NULL
GROUP BY a.store_id, s.name, parent.name, a.name, a.product_count_declared;

CREATE VIEW v_price_changes AS
SELECT * FROM (
    SELECT ps.store_id, ps.sku, ps.run_id, ps.scraped_at, ps.price,
           lag(ps.price) OVER w AS precio_anterior,
           ps.price - lag(ps.price) OVER w AS diferencia
    FROM price_snapshots ps
    WINDOW w AS (PARTITION BY ps.store_id, ps.sku ORDER BY ps.scraped_at)
) t
WHERE precio_anterior IS NOT NULL AND diferencia <> 0;
