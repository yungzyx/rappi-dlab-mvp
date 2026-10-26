-- Impresiones y experimentos (docs/investigacion/app-rappi-2026-10-25.md, fase 6; docs/capa-de-datos.md). Todo es
-- aditivo y nulo en las filas de antes.
-- - Impresiones de listas: el evento `list_view` (lo que una lista dejó a la vista, como VIEW_COMPONENT y
--   VIEW_PRODUCT_IMPRESSIONS en la app de Rappi) y sus elementos, uno por fila, en `app_event_items` con su posición. Sin
--   esto no hay CTR por posición ni forma de corregir el sesgo de posición del orden de la Home o de la búsqueda.
-- - Experimentos: `experiments` declara cada uno con sus variantes y cómo se asigna; `experiment_assignments` guarda la
--   variante de cada persona, estable (se asigna una vez). El primero es `modo_app` (propuesta o actual), que hasta aquí
--   vivía como texto en `payload.mode`; el segundo, el grupo de control de las ofertas de Mochi (`ofertas_control`), cuya
--   oferta retenida queda como impresión contrafactual: el evento `offer_withheld`.
-- - El eco: cada sesión guarda las variantes de su persona al empezar (`app_sessions.variants`).

-- El CHECK de la 044 más `list_view` y `offer_withheld`.
ALTER TABLE app_events DROP CONSTRAINT app_events_type_check;
ALTER TABLE app_events ADD CONSTRAINT app_events_type_check CHECK (type IN (
    'app_open', 'search', 'chat', 'ask', 'view_store', 'view_item', 'cart_add', 'cart_remove', 'checkout_start',
    'order_placed', 'suggestion_shown', 'suggestion_accepted', 'suggestion_dismissed', 'recommendation_click',
    'service_shown', 'service_opened', 'vertical_open', 'order_rated', 'reorder', 'list_view', 'offer_withheld'
));
COMMENT ON COLUMN app_events.type IS 'Qué pasó: abrir la app, buscar, preguntar al agente, ver, carro, pedido, sugerencias y servicios del agente, abrir un vertical, calificar un pedido (order_rated), «Pídelo de nuevo» (reorder), lo que una lista dejó a la vista (list_view: sus elementos en app_event_items) y una oferta de Mochi retenida al grupo de control (offer_withheld: lo que habría mostrado, en app_event_items).';
COMMENT ON COLUMN app_events.position IS 'Lugar en la lista que devolvió la API o que muestra la pantalla (0 = el primero). Equivale a COMPONENT_INDEX o INDEX en Rappi. En list_view es la mayor posición vista de esa lista hasta ese evento (LAST_POSITION_VIEWED en Rappi).';

CREATE TABLE app_event_items (
    event_id    bigint NOT NULL REFERENCES app_events ON DELETE CASCADE,
    position    smallint NOT NULL CHECK (position BETWEEN 0 AND 999),
    entity_type text NOT NULL CHECK (entity_type IN ('catalog_item', 'menu_item', 'store', 'vertical')),
    entity_id   text NOT NULL CHECK (length(entity_id) BETWEEN 1 AND 64),
    concept_id  text REFERENCES concepts ON DELETE SET NULL,
    vertical    text,
    PRIMARY KEY (event_id, position)
);

COMMENT ON TABLE app_event_items IS 'Los elementos de un list_view (lo que quedó a la vista, cada uno con su lugar) o de un offer_withheld (lo que la oferta retenida habría mostrado). La lista, la pantalla y la respuesta de la API van en su evento (surface, origin, request_id). Datos de personas: está en PERSON_TABLES (rappi_ia/delivery.py), se va con su evento («Olvidar» y la purga, en cascada) y la purga de rappi-ia (purge_old_impressions) la borra a los 90 días, como el texto de las consultas.';
COMMENT ON COLUMN app_event_items.event_id IS 'El evento list_view u offer_withheld al que pertenece.';
COMMENT ON COLUMN app_event_items.position IS 'Su lugar en la lista (0 = el primero), el mismo que lleva el clic o el carro que salga de él.';
COMMENT ON COLUMN app_event_items.entity_type IS 'Qué es: catalog_item (producto), menu_item (plato), store (tienda o restaurante) o vertical (un acceso de la Home).';
COMMENT ON COLUMN app_event_items.entity_id IS 'Su id: el del producto, el plato o la tienda, o el código del vertical.';
COMMENT ON COLUMN app_event_items.concept_id IS 'Concepto del producto o plato, si se sabe. Nulo en «Rappi hoy» (ese modo no enseña), igual que en sus eventos.';
COMMENT ON COLUMN app_event_items.vertical IS 'Vertical del elemento (código del catálogo).';

