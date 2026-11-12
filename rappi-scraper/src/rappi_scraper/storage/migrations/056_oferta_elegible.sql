-- La parte expuesta del grupo de control de las ofertas (`ofertas_control`, docs/plan-piloto.md) se cuenta igual en los
-- dos grupos, con un hecho del servidor:
-- - `offer_eligible`: una oferta retenible de Mochi que la API entregó a alguien del grupo de tratamiento. La anota
--   POST /agent/offer con la misma regla que `offer_withheld` en control (los momentos que Mochi propone solo, fuera del
--   buscador, una vez por sesión, origen, concepto y vertical), y lleva lo que mostró en `app_event_items`. Antes, en
--   tratamiento solo quedaba la `suggestion_shown` de la app, que falta si la app no alcanzó a mostrarla.
-- - `capa.v_eventos_amplitude` lleva sus elementos (PRODUCT_ID_LIST, STORE_ID_LIST) como los de `offer_withheld`. Sale
--   como MVP_OFFER_ELIGIBLE, sin equivalente en Rappi (regla de la migración 051). Mismas columnas en el mismo orden.
-- Solo el CHECK, la vista y comentarios: no cambia ni borra datos.

-- El CHECK de la 053 más el tipo nuevo.
ALTER TABLE app_events DROP CONSTRAINT app_events_type_check;
ALTER TABLE app_events ADD CONSTRAINT app_events_type_check CHECK (type IN (
    'app_open', 'search', 'chat', 'ask', 'view_store', 'view_item', 'cart_add', 'cart_remove', 'checkout_start',
    'order_placed', 'suggestion_shown', 'suggestion_accepted', 'suggestion_dismissed', 'recommendation_click',
    'service_shown', 'service_opened', 'vertical_open', 'order_rated', 'reorder', 'list_view', 'offer_withheld',
    'order_cancelled', 'vertical_reorder_shown', 'agent_visibility', 'offer_why_open', 'offer_eligible'
));
COMMENT ON COLUMN app_events.type IS 'Qué pasó: abrir la app, buscar, preguntar al agente, ver, carro, pedido, sugerencias y servicios del agente (la mostrada lleva en payload.basis los tipos de su razón), abrir un vertical, calificar un pedido (order_rated), "Pídelo de nuevo" (reorder), lo que una lista dejó a la vista (list_view), una oferta retenida al grupo de control (offer_withheld) o la misma oferta entregada al grupo de tratamiento (offer_eligible: la anota la API con la misma regla, para contar la parte expuesta igual en los dos grupos), cancelar un pedido (order_cancelled: motivo, etapa y costo de ejemplo en payload; el pedido en cart_id y payload.store_id), Mochi explicó por qué movió los accesos de la Home (vertical_reorder_shown: el acceso en vertical, su lugar nuevo en position y el anterior en payload.antes), ocultar o volver a mostrar a Mochi (agent_visibility: payload.visible) y abrir el "¿Por qué?" de una oferta (offer_why_open: el origen de la oferta, el concepto de su razón y los tipos de su basis en payload.basis).';

COMMENT ON TABLE app_event_items IS 'Los elementos de un list_view (lo que quedó a la vista, cada uno con su lugar), de un offer_withheld (lo que la oferta retenida habría mostrado) o de un offer_eligible (lo que la misma oferta mostró en tratamiento). La lista, la pantalla y la respuesta de la API van en su evento (surface, origin, request_id). Datos de personas: está en PERSON_TABLES (rappi_ia/delivery.py), se va con su evento ("Olvidar" y la purga, en cascada) y la purga de rappi-ia (purge_old_impressions) la borra a los 90 días, como el texto de las consultas.';
COMMENT ON COLUMN app_event_items.event_id IS 'El evento list_view, offer_withheld u offer_eligible al que pertenece.';

