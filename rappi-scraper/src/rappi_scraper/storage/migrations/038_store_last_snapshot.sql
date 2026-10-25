-- El último snapshot de cada tienda en su propia tabla. v_store_format_runs (019) buscaba el último snapshot de cada una
-- de las ~5 mil tiendas en price_snapshots (una lectura de índice por tienda, ~16 mil buffers) en cada consulta que
-- usa v_latest_offers, aunque pidiera una sola tienda: el precio de una línea de pedido tardaba 6-16 ms y la búsqueda
-- de precios del agente era el 18,7 % del tiempo de la base (auditoría de rendimiento del 17-10, hallazgo 1). Ahora ese
-- último snapshot lo mantienen triggers sobre price_snapshots, como latest_prices (032), y la vista lo lee de ahí.
-- La vigencia no cambia: v_latest_offers sigue siendo la única definición de oferta vigente; solo cambia de dónde sale
-- el último snapshot de cada tienda. El formato se sigue leyendo de stores, así que cambiar el store_type de una
-- tienda se ve al tiro, como antes.

CREATE TABLE store_last_snapshot (
    store_id   bigint PRIMARY KEY,
    run_id     bigint NOT NULL,
    scraped_at timestamptz NOT NULL
);
COMMENT ON TABLE store_last_snapshot IS 'Último snapshot de precios de cada tienda (scraped_at más reciente y, con el mismo, la corrida más nueva). La mantienen triggers sobre price_snapshots: no se escribe a mano. La lee v_store_format_runs.';
COMMENT ON COLUMN store_last_snapshot.store_id IS 'Tienda (sucursal) con precios.';
COMMENT ON COLUMN store_last_snapshot.run_id IS 'Corrida de su último snapshot de precios.';
COMMENT ON COLUMN store_last_snapshot.scraped_at IS 'Cuándo se bajó su último snapshot de precios.';

-- El último snapshot de una tienda, leído del historial por price_snapshots_store_latest_idx (019). El INSERT es un
-- upsert: si otra transacción vuelve a poner la fila de la misma tienda entre el DELETE y el INSERT, no hay choque de
-- llave.
CREATE FUNCTION store_last_snapshot_refresh(p_store_id bigint) RETURNS void LANGUAGE sql AS $$
    DELETE FROM store_last_snapshot WHERE store_id = p_store_id;
    INSERT INTO store_last_snapshot (store_id, run_id, scraped_at)
    SELECT store_id, run_id, scraped_at
    FROM price_snapshots
    WHERE store_id = p_store_id
    ORDER BY scraped_at DESC, run_id DESC
    LIMIT 1
    ON CONFLICT (store_id) DO UPDATE SET run_id = EXCLUDED.run_id, scraped_at = EXCLUDED.scraped_at;
$$;

-- Un snapshot nuevo reemplaza al último de su tienda si es más nuevo (por scraped_at y, con el mismo, por corrida).
-- Si un snapshot cambia o se borra (también en cascada, al borrar una corrida, un producto o una tienda), el último de
-- su tienda se vuelve a leer del historial solo si ya ningún snapshot de la tienda tiene la fecha y la corrida
-- guardadas: una tienda tiene miles de snapshots por corrida, y reescribir su fila por cada uno (un reintento con
-- ON CONFLICT … DO UPDATE, o borrar una corrida) la llenaría de versiones muertas dentro de la misma transacción.
CREATE FUNCTION store_last_snapshot_track() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') AND NOT EXISTS (
        SELECT 1
        FROM store_last_snapshot l
        JOIN price_snapshots ps ON ps.store_id = l.store_id AND ps.scraped_at = l.scraped_at AND ps.run_id = l.run_id
        WHERE l.store_id = OLD.store_id
    ) THEN
        PERFORM store_last_snapshot_refresh(OLD.store_id);
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        INSERT INTO store_last_snapshot (store_id, run_id, scraped_at)
        VALUES (NEW.store_id, NEW.run_id, NEW.scraped_at)
        ON CONFLICT (store_id) DO UPDATE SET run_id = EXCLUDED.run_id, scraped_at = EXCLUDED.scraped_at
        WHERE (EXCLUDED.scraped_at, EXCLUDED.run_id) > (store_last_snapshot.scraped_at, store_last_snapshot.run_id);
    END IF;
    RETURN NULL;
END
$$;

CREATE FUNCTION store_last_snapshot_truncate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE store_last_snapshot;
    RETURN NULL;
END
$$;

CREATE TRIGGER price_snapshots_store_last AFTER INSERT OR UPDATE OR DELETE ON price_snapshots
    FOR EACH ROW EXECUTE FUNCTION store_last_snapshot_track();
CREATE TRIGGER price_snapshots_store_last_truncate AFTER TRUNCATE ON price_snapshots
    FOR EACH STATEMENT EXECUTE FUNCTION store_last_snapshot_truncate();

-- El llenado va después de crear los triggers (CREATE TRIGGER bloquea las escrituras al historial hasta el final de la
-- migración). Una lectura de índice por tienda, como hacía la vista; price_snapshots llega a stores en cascada (por
-- store_products), así que toda tienda con snapshots está en stores.
INSERT INTO store_last_snapshot (store_id, run_id, scraped_at)
SELECT s.store_id, l.run_id, l.scraped_at
FROM stores s
CROSS JOIN LATERAL (SELECT ps.run_id, ps.scraped_at FROM price_snapshots ps WHERE ps.store_id = s.store_id
                    ORDER BY ps.scraped_at DESC, ps.run_id DESC LIMIT 1) l;
ANALYZE store_last_snapshot;

-- La misma vista (mismas columnas y el mismo desempate), ahora con el último snapshot de store_last_snapshot. La ventana
-- por formato sigue recorriendo las tiendas con precios (unas mil), pero sin leer price_snapshots. Agrupa por el
-- formato con COLLATE "C": dos formatos son el mismo solo si son iguales byte a byte, con o sin "C" (la intercalación
-- de la base es determinista), y ordenar sin las reglas del idioma deja la ventana en un tercio del tiempo.
CREATE OR REPLACE VIEW v_store_format_runs AS
WITH last AS (
    SELECT s.store_id, COALESCE(s.store_type, 'id:' || s.store_id) AS format, l.run_id, l.scraped_at
    FROM stores s
    JOIN store_last_snapshot l ON l.store_id = s.store_id
)
SELECT store_id, format,
       first_value(run_id) OVER (PARTITION BY format COLLATE "C" ORDER BY scraped_at DESC, run_id DESC) AS format_run_id
FROM last;
COMMENT ON VIEW v_store_format_runs IS 'Para cada tienda con precios, su formato (store_type, o la tienda misma sin formato) y la última corrida que bajó ese formato. El último snapshot de cada tienda sale de store_last_snapshot.';
