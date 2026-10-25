-- Consultas útiles sobre la base `rappi` (PostgreSQL local; ver docs/sql/README.md).
--
-- Cómo usarlo: ábrelo en TablePlus, Beekeeper Studio o VS Code, pon el cursor dentro de una consulta
-- y ejecútala (⌘ + Enter). Cada una responde una pregunta del negocio y enseña una idea de SQL.
-- Todas son de solo lectura, se probaron contra la base y tardan menos de 3 s.
-- Usuarios, eventos y pedidos (tablas app_*) son SIMULADOS: sirven para aprender, no son evidencia.
--
-- Recomendado al conectarte (sesión de solo lectura):
SET default_transaction_read_only = on;

-- ====================================================================================================
-- 1. CATÁLOGO Y PRECIOS
-- ====================================================================================================

-- 1.1 Panorama por vertical
-- Idea de SQL: LEFT JOIN + GROUP BY + COUNT(DISTINCT). Nota: hasta la migración 017 la vista v_vertical_summary tardaba más de 20 s (se cortaba por el timeout), así que el resumen se arma desde las tablas.
-- Tiempo medido: ~464 ms
-- ¿Qué tan grande es cada vertical? Tiendas, productos, marcas y categorías.
-- Nota: la vista v_vertical_summary trae un resumen parecido; tardaba más de 20 s y con la migración 017 unos 6 s
-- (una vista es una consulta guardada: se recalcula completa cada vez).
-- Por eso aquí lo armamos directo desde las tablas.
SELECT sv.vertical,
       COUNT(DISTINCT sv.store_id)              AS tiendas,
       COUNT(DISTINCT sp.store_id)              AS tiendas_con_catalogo,
       COUNT(DISTINCT sp.master_product_id)     AS productos_unicos,
       COUNT(DISTINCT NULLIF(ci.trademark, '')) AS marcas,
       COUNT(DISTINCT ci.category_id)           AS categorias
FROM store_verticals AS sv
LEFT JOIN store_products AS sp ON sp.store_id = sv.store_id
LEFT JOIN catalog_items AS ci ON ci.master_product_id = sp.master_product_id
GROUP BY sv.vertical
ORDER BY productos_unicos DESC;

-- 1.2 Buscar productos sin tildes
-- Idea de SQL: WHERE + ILIKE + es_unaccent() + LEFT JOIN
-- Tiempo medido: ~69 ms
-- Buscar productos por nombre sin importar tildes ni mayúsculas.
-- es_unaccent() quita las tildes e ILIKE ignora mayúsculas:
-- 'CAFE MOLIDO' encuentra 'Café Molido' (16 resultados vs 3 con ILIKE solo).
SELECT ci.name          AS producto,
       ci.trademark     AS marca,
       c.name           AS categoria,
       ci.presentation  AS formato
FROM catalog_items AS ci
LEFT JOIN categories AS c ON c.category_id = ci.category_id
WHERE es_unaccent(ci.name) ILIKE es_unaccent('%CAFE MOLIDO%')
ORDER BY ci.name
LIMIT 10;

-- 1.3 Precio de la Coca-Cola 1.5 L por tienda
-- Idea de SQL: Usar una vista (v_price_compare) + WHERE + ORDER BY + promedio con AVG() OVER ()
-- Tiempo medido: ~113 ms
-- ¿Dónde está más barata la Coca-Cola Original 1.5 L hoy?
-- Paso previo: buscar su id por nombre (hay varias versiones; nos quedamos con la más vendida):
--   SELECT ci.master_product_id, ci.name, COUNT(*) AS tiendas
--   FROM catalog_items AS ci
--   JOIN store_products AS sp ON sp.master_product_id = ci.master_product_id
--   WHERE es_unaccent(ci.name) ILIKE '%coca%cola%original%1.5%'
--   GROUP BY ci.master_product_id, ci.name
--   ORDER BY tiendas DESC
--   LIMIT 3;
--   -> 216464, vendida en 101 tiendas.
-- v_price_compare ya junta producto + tienda + cadena + último precio.
-- AVG(...) OVER () calcula el promedio de TODAS las tiendas sin agruparlas.
SELECT COALESCE(pc.cadena, pc.tienda)           AS cadena,
       pc.city                                  AS ciudad,
       pc.price                                 AS precio,
       pc.discount_pct                          AS descuento_pct,
       pc.price - ROUND(AVG(pc.price) OVER ())  AS vs_promedio
