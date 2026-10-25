-- Capa de perfiles, etapa 2 (docs/superpowers/specs/2026-10-06-capa-perfiles-design.md §3.4–3.5): marcas canónicas y
-- producto canónico (el mismo producto en varias tiendas y verticales).
CREATE TABLE product_brands (
    brand_key      text PRIMARY KEY,                       -- slug estable: coca-cola
    name           text NOT NULL,                          -- la escritura más común
    kind           text NOT NULL DEFAULT 'marca' CHECK (kind IN ('marca', 'cadena')),
    is_store_brand boolean NOT NULL DEFAULT false,         -- marca propia de una tienda (Líder, Great Value…)
    curated        boolean NOT NULL DEFAULT false,
    items          integer NOT NULL DEFAULT 0
);

CREATE TABLE brand_aliases (
    alias     text PRIMARY KEY,                            -- escritura normalizada: «coca cola»
    brand_key text NOT NULL REFERENCES product_brands (brand_key) ON DELETE CASCADE,
    source    text NOT NULL CHECK (source IN ('rappi', 'curado')),
    items     integer NOT NULL DEFAULT 0
);
CREATE INDEX brand_aliases_brand_idx ON brand_aliases (brand_key);

CREATE TABLE item_brands (
    entity_type text NOT NULL CHECK (entity_type IN ('catalog_item', 'menu_item')),
    entity_id   text NOT NULL,
    brand_key   text NOT NULL REFERENCES product_brands (brand_key) ON DELETE CASCADE,
    source      text NOT NULL CHECK (source IN ('rappi', 'regla', 'cadena', 'curado')),
    run_id      bigint REFERENCES layer_runs (run_id) ON DELETE SET NULL,
    PRIMARY KEY (entity_type, entity_id)
);
CREATE INDEX item_brands_brand_idx ON item_brands (brand_key);

CREATE TABLE canonical_products (
    canonical_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brand_key    text NOT NULL REFERENCES product_brands (brand_key) ON DELETE CASCADE,
    name_key     text NOT NULL,                            -- nombre sin marca, tamaño ni pack, palabras ordenadas
    total        double precision NOT NULL,
    unit         text NOT NULL,
    label        text NOT NULL,                            -- el nombre más común, para mostrar
    items        integer NOT NULL DEFAULT 1,
    UNIQUE (brand_key, name_key, total, unit)
);

CREATE TABLE item_canonical (
    master_product_id bigint PRIMARY KEY,
    canonical_id      bigint NOT NULL REFERENCES canonical_products (canonical_id) ON DELETE CASCADE,
    method            text NOT NULL CHECK (method IN ('exacto', 'regla', 'curado')),
    confidence        real NOT NULL,
    run_id            bigint REFERENCES layer_runs (run_id) ON DELETE SET NULL
);
CREATE INDEX item_canonical_canonical_idx ON item_canonical (canonical_id);

COMMENT ON TABLE product_brands IS 'Marcas canónicas (slug estable) con su escritura más común y si son marca propia de una tienda. Las líneas («Soprole Next») son alias de su marca.';
COMMENT ON TABLE brand_aliases IS 'Escrituras normalizadas de cada marca («coca cola», «cocacola» → coca-cola).';
COMMENT ON TABLE item_brands IS 'Marca de cada producto (declarada por Rappi o deducida del nombre) y cadena de cada plato.';
COMMENT ON TABLE canonical_products IS 'Producto canónico: el mismo producto (marca + nombre + tamaño) aunque Rappi lo liste con distintos ids.';
COMMENT ON TABLE item_canonical IS 'A qué producto canónico pertenece cada producto de Rappi, con método y confianza.';

CREATE VIEW capa.item_brands AS
SELECT b.entity_type, b.entity_id, b.brand_key, p.name AS brand_name, p.kind, p.is_store_brand, b.source
FROM item_brands b JOIN product_brands p USING (brand_key);

COMMENT ON VIEW capa.item_brands IS 'Marca de cada ítem (productos y platos), con su nombre, si es marca propia y de dónde salió.';

CREATE VIEW capa.canonical_products AS
SELECT c.canonical_id, c.brand_key, b.name AS brand_name, c.label, c.total, c.unit, c.items,
       array_agg(DISTINCT sv.vertical ORDER BY sv.vertical) AS verticals,
       array_agg(DISTINCT ic.master_product_id ORDER BY ic.master_product_id) AS master_product_ids
FROM canonical_products c
JOIN product_brands b USING (brand_key)
JOIN item_canonical ic USING (canonical_id)
JOIN store_products sp ON sp.master_product_id = ic.master_product_id
JOIN v_store_verticals sv ON sv.store_id = sp.store_id
GROUP BY c.canonical_id, c.brand_key, b.name, c.label, c.total, c.unit, c.items;

COMMENT ON VIEW capa.canonical_products IS 'Producto canónico con las verticales donde se vende y los ids de Rappi que lo componen. Las verticales se inflan con las tiendas listadas en varias (Express Líder): lo que Rappi lista con ids distintos es `items > 1`.';
