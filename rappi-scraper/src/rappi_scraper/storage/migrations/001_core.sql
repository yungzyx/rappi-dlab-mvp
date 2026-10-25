-- Núcleo: verticales, tiendas, catálogo único y ofertas por tienda con historial.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE scrape_runs (
    run_id      bigserial PRIMARY KEY,
    kind        text NOT NULL,                -- 'stores' | 'restaurants' | 'legacy_csv'
    params      jsonb NOT NULL DEFAULT '{}',
    status      text NOT NULL DEFAULT 'running',
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);

-- Cola reanudable: un job por grupo de tiendas (marca/formato) o restaurante/cadena.
CREATE TABLE scrape_jobs (
    run_id      bigint NOT NULL REFERENCES scrape_runs ON DELETE CASCADE,
    job_key     text NOT NULL,
    job_type    text NOT NULL,                -- 'store_group' | 'restaurant'
    payload     jsonb NOT NULL,               -- sucursales candidatas, vertical, etc.
    status      text NOT NULL DEFAULT 'pending', -- pending | done | skipped | failed
    attempts    int NOT NULL DEFAULT 0,
    result      jsonb,
    error       text,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, job_key)
);

CREATE TABLE verticals (
    code        text PRIMARY KEY,
    name        text NOT NULL,
    source_path text NOT NULL
);

INSERT INTO verticals (code, name, source_path) VALUES
    ('supermercado', 'Supermercados',        '/tiendas/tipo/market'),
    ('conveniencia', 'Conveniencia',         '/tiendas/tipo/express-big'),
    ('turbo',        'Turbo',                '/tiendas/tipo/turbo-home'),
    ('mall',         'Rappi Mall',           '/tiendas/tipo/rappimall-parent'),
    ('farmacia',     'Farmacias',            '/tiendas/tipo/farma'),
    ('licores',      'Licores',              '/tiendas/tipo/licores'),
    ('chocolateria', 'Chocolaterías',        '/tiendas/tipo/chocolateria'),
    ('restaurantes', 'Restaurantes',         '/restaurantes');

CREATE TABLE brands (
    brand_id    bigint PRIMARY KEY,
    name        text NOT NULL,
    kind        text NOT NULL DEFAULT 'store' -- 'store' | 'restaurant'
);

CREATE TABLE stores (
    store_id    bigint PRIMARY KEY,
    name        text NOT NULL,
    brand_id    bigint REFERENCES brands,
    store_type  text,
    sub_group   text,                         -- subvertical según Rappi (p. ej. 'Tecnologia')
    city        text,
    address     text,
    lat         double precision,
    lng         double precision,
    path        text,
    raw         jsonb,
    first_seen  timestamptz NOT NULL DEFAULT now(),
    last_seen   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX stores_store_type_idx ON stores (store_type);
CREATE INDEX stores_brand_idx ON stores (brand_id);

-- Una tienda puede aparecer en varios verticales (N:M).
CREATE TABLE store_verticals (
    store_id               bigint NOT NULL REFERENCES stores ON DELETE CASCADE,
    vertical               text NOT NULL REFERENCES verticals,
    subvertical            text,
    landing_classification text,
    filters                text[] NOT NULL DEFAULT '{}',
    last_seen              timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (store_id, vertical)
);
CREATE INDEX store_verticals_vertical_idx ON store_verticals (vertical);

CREATE TABLE categories (
    category_id bigint PRIMARY KEY,
    name        text NOT NULL
);

CREATE TABLE aisles (
    store_id               bigint NOT NULL REFERENCES stores ON DELETE CASCADE,
    aisle_id               bigint NOT NULL,
    parent_aisle_id        bigint,             -- NULL = pasillo; con valor = sub-pasillo
    name                   text NOT NULL,
    friendly_url           text,
    product_count_declared int,
    PRIMARY KEY (store_id, aisle_id)
);

-- Contenido único (lo que después se convierte en embeddings).
CREATE TABLE catalog_items (
    master_product_id bigint PRIMARY KEY,
    name              text NOT NULL,
    description       text,
    presentation      text,
    quantity          numeric,
    unit_type         text,
    trademark         text,
    category_id       bigint REFERENCES categories,
    image_url         text,
    attributes        jsonb NOT NULL DEFAULT '{}',
    is_alcoholic      boolean NOT NULL DEFAULT false,
    age_restricted    boolean NOT NULL DEFAULT false,
    first_seen        timestamptz NOT NULL DEFAULT now(),
    last_seen         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX catalog_items_category_idx ON catalog_items (category_id);

-- Oferta: el producto en una tienda concreta (SKU de la tienda).
CREATE TABLE store_products (
    store_id          bigint NOT NULL REFERENCES stores ON DELETE CASCADE,
    sku               text NOT NULL,
    master_product_id bigint REFERENCES catalog_items,
    aisle_id          bigint,
    sub_aisle_id      bigint,
    raw               jsonb,
    first_seen        timestamptz NOT NULL DEFAULT now(),
    last_seen         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (store_id, sku)
);
CREATE INDEX store_products_master_idx ON store_products (master_product_id);

CREATE TABLE price_snapshots (
    run_id       bigint NOT NULL REFERENCES scrape_runs ON DELETE CASCADE,
    store_id     bigint NOT NULL,
    sku          text NOT NULL,
    price        numeric,
    real_price   numeric,
    discount_pct numeric,
    pum          text,
    in_stock     boolean,
    stock        int,
    scraped_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, store_id, sku),
    FOREIGN KEY (store_id, sku) REFERENCES store_products ON DELETE CASCADE
);