FROM v_price_compare AS pc
WHERE pc.master_product_id = 216464
  AND pc.in_stock
ORDER BY pc.price
LIMIT 10;

-- 1.4 Mayores descuentos en supermercado
-- Idea de SQL: Vista de último precio (v_latest_prices) + varios JOIN + WHERE + GROUP BY para no repetir sucursales
-- Tiempo medido: ~375 ms
-- ¿Qué productos de supermercado tienen hoy los descuentos más grandes?
-- v_latest_prices = el último precio de cada producto en cada tienda.
-- Agrupamos para que un mismo producto en muchas sucursales salga una sola vez.
SELECT ci.name                      AS producto,
       INITCAP(s.name)              AS tienda,
       lp.real_price                AS precio_normal,
       lp.price                     AS precio_oferta,
       lp.discount_pct              AS descuento_pct,
       COUNT(DISTINCT lp.store_id)  AS sucursales
FROM v_latest_prices AS lp
JOIN store_verticals AS sv ON sv.store_id = lp.store_id
JOIN stores AS s ON s.store_id = lp.store_id
JOIN store_products AS sp ON sp.store_id = lp.store_id AND sp.sku = lp.sku
JOIN catalog_items AS ci ON ci.master_product_id = sp.master_product_id
WHERE sv.vertical = 'supermercado'
  AND lp.in_stock
  AND lp.discount_pct > 0
GROUP BY ci.name, INITCAP(s.name), lp.real_price, lp.price, lp.discount_pct
ORDER BY descuento_pct DESC, sucursales DESC
LIMIT 10;

-- 1.5 Precios por categoría en supermercado
-- Idea de SQL: WITH (CTE) + GROUP BY + AVG/MIN/MAX + HAVING
-- Tiempo medido: ~594 ms
-- ¿Cuánto cuesta en promedio un producto de cada categoría del supermercado?
-- Solo categorías con al menos 20 productos (HAVING filtra grupos, WHERE filtra filas).
-- Ojo: un mismo producto se vende en muchas tiendas. Si promediamos todas las filas,
-- los productos que están en 300 tiendas pesan 300 veces más.
-- Por eso vamos en dos pasos: 1) un precio por producto, 2) estadísticas por categoría.
WITH precio_producto AS (
  -- paso 1: precio promedio de cada producto entre las tiendas que lo venden
  SELECT ci.category_id,
         ci.master_product_id,
         AVG(lp.price)  AS precio
  FROM v_latest_prices AS lp
  JOIN store_verticals AS sv ON sv.store_id = lp.store_id
  JOIN store_products AS sp ON sp.store_id = lp.store_id AND sp.sku = lp.sku
  JOIN catalog_items AS ci ON ci.master_product_id = sp.master_product_id
  WHERE sv.vertical = 'supermercado'
    AND lp.in_stock
    AND lp.price > 0
  GROUP BY ci.category_id, ci.master_product_id
),
por_categoria AS (
  -- paso 2: cada producto cuenta una sola vez
  SELECT pp.category_id,
         COUNT(*)               AS productos,
         ROUND(AVG(pp.precio))  AS precio_promedio,
         ROUND(MIN(pp.precio))  AS precio_min,
         ROUND(MAX(pp.precio))  AS precio_max
  FROM precio_producto AS pp
  GROUP BY pp.category_id
  HAVING COUNT(*) >= 20
)
SELECT c.name  AS categoria,
       p.productos,
       p.precio_promedio,
       p.precio_min,
       p.precio_max
FROM por_categoria AS p
JOIN categories AS c ON c.category_id = p.category_id
ORDER BY p.productos DESC
LIMIT 10;

