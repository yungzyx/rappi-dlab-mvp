-- Permisos del rol de la API. Los aplica `rappi-ia deploy-migrate` después de migrar, con DB_API_ROLE (en el stack,
-- rappi_api), conectado como el dueño de las tablas (rappi_owner). Idempotente: se repite en cada despliegue y alcanza
-- a las tablas que trajo la migración nueva.
-- {api_role} es el rol (lo pone deploy-migrate como identificador); una llave literal en este archivo va doble.

-- Primero se quita lo que sobre (de un despliegue anterior o puesto a mano): el rol queda con justo lo de abajo. Nadie
-- más que el dueño crea objetos en public (PostgreSQL 15+ ya lo trae así; se repite por si la base viene de antes).
REVOKE INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM {api_role};
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Leer: todo el catálogo, los conceptos y las vistas estables de la capa de datos.
GRANT USAGE ON SCHEMA public, capa TO {api_role};
GRANT SELECT ON ALL TABLES IN SCHEMA public, capa TO {api_role};

-- Escribir: solo los datos de las personas del prototipo (sesión, eventos y sus elementos vistos, sesiones de la app,
-- variantes de los experimentos, pedidos, preferencias y permiso para pedir con el agente, segmentos, afinidad por
-- vertical y recompra) y las definiciones de segmentos, que el recálculo después de un pedido vuelve a sembrar si
-- cambiaron las reglas. La lista está una sola vez: de ella salen el permiso de escribir y el de usar las secuencias
-- de esas tablas (p. ej. app_events.event_id), para poder insertar. Al sumar una tabla que escribe la API, va aquí
-- (el test de deploy-migrate lo revisa contra PERSON_TABLES de rappi_ia/delivery.py).
DO $$
DECLARE
    api_tables regclass[] := ARRAY[
        'app_users', 'app_events', 'app_event_items', 'app_sessions', 'experiment_assignments', 'app_orders',
        'app_order_lines', 'agent_preferences', 'agent_autonomy', 'user_segments', 'user_segment_history',
        'segment_defs', 'user_vertical_affinity', 'replenishment'
    ]::regclass[];
    tbl regclass;
    seq regclass;
BEGIN
    FOREACH tbl IN ARRAY api_tables LOOP
        EXECUTE format('GRANT INSERT, UPDATE, DELETE ON %s TO {api_role}', tbl);
    END LOOP;
    FOR seq IN
        SELECT d.objid::regclass FROM pg_depend d JOIN pg_class s ON s.oid = d.objid AND s.relkind = 'S'
        WHERE d.classid = 'pg_class'::regclass AND d.refclassid = 'pg_class'::regclass
          AND d.refobjid = ANY (api_tables)
    LOOP
        EXECUTE format('GRANT USAGE ON SEQUENCE %s TO {api_role}', seq);
    END LOOP;
END
$$;

-- Lo que el dueño cree más adelante (fuera de una migración) también se puede leer. El dueño es quien aplica este
-- archivo: rappi_owner en el servidor y el usuario del Mac en la demo desde un Mac (deploy/macos/rol-api.sh).
ALTER DEFAULT PRIVILEGES GRANT SELECT ON TABLES TO {api_role};
