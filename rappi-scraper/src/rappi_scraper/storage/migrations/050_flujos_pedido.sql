-- Flujos del pedido que faltaban (docs/investigacion/app-rappi-2026-10-25.md, fase 8): cancelar, programar y la
-- preferencia de sustitución. Todo es aditivo; las filas de antes quedan confirmadas, sin programar y sin preferencia.
-- - El estado del pedido (`status`, `cancelled_at`, `cancel_reason`) lo escribe el evento `order_cancelled` de la app,
--   en los dos modos: es lo que pasó con el pedido, no algo que se aprende. En `propuesta`, un pedido cancelado no
--   cuenta para la recompra, el «volver», el motor ni los segmentos (todos leen `status = 'confirmado'`).
-- - Programar (`scheduled_for`) y el tipo de entrega (`delivery_type`) los manda la app en POST /orders. Un pedido que
--   Mochi hace solo («Pedir por mí») nunca se programa: la API lo rechaza.
-- - La preferencia de sustitución (`substitution`) es por línea, la que la persona eligió en el checkout de Súper o
--   Turbo para si el producto se agota.

ALTER TABLE app_orders
    ADD COLUMN status text NOT NULL DEFAULT 'confirmado' CHECK (status IN ('confirmado', 'cancelado')),
    ADD COLUMN cancelled_at timestamptz,
    ADD COLUMN cancel_reason text,
    ADD COLUMN scheduled_for timestamptz,
    ADD COLUMN delivery_type text CHECK (delivery_type IN ('basica', 'sin_prisa', 'prioritaria'));

COMMENT ON COLUMN app_orders.status IS 'Estado del pedido: confirmado (el de siempre) o cancelado (evento order_cancelled de la app, en los dos modos). Un pedido cancelado no cuenta para la recompra, el «volver», el motor ni los segmentos.';
COMMENT ON COLUMN app_orders.cancelled_at IS 'Cuándo lo canceló la persona (la hora del evento en la app, o la llegada si no la trae). Nula si no se canceló.';
COMMENT ON COLUMN app_orders.cancel_reason IS 'Por qué lo canceló, según la persona: códigos de events/store.py (CANCEL_REASONS), como demora o ya_no. Nula si no se canceló.';
COMMENT ON COLUMN app_orders.scheduled_for IS 'Inicio de la franja de una hora para la que se programó el pedido (hoy o mañana). Nula si se pidió para ahora.';
COMMENT ON COLUMN app_orders.delivery_type IS 'Tipo de entrega elegido en el checkout: basica, sin_prisa o prioritaria (sus montos son supuestos de la demo, no tarifas de Rappi). Nulo en un retiro en tienda, en un pedido de Mochi y en los de antes de la migración 050.';

ALTER TABLE app_order_lines
    ADD COLUMN substitution text CHECK (substitution IN ('sustituto', 'elijan', 'reembolso'));

COMMENT ON COLUMN app_order_lines.substitution IS 'Qué hacer si el producto se agota, elegido en el checkout de Súper o Turbo: sustituto (uno del mismo concepto en la misma tienda), elijan («Si no contesto, elijan por mí») o reembolso. Nula en las demás verticales y en las líneas de antes.';

-- El CHECK de la 047 más `order_cancelled`.
ALTER TABLE app_events DROP CONSTRAINT app_events_type_check;
ALTER TABLE app_events ADD CONSTRAINT app_events_type_check CHECK (type IN (
    'app_open', 'search', 'chat', 'ask', 'view_store', 'view_item', 'cart_add', 'cart_remove', 'checkout_start',
    'order_placed', 'suggestion_shown', 'suggestion_accepted', 'suggestion_dismissed', 'recommendation_click',
    'service_shown', 'service_opened', 'vertical_open', 'order_rated', 'reorder', 'list_view', 'offer_withheld',
    'order_cancelled'
));
COMMENT ON COLUMN app_events.type IS 'Qué pasó: abrir la app, buscar, preguntar al agente, ver, carro, pedido, sugerencias y servicios del agente, abrir un vertical, calificar un pedido (order_rated), «Pídelo de nuevo» (reorder), lo que una lista dejó a la vista (list_view), una oferta retenida al grupo de control (offer_withheld) y cancelar un pedido (order_cancelled: motivo, etapa y costo de ejemplo en payload; el pedido en cart_id y payload.store_id).';
