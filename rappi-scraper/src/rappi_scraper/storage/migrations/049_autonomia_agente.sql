-- «Pedir por mí»: cuánta autonomía le da cada persona a Mochi para pedir (pedido del usuario del 25-10-2026). El agente
-- de la app de Rappi ofrece «Revisar antes de enviar» o el pedido automático en todas o algunas tiendas
-- (docs/investigacion/app-rappi-2026-10-25.md); aquí es acotado (rappi_ia/offers/autonomy.py, docs/diseno-ia.md):
-- - Sin fila, «Revisar antes de pedir» (lo de siempre): Mochi arma el resumen y se paga en el checkout.
-- - Con fila, «Pedir por mí»: en las tiendas elegidas (de las que ya pidió) Mochi pide solo «lo de siempre» (los mismos
--   productos de su último pedido ahí, con precio vigente), hasta el tope por pedido, nunca alcohol, +18, Farmacia,
--   bebé ni salud (offers/guards.py), ni en una tienda cerrada o bajo su compra mínima. Si algo falla, revisa antes.
-- - Apagarlo borra la fila. La población de la fila es la de la persona (un trigger lo revisa): nunca se mezclan.
-- Es una tabla de personas: está en PERSON_TABLES (rappi_ia/delivery.py) y se borra con la persona («Olvidar» y la
-- purga de inactivas, en cascada).

CREATE TABLE agent_autonomy (
    user_id    text PRIMARY KEY REFERENCES app_users ON DELETE CASCADE,
    store_ids  bigint[] NOT NULL CHECK (cardinality(store_ids) BETWEEN 1 AND 10),
    max_total  integer NOT NULL CHECK (max_total BETWEEN 1000 AND 200000),
    source     text NOT NULL CHECK (source IN ('synthetic', 'prototype')),
    updated_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE agent_autonomy IS '«Pedir por mí»: las tiendas donde la persona deja que Mochi pida solo «lo de siempre» (su último pedido ahí) y el tope por pedido. Sin fila, «Revisar antes de pedir». Nunca alcohol, +18, Farmacia, bebé ni salud, ni en una tienda cerrada o bajo su compra mínima (rappi_ia/offers/autonomy.py). Datos de personas: está en PERSON_TABLES (rappi_ia/delivery.py) y se borra con la persona («Olvidar» y la purga de inactivas, en cascada).';
COMMENT ON COLUMN agent_autonomy.user_id IS 'Persona (id seudónimo).';
COMMENT ON COLUMN agent_autonomy.store_ids IS 'Las tiendas (stores.store_id) donde Mochi puede pedir solo: de 1 a 10, todas de las que la persona ya pidió y ninguna de Farmacia o Licores.';
COMMENT ON COLUMN agent_autonomy.max_total IS 'Tope por pedido en pesos chilenos, que elige la persona: Mochi nunca pide solo por encima: la API lo revisa con los productos a precio del catálogo, y la app con el total del resumen (con envío y servicio).';
COMMENT ON COLUMN agent_autonomy.source IS 'Población: synthetic (generador con semilla) o prototype, la misma de la persona (trigger agent_autonomy_source). Nunca se mezclan.';
COMMENT ON COLUMN agent_autonomy.updated_at IS 'Cuándo la persona lo encendió o cambió por última vez.';

-- La población de la fila es la de la persona: un permiso del prototipo nunca queda colgado de alguien simulado.
CREATE FUNCTION agent_autonomy_source_check() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM app_users WHERE user_id = NEW.user_id AND source = NEW.source) THEN
        RAISE EXCEPTION 'agent_autonomy: la población (%) no es la de la persona %', NEW.source, NEW.user_id;
    END IF;
    RETURN NEW;
END
$$;
COMMENT ON FUNCTION agent_autonomy_source_check() IS 'Revisa que la población de una fila de agent_autonomy sea la de su persona (app_users.source).';

CREATE TRIGGER agent_autonomy_source BEFORE INSERT OR UPDATE ON agent_autonomy
    FOR EACH ROW EXECUTE FUNCTION agent_autonomy_source_check();