-- 1.6 Canasta básica más barata por cadena
-- Idea de SQL: Varios WITH (CTE) + VALUES + GROUP BY + HAVING COUNT(*) = total + SUM() OVER () para la diferencia contra la más barata
-- Tiempo medido: ~120 ms
-- ¿Qué cadena tiene la canasta básica más barata?
-- Canasta de 5 productos comunes (ids encontrados por nombre, como en la consulta 2).
-- Comparación justa: solo entran las cadenas que venden LOS 5 productos con stock.
-- La cadena es el nombre de la tienda: la tabla brands separa formatos
-- (Turbo Fresco, Turbo Express, Lider Big...) y muchas tiendas no tienen brand.
-- INITCAP hace que 'UNIMARC' y 'Unimarc' cuenten como la misma cadena.
WITH canasta (master_product_id, producto) AS (
  VALUES (196743, 'Leche entera Colun 1 L'),
         (131404, 'Nescafé Tradición 50 g'),
         (68699,  'Spaghetti 5 Carozzi 400 g'),
         (545947, 'Arroz Banquete grado 1, 1 kg'),
         (44749,  'Aceite Belmont canola 1 L')
),
precio_por_comercio AS (
  -- precio más bajo de cada producto en cada cadena
  SELECT INITCAP(pc.tienda)  AS comercio,
         pc.master_product_id,
         MIN(pc.price)       AS precio
  FROM v_price_compare AS pc
  JOIN canasta AS k ON k.master_product_id = pc.master_product_id
  WHERE pc.in_stock
  GROUP BY comercio, pc.master_product_id
)
SELECT p.comercio,
       SUM(p.precio)                               AS total_canasta,
       SUM(p.precio) - MIN(SUM(p.precio)) OVER ()  AS vs_mas_barato
FROM precio_por_comercio AS p
GROUP BY p.comercio
HAVING COUNT(*) = (SELECT COUNT(*) FROM canasta)
ORDER BY total_canasta
LIMIT 10;

-- ====================================================================================================
-- 2. RESTAURANTES Y PLATOS
-- ====================================================================================================

-- 2.1 Restaurantes y platos por cocina
-- Idea de SQL: LEFT JOIN + GROUP BY + COUNT(DISTINCT)
-- Tiempo medido: ~450 ms
-- ¿Cuántos restaurantes y cuántos platos hay por tipo de cocina?
-- Ojo: un restaurante puede tener varias cocinas, así que se cuenta en cada una.
SELECT rc.cuisine                   AS cocina,
       COUNT(DISTINCT rc.store_id)  AS restaurantes,
       COUNT(mi.item_id)            AS platos,
       ROUND(COUNT(mi.item_id)::numeric / COUNT(DISTINCT rc.store_id)) AS platos_por_local
FROM restaurant_cuisines AS rc
LEFT JOIN menu_items AS mi
       ON mi.store_id = rc.store_id
GROUP BY rc.cuisine
ORDER BY restaurantes DESC
LIMIT 10;

-- 2.2 Mejor evaluados (mín. 50 reseñas)
-- Idea de SQL: JOIN + WHERE con umbral + ORDER BY de dos columnas + manejo de NULL
-- Tiempo medido: ~1 ms
-- ¿Cuáles son los restaurantes mejor evaluados que tienen al menos 50 reseñas?
-- Sin un mínimo de reseñas, un local con pocas notas altas saldría primero.
-- Solo 269 de los 3.095 restaurantes traen nota (el resto viene en NULL).
SELECT s.name           AS restaurante,
       s.city           AS comuna,
       d.rating         AS nota,
       d.review_count   AS resenas,
       d.delivery_cost  AS costo_envio
FROM restaurant_details AS d
JOIN stores AS s
  ON s.store_id = d.store_id
WHERE d.review_count >= 50
  AND d.rating IS NOT NULL
ORDER BY d.rating DESC,
         d.review_count DESC
LIMIT 10;

