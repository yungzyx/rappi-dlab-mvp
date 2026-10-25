-- Precio vigente sin recorrer el historial (D-I9, D-M6). price_snapshots guarda una fila por producto, tienda y
-- corrida y crece cada semana sin tope; armar la búsqueda, el reporte y varias consultas de la API ordenaban todo ese
-- historial para quedarse con el último precio de cada SKU. Ahora ese último precio vive en su propia tabla, que
-- mantienen triggers sobre las tablas de historial: así vale para el scraper, la siembra de prueba, los tests y los
-- borrados en cascada, sin que cada uno se acuerde de actualizarla.
-- El último precio es el de scraped_at más reciente y, con el mismo scraped_at (importaciones de CSV antiguas), el de la
-- corrida más nueva: el desempate de v_store_format_runs, que v_latest_prices no tenía (D-M6).
-- La migración llena las tablas una vez desde el historial (en la base real, unos segundos) y no reescribe
-- price_snapshots ni menu_price_snapshots.

CREATE TABLE latest_prices (
    store_id     bigint NOT NULL,
    sku          text NOT NULL,
    price        numeric,
    real_price   numeric,
    discount_pct numeric,
    pum          text,
    in_stock     boolean,
    run_id       bigint NOT NULL,
    scraped_at   timestamptz NOT NULL,
    PRIMARY KEY (store_id, sku)
);
COMMENT ON TABLE latest_prices IS 'Último precio de cada SKU en cada tienda (la fila más nueva de price_snapshots, desempatada por corrida). La mantienen triggers sobre price_snapshots: no se escribe a mano.';
COMMENT ON COLUMN latest_prices.store_id IS 'Tienda (sucursal) de la oferta.';
COMMENT ON COLUMN latest_prices.sku IS 'SKU de la oferta en esa tienda.';
COMMENT ON COLUMN latest_prices.price IS 'Precio del último snapshot.';
COMMENT ON COLUMN latest_prices.real_price IS 'Precio de lista (antes del descuento) del último snapshot.';
COMMENT ON COLUMN latest_prices.discount_pct IS 'Descuento en porcentaje del último snapshot.';
COMMENT ON COLUMN latest_prices.pum IS 'Precio por unidad de medida tal como lo publica Rappi.';
COMMENT ON COLUMN latest_prices.in_stock IS 'Si la tienda lo tenía disponible en el último snapshot.';
COMMENT ON COLUMN latest_prices.run_id IS 'Corrida del último snapshot.';
COMMENT ON COLUMN latest_prices.scraped_at IS 'Cuándo se bajó el último snapshot.';

CREATE TABLE latest_menu_prices (
    item_id      bigint PRIMARY KEY,
    price        numeric,
    real_price   numeric,
    discount_pct numeric,
    is_available boolean,
    run_id       bigint NOT NULL,
    scraped_at   timestamptz NOT NULL
);
COMMENT ON TABLE latest_menu_prices IS 'Último precio de cada plato (la fila más nueva de menu_price_snapshots, desempatada por corrida). La mantienen triggers sobre menu_price_snapshots: no se escribe a mano.';
COMMENT ON COLUMN latest_menu_prices.item_id IS 'Plato (menu_items.item_id).';
COMMENT ON COLUMN latest_menu_prices.price IS 'Precio del último snapshot.';
COMMENT ON COLUMN latest_menu_prices.real_price IS 'Precio de lista (antes del descuento) del último snapshot.';
COMMENT ON COLUMN latest_menu_prices.discount_pct IS 'Descuento en porcentaje del último snapshot.';
COMMENT ON COLUMN latest_menu_prices.is_available IS 'Si el plato estaba disponible en el último snapshot.';
COMMENT ON COLUMN latest_menu_prices.run_id IS 'Corrida del último snapshot.';
COMMENT ON COLUMN latest_menu_prices.scraped_at IS 'Cuándo se bajó el último snapshot.';

