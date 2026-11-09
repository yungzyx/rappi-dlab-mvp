-- `capa.v_eventos_amplitude` lleva dos datos del payload que antes perdía (pendiente anotado en #90):
-- - `KIND` (`payload.kind`): separa un `suggestion_dismissed` con kind "expirada" (la oferta se fue sola del globo de la
--   Home, events/store.py:EXPIRED_KIND) de un rechazo, y el "Después" de "¿Volvemos a…?" (kind "volver" o "vuelta").
--   El panel, el resumen y winback ya los separan; sin esto, quien leyera la vista contaba la expirada como rechazo.
--   KIND sale en todo evento que traiga payload.kind: también en la mostrada (`suggestion_shown`, VIEW_COMPONENT), con
--   "lo_mas_pedido" o con "volver"/"vuelta" en la invitación de "¿Volvemos a…?". Para contar los "Después" hay que
--   filtrar también por event_type (MVP_SUGGESTION_DISMISSED).
-- - `VISIBLE` (`payload.visible`): si un `agent_visibility` ocultó a Mochi (false) o lo trajo de vuelta (true). El false
--   de jsonb no es nulo, así que jsonb_strip_nulls lo conserva.
-- No hay un event_type nuevo: siguen como MVP_SUGGESTION_DISMISSED y MVP_AGENT_VISIBILITY. Mismas columnas en el mismo
-- orden (CREATE OR REPLACE conserva los GRANT y los comentarios de columna). Solo la vista y un comentario: no cambia
-- ni borra datos.

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
    WHERE i.event_id = e.event_id AND e.type IN ('list_view', 'offer_withheld')
) it ON true;

COMMENT ON COLUMN capa.v_eventos_amplitude.event_properties IS 'Propiedades con los nombres de Rappi, en mayúsculas (sin las nulas): CONTEXT (surface), SOURCE y COMPONENT_NAME (origin), COMPONENT_INDEX (position), VERTICAL, STORE_ID, PRODUCT_ID, REQUEST_ID, CART_ID, PRODUCT_VALUE, TOTAL, RESULTS, PRICE, OFFER_VALUE y OPEN (el catálogo fijado al registrar, payload.catalogo), PRODUCT_ID_LIST y STORE_ID_LIST (lo que la lista dejó a la vista), LAST_POSITION_VIEWED, KIND (payload.kind, en todo evento que lo traiga: en MVP_SUGGESTION_DISMISSED, "expirada" si la oferta se fue sola, que no es un rechazo, o "volver"/"vuelta" en el "Después" de "¿Volvemos a…?", y sin KIND en un rechazo; en VIEW_COMPONENT de una suggestion_shown, "lo_mas_pedido" o "volver"/"vuelta" en la invitación mostrada. Para contar los "Después" hay que filtrar también por event_type) y VISIBLE (payload.visible de agent_visibility: false al ocultar a Mochi, true al traerlo de vuelta).';
