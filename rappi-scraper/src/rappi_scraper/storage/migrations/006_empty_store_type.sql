-- Un store_type vacío no es un formato: esas tiendas no deben compartir verticales entre sí.
UPDATE stores SET store_type = NULL WHERE store_type = '';
UPDATE stores SET sub_group = NULL WHERE sub_group = '';

CREATE OR REPLACE VIEW v_store_verticals AS
SELECT sv.store_id, sv.vertical, sv.subvertical
FROM store_verticals sv
UNION
SELECT s.store_id, sv.vertical, sv.subvertical
FROM stores s
JOIN stores other ON other.store_type = s.store_type
JOIN store_verticals sv ON sv.store_id = other.store_id
WHERE s.store_type IS NOT NULL AND s.store_type <> '';