-- Un snapshot nuevo reemplaza al último si es igual o más nuevo (por scraped_at y, con el mismo, por corrida). Si un
-- snapshot cambia o se borra (también en cascada, al borrar una corrida o un producto), el último de su SKU se vuelve
-- a leer del historial por su índice.
CREATE FUNCTION latest_prices_refresh(p_store_id bigint, p_sku text) RETURNS void LANGUAGE sql AS $$
    DELETE FROM latest_prices WHERE store_id = p_store_id AND sku = p_sku;
    INSERT INTO latest_prices (store_id, sku, price, real_price, discount_pct, pum, in_stock, run_id, scraped_at)
    SELECT store_id, sku, price, real_price, discount_pct, pum, in_stock, run_id, scraped_at
    FROM price_snapshots
    WHERE store_id = p_store_id AND sku = p_sku
    ORDER BY scraped_at DESC, run_id DESC
    LIMIT 1;
$$;

CREATE FUNCTION latest_prices_track() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO latest_prices (store_id, sku, price, real_price, discount_pct, pum, in_stock, run_id, scraped_at)
        VALUES (NEW.store_id, NEW.sku, NEW.price, NEW.real_price, NEW.discount_pct, NEW.pum, NEW.in_stock, NEW.run_id,
                NEW.scraped_at)
        ON CONFLICT (store_id, sku) DO UPDATE SET
            price = EXCLUDED.price, real_price = EXCLUDED.real_price, discount_pct = EXCLUDED.discount_pct,
            pum = EXCLUDED.pum, in_stock = EXCLUDED.in_stock, run_id = EXCLUDED.run_id,
            scraped_at = EXCLUDED.scraped_at
        WHERE (EXCLUDED.scraped_at, EXCLUDED.run_id) >= (latest_prices.scraped_at, latest_prices.run_id);
        RETURN NULL;
    END IF;
    PERFORM latest_prices_refresh(OLD.store_id, OLD.sku);
    IF TG_OP = 'UPDATE' AND (NEW.store_id, NEW.sku) IS DISTINCT FROM (OLD.store_id, OLD.sku) THEN
        PERFORM latest_prices_refresh(NEW.store_id, NEW.sku);
    END IF;
    RETURN NULL;
END
$$;

CREATE FUNCTION latest_prices_truncate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE latest_prices;
    RETURN NULL;
END
$$;

CREATE TRIGGER price_snapshots_latest AFTER INSERT OR UPDATE OR DELETE ON price_snapshots
    FOR EACH ROW EXECUTE FUNCTION latest_prices_track();
CREATE TRIGGER price_snapshots_latest_truncate AFTER TRUNCATE ON price_snapshots
    FOR EACH STATEMENT EXECUTE FUNCTION latest_prices_truncate();

CREATE FUNCTION latest_menu_prices_refresh(p_item_id bigint) RETURNS void LANGUAGE sql AS $$
    DELETE FROM latest_menu_prices WHERE item_id = p_item_id;
    INSERT INTO latest_menu_prices (item_id, price, real_price, discount_pct, is_available, run_id, scraped_at)
    SELECT item_id, price, real_price, discount_pct, is_available, run_id, scraped_at
    FROM menu_price_snapshots
    WHERE item_id = p_item_id
    ORDER BY scraped_at DESC, run_id DESC
    LIMIT 1;
$$;

