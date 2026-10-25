-- Vigencia de las ofertas, en un solo lugar. Cada corrida baja una sucursal por formato de tienda (store_type; una
-- tienda sin formato es su propio formato), y no siempre la misma. Para cada tienda con precios, la vista da la última
-- corrida que bajó su formato: una oferta es vigente si su último precio es de esa corrida. La usan la búsqueda
-- (precio_min y «tiendas» de search_documents) y el precio que muestra Bigotes, para que el tope de precio y el precio
-- mostrado salgan de las mismas sucursales (608121 en Licores: la búsqueda filtraba por 77.940 y Bigotes mostraba
-- 39.950 de una sucursal que solo salió en la corrida 1).
-- El índice deja en una lectura el último precio de cada tienda (sin él, la vista recorre todos sus precios).
CREATE INDEX price_snapshots_store_latest_idx ON price_snapshots (store_id, scraped_at DESC, run_id DESC);

CREATE VIEW v_store_format_runs AS
WITH last AS (
    SELECT s.store_id, COALESCE(s.store_type, 'id:' || s.store_id) AS format, l.run_id, l.scraped_at
    FROM stores s
    CROSS JOIN LATERAL (SELECT ps.run_id, ps.scraped_at FROM price_snapshots ps WHERE ps.store_id = s.store_id
                        ORDER BY ps.scraped_at DESC, ps.run_id DESC LIMIT 1) l
)
SELECT store_id, format,
       first_value(run_id) OVER (PARTITION BY format ORDER BY scraped_at DESC, run_id DESC) AS format_run_id
FROM last;
