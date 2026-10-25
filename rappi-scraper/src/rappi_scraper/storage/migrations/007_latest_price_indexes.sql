-- Índices para "último precio" por producto/plato (las PK empiezan por run_id y no sirven para eso).
CREATE INDEX price_snapshots_latest_idx ON price_snapshots (store_id, sku, scraped_at DESC);
CREATE INDEX menu_price_snapshots_latest_idx ON menu_price_snapshots (item_id, scraped_at DESC);
