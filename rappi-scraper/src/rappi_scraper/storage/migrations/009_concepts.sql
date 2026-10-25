-- Capa 2: taxonomía propia de conceptos, mapeo de categorías y complementos entre conceptos.
-- Lo llena `rappi-ia concepts` (rappi-ia/). Todo dato inferido guarda método, confianza y versión.
-- Tablas propias (no columnas en tablas del scraper): `build_search_documents` y el scraper no las tocan.

CREATE TABLE concepts (
    concept_id      text PRIMARY KEY,
    name            text NOT NULL,
    parent_id       text REFERENCES concepts (concept_id),
    emoji           text,
    keywords        text[] NOT NULL DEFAULT '{}',
    sensitive       boolean NOT NULL DEFAULT false,  -- nunca se sugiere por iniciativa propia
    age_restricted  boolean NOT NULL DEFAULT false,  -- +18
    taxonomy_version text NOT NULL,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Nombres de Rappi (categoría de producto, sección de menú, cocina) → concepto.
CREATE TABLE category_map (
    source_kind   text NOT NULL CHECK (source_kind IN ('categoria', 'seccion_menu', 'cocina')),
    source_key    text NOT NULL,  -- lower(trim(nombre))
    source_name   text NOT NULL,
    concept_id    text NOT NULL REFERENCES concepts (concept_id) ON DELETE CASCADE,
    method        text NOT NULL CHECK (method IN ('curado', 'llm', 'regla', 'embedding')),
    confidence    real NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    model_version text,
    note          text,
    valid_from    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_kind, source_key)
);

-- Un concepto principal por producto o plato.
CREATE TABLE item_concepts (
    entity_type   text NOT NULL CHECK (entity_type IN ('catalog_item', 'menu_item')),
    entity_id     text NOT NULL,
    concept_id    text NOT NULL REFERENCES concepts (concept_id) ON DELETE CASCADE,
    method        text NOT NULL CHECK (method IN ('curado', 'llm', 'regla', 'embedding')),
    confidence    real NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    model_version text,
    source        text,  -- de dónde salió: 'categoria:Cervezas', 'nombre:pizza', 'seccion:Pastas'…
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (entity_type, entity_id)
);
CREATE INDEX item_concepts_concept_idx ON item_concepts (concept_id);

-- Complementos: "quien lleva X suele querer Y". Curados o aprendidos por co-ocurrencia.
CREATE TABLE concept_edges (
    from_concept text NOT NULL REFERENCES concepts (concept_id) ON DELETE CASCADE,
    to_concept   text NOT NULL REFERENCES concepts (concept_id) ON DELETE CASCADE,
    method       text NOT NULL CHECK (method IN ('curado', 'coocurrencia')),
    weight       real NOT NULL CHECK (weight BETWEEN 0 AND 1),
    support      integer,             -- usuarios que respaldan la arista (co-ocurrencia)
    data_source  text NOT NULL DEFAULT 'curado' CHECK (data_source IN ('curado', 'synthetic', 'prototype')),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (from_concept, to_concept, method),
    CHECK (from_concept <> to_concept)
);

-- Surtido por concepto y vertical (productos del catálogo + platos de restaurantes).
CREATE VIEW v_concept_assortment AS
SELECT ic.concept_id, iv.vertical, count(DISTINCT ic.entity_id) AS items
FROM item_concepts ic
JOIN v_item_verticals iv ON ic.entity_type = 'catalog_item' AND iv.master_product_id::text = ic.entity_id
GROUP BY 1, 2
UNION ALL
SELECT concept_id, 'restaurantes', count(*)
FROM item_concepts
WHERE entity_type = 'menu_item'
GROUP BY 1;
