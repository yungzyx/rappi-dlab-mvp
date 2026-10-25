-- Después del pedido (docs/investigacion/app-rappi-2026-10-25.md, fase 2): la calificación que la persona le pone a un
-- pedido entregado y la tienda de cada línea. Todo es aditivo y nulo en las filas de antes.
-- - La calificación (`rating`, `rating_reasons`, `rated_at`) la escribe el evento `order_rated` de la app (modo
--   propuesta): en el pedido de ese carro. Una calificación de 3 estrellas o menos pausa la recompra y el «¿Volvemos
--   a…?» de los conceptos y las tiendas de ese pedido (offers/winback.py: paused). En «Rappi hoy» el evento se guarda
--   en app_events, pero no escribe aquí: ese modo no enseña.
-- - Dos eventos nuevos: `order_rated` (la calificación) y `reorder` («Pídelo de nuevo» armó el carro con un pedido
--   anterior).
-- - La tienda de cada línea (`store_id`): la app ya la mandaba (el precio cambia entre tiendas) y no se guardaba. Con
--   ella la pausa sabe qué tienda salió mal.

ALTER TABLE app_orders
    ADD COLUMN rating smallint CHECK (rating BETWEEN 1 AND 5),
    ADD COLUMN rating_reasons text[],
    ADD COLUMN rated_at timestamptz;

COMMENT ON COLUMN app_orders.rating IS 'Estrellas (1 a 5) que la persona le puso al pedido entregado (evento order_rated, modo propuesta). Nula si no lo calificó. Con 3 o menos se pausan la recompra y el «volver» de sus conceptos y tiendas (offers/winback.py).';
COMMENT ON COLUMN app_orders.rating_reasons IS 'Lo que salió mal, según la persona, si calificó con 3 estrellas o menos («¿Qué problema tuvo el pedido?»): códigos de events/store.py (RATING_REASONS), como tarde o faltante.';
COMMENT ON COLUMN app_orders.rated_at IS 'Cuándo lo calificó (la hora del evento en la app, o la llegada si no la trae). La pausa por una calificación mala cuenta desde aquí.';

ALTER TABLE app_order_lines ADD COLUMN store_id bigint;

COMMENT ON COLUMN app_order_lines.store_id IS 'Tienda (o restaurante) de donde se agregó la línea: su precio es el de ahí. Nula en las líneas de antes de la migración 044 y en las simuladas.';

-- El CHECK de la 036 más `order_rated` y `reorder`.
ALTER TABLE app_events DROP CONSTRAINT app_events_type_check;
ALTER TABLE app_events ADD CONSTRAINT app_events_type_check CHECK (type IN (
    'app_open', 'search', 'chat', 'ask', 'view_store', 'view_item', 'cart_add', 'cart_remove', 'checkout_start',
    'order_placed', 'suggestion_shown', 'suggestion_accepted', 'suggestion_dismissed', 'recommendation_click',
    'service_shown', 'service_opened', 'vertical_open', 'order_rated', 'reorder'
));
COMMENT ON COLUMN app_events.type IS 'Qué pasó: abrir la app, buscar, preguntar al agente, ver, carro, pedido, sugerencias y servicios del agente, abrir un vertical, calificar un pedido (order_rated: estrellas y motivos en payload, el pedido en cart_id) y «Pídelo de nuevo» (reorder).';
