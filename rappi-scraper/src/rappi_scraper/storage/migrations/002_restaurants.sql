-- Restaurantes: viven en `stores` (vertical 'restaurantes') con detalle, cocinas y menú.

CREATE TABLE restaurant_details (
    store_id      bigint PRIMARY KEY REFERENCES stores ON DELETE CASCADE,
    rating        numeric,
    review_count  int,
    delivery_cost numeric,
    eta           text,
    schedules     jsonb,
    tags          text[] NOT NULL DEFAULT '{}'
);

CREATE TABLE cuisines (
    name text PRIMARY KEY
);

CREATE TABLE restaurant_cuisines (
    store_id bigint NOT NULL REFERENCES stores ON DELETE CASCADE,
    cuisine  text NOT NULL REFERENCES cuisines,
    PRIMARY KEY (store_id, cuisine)
);

CREATE TABLE menu_sections (
    store_id   bigint NOT NULL REFERENCES stores ON DELETE CASCADE,
    section_id bigint NOT NULL,
    name       text NOT NULL,
    position   int,
    PRIMARY KEY (store_id, section_id)
);

CREATE TABLE menu_items (
    item_id      bigint PRIMARY KEY,
    store_id     bigint NOT NULL REFERENCES stores ON DELETE CASCADE,
    section_id   bigint,
    name         text NOT NULL,
    description  text,
    image_url    text,
    is_popular   boolean NOT NULL DEFAULT false,
    has_toppings boolean NOT NULL DEFAULT false,
    first_seen   timestamptz NOT NULL DEFAULT now(),
    last_seen    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX menu_items_store_idx ON menu_items (store_id);

CREATE TABLE menu_price_snapshots (
    run_id       bigint NOT NULL REFERENCES scrape_runs ON DELETE CASCADE,
    item_id      bigint NOT NULL REFERENCES menu_items ON DELETE CASCADE,
    price        numeric,
    real_price   numeric,
    discount_pct numeric,
    is_available boolean,
    scraped_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, item_id)
);
