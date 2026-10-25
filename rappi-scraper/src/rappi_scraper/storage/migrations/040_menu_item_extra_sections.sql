-- Un plato puede estar en más de una sección del menú: Rappi lo repite, con el mismo id, en «Más vendidos» y en la
-- suya. menu_items guardaba una sola (section_id, la última aparición), así que «Más vendidos» quedaba vacía: 24 de las
-- 66 secciones que se llaman como lo más pedido en `rappi` (21-10). section_id no cambia; las otras secciones del plato
-- van en extra_section_ids, y quien lea los platos de una sección junta las dos. Sin llenado: los platos ya guardados
-- no dicen en qué otras secciones estaban, lo sabrá la próxima descarga de restaurantes.
ALTER TABLE menu_items ADD COLUMN extra_section_ids bigint[] NOT NULL DEFAULT '{}';
COMMENT ON COLUMN menu_items.extra_section_ids IS 'Las otras secciones del menú (menu_sections.section_id) donde también está el plato, p. ej. «Más vendidos». section_id es la última; un plato en una sola sección tiene ''{}''. Cada descarga la reemplaza.';
