-- Tiendas Turbo que solo salieron en los filtros de otro listado: el descubrimiento no conocía su store_type y las
-- dejó en el vertical del listado (en la base del 03-10, 900102097 y 900102111 en supermercado, con 1.612 ofertas).
-- Pasan a turbo con sus filtros, como haría canonical_vertical. Bajarlas otra vez ya no las corrige: ahora el
-- descubrimiento usa el store_type guardado y su job ya no nombra el vertical del listado.
UPDATE store_verticals sv SET vertical = 'turbo'
FROM (SELECT DISTINCT ON (x.store_id) x.store_id, x.vertical
      FROM store_verticals x
      JOIN stores s ON s.store_id = x.store_id
      WHERE (s.store_type LIKE 'turbo%' OR s.sub_group = 'Turbo') AND x.vertical <> 'turbo'
        AND NOT EXISTS (SELECT 1 FROM store_verticals t WHERE t.store_id = x.store_id AND t.vertical = 'turbo')
      ORDER BY x.store_id, x.last_seen DESC) m
WHERE sv.store_id = m.store_id AND sv.vertical = m.vertical;

DELETE FROM store_verticals sv
USING stores s
WHERE s.store_id = sv.store_id AND (s.store_type LIKE 'turbo%' OR s.sub_group = 'Turbo') AND sv.vertical <> 'turbo';