-- 2.3 Precio típico de un plato por cocina
-- Idea de SQL: CTE (WITH) + DISTINCT ON para tomar el último snapshot + AVG vs mediana (PERCENTILE_CONT)
-- Tiempo medido: ~279 ms
-- ¿Cuál es el precio promedio (y mediano) de un plato según el tipo de cocina?
-- Patrón "último snapshot": un plato puede tener varias fotos de precio
-- (una por corrida del scraper). DISTINCT ON (item_id) + ORDER BY scraped_at DESC
-- deja solo la fila más reciente de cada plato.
-- La mediana no se distorsiona con platos extremos (hay algunos de $800.000).
WITH ultimo_precio AS (
  SELECT DISTINCT ON (p.item_id)
         p.item_id,
         p.price
  FROM menu_price_snapshots AS p
  ORDER BY p.item_id,
           p.scraped_at DESC
)
SELECT rc.cuisine                AS cocina,
       COUNT(*)                  AS platos,
       ROUND(AVG(up.price))      AS precio_promedio,
       ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY up.price)::numeric) AS precio_mediano
FROM ultimo_precio AS up
JOIN menu_items AS mi
  ON mi.item_id = up.item_id
JOIN restaurant_cuisines AS rc
  ON rc.store_id = mi.store_id
WHERE up.price > 0            -- descarta extras gratis (precio 0)
GROUP BY rc.cuisine
ORDER BY precio_mediano DESC
LIMIT 10;

-- 2.4 Platos populares de sushi
-- Idea de SQL: JOIN de varias tablas (llave compuesta) + OR con ILIKE ANY + reutilizar el CTE de último precio
-- Tiempo medido: ~92 ms; con extra_section_ids, ~1,4 veces eso (21-10, con la columna simulada)
-- ¿Cuáles son los platos populares de los restaurantes de sushi y cuánto cuestan?
-- is_popular casi no viene marcado en los datos (solo 3 platos en total),
-- así que también contamos como "popular" un plato que el restaurante puso
-- en una sección tipo "Más vendidos", "Destacados", "Favoritos", etc.
-- Un plato puede estar en varias secciones (en "Más vendidos" y en la suya):
-- section_id es la última y las demás van en extra_section_ids (migración 040).
WITH ultimo_precio AS (
  SELECT DISTINCT ON (p.item_id)
         p.item_id,
         p.price
  FROM menu_price_snapshots AS p
  ORDER BY p.item_id,
           p.scraped_at DESC
)
SELECT s.name     AS restaurante,
       ms.name    AS seccion,
       mi.name    AS plato,
       up.price   AS precio
FROM menu_items AS mi
JOIN menu_sections AS ms
  ON ms.store_id = mi.store_id
 AND (ms.section_id = mi.section_id
      OR ms.section_id = ANY (mi.extra_section_ids))
JOIN restaurant_cuisines AS rc
  ON rc.store_id = mi.store_id
JOIN stores AS s
  ON s.store_id = mi.store_id
JOIN ultimo_precio AS up
  ON up.item_id = mi.item_id
WHERE rc.cuisine = 'Sushi'
  AND (mi.is_popular
       OR ms.name ILIKE ANY (ARRAY['%vendid%', '%popular%', '%pedid%',
                                   '%destacad%', '%favorito%', '%recomend%']))
  AND up.price > 0
ORDER BY up.price
LIMIT 10;

-- 2.5 Buscar un plato sin importar tildes
-- Idea de SQL: Búsqueda de texto con ILIKE + es_unaccent() + concatenación ||
-- Tiempo medido: ~82 ms
-- ¿Dónde venden "ají de gallina" y cuál es el más barato?
-- es_unaccent() quita tildes a ambos lados: así "aji", "ají" y "AJÍ" coinciden.
-- Con un ILIKE normal "aji de gallina" encuentra 68 platos; ignorando tildes, 236.
-- Cambia el texto entre comillas para buscar otro plato (ej. 'lomo saltado').
WITH ultimo_precio AS (
  SELECT DISTINCT ON (p.item_id)
         p.item_id,
         p.price
  FROM menu_price_snapshots AS p
  ORDER BY p.item_id,
           p.scraped_at DESC
)
SELECT s.name     AS restaurante,
       s.city     AS comuna,
       mi.name    AS plato,
       up.price   AS precio
FROM menu_items AS mi
JOIN stores AS s
  ON s.store_id = mi.store_id
JOIN ultimo_precio AS up
  ON up.item_id = mi.item_id
WHERE es_unaccent(mi.name) ILIKE '%' || es_unaccent('aji de gallina') || '%'
  AND up.price > 0