CREATE FUNCTION latest_menu_prices_track() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO latest_menu_prices (item_id, price, real_price, discount_pct, is_available, run_id, scraped_at)
        VALUES (NEW.item_id, NEW.price, NEW.real_price, NEW.discount_pct, NEW.is_available, NEW.run_id, NEW.scraped_at)
        ON CONFLICT (item_id) DO UPDATE SET
            price = EXCLUDED.price, real_price = EXCLUDED.real_price, discount_pct = EXCLUDED.discount_pct,
            is_available = EXCLUDED.is_available, run_id = EXCLUDED.run_id, scraped_at = EXCLUDED.scraped_at
        WHERE (EXCLUDED.scraped_at, EXCLUDED.run_id) >= (latest_menu_prices.scraped_at, latest_menu_prices.run_id);
        RETURN NULL;
    END IF;
    PERFORM latest_menu_prices_refresh(OLD.item_id);
    IF TG_OP = 'UPDATE' AND NEW.item_id <> OLD.item_id THEN
        PERFORM latest_menu_prices_refresh(NEW.item_id);
    END IF;
    RETURN NULL;
END
$$;

CREATE FUNCTION latest_menu_prices_truncate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE latest_menu_prices;
    RETURN NULL;
END
$$;

CREATE TRIGGER menu_price_snapshots_latest AFTER INSERT OR UPDATE OR DELETE ON menu_price_snapshots
    FOR EACH ROW EXECUTE FUNCTION latest_menu_prices_track();
CREATE TRIGGER menu_price_snapshots_latest_truncate AFTER TRUNCATE ON menu_price_snapshots
    FOR EACH STATEMENT EXECUTE FUNCTION latest_menu_prices_truncate();

-- El llenado va después de crear los triggers: CREATE TRIGGER bloquea las escrituras al historial hasta el final de
-- la migración, así que ningún snapshot que se guarde mientras tanto queda fuera de las tablas.
INSERT INTO latest_prices (store_id, sku, price, real_price, discount_pct, pum, in_stock, run_id, scraped_at)
SELECT DISTINCT ON (store_id, sku) store_id, sku, price, real_price, discount_pct, pum, in_stock, run_id, scraped_at
FROM price_snapshots
ORDER BY store_id, sku, scraped_at DESC, run_id DESC;

INSERT INTO latest_menu_prices (item_id, price, real_price, discount_pct, is_available, run_id, scraped_at)
SELECT DISTINCT ON (item_id) item_id, price, real_price, discount_pct, is_available, run_id, scraped_at
FROM menu_price_snapshots
ORDER BY item_id, scraped_at DESC, run_id DESC;

-- La misma vista de siempre (mismas columnas), ahora leída de latest_prices: con el desempate por corrida.
CREATE OR REPLACE VIEW v_latest_prices AS
SELECT store_id, sku, price, real_price, discount_pct, pum, in_stock, run_id, scraped_at
FROM latest_prices;
COMMENT ON VIEW v_latest_prices IS 'Último precio de cada SKU en cada tienda (lee latest_prices).';

-- Los jobs que omitieron algún pasillo son pocos: el índice parcial evita leer todos los jobs en cada consulta de la
-- vista de abajo.
CREATE INDEX scrape_jobs_skipped_aisles_idx ON scrape_jobs (run_id)
    WHERE job_type = 'store_group' AND status = 'done'
      AND jsonb_typeof(result->'pasillos_omitidos') = 'array' AND result->'pasillos_omitidos' <> '[]';

