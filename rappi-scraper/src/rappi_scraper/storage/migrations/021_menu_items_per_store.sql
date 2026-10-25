-- Rappi repite el id de un plato entre restaurantes distintos. Con item_id como clave global, el último restaurante
-- descargado se quedaba con el plato (y su precio) y el otro lo perdía: 11 locales sin platos y 1.717 precios pisados
-- (30-09). Ahora el plato es único por (store_id, rappi_item_id). item_id sigue siendo la clave del plato (vistas,
-- búsqueda, conceptos y pedidos no cambian): es el id de Rappi para el primer restaurante que lo tiene y un número
-- negativo para los siguientes (Rappi usa ids positivos, así que no chocan).
ALTER TABLE menu_items ADD COLUMN rappi_item_id bigint;
UPDATE menu_items SET rappi_item_id = item_id;
ALTER TABLE menu_items ALTER COLUMN rappi_item_id SET NOT NULL;
ALTER TABLE menu_items ADD CONSTRAINT menu_items_store_rappi_item_key UNIQUE (store_id, rappi_item_id);
CREATE SEQUENCE menu_items_shared_id_seq;
