-- La corrida de cada formato guardada en la fila de cada tienda, y v_store_format_runs sin ventana ni joins. Con la 038
-- la vista calculaba la ventana por formato sobre store_last_snapshot: barata (~1 ms), pero el planificador ya no la
-- tomaba por cara y la ponía como lado interno de un Nested Loop. Una ventana no se puede buscar por store_id, así que
-- se volvía a recorrer entera por cada fila de afuera: las Ofertas (catalog/deals.py) pasaron de ~0,4 s a ~5 s (20.920
-- vueltas, 19,7 millones de filas descartadas), con un 504 en la demo. Ahora la vista lee una sola tabla de ~1.000
-- filas con llave store_id: el planificador la estima bien, la puede leer entera para un hash o buscar por llave, y
-- ninguno de los dos planes degenera así.
-- store_last_snapshot guarda además el formato de la tienda (format) y la última corrida de ese formato
-- (format_run_id). Los mantienen triggers: cuando cambia el último snapshot de una tienda se recalcula su formato, y
-- cuando una tienda cambia de formato en stores, su fila se mueve de formato. Borrar una tienda borra su fila en cascada
-- (por sus snapshots), y eso también recalcula su formato.
-- Costo: cada snapshot que se guarda lee su tienda en stores (el BEFORE INSERT de store_last_snapshot, por su llave). La
-- fila de una tienda cambia solo con el primer snapshot de cada transacción de precios (los demás traen la misma fecha y
-- corrida), y las filas de su formato se reescriben solo si cambia la corrida del formato (en rappi, a lo más 8 tiendas
-- por formato, por el índice de abajo).
-- Supone un solo escritor de precios por formato a la vez: dos transacciones que guardan precios de tiendas del mismo
-- formato en paralelo recalculan el formato cada una sin ver lo que la otra no ha confirmado. Lo garantiza el candado
-- de descargas (lock.py), que toman todos los comandos que escriben precios, también `rappi import-csv`.
-- La vigencia no cambia: v_latest_offers sigue siendo la única definición de oferta vigente.

ALTER TABLE store_last_snapshot ADD COLUMN format text, ADD COLUMN format_run_id bigint;
COMMENT ON COLUMN store_last_snapshot.format IS 'Formato de la tienda (stores.store_type o, sin él, ''id:'' y el store_id). Lo mantiene un trigger sobre stores.';
COMMENT ON COLUMN store_last_snapshot.format_run_id IS 'Última corrida que bajó el formato: la del último snapshot más nuevo entre las tiendas del formato (scraped_at y, con el mismo, la corrida más nueva).';
COMMENT ON TABLE store_last_snapshot IS 'Último snapshot de precios de cada tienda (scraped_at más reciente y, con el mismo, la corrida más nueva), con su formato y la última corrida de ese formato. La mantienen triggers sobre price_snapshots y stores: no se escribe a mano. Es v_store_format_runs.';

-- El llenado, con la definición de la 038 (la ventana por formato).
UPDATE store_last_snapshot l
SET format = x.format, format_run_id = x.format_run_id
FROM (
    SELECT l2.store_id, COALESCE(s.store_type, 'id:' || s.store_id) AS format,
           first_value(l2.run_id) OVER (PARTITION BY COALESCE(s.store_type, 'id:' || s.store_id)
                                        ORDER BY l2.scraped_at DESC, l2.run_id DESC) AS format_run_id
    FROM store_last_snapshot l2
    JOIN stores s ON s.store_id = l2.store_id
) x
WHERE x.store_id = l.store_id;
DELETE FROM store_last_snapshot WHERE format IS NULL;  -- sin tienda en stores (no debería haber)
ALTER TABLE store_last_snapshot ALTER COLUMN format SET NOT NULL, ALTER COLUMN format_run_id SET NOT NULL;
CREATE INDEX store_last_snapshot_format_idx ON store_last_snapshot (format, scraped_at DESC, run_id DESC);

-- La última corrida de un formato, puesta en las filas de sus tiendas que no la tienen.
CREATE FUNCTION store_format_run_refresh(p_format text) RETURNS void LANGUAGE sql AS $$
    UPDATE store_last_snapshot l
    SET format_run_id = x.run_id
    FROM (SELECT run_id FROM store_last_snapshot WHERE format = p_format
          ORDER BY scraped_at DESC, run_id DESC LIMIT 1) x
    WHERE l.format = p_format AND l.format_run_id IS DISTINCT FROM x.run_id;
$$;

-- Una fila nueva toma el formato de su tienda; sin tienda (se está borrando en cascada) no se guarda. La corrida del
-- formato queda provisoria: la pone bien el trigger de después.
CREATE FUNCTION store_format_run_fill() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    SELECT COALESCE(s.store_type, 'id:' || s.store_id) INTO NEW.format FROM stores s WHERE s.store_id = NEW.store_id;
    IF NEW.format IS NULL THEN
        RETURN NULL;
    END IF;
    NEW.format_run_id := NEW.run_id;
    RETURN NEW;
END
$$;

-- Cambió el último snapshot de una tienda o su formato: se recalculan el formato que deja y el que toma. El UPDATE de
-- store_format_run_refresh solo escribe format_run_id, así que no vuelve a disparar este trigger.
CREATE FUNCTION store_format_run_track() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        PERFORM store_format_run_refresh(OLD.format);
    END IF;
    IF TG_OP = 'INSERT' OR (TG_OP = 'UPDATE' AND NEW.format IS DISTINCT FROM OLD.format) THEN
        PERFORM store_format_run_refresh(NEW.format);
    END IF;
    RETURN NULL;
END
$$;

-- Una tienda cambia de formato (o de id) en stores: su fila pasa al formato nuevo.
CREATE FUNCTION store_format_run_store_changed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE store_last_snapshot SET format = COALESCE(NEW.store_type, 'id:' || NEW.store_id)
    WHERE store_id = OLD.store_id;
    RETURN NULL;
END
$$;

CREATE TRIGGER store_last_snapshot_fill BEFORE INSERT ON store_last_snapshot
    FOR EACH ROW EXECUTE FUNCTION store_format_run_fill();
CREATE TRIGGER store_last_snapshot_format AFTER INSERT OR DELETE OR UPDATE OF run_id, scraped_at, format
    ON store_last_snapshot FOR EACH ROW EXECUTE FUNCTION store_format_run_track();
-- Solo si cambia el formato: la descarga vuelve a guardar cada tienda (ON CONFLICT … DO UPDATE) con el mismo store_type.
CREATE TRIGGER stores_format_changed AFTER UPDATE OF store_type, store_id ON stores
    FOR EACH ROW WHEN (COALESCE(OLD.store_type, 'id:' || OLD.store_id) IS DISTINCT FROM
                       COALESCE(NEW.store_type, 'id:' || NEW.store_id))
    EXECUTE FUNCTION store_format_run_store_changed();

ANALYZE store_last_snapshot;

-- La misma vista (mismas columnas, las mismas filas), ahora una sola tabla: cada tienda con precios, su formato y la
-- última corrida de ese formato.
CREATE OR REPLACE VIEW v_store_format_runs AS
SELECT store_id, format, format_run_id
FROM store_last_snapshot;
COMMENT ON VIEW v_store_format_runs IS 'Para cada tienda con precios, su formato (store_type, o la tienda misma sin formato) y la última corrida que bajó ese formato. Lee store_last_snapshot, que guarda las tres columnas: se puede buscar por store_id.';
