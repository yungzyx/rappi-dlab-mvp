-- Capa de perfiles, etapa 1 (docs/superpowers/specs/2026-10-06-capa-perfiles-design.md): linaje de corridas,
-- atributos de ítem y medidas normalizadas. `capa` es el esquema estable para herramientas externas (vistas).
CREATE SCHEMA IF NOT EXISTS capa;

CREATE TABLE layer_runs (
    run_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    layer         text NOT NULL CHECK (layer IN ('attributes', 'measures', 'brands', 'canonical', 'relations', 'segments')),
    rules_version text NOT NULL,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    status        text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'done', 'failed')),
    counts        jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX layer_runs_layer_idx ON layer_runs (layer, started_at DESC);

CREATE TABLE attribute_defs (
    attribute_id  text PRIMARY KEY,
    name          text NOT NULL,
    family        text NOT NULL,
    applies_to    text NOT NULL CHECK (applies_to IN ('catalog_item', 'menu_item', 'both')),
    value_type    text NOT NULL CHECK (value_type IN ('flag', 'text')),
    description   text NOT NULL DEFAULT '',
    rules_version text NOT NULL
);

CREATE TABLE item_attributes (
    entity_type   text NOT NULL CHECK (entity_type IN ('catalog_item', 'menu_item')),
    entity_id     text NOT NULL,
    attribute_id  text NOT NULL REFERENCES attribute_defs (attribute_id) ON DELETE CASCADE,
    value         text,
    source        text NOT NULL CHECK (source IN ('rappi', 'regla', 'derivado', 'aprendido', 'curado')),
    confidence    real NOT NULL,
    evidence      text,
    rules_version text NOT NULL,
    run_id        bigint REFERENCES layer_runs (run_id) ON DELETE SET NULL,
    PRIMARY KEY (entity_type, entity_id, attribute_id)
);
CREATE INDEX item_attributes_attribute_idx ON item_attributes (attribute_id, entity_type);

CREATE TABLE item_measures (
    entity_type   text NOT NULL CHECK (entity_type IN ('catalog_item', 'menu_item')),
    entity_id     text NOT NULL,
    quantity      double precision,
    unit          text CHECK (unit IN ('g', 'ml', 'und', 'cm')),
    pack          integer NOT NULL DEFAULT 1 CHECK (pack >= 1),
    total         double precision,
    size_label    text,
    suspect       text,  -- por qué la medida de Rappi parece un error (peso de 44 toneladas, «1 mg» de almendras)
    source        text NOT NULL CHECK (source IN ('rappi', 'regla')),
    evidence      text,
    run_id        bigint REFERENCES layer_runs (run_id) ON DELETE SET NULL,
    PRIMARY KEY (entity_type, entity_id)
);

COMMENT ON TABLE layer_runs IS 'Linaje: cada corrida de cada capa derivada (qué reglas, cuántas filas, cuándo).';
COMMENT ON TABLE attribute_defs IS 'Vocabulario de atributos de ítem (sin gluten, vegano, familiar…), sembrado desde attributes.toml.';
COMMENT ON TABLE item_attributes IS 'Atributos de cada producto o plato, con fuente (rappi, regla, derivado), confianza y evidencia.';
COMMENT ON TABLE item_measures IS 'Tamaño normalizado de cada ítem: cantidad por unidad, unidad base (g, ml, und), pack y total. `suspect` marca las medidas que parecen un error de Rappi.';

-- Contrato estable para herramientas externas (esquema `capa`): las tablas internas pueden cambiar, estas vistas no.
CREATE VIEW capa.item_attributes AS
SELECT a.entity_type, a.entity_id, a.attribute_id, d.name AS attribute_name, d.family, a.value, a.source,
       a.confidence, a.evidence
FROM item_attributes a JOIN attribute_defs d USING (attribute_id);

CREATE VIEW capa.item_unit_prices AS
SELECT s.vertical, s.entity_type, s.entity_id, s.price_min AS price, m.unit, m.pack, m.total,
       CASE WHEN m.unit = 'g' THEN s.price_min / m.total * 1000 END AS price_per_kg,
       CASE WHEN m.unit = 'ml' THEN s.price_min / m.total * 1000 END AS price_per_l,
       CASE WHEN m.unit = 'und' THEN s.price_min / m.total END AS price_per_unit
FROM search_documents s
JOIN item_measures m ON m.entity_type = s.entity_type AND m.entity_id = s.entity_id
WHERE s.price_min > 0 AND m.total > 0 AND m.suspect IS NULL;

COMMENT ON VIEW capa.item_attributes IS 'Atributos de cada producto o plato (sin gluten, vegano, familiar…) con nombre, familia, fuente y evidencia.';
COMMENT ON VIEW capa.item_unit_prices IS 'Precio vigente por vertical y precio por kilo, litro o unidad (precio ÷ tamaño total normalizado).';
COMMENT ON COLUMN capa.item_unit_prices.price IS 'Precio vigente más bajo del ítem en esa vertical (CLP).';
COMMENT ON COLUMN capa.item_unit_prices.price_per_kg IS 'CLP por kilo, solo para ítems medidos en gramos.';
COMMENT ON COLUMN capa.item_unit_prices.price_per_l IS 'CLP por litro, solo para ítems medidos en mililitros.';
COMMENT ON COLUMN capa.item_unit_prices.price_per_unit IS 'CLP por unidad, solo para ítems medidos en unidades.';

-- Precio por unidad comparable frente a la mediana de su concepto en su vertical: detecta precios mal cargados
-- (una gaseosa de 2 L a $232.430) sin tocar el dato original.
CREATE VIEW capa.unit_price_ratios AS
WITH unit_prices AS (
    SELECT u.vertical, u.entity_type, u.entity_id, ic.concept_id,
           CASE WHEN u.price_per_kg IS NOT NULL THEN 'kg' WHEN u.price_per_l IS NOT NULL THEN 'l' ELSE 'und' END AS per,
           coalesce(u.price_per_kg, u.price_per_l, u.price_per_unit) AS unit_price
    FROM capa.item_unit_prices u
    JOIN item_concepts ic ON ic.entity_type = u.entity_type AND ic.entity_id = u.entity_id
    WHERE coalesce(u.price_per_kg, u.price_per_l, u.price_per_unit) IS NOT NULL
), medians AS (
    SELECT vertical, concept_id, per, count(*) AS items,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY unit_price) AS median_price
    FROM unit_prices GROUP BY vertical, concept_id, per
)
SELECT p.vertical, p.concept_id, p.entity_type, p.entity_id, p.per, p.unit_price, m.median_price,
       p.unit_price / NULLIF(m.median_price, 0) AS ratio, m.items AS items_in_group
FROM unit_prices p JOIN medians m USING (vertical, concept_id, per);

COMMENT ON VIEW capa.unit_price_ratios IS 'Precio por unidad comparable (kg, l o und) de cada ítem frente a la mediana de su concepto en su vertical.';
COMMENT ON COLUMN capa.unit_price_ratios.ratio IS 'Precio por unidad ÷ mediana del grupo: muy alto o muy bajo es sospechoso de precio mal cargado.';