-- Oferta vigente, definida una sola vez: la usan la búsqueda (rappi_scraper/storage/search.py), la API (catálogo,
-- tiendas, precio del pedido, ofertas, «Cerca de ti») y el agente (rappi_ia). Cada corrida baja una sucursal por
-- formato de tienda; una oferta es vigente si su último precio es de la última corrida que bajó su formato
-- (v_store_format_runs, migración 019). Excepción: si esa corrida no pudo leer un pasillo o sub-pasillo de la tienda
-- (`pasillos_omitidos` del job que la bajó), una oferta de ese pasillo sigue vigente si su último precio es de la
-- bajada anterior de su formato (el job store_group terminado anterior del mismo formato) y esa bajada fue de esta
-- misma tienda: una página caída no la esconde, pero tampoco revive lo que esa bajada ya no encontró, ni los precios
-- de hace semanas de una sucursal que se volvió a bajar después de otra (B → A → B). Las tiendas sin precios no salen
-- (no tienen formato descargado).
CREATE VIEW v_latest_offers AS
SELECT lp.store_id, lp.sku, lp.price, lp.real_price, lp.discount_pct, lp.in_stock, lp.run_id, lp.scraped_at,
       f.format_run_id,
       CASE WHEN lp.run_id = f.format_run_id THEN true
            WHEN r.run_id IS NULL OR lp.run_id >= r.run_id THEN false
            -- De un pasillo omitido…
            WHEN NOT EXISTS (SELECT 1 FROM store_products sp
                             WHERE sp.store_id = lp.store_id AND sp.sku = lp.sku
                               AND (sp.aisle_id = ANY(r.aisles) OR sp.sub_aisle_id = ANY(r.aisles))) THEN false
            -- …y su último precio es de la bajada anterior del formato (que, si fue de otra sucursal, no lo trae). Sin
            -- bajada anterior (un CSV importado no deja jobs) no hay rescate: false, nunca NULL.
            ELSE COALESCE(lp.run_id = (SELECT max(j.run_id) FROM scrape_jobs j
                                       JOIN stores js ON js.store_id = (j.result->>'store_id')::bigint
                                       WHERE j.job_type = 'store_group' AND j.status = 'done' AND j.run_id < r.run_id
                                         AND COALESCE(js.store_type, 'id:' || js.store_id) = f.format), false)
       END AS current
FROM latest_prices lp
JOIN v_store_format_runs f ON f.store_id = lp.store_id
-- Los pasillos omitidos de cada tienda en cada corrida (pocos jobs, por el índice parcial de arriba). Va sin WITH para
-- que la vista se funda con la consulta que la usa: así una consulta por tienda o por producto lee latest_prices por su
-- llave.
LEFT JOIN (
    SELECT j.run_id, (j.result->>'store_id')::bigint AS store_id, array_agg(a.aisle_id::bigint) AS aisles
    FROM scrape_jobs j
    CROSS JOIN LATERAL jsonb_array_elements_text(j.result->'pasillos_omitidos') a(aisle_id)
    WHERE j.job_type = 'store_group' AND j.status = 'done'
      AND jsonb_typeof(j.result->'pasillos_omitidos') = 'array' AND j.result->'pasillos_omitidos' <> '[]'
    GROUP BY 1, 2
) r ON r.run_id = f.format_run_id AND r.store_id = lp.store_id;
COMMENT ON VIEW v_latest_offers IS 'Último precio de cada oferta (tienda y SKU) con su vigencia: la única definición de oferta vigente que usan la búsqueda, la API y el agente.';
COMMENT ON COLUMN v_latest_offers.store_id IS 'Tienda (sucursal) de la oferta.';
COMMENT ON COLUMN v_latest_offers.sku IS 'SKU de la oferta en esa tienda.';
COMMENT ON COLUMN v_latest_offers.price IS 'Último precio.';
COMMENT ON COLUMN v_latest_offers.real_price IS 'Precio de lista (antes del descuento) del último snapshot.';
COMMENT ON COLUMN v_latest_offers.discount_pct IS 'Descuento en porcentaje del último snapshot.';
COMMENT ON COLUMN v_latest_offers.in_stock IS 'Si la tienda lo tenía disponible en el último snapshot.';
COMMENT ON COLUMN v_latest_offers.run_id IS 'Corrida del último precio.';
COMMENT ON COLUMN v_latest_offers.scraped_at IS 'Cuándo se bajó el último precio.';
COMMENT ON COLUMN v_latest_offers.format_run_id IS 'Última corrida que bajó el formato de la tienda (v_store_format_runs).';
COMMENT ON COLUMN v_latest_offers.current IS 'Si la oferta está vigente: su último precio es de format_run_id o, en un pasillo que esa corrida no pudo leer, de la bajada anterior de su formato.';