CREATE OR REPLACE VIEW capa.v_eventos_amplitude AS
SELECT e.event_id, e.source,
       t.event_type,
       t.event_type NOT LIKE 'MVP\_%' AS equivalente,
       e.type AS evento_mvp,
       coalesce(e.client_event_id, md5('rappi-dlab:' || e.event_id)::uuid) AS uuid,
       e.seq AS sequence_number,
       e.session_id,
       (extract(epoch FROM s.started_at) * 1000)::bigint AS session_start_ms,
       (extract(epoch FROM coalesce(e.client_ts, e.ts)) * 1000)::bigint AS "timestamp",
       e.user_id,
       s.platform,
       s.app_version AS version_name,
       jsonb_strip_nulls(jsonb_build_object(
           'CONTEXT', e.surface,
           'SOURCE', e.origin,
           'COMPONENT_NAME', e.origin,
           'COMPONENT_INDEX', e.position,
           'VERTICAL', e.vertical,
           'STORE_ID', CASE WHEN e.entity_type = 'store' THEN e.entity_id ELSE e.payload ->> 'store_id' END,
           'PRODUCT_ID', CASE WHEN e.entity_type IN ('catalog_item', 'menu_item') THEN e.entity_id END,
           'REQUEST_ID', e.request_id,
           'CART_ID', e.cart_id,
           'PRODUCT_VALUE', CASE WHEN e.type IN ('view_item', 'cart_add', 'cart_remove') THEN e.value END,
           'TOTAL', CASE WHEN e.type = 'order_placed' THEN e.value END,
           'RESULTS', e.results,
           'PRICE', e.payload -> 'catalogo' -> 'precio',
           'OFFER_VALUE', e.payload -> 'catalogo' -> 'descuento_pct',
           'OPEN', e.payload -> 'catalogo' -> 'abierta',
           'PRODUCT_ID_LIST', it.products,
           'STORE_ID_LIST', it.stores,
           'LAST_POSITION_VIEWED', CASE WHEN e.type = 'list_view' THEN e.position END,
           'KIND', e.payload ->> 'kind',
           'VISIBLE', e.payload -> 'visible'
       )) AS event_properties,
       jsonb_strip_nulls(jsonb_build_object('EXPERIMENTS', s.variants, 'APP_MODE', s.mode)) AS user_properties
FROM app_events e
CROSS JOIN LATERAL (
    SELECT CASE e.type
               WHEN 'app_open' THEN 'APP_LAUNCH'
               WHEN 'search' THEN CASE WHEN e.unmet THEN 'LOCAL_SEARCH_NULL_RESULTS' ELSE 'LOCAL_SEARCH' END
               WHEN 'chat' THEN 'RECEIVE_MESSAGE_CHAT_V2'
               WHEN 'ask' THEN 'RECEIVE_MESSAGE_CHAT_V2'
               WHEN 'view_store' THEN 'VIEW_STORE'
               WHEN 'view_item' THEN 'VIEW_PRODUCT_DESCRIPTION'
               WHEN 'cart_add' THEN 'ADD_TO_CART'
               WHEN 'checkout_start' THEN 'PROCEED_TO_CHECKOUT'
               WHEN 'order_placed' THEN 'ORDER_PLACED_CONFIRMED_BACK'
               WHEN 'list_view' THEN 'VIEW_COMPONENT'
               WHEN 'suggestion_shown' THEN 'VIEW_COMPONENT'
               WHEN 'suggestion_accepted' THEN 'SELECT_PRODUCT'
               WHEN 'recommendation_click' THEN CASE WHEN e.entity_type = 'store' THEN 'SELECT_STORE'
                                                     ELSE 'SELECT_PRODUCT' END
               WHEN 'service_shown' THEN 'home_placement_content_view'
               WHEN 'service_opened' THEN 'home_placement_content_click'
               WHEN 'vertical_open' THEN 'SELECT_STORE_TYPE'
               WHEN 'order_rated' THEN 'RATE_STAR_TAP'
               ELSE 'MVP_' || upper(e.type)
           END AS event_type
) t
LEFT JOIN app_sessions s ON s.user_id = e.user_id AND s.session_id = e.session_id
LEFT JOIN LATERAL (
    SELECT array_agg(i.entity_id ORDER BY i.position) FILTER (WHERE i.entity_type IN ('catalog_item', 'menu_item'))
             AS products,
           array_agg(i.entity_id ORDER BY i.position) FILTER (WHERE i.entity_type = 'store') AS stores
    FROM app_event_items i
    WHERE i.event_id = e.event_id AND e.type IN ('list_view', 'offer_withheld', 'offer_eligible')
) it ON true;
