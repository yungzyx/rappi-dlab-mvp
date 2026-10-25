-- Elección de vertical de Bigotes (rappi-ia/src/rappi_ia/agent/verticals.py), 03-10-2026.

-- Lo que se pide hecho (comida preparada, postres, café…) puede buscarse en restaurantes; el resto no, aunque sus
-- locales lo tengan en los combos. Antes era una lista fija en el agente; ahora viene de la taxonomía (`prepared`).
ALTER TABLE concepts ADD COLUMN prepared boolean NOT NULL DEFAULT false;

-- «También en»: tiendas con más productos de cada concepto, por vertical. Se calculaba en cada respuesta uniendo
-- item_concepts con store_products y menu_items (0,4 s en caliente, ~2,5 s en frío); se materializa y se refresca
-- junto con concept_assortment al final de `rappi-ia concepts`. `items` cuenta pares (producto, sucursal).
CREATE MATERIALIZED VIEW concept_store_assortment AS
WITH items AS (
    SELECT ic.concept_id, sp.store_id
    FROM item_concepts ic
    JOIN store_products sp ON ic.entity_type = 'catalog_item' AND sp.master_product_id::text = ic.entity_id
    UNION ALL
    SELECT ic.concept_id, mi.store_id
    FROM item_concepts ic
    JOIN menu_items mi ON ic.entity_type = 'menu_item' AND mi.item_id::text = ic.entity_id
)
SELECT i.concept_id, sv.vertical, trim(s.name) AS store_name, max(nullif(s.raw ->> 'image', '')) AS logo,
       count(*)::integer AS items
FROM items i
JOIN stores s USING (store_id)
JOIN store_verticals sv USING (store_id)
WHERE trim(s.name) <> ''
GROUP BY 1, 2, 3;
CREATE UNIQUE INDEX concept_store_assortment_pk ON concept_store_assortment (concept_id, vertical, store_name);
