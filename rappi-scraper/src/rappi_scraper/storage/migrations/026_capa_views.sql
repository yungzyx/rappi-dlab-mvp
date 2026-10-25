-- Capa de perfiles, etapa 5 (docs/superpowers/specs/2026-10-06-capa-perfiles-design.md): contrato estable `capa`.
-- Vistas nuevas (items, segmentos, corridas) y comentario en español en cada vista y columna de `capa`.
-- Las tablas internas pueden cambiar; estas vistas no (docs/capa-de-datos.md).

CREATE VIEW capa.items AS
SELECT s.entity_type, s.entity_id, s.vertical,
       coalesce(ci.name, mi.name) AS name,
       ic.concept_id, c.name AS concept_name, c.parent_id AS concept_group,
       ib.brand_key, pb.name AS brand_name,
       icn.canonical_id,
       CASE WHEN m.suspect IS NULL THEN m.unit END AS unit,
       m.pack,
       CASE WHEN m.suspect IS NULL THEN m.total END AS total,
       s.price_min AS price
FROM search_documents s
LEFT JOIN catalog_items ci ON s.entity_type = 'catalog_item' AND ci.master_product_id::text = s.entity_id
LEFT JOIN menu_items mi ON s.entity_type = 'menu_item' AND mi.item_id::text = s.entity_id
LEFT JOIN item_concepts ic ON ic.entity_type = s.entity_type AND ic.entity_id = s.entity_id
LEFT JOIN concepts c ON c.concept_id = ic.concept_id
LEFT JOIN item_brands ib ON ib.entity_type = s.entity_type AND ib.entity_id = s.entity_id
LEFT JOIN product_brands pb ON pb.brand_key = ib.brand_key
LEFT JOIN item_canonical icn ON s.entity_type = 'catalog_item' AND icn.master_product_id::text = s.entity_id
LEFT JOIN item_measures m ON m.entity_type = s.entity_type AND m.entity_id = s.entity_id
WHERE s.entity_type <> 'store';

CREATE VIEW capa.segment_defs AS
SELECT segment_id, name, family, sensitive, description, rule, rules_version FROM segment_defs;

CREATE VIEW capa.user_segments AS
SELECT s.user_id, u.source, s.segment_id, d.name AS segment_name, d.family, s.score, s.level, s.signals, s.evidence,
       s.first_seen, s.last_signal, s.source AS origin
FROM user_segments s JOIN segment_defs d USING (segment_id) JOIN app_users u USING (user_id)
WHERE NOT d.sensitive;

CREATE VIEW capa.segment_sizes AS
WITH cells AS (
    SELECT u.source, h.week, h.segment_id, h.level, count(*) AS users
    FROM user_segment_history h JOIN app_users u USING (user_id)
    GROUP BY u.source, h.week, h.segment_id, h.level
),
population AS (SELECT source, count(*) AS n FROM app_users GROUP BY source)
SELECT c.source, c.week, c.segment_id, d.name AS segment_name, d.family, d.sensitive,
       CASE WHEN d.sensitive THEN 'todos' ELSE c.level END AS level,
       sum(c.users)::bigint AS users
FROM cells c JOIN segment_defs d USING (segment_id) JOIN population p USING (source)
GROUP BY c.source, c.week, c.segment_id, d.name, d.family, d.sensitive, CASE WHEN d.sensitive THEN 'todos' ELSE c.level END, p.n
HAVING NOT d.sensitive OR (sum(c.users) >= 5 AND p.n - sum(c.users) >= 5);

CREATE VIEW capa.layer_runs AS
SELECT run_id, layer, rules_version, started_at, finished_at, status, counts FROM layer_runs;

