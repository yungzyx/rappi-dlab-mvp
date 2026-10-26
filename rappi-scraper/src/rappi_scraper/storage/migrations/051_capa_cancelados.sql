-- Lo que quedó de la revisión del backend (26-10-2026) en la base: un pedido cancelado (migración 050) deja de contar
-- también en las vistas de `capa`, y las reglas de población de 047 y 049 alcanzan a `agent_preferences`.
-- - `capa.v_embudo_sesion`: `pedido`, `pedidos` y `monto_pedidos` no cuentan el `order_placed` de un pedido cancelado
--   (el evento queda, pero el pedido no ocurrió). El panel lo lee en /analytics/embudo-sesion.
-- - `capa.v_eventos_amplitude`: `equivalente` sale del nombre (false si lleva el prefijo MVP_), así un evento nuevo
--   sin equivalente en Rappi, como `order_cancelled`, ya no queda marcado como equivalente.
-- - `agent_preferences` revisa que su población sea la de la persona, como `experiment_assignments` (047) y
--   `agent_autonomy` (049), y la función de la 047 recibe su comentario.
-- Solo vistas, un trigger y comentarios: no cambia ni borra datos.

CREATE OR REPLACE VIEW capa.v_embudo_sesion AS
SELECT e.source, e.user_id, e.session_id,
       coalesce(s.started_at, min(e.ts)) AS inicio,
       coalesce(s.mode, CASE WHEN bool_or(coalesce(e.payload ->> 'mode', '') = 'actual') THEN 'actual'
                             ELSE 'propuesta' END) AS modo,
       s.variants AS variantes,
       bool_or(e.type IN ('list_view', 'suggestion_shown') OR (e.type = 'search' AND e.results > 0)) AS vio,
       bool_or(e.type IN ('view_store', 'view_item', 'recommendation_click', 'vertical_open', 'suggestion_accepted',
                          'service_opened', 'cart_add')) AS clic,
       bool_or(e.type = 'cart_add') AS carro,
       bool_or(e.type = 'checkout_start') AS pago,
       bool_or(e.type = 'order_placed' AND o.status IS DISTINCT FROM 'cancelado') AS pedido,
       count(*) FILTER (WHERE e.type = 'order_placed' AND o.status IS DISTINCT FROM 'cancelado') AS pedidos,
       coalesce(sum(e.value) FILTER (WHERE e.type = 'order_placed' AND o.status IS DISTINCT FROM 'cancelado'), 0)
           AS monto_pedidos
FROM app_events e
LEFT JOIN app_sessions s ON s.user_id = e.user_id AND s.session_id = e.session_id
-- El pedido de un order_placed (payload.order_id, que pone POST /orders). Los simulados no lo traen y cuentan.
LEFT JOIN app_orders o ON e.type = 'order_placed' AND o.order_id = e.payload ->> 'order_id'
GROUP BY e.source, e.user_id, e.session_id, s.started_at, s.mode, s.variants;

COMMENT ON COLUMN capa.v_embudo_sesion.pedido IS 'Pidió (order_placed, que solo crea el servidor), sin contar un pedido que después se canceló (app_orders.status, migración 050).';
COMMENT ON COLUMN capa.v_embudo_sesion.pedidos IS 'Cuántos pedidos (un carro de dos tiendas son dos), sin los cancelados.';
COMMENT ON COLUMN capa.v_embudo_sesion.monto_pedidos IS 'La suma de sus pedidos, en pesos (con el precio del catálogo que puso la API), sin los cancelados.';

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
           'LAST_POSITION_VIEWED', CASE WHEN e.type = 'list_view' THEN e.position END
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

COMMENT ON COLUMN capa.v_eventos_amplitude.equivalente IS 'Si el evento tiene equivalente en el plan de Rappi: false en los que llevan el prefijo MVP_ (MVP_CART_REMOVE, MVP_SUGGESTION_DISMISSED, MVP_REORDER, MVP_OFFER_WITHHELD y MVP_ORDER_CANCELLED). Sale del nombre: un evento nuevo sin traducción queda en false solo.';

COMMENT ON FUNCTION experiment_assignment_check() IS 'Revisa que la variante de una fila de experiment_assignments sea de su experimento y que su población sea la de su persona (app_users.source).';

-- La población de la fila es la de la persona, como en agent_autonomy (049): una preferencia del prototipo nunca queda
-- colgada de alguien simulado.
CREATE FUNCTION agent_preferences_source_check() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM app_users WHERE user_id = NEW.user_id AND source = NEW.source) THEN
        RAISE EXCEPTION 'agent_preferences: la población (%) no es la de la persona %', NEW.source, NEW.user_id;
    END IF;
    RETURN NEW;
END
$$;
COMMENT ON FUNCTION agent_preferences_source_check() IS 'Revisa que la población de una fila de agent_preferences sea la de su persona (app_users.source).';

CREATE TRIGGER agent_preferences_source BEFORE INSERT OR UPDATE ON agent_preferences
    FOR EACH ROW EXECUTE FUNCTION agent_preferences_source_check();