ORDER BY up.price
LIMIT 10;

-- 2.6 Restaurantes más especializados en pizza
-- Idea de SQL: LEFT JOIN con filtro en el ON + conversión de tipo ::text + porcentaje con COUNT
-- Tiempo medido: ~20 ms
-- ¿Qué restaurantes tienen más platos de pizza en su carta (y qué % de la carta es pizza)?
-- item_concepts guarda la etiqueta de cada plato. Su entity_id es texto,
-- por eso convertimos item_id (número) a texto con ::text para unirlos.
-- El filtro del concepto va en el ON del LEFT JOIN (no en el WHERE):
-- así se conservan todos los platos de la carta y podemos calcular el %.
-- Para otro concepto, cambia 'pizza' (ver la lista en la tabla concepts).
SELECT s.name                                         AS restaurante,
       COUNT(ic.entity_id)                            AS platos_pizza,
       COUNT(*)                                       AS platos_carta,
       ROUND(100.0 * COUNT(ic.entity_id) / COUNT(*))  AS pct_pizza
FROM menu_items AS mi
JOIN stores AS s
  ON s.store_id = mi.store_id
LEFT JOIN item_concepts AS ic
       ON ic.entity_type = 'menu_item'
      AND ic.entity_id   = mi.item_id::text
      AND ic.concept_id  = 'pizza'
GROUP BY s.store_id,
         s.name
ORDER BY platos_pizza DESC
LIMIT 10;

-- ====================================================================================================
-- 3. ENTRE VERTICALES Y CONCEPTOS
-- ====================================================================================================

-- 3.1 Productos que cruzan 3+ verticales
-- Idea de SQL: Usar una VISTA + LEFT JOIN con conversión de tipo (::text) + WHERE + ORDER BY + LIMIT
-- Tiempo medido: ~2.9 s
-- ¿Qué productos se venden en 3 o más verticales y a qué concepto pertenecen?
SELECT x.name AS producto,
       x.trademark AS marca,
       x.n_verticales,
       array_to_string(x.verticales, ', ') AS verticales,
       c.name AS concepto
FROM v_cross_vertical_items AS x
LEFT JOIN item_concepts AS ic
  ON ic.entity_type = 'catalog_item'
 AND ic.entity_id = x.master_product_id::text  -- entity_id es texto: convertimos el número a texto
LEFT JOIN concepts AS c
  ON c.concept_id = ic.concept_id
WHERE x.n_verticales >= 3
ORDER BY x.n_verticales DESC, x.name
LIMIT 15;

-- 3.2 Surtido de cerveza por vertical
-- Idea de SQL: Vista materializada (resultado precalculado) + WHERE + porcentaje con SUM() OVER ()
-- Tiempo medido: ~5 ms
-- ¿En qué verticales hay cerveza y cómo se reparte su surtido entre ellas?
-- (en 'restaurantes' se cuentan platos del menú; en el resto, productos del catálogo)
-- OJO: un mismo producto puede venderse en varias verticales y se cuenta en cada una,
-- por eso el % es sobre la SUMA de la columna (apariciones), no sobre productos únicos.
SELECT ca.vertical,
       ca.items AS surtido,
       ROUND(100.0 * ca.items / SUM(ca.items) OVER (), 1) AS pct_de_la_suma
FROM concept_assortment AS ca
WHERE ca.concept_id = 'cerveza'
ORDER BY ca.items DESC
LIMIT 10;

-- 3.3 Conceptos menos cubiertos
-- Idea de SQL: Self-JOIN (concepto con su grupo padre) + LEFT JOIN + GROUP BY + COUNT(*) FILTER
-- Tiempo medido: ~110 ms
-- ¿Qué conceptos tienen menos productos y platos asociados? (los menos cubiertos)
SELECT concat_ws(' ', g.emoji, g.name) AS grupo,
       concat_ws(' ', c.emoji, c.name) AS concepto,
       COUNT(*) FILTER (WHERE ic.entity_type = 'catalog_item') AS productos,
       COUNT(*) FILTER (WHERE ic.entity_type = 'menu_item') AS platos,
       COUNT(ic.entity_id) AS total