CREATE TABLE experiments (
    experiment_id text PRIMARY KEY CHECK (experiment_id ~ '^[a-z0-9_]{1,40}$'),
    description   text NOT NULL,
    variants      text[] NOT NULL CHECK (cardinality(variants) >= 2),
    assignment    text NOT NULL CHECK (assignment IN ('azar', 'elegida')),
    started_at    timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE experiments IS 'Los experimentos del MVP, declarados: qué comparan, sus variantes y cómo se asigna cada persona. Equivale a las configuraciones de Statsig de la app de Rappi. No es una tabla de personas.';
COMMENT ON COLUMN experiments.experiment_id IS 'Id del experimento (modo_app, ofertas_control).';
COMMENT ON COLUMN experiments.description IS 'Qué compara y cómo leerlo, en español.';
COMMENT ON COLUMN experiments.variants IS 'Sus variantes. La primera es la de siempre.';
COMMENT ON COLUMN experiments.assignment IS 'azar: la persona cae en una variante por un sorteo estable (un hash de su id), así que comparar variantes mide un efecto; elegida: la variante la elige alguien (quien presenta la demo), así que comparar variantes describe, no mide un efecto.';
COMMENT ON COLUMN experiments.started_at IS 'Desde cuándo existe.';

INSERT INTO experiments (experiment_id, description, variants, assignment) VALUES
    ('modo_app',
     'El modo de la app: propuesta (el prototipo con Mochi) o actual («Rappi hoy», la réplica de la app de hoy). La variante de cada persona es el modo de su primera sesión; el de cada sesión está en app_sessions.mode. No es al azar: lo elige quien presenta la demo (fuera de una demo la app siempre es propuesta), así que sus diferencias no son un efecto.',
     ARRAY['propuesta', 'actual'], 'elegida'),
    ('ofertas_control',
     'Grupo de control de las ofertas de Mochi (POST /agent/offer): a la variante control no se le muestran las que Mochi propone solo (no las que la persona pide: plan y perfil). Cada oferta retenida queda como impresión contrafactual (offer_withheld) con lo que habría mostrado. La parte en control la fija OFFERS_CONTROL_PCT; en 0 (lo de siempre) nadie entra y nada se retiene.',
     ARRAY['tratamiento', 'control'], 'azar');

CREATE TABLE experiment_assignments (
    user_id       text NOT NULL REFERENCES app_users ON DELETE CASCADE,
    experiment_id text NOT NULL REFERENCES experiments,
    variant       text NOT NULL,
    assigned_at   timestamptz NOT NULL DEFAULT now(),
    source        text NOT NULL CHECK (source IN ('synthetic', 'prototype')),
    PRIMARY KEY (user_id, experiment_id)
);
CREATE INDEX experiment_assignments_experiment_idx ON experiment_assignments (experiment_id, source, variant);

COMMENT ON TABLE experiment_assignments IS 'La variante de cada persona en cada experimento: se asigna una vez (en POST /session o la primera vez que hace falta) y no cambia. Datos de personas: está en PERSON_TABLES (rappi_ia/delivery.py) y se borra con la persona («Olvidar» y la purga de inactivas, en cascada).';
COMMENT ON COLUMN experiment_assignments.user_id IS 'Persona (id seudónimo).';
COMMENT ON COLUMN experiment_assignments.experiment_id IS 'El experimento (experiments).';
COMMENT ON COLUMN experiment_assignments.variant IS 'Su variante: una de experiments.variants.';
COMMENT ON COLUMN experiment_assignments.assigned_at IS 'Cuándo se le asignó.';
COMMENT ON COLUMN experiment_assignments.source IS 'Población de la persona: synthetic o prototype, la misma de app_users. Una comparación entre variantes se hace dentro de una sola: nunca se mezclan.';

-- La variante tiene que ser del experimento y la población, la de la persona: un CHECK no puede mirar otras tablas.
CREATE FUNCTION experiment_assignment_check() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM experiments e WHERE e.experiment_id = NEW.experiment_id AND NEW.variant = ANY(e.variants)) THEN
        RAISE EXCEPTION 'Variante % desconocida en el experimento %', NEW.variant, NEW.experiment_id;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM app_users u WHERE u.user_id = NEW.user_id AND u.source = NEW.source) THEN
        RAISE EXCEPTION 'La población de la asignación no es la de la persona %', NEW.user_id;
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER experiment_assignments_check BEFORE INSERT OR UPDATE ON experiment_assignments
    FOR EACH ROW EXECUTE FUNCTION experiment_assignment_check();

ALTER TABLE app_sessions ADD COLUMN variants jsonb;
COMMENT ON COLUMN app_sessions.variants IS 'Las variantes de la persona en los experimentos al empezar la sesión ({"modo_app": "propuesta", "ofertas_control": "control"}): el eco del experimento junto a sus eventos. Nula en las sesiones de antes de la migración 047.';
