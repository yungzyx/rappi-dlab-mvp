-- Capa 3 (rappi-ia): usuarios, eventos y pedidos de la app. Hoy solo con datos SIMULADOS (`synthetic`) o del
-- prototipo (`prototype`): nunca se mezclan con datos reales. Ids de usuario seudónimos.

CREATE TABLE app_users (
    user_id               text PRIMARY KEY,
    source                text NOT NULL CHECK (source IN ('synthetic', 'prototype')),
    segment               text,         -- persona del generador simulado
    city                  text,
    consent_notifications boolean NOT NULL DEFAULT false,  -- avisos y reactivación solo con consentimiento
    created_at            timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app_events (
    event_id    bigserial PRIMARY KEY,
    user_id     text NOT NULL REFERENCES app_users ON DELETE CASCADE,
    session_id  text NOT NULL,          -- una sesión termina tras 30 min sin actividad
    ts          timestamptz NOT NULL DEFAULT now(),
    type        text NOT NULL CHECK (type IN (
                    'app_open', 'search', 'chat', 'view_store', 'view_item',
                    'cart_add', 'cart_remove', 'checkout_start', 'order_placed',
                    'suggestion_shown', 'suggestion_accepted', 'suggestion_dismissed', 'recommendation_click')),
    vertical    text,
    concept_id  text REFERENCES concepts ON DELETE SET NULL,
    entity_type text CHECK (entity_type IN ('catalog_item', 'menu_item', 'store')),
    entity_id   text,
    cart_id     text,                   -- eventos de carro
    query       text,                   -- con datos personales redactados; se borra a los 90 días
    modality    text CHECK (modality IN ('texto', 'voz', 'foto')),
    results     integer,
    unmet       boolean,                -- búsqueda/consulta sin resultado (demanda no satisfecha)
    value       numeric,                -- monto (pedidos) o precio del ítem
    payload     jsonb NOT NULL DEFAULT '{}',
    source      text NOT NULL CHECK (source IN ('synthetic', 'prototype'))
);
CREATE INDEX app_events_user_ts_idx ON app_events (user_id, ts);
CREATE INDEX app_events_type_ts_idx ON app_events (type, ts);
CREATE INDEX app_events_concept_idx ON app_events (concept_id, ts) WHERE concept_id IS NOT NULL;
CREATE INDEX app_events_unmet_idx ON app_events (ts) WHERE unmet;

-- Un pedido es de una tienda (un vertical). Las líneas apuntan a un producto o a un plato.
CREATE TABLE app_orders (
    order_id   text PRIMARY KEY,
    user_id    text NOT NULL REFERENCES app_users ON DELETE CASCADE,
    session_id text,
    cart_id    text,
    ts         timestamptz NOT NULL,
    vertical   text NOT NULL,
    total      numeric NOT NULL,
    source     text NOT NULL CHECK (source IN ('synthetic', 'prototype'))
);
CREATE INDEX app_orders_user_ts_idx ON app_orders (user_id, ts);

CREATE TABLE app_order_lines (
    order_id        text NOT NULL REFERENCES app_orders ON DELETE CASCADE,
    line_no         integer NOT NULL,
    entity_type     text NOT NULL CHECK (entity_type IN ('catalog_item', 'menu_item')),
    entity_id       text NOT NULL,
    concept_id      text REFERENCES concepts ON DELETE SET NULL,
    qty             integer NOT NULL DEFAULT 1,
    unit_price      numeric,
    from_suggestion boolean NOT NULL DEFAULT false,  -- agregado desde una sugerencia de Bigotes
    PRIMARY KEY (order_id, line_no)
);

-- Productos que cruzan verticales contando solo tiendas de UN vertical (sin la doble etiqueta de Lider/Unimarc).
CREATE VIEW v_cross_vertical_items_real AS
WITH single_vertical_stores AS (
    SELECT store_id, min(vertical) AS vertical FROM v_store_verticals GROUP BY store_id HAVING count(*) = 1
)
SELECT sp.master_product_id, array_agg(DISTINCT s.vertical ORDER BY s.vertical) AS verticales,
       count(DISTINCT s.vertical) AS n_verticales
FROM store_products sp
JOIN single_vertical_stores s USING (store_id)
WHERE sp.master_product_id IS NOT NULL
GROUP BY sp.master_product_id
HAVING count(DISTINCT s.vertical) > 1;