FROM concepts AS c
JOIN concepts AS g
  ON g.concept_id = c.parent_id            -- el "padre" es el grupo
LEFT JOIN item_concepts AS ic
  ON ic.concept_id = c.concept_id          -- LEFT: conserva conceptos sin ítems
GROUP BY g.concept_id, c.concept_id        -- agrupar por la clave permite mostrar sus otras columnas
ORDER BY total ASC, concepto
LIMIT 15;

-- 3.4 Qué sugerir junto a la cerveza
-- Idea de SQL: JOIN a la misma tabla dos veces con alias distintos (origen y destino)
-- Tiempo medido: ~2 ms
-- Si alguien compra cerveza, ¿qué le sugerimos? (complementos curados a mano)
SELECT concat_ws(' ', o.emoji, o.name) AS si_compra,
       concat_ws(' ', d.emoji, d.name) AS sugerir,
       e.weight AS fuerza
FROM concept_edges AS e
JOIN concepts AS o
  ON o.concept_id = e.from_concept        -- misma tabla dos veces: "o" = origen
JOIN concepts AS d
  ON d.concept_id = e.to_concept          -- "d" = destino
WHERE e.method = 'curado'
  AND e.from_concept = 'cerveza'
ORDER BY e.weight DESC
LIMIT 10;

-- 3.5 Demanda SIMULADA vs oferta real
-- Idea de SQL: CTE (WITH) + LEFT JOIN + COALESCE + CASE para diagnosticar
-- Tiempo medido: ~100 ms
-- ATENCIÓN: la demanda es SIMULADA (app_events con source = 'synthetic', usuarios ficticios).
-- ¿Qué buscan los usuarios simulados sin encontrar resultados, y cuánta oferta REAL existe en esa vertical?
WITH demanda AS (
  SELECT e.vertical,
         e.concept_id,
         COUNT(*) AS busquedas_fallidas,
         MIN(e.query) AS ejemplo
  FROM app_events AS e
  WHERE e.source = 'synthetic'
    AND e.type = 'search'
    AND e.unmet
  GROUP BY e.vertical, e.concept_id
)
SELECT d.vertical,
       COALESCE(c.name, '(sin concepto)') AS concepto,
       d.ejemplo,
       d.busquedas_fallidas AS busquedas_fallidas_simuladas,
       CASE
         WHEN c.concept_id IS NULL THEN NULL   -- sin concepto no podemos medir la oferta: NULL = "no se sabe"
         ELSE COALESCE(ca.items, 0)            -- con concepto pero sin fila en la vista = 0 de verdad
       END AS oferta_real,
       CASE
         WHEN c.concept_id IS NULL THEN 'Falta en la taxonomía'
         WHEN COALESCE(ca.items, 0) = 0 THEN 'Sin surtido'
         WHEN ca.items < 50 THEN 'Surtido escaso'
         ELSE 'Hay surtido: revisar buscador'
       END AS diagnostico
FROM demanda AS d
LEFT JOIN concepts AS c
  ON c.concept_id = d.concept_id
LEFT JOIN concept_assortment AS ca
  ON ca.concept_id = d.concept_id
 AND ca.vertical = d.vertical
ORDER BY oferta_real ASC NULLS FIRST, d.busquedas_fallidas DESC
LIMIT 10;

-- 3.6 Auditoría categoría → concepto
-- Idea de SQL: CTE de conteo + LEFT JOIN por clave de texto (lower) + ORDER BY por dos criterios
-- Tiempo medido: ~63 ms
-- ¿Qué categorías de Rappi se asignaron a un concepto con MENOS confianza, y cuántos productos afectan?
WITH productos_por_categoria AS (
  SELECT lower(cat.name) AS source_key,       -- category_map guarda el nombre en minúsculas
         COUNT(*) AS productos
  FROM catalog_items AS ci
  JOIN categories AS cat
    ON cat.category_id = ci.category_id
  GROUP BY lower(cat.name)
)
SELECT cm.source_name AS categoria,
       concat_ws(' ', c.emoji, c.name) AS concepto_asignado,
       cm.method AS metodo,
       cm.confidence AS confianza,
       COALESCE(p.productos, 0) AS productos_afectados,
       cm.note AS nota