COMMENT ON VIEW capa.items IS 'Un ítem (producto o plato) por vertical, con su concepto, marca, producto canónico, medida y precio vigente: el punto de entrada para buscar o analizar el catálogo.';
COMMENT ON VIEW capa.segment_defs IS 'Definición de cada segmento de usuario por comportamiento (reglas de segments.toml).';
COMMENT ON VIEW capa.user_segments IS 'Segmentos de cada persona con puntaje, nivel y evidencia. No incluye los segmentos sensibles. Ids de persona seudónimos; las filas de la fuente synthetic son simuladas (no son evidencia).';
COMMENT ON VIEW capa.segment_sizes IS 'Cuántas personas hay en cada segmento, semana y fuente. Un segmento sensible aparece una sola vez (nivel «todos») y solo si tiene 5 o más personas y el resto de su fuente también son 5 o más.';
COMMENT ON VIEW capa.layer_runs IS 'Linaje de las capas: cuándo corrió cada una, con qué versión de reglas y cuántas filas produjo.';
COMMENT ON COLUMN capa.items.entity_type IS 'catalog_item (producto) o menu_item (plato).';
COMMENT ON COLUMN capa.items.entity_id IS 'Id del producto (master_product_id) o del plato (item_id), como texto.';
COMMENT ON COLUMN capa.items.vertical IS 'Vertical donde se vende.';
COMMENT ON COLUMN capa.items.name IS 'Nombre del producto o del plato.';
COMMENT ON COLUMN capa.items.concept_id IS 'Concepto de la taxonomía propia (cerveza, pizza…); vacío si no tiene.';
COMMENT ON COLUMN capa.items.concept_name IS 'Nombre del concepto.';
COMMENT ON COLUMN capa.items.concept_group IS 'Grupo del concepto (alcohol, comida, mascotas…).';
COMMENT ON COLUMN capa.items.brand_key IS 'Id de la marca canónica (en los platos, la de la cadena del restaurante); vacío si no se pudo determinar.';
COMMENT ON COLUMN capa.items.brand_name IS 'Nombre de la marca o de la cadena.';
COMMENT ON COLUMN capa.items.canonical_id IS 'Producto canónico (mismo producto entre ids y verticales); solo productos con marca y medida fiable.';
COMMENT ON COLUMN capa.items.unit IS 'Unidad base de la medida: g, ml, und o cm.';
COMMENT ON COLUMN capa.items.pack IS 'Unidades por pack; 1 si no es pack; vacío en los platos sin medida.';
COMMENT ON COLUMN capa.items.total IS 'Tamaño total normalizado en la unidad base; vacío si la medida es dudosa o falta.';
COMMENT ON COLUMN capa.items.price IS 'Precio vigente más bajo en esa vertical (CLP).';
COMMENT ON COLUMN capa.segment_defs.segment_id IS 'Id estable del segmento (compra-sin-gluten, hamburguesero…).';
COMMENT ON COLUMN capa.segment_defs.name IS 'Nombre para mostrar; los sensibles se nombran por conducta, nunca por condición.';
COMMENT ON COLUMN capa.segment_defs.family IS 'Familia: dieta, comida, dulces, bebidas, hogar, cuidado, intereses, momentos, valor, relacion, servicios o geografia.';
COMMENT ON COLUMN capa.segment_defs.sensitive IS 'Segmento sensible: capa.user_segments no trae sus filas por persona y capa.segment_sizes solo muestra su total con 5 o más personas.';
COMMENT ON COLUMN capa.segment_defs.description IS 'Qué hace una persona para estar en el segmento.';
COMMENT ON COLUMN capa.segment_defs.rule IS 'La regla sembrada (señales, pesos, ventana, umbrales) en JSON.';
COMMENT ON COLUMN capa.segment_defs.rules_version IS 'Versión de las reglas con que se sembró.';
COMMENT ON COLUMN capa.user_segments.user_id IS 'Id seudónimo de la persona.';
COMMENT ON COLUMN capa.user_segments.source IS 'synthetic (simulada) o prototype (usuarios del prototipo).';
COMMENT ON COLUMN capa.user_segments.segment_id IS 'Id del segmento.';
COMMENT ON COLUMN capa.user_segments.segment_name IS 'Nombre del segmento.';
COMMENT ON COLUMN capa.user_segments.family IS 'Familia del segmento.';
COMMENT ON COLUMN capa.user_segments.score IS 'Puntaje: suma ponderada de los eventos que calzan, con decaimiento por antigüedad; en los segmentos por métrica (relación y valor), el valor de la métrica.';
COMMENT ON COLUMN capa.user_segments.level IS 'bajo, medio o alto según los umbrales de la regla.';
COMMENT ON COLUMN capa.user_segments.signals IS 'Ocasiones distintas (pedidos o sesiones) que cuentan; 0 en los segmentos por métrica.';
COMMENT ON COLUMN capa.user_segments.evidence IS 'Los 3 conceptos o atributos que más aportan (`top`, sin lo que mira un segmento sensible) y la parte de su actividad que calza (`share`); en los segmentos por métrica, la métrica y su valor.';
COMMENT ON COLUMN capa.user_segments.first_seen IS 'Fecha de la señal más antigua que cuenta.';
COMMENT ON COLUMN capa.user_segments.last_signal IS 'Fecha de la señal más reciente que cuenta.';
COMMENT ON COLUMN capa.user_segments.origin IS 'regla (calculado) o curado (puesto a mano).';
COMMENT ON COLUMN capa.segment_sizes.source IS 'synthetic (simulada) o prototype.';
COMMENT ON COLUMN capa.segment_sizes.week IS 'Lunes de la semana de la foto.';
COMMENT ON COLUMN capa.segment_sizes.segment_id IS 'Id del segmento.';
COMMENT ON COLUMN capa.segment_sizes.segment_name IS 'Nombre del segmento.';
COMMENT ON COLUMN capa.segment_sizes.family IS 'Familia del segmento.';
COMMENT ON COLUMN capa.segment_sizes.sensitive IS 'Si el segmento es sensible.';
COMMENT ON COLUMN capa.segment_sizes.level IS 'bajo, medio o alto; «todos» en los segmentos sensibles, que no se separan por nivel.';
COMMENT ON COLUMN capa.segment_sizes.users IS 'Personas en ese segmento (y nivel) esa semana.';
COMMENT ON COLUMN capa.layer_runs.run_id IS 'Id de la corrida.';
COMMENT ON COLUMN capa.layer_runs.layer IS 'measures, brands, canonical, attributes, relations o segments.';
COMMENT ON COLUMN capa.layer_runs.rules_version IS 'Fecha de las reglas más una huella de su contenido.';
COMMENT ON COLUMN capa.layer_runs.started_at IS 'Inicio de la corrida.';
COMMENT ON COLUMN capa.layer_runs.finished_at IS 'Cuándo terminó la corrida.';
COMMENT ON COLUMN capa.layer_runs.status IS 'done; una corrida que falla se deshace con su transacción y no queda registrada.';
COMMENT ON COLUMN capa.layer_runs.counts IS 'Conteos de lo que produjo (JSON).';

