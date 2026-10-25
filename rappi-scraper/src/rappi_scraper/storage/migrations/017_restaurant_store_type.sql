-- 'restaurant' tampoco es un formato: Rappi manda ese storeType para todos los restaurantes. Cruzarlos por
-- store_type armaba un auto-join de 13 millones de filas con 3.604 restaurantes (v_vertical_summary tardaba ~22 s,
-- más que el timeout de 20 s de la API) y le pasaría a todos el vertical de un restaurante que salga en otro listado.
-- En la base del 03-10 la vista devuelve las mismas filas sin ese cruce.
CREATE OR REPLACE VIEW v_store_verticals AS
SELECT sv.store_id, sv.vertical, sv.subvertical
FROM store_verticals sv
UNION
SELECT s.store_id, sv.vertical, sv.subvertical
FROM stores s
JOIN stores other ON other.store_type = s.store_type
JOIN store_verticals sv ON sv.store_id = other.store_id
WHERE s.store_type IS NOT NULL AND s.store_type NOT IN ('', 'restaurant');
