-- v_vertical_summary: los restaurantes cuentan como scrapeados si tienen platos (no productos).
CREATE OR REPLACE VIEW v_vertical_summary AS
SELECT v.code AS vertical,
       (SELECT count(DISTINCT store_id) FROM v_store_verticals x WHERE x.vertical = v.code) AS tiendas_descubiertas,
       (SELECT count(DISTINCT x.store_id) FROM v_store_verticals x
          WHERE x.vertical = v.code
            AND (EXISTS (SELECT 1 FROM store_products sp WHERE sp.store_id = x.store_id)
                 OR EXISTS (SELECT 1 FROM menu_items mi WHERE mi.store_id = x.store_id))) AS tiendas_scrapeadas,
       (SELECT count(*) FROM v_item_verticals iv WHERE iv.vertical = v.code) AS productos_unicos,
       (SELECT count(DISTINCT ci.trademark) FROM v_item_verticals iv
          JOIN catalog_items ci USING (master_product_id)
          WHERE iv.vertical = v.code AND ci.trademark <> '') AS marcas,
       (SELECT count(DISTINCT ci.category_id) FROM v_item_verticals iv
          JOIN catalog_items ci USING (master_product_id) WHERE iv.vertical = v.code) AS categorias,
       (SELECT count(*) FROM menu_items mi
          JOIN store_verticals x ON x.store_id = mi.store_id AND x.vertical = v.code) AS platos
FROM verticals v;
