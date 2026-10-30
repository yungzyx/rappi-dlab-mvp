-- Dos eventos nuevos de la app (prototipo final), para que el panel pueda contarlos más adelante:
-- - `vertical_reorder_shown`: Mochi movió los accesos de la Home y explicó por qué (el acceso que más subió en
--   `vertical`, su lugar nuevo en `position`, el de antes en `payload.antes` y la respuesta de
--   GET /profile/{id}/verticales que los ordenó en `request_id`). No enseña al motor: la afinidad solo lee los tipos de
--   motor/data.py (EVENT_KINDS).
-- - `agent_visibility`: la persona ocultó a Mochi (`payload.visible` false) o lo trajo de vuelta en Cuenta (true).
-- Solo el CHECK y su comentario: no cambia ni borra datos. En capa.v_eventos_amplitude salen como MVP_ (sin equivalente
-- en el plan de Rappi), por la regla de la migración 051.

-- El CHECK de la 050 más los dos tipos nuevos.
ALTER TABLE app_events DROP CONSTRAINT app_events_type_check;
ALTER TABLE app_events ADD CONSTRAINT app_events_type_check CHECK (type IN (
    'app_open', 'search', 'chat', 'ask', 'view_store', 'view_item', 'cart_add', 'cart_remove', 'checkout_start',
    'order_placed', 'suggestion_shown', 'suggestion_accepted', 'suggestion_dismissed', 'recommendation_click',
    'service_shown', 'service_opened', 'vertical_open', 'order_rated', 'reorder', 'list_view', 'offer_withheld',
    'order_cancelled', 'vertical_reorder_shown', 'agent_visibility'
));
COMMENT ON COLUMN app_events.type IS 'Qué pasó: abrir la app, buscar, preguntar al agente, ver, carro, pedido, sugerencias y servicios del agente, abrir un vertical, calificar un pedido (order_rated), «Pídelo de nuevo» (reorder), lo que una lista dejó a la vista (list_view), una oferta retenida al grupo de control (offer_withheld), cancelar un pedido (order_cancelled: motivo, etapa y costo de ejemplo en payload; el pedido en cart_id y payload.store_id), Mochi explicó por qué movió los accesos de la Home (vertical_reorder_shown: el acceso en vertical, su lugar nuevo en position y el anterior en payload.antes) y ocultar o volver a mostrar a Mochi (agent_visibility: payload.visible).';
