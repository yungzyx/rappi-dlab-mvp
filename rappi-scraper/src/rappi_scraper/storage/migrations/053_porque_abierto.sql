-- Un evento nuevo de la app, para la prueba con usuarios (docs/prueba-usuarios.md):
-- - `offer_why_open`: la persona abrió el "¿Por qué?" de una oferta de Mochi. Lleva el origen de la oferta
--   (`agent-<momento>` o `para-ti`), el concepto de su razón en `concept_id` (si tiene) y los tipos de su `basis` en
--   `payload.basis` (`recompra`, `busqueda`, `perfil`…). Solo los tipos: el texto de la razón puede traer lo que la
--   persona escribió, y el payload no pasa por la redacción ni la purga de las consultas. No enseña al motor.
-- La mostrada (`suggestion_shown`) suma los mismos tipos en `payload.basis`: es payload libre, sin cambio de esquema.
-- Solo el CHECK y su comentario: no cambia ni borra datos. En capa.v_eventos_amplitude sale como MVP_ (sin equivalente
-- en el plan de Rappi), por la regla de la migración 051.

-- El CHECK de la 052 más el tipo nuevo.
ALTER TABLE app_events DROP CONSTRAINT app_events_type_check;
ALTER TABLE app_events ADD CONSTRAINT app_events_type_check CHECK (type IN (
    'app_open', 'search', 'chat', 'ask', 'view_store', 'view_item', 'cart_add', 'cart_remove', 'checkout_start',
    'order_placed', 'suggestion_shown', 'suggestion_accepted', 'suggestion_dismissed', 'recommendation_click',
    'service_shown', 'service_opened', 'vertical_open', 'order_rated', 'reorder', 'list_view', 'offer_withheld',
    'order_cancelled', 'vertical_reorder_shown', 'agent_visibility', 'offer_why_open'
));
COMMENT ON COLUMN app_events.type IS 'Qué pasó: abrir la app, buscar, preguntar al agente, ver, carro, pedido, sugerencias y servicios del agente (la mostrada lleva en payload.basis los tipos de su razón), abrir un vertical, calificar un pedido (order_rated), "Pídelo de nuevo" (reorder), lo que una lista dejó a la vista (list_view), una oferta retenida al grupo de control (offer_withheld), cancelar un pedido (order_cancelled: motivo, etapa y costo de ejemplo en payload; el pedido en cart_id y payload.store_id), Mochi explicó por qué movió los accesos de la Home (vertical_reorder_shown: el acceso en vertical, su lugar nuevo en position y el anterior en payload.antes), ocultar o volver a mostrar a Mochi (agent_visibility: payload.visible) y abrir el "¿Por qué?" de una oferta (offer_why_open: el origen de la oferta, el concepto de su razón y los tipos de su basis en payload.basis).';
