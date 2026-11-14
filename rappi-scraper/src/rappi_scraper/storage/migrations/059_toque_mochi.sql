-- Tocar a Mochi deja evento: `agent_open`, una vez por apertura de su menú (la mascota en la Home, `surface` 'home' y
-- `origin` 'mascota-home', o Mochi flotante, `surface` 'agent' y `origin` 'mascota-flotante'). Antes, abrirlo no dejaba
-- nada y la adopción ("usó a Mochi", analytics/queries.py: _USED_AGENT) solo contaba a quien buscaba con él o aceptaba
-- una oferta suya. Sin payload. No enseña al motor (motor/data.py: EVENT_KINDS) y vive en `app_events`: "Borrar mis
-- datos" y la purga se lo llevan con la persona. En capa.v_eventos_amplitude sale como MVP_AGENT_OPEN (sin equivalente
-- en el plan de Rappi), por la regla de la migración 051, con CONTEXT y SOURCE.
-- Solo el CHECK y su comentario: no cambia ni borra datos.

-- El CHECK de la 057 más el tipo nuevo.
ALTER TABLE app_events DROP CONSTRAINT app_events_type_check;
ALTER TABLE app_events ADD CONSTRAINT app_events_type_check CHECK (type IN (
    'app_open', 'search', 'chat', 'ask', 'view_store', 'view_item', 'cart_add', 'cart_remove', 'checkout_start',
    'order_placed', 'suggestion_shown', 'suggestion_accepted', 'suggestion_dismissed', 'recommendation_click',
    'service_shown', 'service_opened', 'vertical_open', 'order_rated', 'reorder', 'list_view', 'offer_withheld',
    'order_cancelled', 'vertical_reorder_shown', 'agent_visibility', 'offer_why_open', 'offer_eligible',
    'survey_shown', 'survey_answer', 'survey_dismissed', 'agent_open'
));
COMMENT ON COLUMN app_events.type IS 'Qué pasó: abrir la app, buscar, preguntar al agente, ver, carro, pedido, sugerencias y servicios del agente (la mostrada lleva en payload.basis los tipos de su razón), abrir un vertical, calificar un pedido (order_rated), "Pídelo de nuevo" (reorder), lo que una lista dejó a la vista (list_view), una oferta retenida al grupo de control (offer_withheld) o la misma oferta entregada al grupo de tratamiento (offer_eligible: la anota la API con la misma regla, para contar la parte expuesta igual en los dos grupos), cancelar un pedido (order_cancelled: motivo, etapa y costo de ejemplo en payload; el pedido en cart_id y payload.store_id), Mochi explicó por qué movió los accesos de la Home (vertical_reorder_shown: el acceso en vertical, su lugar nuevo en position y el anterior en payload.antes), ocultar o volver a mostrar a Mochi (agent_visibility: payload.visible), abrir el "¿Por qué?" de una oferta (offer_why_open: el origen de la oferta, el concepto de su razón y los tipos de su basis en payload.basis) y la pregunta in-app de la H3 (survey_shown, survey_answer y survey_dismissed: payload.question p1 o p3, payload.trigger, payload.answer en la respuesta; la búsqueda en request_id), y abrir el menú de Mochi tocando la mascota (agent_open: en la Home, surface home, o Mochi flotante, surface agent; origin dice cuál).';