FROM category_map AS cm
JOIN concepts AS c
  ON c.concept_id = cm.concept_id
LEFT JOIN productos_por_categoria AS p
  ON p.source_key = cm.source_key
WHERE cm.source_kind = 'categoria'
ORDER BY cm.confidence ASC, productos_afectados DESC
LIMIT 10;

-- ====================================================================================================
-- 4. TÉCNICAS PARA USAR SQL BIEN
-- ====================================================================================================

-- 4.1 Buscar productos por texto (full-text) en una vertical
-- Idea de SQL: Búsqueda de texto completo: tsvector @@ websearch_to_tsquery + ts_rank
-- Tiempo medido: ~1 ms
-- Búsqueda de texto completo: "café en grano", sin instantáneo, solo en supermercado
SELECT sd.entity_id                                   AS master_product_id,
       split_part(sd.content, '. ', 1)                AS producto,
       ROUND(ts_rank(sd.tsv_unaccent, q)::numeric, 3) AS relevancia
FROM search_documents AS sd,
     websearch_to_tsquery('spanish', es_unaccent('cafe en grano -instantaneo')) AS q
WHERE sd.vertical = 'supermercado'        -- filtra por partición: solo lee supermercado
  AND sd.entity_type = 'catalog_item'
  AND sd.tsv_unaccent @@ q                -- @@ = "calza con la búsqueda" (usa el índice GIN)
ORDER BY relevancia DESC, producto
LIMIT 10;

-- 4.2 Leer campos JSON (jsonb) de metadata
-- Idea de SQL: jsonb: operadores -> y ->> + conversión de tipos (cast)
-- Tiempo medido: ~16 ms
-- Leer campos del jsonb "metadata": ->> devuelve texto, luego se convierte (cast) a número
SELECT split_part(sd.content, '. ', 1)              AS producto,
       (sd.metadata ->> 'tiendas')::int             AS tiendas,
       jsonb_array_length(sd.metadata -> 'cadenas') AS cadenas,
       (sd.metadata ->> 'precio_min')::numeric      AS precio_min,
       (sd.metadata ->> 'precio_max')::numeric      AS precio_max,
       (sd.metadata ->> 'precio_max')::numeric
     - (sd.metadata ->> 'precio_min')::numeric      AS brecha
FROM search_documents AS sd
WHERE sd.vertical = 'supermercado'
  AND sd.entity_type = 'catalog_item'
ORDER BY tiendas DESC, brecha DESC
LIMIT 10;

-- 4.3 Resolver paso a paso con WITH (CTE)
-- Idea de SQL: CTE (WITH) encadenadas + percentile_cont + auto-JOIN por producto
-- Tiempo medido: ~376 ms
-- ¿Cuánto más caro es el MISMO producto fuera del supermercado tradicional?
WITH ultimos AS (   -- Paso 1: último precio de cada producto en cada tienda, con su vertical
  SELECT sp.master_product_id,
         sv.vertical,
         sv.subvertical,
         lp.price
  FROM v_latest_prices AS lp
  JOIN store_products AS sp USING (store_id, sku)
  JOIN store_verticals AS sv USING (store_id)
  WHERE lp.price > 0
),
base AS (           -- Paso 2: precio más bajo en supermercados tradicionales (subvertical 'Super')
  SELECT master_product_id,
         MIN(price) AS precio_super
  FROM ultimos
  WHERE vertical = 'supermercado'
    AND subvertical = 'Super'
  GROUP BY master_product_id
),
otras AS (          -- Paso 3: precio más bajo del producto en cada una de las otras verticales
  SELECT master_product_id,
         vertical,
         MIN(price) AS precio
  FROM ultimos
  WHERE vertical <> 'supermercado'
  GROUP BY master_product_id, vertical
)
SELECT o.vertical,  -- Paso 4: comparar producto a producto y resumir por vertical
       COUNT(*) AS productos_comunes,
       ROUND((100 * percentile_cont(0.5) WITHIN GROUP (ORDER BY o.precio / b.precio_super))::numeric - 100, 1) AS sobreprecio_mediano_pct,
       ROUND(100.0 * AVG((o.precio > b.precio_super)::int), 1) AS pct_productos_mas_caros