COMMENT ON COLUMN capa.item_attributes.entity_type IS 'catalog_item (producto) o menu_item (plato).';
COMMENT ON COLUMN capa.item_attributes.entity_id IS 'Id del producto (master_product_id) o del plato (item_id), como texto.';
COMMENT ON COLUMN capa.item_attributes.attribute_id IS 'Id estable del atributo (sin-gluten, vegano, familiar…).';
COMMENT ON COLUMN capa.item_attributes.attribute_name IS 'Nombre del atributo para mostrar.';
COMMENT ON COLUMN capa.item_attributes.family IS 'Familia del atributo: dieta, alergenos, publico, formato, precio, origen, sustentable, ocasion o platos.';
COMMENT ON COLUMN capa.item_attributes.value IS 'Valor, solo para atributos de texto; vacío en las banderas.';
COMMENT ON COLUMN capa.item_attributes.source IS 'De dónde sale: rappi (lo declara Rappi), regla (el nombre o la descripción), derivado (precios, marcas, medidas), aprendido o curado.';
COMMENT ON COLUMN capa.item_attributes.confidence IS 'Confianza de 0 a 1 (Rappi 0,95, regla 0,8, derivado 0,9).';
COMMENT ON COLUMN capa.item_attributes.evidence IS 'Qué lo respalda: el campo de Rappi, la frase que calzó o la regla derivada.';
COMMENT ON COLUMN capa.item_unit_prices.vertical IS 'Vertical donde se vende (supermercado, licores, restaurantes…).';
COMMENT ON COLUMN capa.item_unit_prices.entity_type IS 'catalog_item (producto) o menu_item (plato).';
COMMENT ON COLUMN capa.item_unit_prices.entity_id IS 'Id del producto o del plato, como texto.';
COMMENT ON COLUMN capa.item_unit_prices.unit IS 'Unidad base de la medida: g, ml, und o cm.';
COMMENT ON COLUMN capa.item_unit_prices.pack IS 'Unidades por pack (6 en «6 x 350 ml»); 1 si no es pack.';
COMMENT ON COLUMN capa.item_unit_prices.total IS 'Tamaño total normalizado: cantidad × pack, en la unidad base.';
COMMENT ON COLUMN capa.unit_price_ratios.vertical IS 'Vertical donde se vende.';
COMMENT ON COLUMN capa.unit_price_ratios.concept_id IS 'Concepto del ítem.';
COMMENT ON COLUMN capa.unit_price_ratios.entity_type IS 'catalog_item (producto) o menu_item (plato).';
COMMENT ON COLUMN capa.unit_price_ratios.entity_id IS 'Id del producto o del plato, como texto.';
COMMENT ON COLUMN capa.unit_price_ratios.per IS 'Unidad de comparación: kg, l o und.';
COMMENT ON COLUMN capa.unit_price_ratios.unit_price IS 'Precio por kilo, litro o unidad del ítem (CLP).';
COMMENT ON COLUMN capa.unit_price_ratios.median_price IS 'Mediana del precio por unidad de su concepto y vertical (CLP).';
COMMENT ON COLUMN capa.unit_price_ratios.items_in_group IS 'Cuántos ítems comparables tiene ese concepto en esa vertical.';
COMMENT ON COLUMN capa.item_brands.entity_type IS 'catalog_item (producto) o menu_item (plato).';
COMMENT ON COLUMN capa.item_brands.entity_id IS 'Id del producto o del plato, como texto.';
COMMENT ON COLUMN capa.item_brands.brand_key IS 'Id estable de la marca (coca-cola).';
COMMENT ON COLUMN capa.item_brands.brand_name IS 'Escritura más común de la marca.';
COMMENT ON COLUMN capa.item_brands.kind IS 'marca (de producto) o cadena (restaurante).';
COMMENT ON COLUMN capa.item_brands.is_store_brand IS 'Marca propia de una tienda (Líder, Great Value…).';
COMMENT ON COLUMN capa.item_brands.source IS 'rappi (declarada), regla (deducida del nombre), cadena (restaurante) o curado.';
COMMENT ON COLUMN capa.canonical_products.canonical_id IS 'Id del producto canónico (estable entre corridas).';
COMMENT ON COLUMN capa.canonical_products.brand_key IS 'Id de su marca.';
COMMENT ON COLUMN capa.canonical_products.brand_name IS 'Nombre de su marca.';
COMMENT ON COLUMN capa.canonical_products.label IS 'Nombre más común del producto, para mostrar.';
COMMENT ON COLUMN capa.canonical_products.total IS 'Tamaño total en la unidad base.';
COMMENT ON COLUMN capa.canonical_products.unit IS 'Unidad base: g, ml o und.';
COMMENT ON COLUMN capa.canonical_products.items IS 'Cuántos ids de Rappi lo representan.';
COMMENT ON COLUMN capa.canonical_products.verticals IS 'Verticales donde se vende (una tienda con doble etiqueta infla este conteo).';
COMMENT ON COLUMN capa.canonical_products.master_product_ids IS 'Ids de Rappi (master_product_id) que son este producto.';
COMMENT ON COLUMN capa.knowledge_edges.from_kind IS 'Tipo del nodo de origen: concept, group, attribute, segment, brand, vertical, occasion, service, canonical o term.';
COMMENT ON COLUMN capa.knowledge_edges.from_id IS 'Id del nodo de origen.';
COMMENT ON COLUMN capa.knowledge_edges.relation IS 'Id de la relación (complementa, sustituye, tiene_atributo…).';
COMMENT ON COLUMN capa.knowledge_edges.relation_name IS 'Nombre de la relación para mostrar.';
COMMENT ON COLUMN capa.knowledge_edges.to_kind IS 'Tipo del nodo de destino.';
COMMENT ON COLUMN capa.knowledge_edges.to_id IS 'Id del nodo de destino.';
COMMENT ON COLUMN capa.knowledge_edges.weight IS 'Fuerza de la relación, de 0 a 1.';
COMMENT ON COLUMN capa.knowledge_edges.method IS 'curado (a mano), derivado (de reglas y catálogo) o coocurrencia (aprendido de uso).';
COMMENT ON COLUMN capa.knowledge_edges.data_source IS 'curado, catalogo o prototype; lo aprendido de datos simulados no se expone.';
COMMENT ON COLUMN capa.knowledge_edges.support IS 'Ítems, sesiones o personas que respaldan la arista.';
COMMENT ON COLUMN capa.knowledge_edges.evidence IS 'De dónde sale (archivo de reglas o tabla).';