FROM otras AS o
JOIN base AS b USING (master_product_id)
GROUP BY o.vertical
HAVING COUNT(*) >= 30
ORDER BY sobreprecio_mediano_pct DESC
LIMIT 10;

-- 4.4 Top 3 por categoría con funciones de ventana
-- Idea de SQL: Función de ventana: RANK() OVER (PARTITION BY ... ORDER BY ...)
-- Tiempo medido: ~136 ms
-- Top 3 productos más caros por categoría (precio "desde" = el más bajo entre tiendas)
WITH precio_producto AS (
  SELECT c.name        AS categoria,
         ci.name       AS producto,
         MIN(lp.price) AS precio_desde
  FROM catalog_items AS ci
  JOIN categories AS c USING (category_id)
  JOIN store_products AS sp USING (master_product_id)
  JOIN v_latest_prices AS lp USING (store_id, sku)
  WHERE c.name IN ('Café', 'Vino tinto', 'Chocolates')
    AND lp.price > 0
  GROUP BY c.name, ci.master_product_id, ci.name
)
SELECT r.categoria,
       r.producto,
       r.precio_desde,
       r.puesto
FROM (
  SELECT pp.categoria,
         pp.producto,
         pp.precio_desde,
         RANK() OVER (PARTITION BY pp.categoria ORDER BY pp.precio_desde DESC) AS puesto
  FROM precio_producto AS pp
) AS r
WHERE r.puesto <= 3          -- se filtra afuera: WHERE no puede usar funciones de ventana
ORDER BY r.categoria, r.puesto, r.producto
LIMIT 15;

-- 4.5 Medir y acelerar con EXPLAIN (ANALYZE, BUFFERS)
-- Idea de SQL: EXPLAIN (ANALYZE, BUFFERS) + reescritura con JOIN LATERAL que aprovecha un índice
-- Tiempo medido: ~4 ms
-- VERSIÓN LENTA (Execution Time ~100 ms, Buffers: shared hit=146842)
-- La vista calcula el último precio de TODOS los productos y recién después filtra
EXPLAIN (ANALYZE, BUFFERS)
SELECT v.tienda,
       v.cadena,
       v.city,
       v.price
FROM v_price_compare AS v
WHERE v.master_product_id = 89200   -- Soprole Leche Natural Entera
ORDER BY v.price, v.store_id
LIMIT 5;

-- VERSIÓN RÁPIDA (Execution Time ~2,2 ms, Buffers: shared hit=840)
-- Para cada tienda del producto, trae solo su último precio usando el índice (store_id, sku, scraped_at DESC)
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.name  AS tienda,
       b.name  AS cadena,
       s.city,
       ult.price
FROM store_products AS sp
JOIN stores AS s USING (store_id)
LEFT JOIN brands AS b ON b.brand_id = s.brand_id
CROSS JOIN LATERAL (
  SELECT ps.price
  FROM price_snapshots AS ps
  WHERE ps.store_id = sp.store_id
    AND ps.sku = sp.sku
  ORDER BY ps.scraped_at DESC
  LIMIT 1
) AS ult
WHERE sp.master_product_id = 89200   -- Soprole Leche Natural Entera
ORDER BY ult.price, sp.store_id
LIMIT 5;

-- 4.6 Exportar resultados a CSV con \copy
-- Idea de SQL: Exportar con \copy (...) TO 'archivo.csv' WITH (FORMAT csv, HEADER)
-- Tiempo medido: ~82 ms
-- En psql, en UNA sola línea. El archivo queda en tu Escritorio (~ = tu carpeta personal):
\copy (SELECT v.producto, v.cadena, v.tienda, v.city, v.price FROM v_price_compare AS v WHERE v.master_product_id = 89200 ORDER BY v.price, v.store_id LIMIT 500) TO '~/Desktop/soprole_precios.csv' WITH (FORMAT csv, HEADER)
-- psql responde: COPY 87

-- Alternativa para consultas largas en varias líneas:
-- \pset format csv
-- SELECT ...
-- FROM ...
-- LIMIT 500
-- \g ~/Desktop/soprole_precios.csv
