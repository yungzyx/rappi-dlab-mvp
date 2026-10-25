-- Señales derivadas de los eventos, en el esquema `capa` (docs/capa-de-datos.md#eventos-de-la-app-y-su-sobre): carros
-- abandonados, el embudo de cada sesión, el CTR por posición y superficie, y el puente con el plan de tracking de la app
-- de Rappi (`v_eventos_amplitude`). Solo vistas: no hay datos nuevos. Cada fila dice su población (`source`):
-- synthetic o prototype, y quien las lea filtra una sola, nunca las mezcla.

CREATE VIEW capa.v_carros_abandonados AS
WITH cart_events AS (
    SELECT e.source, e.user_id, e.cart_id, e.session_id, e.ts, e.type, e.vertical, e.value,
           CASE WHEN jsonb_typeof(e.payload -> 'qty') = 'number'
                THEN least(greatest((e.payload ->> 'qty')::numeric, 0), 99) ELSE 1 END AS qty,
           coalesce(e.payload ->> 'mode', '') = 'actual' AS actual
    FROM app_events e
    WHERE e.type IN ('cart_add', 'cart_remove', 'checkout_start') AND e.cart_id IS NOT NULL
),
carts AS (
    SELECT source, user_id, cart_id,
           (array_agg(session_id ORDER BY ts))[1] AS session_id,
           CASE WHEN bool_or(actual) THEN 'actual' ELSE 'propuesta' END AS modo,
           min(ts) AS primer_evento,
           max(ts) AS ultimo_evento,
           coalesce(sum(qty) FILTER (WHERE type = 'cart_add'), 0)
             - coalesce(sum(qty) FILTER (WHERE type = 'cart_remove'), 0) AS unidades,
           coalesce(sum(value * qty) FILTER (WHERE type = 'cart_add'), 0)
             - coalesce(sum(value * qty) FILTER (WHERE type = 'cart_remove'), 0) AS monto,
           bool_or(type = 'checkout_start') AS llego_a_pagar,
           array_agg(DISTINCT vertical ORDER BY vertical) FILTER (WHERE vertical IS NOT NULL) AS verticales
    FROM cart_events
    GROUP BY source, user_id, cart_id
)
SELECT c.source, c.user_id, c.cart_id, c.session_id, c.modo, c.primer_evento, c.ultimo_evento, c.unidades,
       greatest(c.monto, 0) AS monto, c.llego_a_pagar, c.verticales
FROM carts c
WHERE c.unidades > 0
  AND c.ultimo_evento < now() - interval '60 minutes'
  AND NOT EXISTS (
      SELECT 1 FROM app_orders o
      WHERE o.user_id = c.user_id AND o.cart_id = c.cart_id AND o.ts <= c.ultimo_evento + interval '60 minutes'
  );

COMMENT ON VIEW capa.v_carros_abandonados IS 'Carros abandonados (ABANDONED_CART y ABANDONED_CHECKOUT en la app de Rappi, que aquí se derivan sin eventos nuevos): un carro con algo adentro (agregado menos quitado) cuyo último evento de carro fue hace más de 60 minutos y que no terminó en un pedido del mismo carro dentro de esos 60 minutos. Personal (un id seudónimo por fila). El panel cuenta otro abandono, a 24 horas (analytics/queries.py).';
COMMENT ON COLUMN capa.v_carros_abandonados.source IS 'Población: synthetic (simulada) o prototype. Nunca mezcladas.';
COMMENT ON COLUMN capa.v_carros_abandonados.user_id IS 'Persona (id seudónimo).';
COMMENT ON COLUMN capa.v_carros_abandonados.cart_id IS 'El carro (cart_id de sus eventos).';
COMMENT ON COLUMN capa.v_carros_abandonados.session_id IS 'La sesión de su primer evento de carro.';
COMMENT ON COLUMN capa.v_carros_abandonados.modo IS 'propuesta (el prototipo con Mochi) o actual («Rappi hoy»), según sus eventos.';
COMMENT ON COLUMN capa.v_carros_abandonados.primer_evento IS 'Hora de su primer evento de carro (llegada a la API).';
COMMENT ON COLUMN capa.v_carros_abandonados.ultimo_evento IS 'Hora de su último evento de carro (agregar, quitar o ir a pagar).';
COMMENT ON COLUMN capa.v_carros_abandonados.unidades IS 'Unidades que quedaron: agregadas menos quitadas (payload.qty si viene, si no 1).';
COMMENT ON COLUMN capa.v_carros_abandonados.monto IS 'Lo que sumaba, en pesos, con el precio que mandó la app en cada evento (value por unidades): una aproximación, no el total de un pedido.';
COMMENT ON COLUMN capa.v_carros_abandonados.llego_a_pagar IS 'Si alcanzó a iniciar el pago (checkout_start): ABANDONED_CHECKOUT en vez de ABANDONED_CART.';
COMMENT ON COLUMN capa.v_carros_abandonados.verticales IS 'Las verticales de lo que tenía (códigos del catálogo).';

CREATE VIEW capa.v_embudo_sesion AS
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
       bool_or(e.type = 'order_placed') AS pedido,
       count(*) FILTER (WHERE e.type = 'order_placed') AS pedidos,
       coalesce(sum(e.value) FILTER (WHERE e.type = 'order_placed'), 0) AS monto_pedidos
FROM app_events e
LEFT JOIN app_sessions s ON s.user_id = e.user_id AND s.session_id = e.session_id
GROUP BY e.source, e.user_id, e.session_id, s.started_at, s.mode, s.variants;

COMMENT ON VIEW capa.v_embudo_sesion IS 'El embudo de cada sesión: si vio algo (una lista, una sugerencia o resultados de búsqueda), si tocó algo, si agregó al carro, si fue a pagar y si pidió. Cada paso se marca aunque falte el anterior; quien cuente el embudo exige los pasos anteriores (como /analytics/embudo-sesion). Personal (un id seudónimo por fila).';
COMMENT ON COLUMN capa.v_embudo_sesion.source IS 'Población: synthetic (simulada) o prototype. Nunca mezcladas.';
COMMENT ON COLUMN capa.v_embudo_sesion.user_id IS 'Persona (id seudónimo).';
COMMENT ON COLUMN capa.v_embudo_sesion.session_id IS 'La sesión (30 minutos sin actividad la cierran).';
COMMENT ON COLUMN capa.v_embudo_sesion.inicio IS 'Cuándo empezó (app_sessions.started_at o, sin esa fila, su primer evento).';
COMMENT ON COLUMN capa.v_embudo_sesion.modo IS 'propuesta (el prototipo con Mochi) o actual («Rappi hoy»): el de app_sessions o, sin esa fila, el de sus eventos.';
COMMENT ON COLUMN capa.v_embudo_sesion.variantes IS 'Las variantes de la persona en los experimentos al empezar la sesión (app_sessions.variants); nula antes de la migración 047.';
COMMENT ON COLUMN capa.v_embudo_sesion.vio IS 'Vio algo: una lista (list_view), una sugerencia de Mochi (suggestion_shown) o resultados de una búsqueda.';
COMMENT ON COLUMN capa.v_embudo_sesion.clic IS 'Tocó algo: abrió una tienda, un producto, una recomendación o un vertical, aceptó una sugerencia, abrió un servicio o agregó algo con el «+» (que no abre el producto).';
COMMENT ON COLUMN capa.v_embudo_sesion.carro IS 'Agregó algo al carro (cart_add).';
COMMENT ON COLUMN capa.v_embudo_sesion.pago IS 'Fue a pagar (checkout_start).';
COMMENT ON COLUMN capa.v_embudo_sesion.pedido IS 'Pidió (order_placed, que solo crea el servidor).';
COMMENT ON COLUMN capa.v_embudo_sesion.pedidos IS 'Cuántos pedidos (un carro de dos tiendas son dos).';
COMMENT ON COLUMN capa.v_embudo_sesion.monto_pedidos IS 'La suma de sus pedidos, en pesos (con el precio del catálogo que puso la API).';

CREATE VIEW capa.v_ctr_posicion AS
WITH seen AS (
    SELECT DISTINCT e.source, e.user_id, e.session_id, e.surface, e.origin, e.request_id, i.position, i.entity_type,
           i.entity_id, coalesce(e.payload ->> 'mode', 'propuesta') AS modo
    FROM app_events e
    JOIN app_event_items i ON i.event_id = e.event_id
    LEFT JOIN concepts c ON c.concept_id = i.concept_id
    WHERE e.type = 'list_view' AND e.surface IS NOT NULL AND e.origin IS NOT NULL AND c.sensitive IS NOT TRUE
),
outcome AS (
    SELECT s.*,
           EXISTS (
               SELECT 1 FROM app_events k
               WHERE k.user_id = s.user_id AND k.session_id = s.session_id
                 AND k.type IN ('view_store', 'view_item', 'recommendation_click', 'vertical_open', 'cart_add')
                 AND k.surface = s.surface AND k.origin = s.origin AND k.position = s.position
                 AND k.request_id IS NOT DISTINCT FROM s.request_id
                 AND CASE WHEN s.entity_type = 'vertical' THEN k.vertical = s.entity_id ELSE k.entity_id = s.entity_id END
           ) AS clic,
           EXISTS (
               SELECT 1 FROM app_events k
               WHERE k.user_id = s.user_id AND k.session_id = s.session_id AND k.type = 'cart_add'
                 AND k.surface = s.surface AND k.origin = s.origin AND k.position = s.position
                 AND k.request_id IS NOT DISTINCT FROM s.request_id AND k.entity_id = s.entity_id
           ) AS carro
    FROM seen s
)
SELECT source, modo, surface, origin, position,
       count(*) AS impresiones,
       count(DISTINCT user_id) AS personas,
       count(*) FILTER (WHERE clic) AS clics,
       round(count(*) FILTER (WHERE clic)::numeric / count(*), 4) AS ctr,
       count(*) FILTER (WHERE carro) AS al_carro
FROM outcome
GROUP BY source, modo, surface, origin, position;

COMMENT ON VIEW capa.v_ctr_posicion IS 'CTR por posición, pantalla y lista: de los elementos que quedaron a la vista (list_view y app_event_items, una vez por sesión, respuesta, lugar y elemento), cuántos se tocaron en esa misma sesión desde ese mismo lugar (el mismo surface, origin, position y request_id, y el mismo elemento). Sin conceptos sensibles. La base para medir y corregir el sesgo de posición. Agregada: sin ids de personas.';
COMMENT ON COLUMN capa.v_ctr_posicion.source IS 'Población: synthetic (simulada) o prototype. Nunca mezcladas.';
COMMENT ON COLUMN capa.v_ctr_posicion.modo IS 'propuesta (el prototipo con Mochi) o actual («Rappi hoy»).';
COMMENT ON COLUMN capa.v_ctr_posicion.surface IS 'Pantalla de la lista (home, search, store, restaurants, turbo, agent…): CONTEXT en Rappi.';
COMMENT ON COLUMN capa.v_ctr_posicion.origin IS 'La lista (accesos, resultados, pasillo, lista, agent-<momento>…): SOURCE o COMPONENT_NAME en Rappi.';
COMMENT ON COLUMN capa.v_ctr_posicion.position IS 'El lugar en la lista (0 = el primero): COMPONENT_INDEX en Rappi.';
COMMENT ON COLUMN capa.v_ctr_posicion.impresiones IS 'Elementos que quedaron a la vista en ese lugar.';
COMMENT ON COLUMN capa.v_ctr_posicion.personas IS 'Personas distintas que los vieron.';
COMMENT ON COLUMN capa.v_ctr_posicion.clics IS 'De esos, cuántos se tocaron desde ahí: abrir la tienda, el producto, la recomendación o el vertical, o agregarlo con el «+». Abrir la hoja de un producto que no viene de una recomendación no deja evento: no cuenta.';
COMMENT ON COLUMN capa.v_ctr_posicion.ctr IS 'clics / impresiones (0 a 1).';
COMMENT ON COLUMN capa.v_ctr_posicion.al_carro IS 'De esos, cuántos se agregaron al carro desde ahí.';

CREATE VIEW capa.v_eventos_amplitude AS
SELECT e.event_id, e.source,
       CASE e.type
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
           WHEN 'recommendation_click' THEN CASE WHEN e.entity_type = 'store' THEN 'SELECT_STORE' ELSE 'SELECT_PRODUCT' END
           WHEN 'service_shown' THEN 'home_placement_content_view'
           WHEN 'service_opened' THEN 'home_placement_content_click'
           WHEN 'vertical_open' THEN 'SELECT_STORE_TYPE'
           WHEN 'order_rated' THEN 'RATE_STAR_TAP'
           ELSE 'MVP_' || upper(e.type)
       END AS event_type,
       e.type NOT IN ('cart_remove', 'suggestion_dismissed', 'reorder', 'offer_withheld') AS equivalente,
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
LEFT JOIN app_sessions s ON s.user_id = e.user_id AND s.session_id = e.session_id
LEFT JOIN LATERAL (
    SELECT array_agg(i.entity_id ORDER BY i.position) FILTER (WHERE i.entity_type IN ('catalog_item', 'menu_item'))
             AS products,
           array_agg(i.entity_id ORDER BY i.position) FILTER (WHERE i.entity_type = 'store') AS stores
    FROM app_event_items i
    WHERE i.event_id = e.event_id AND e.type IN ('list_view', 'offer_withheld')
) it ON true;

COMMENT ON VIEW capa.v_eventos_amplitude IS 'Puente de integración: nuestros eventos con los nombres y el sobre del plan de tracking de la app de Rappi (Amplitude), uno por fila. No agrega datos: traduce los de app_events, app_sessions y app_event_items. Los que Rappi no tiene llevan el prefijo MVP_ y equivalente = false. La tabla de equivalencias está en docs/capa-de-datos.md. Personal (un id seudónimo por fila); la consulta y los conceptos no van.';
COMMENT ON COLUMN capa.v_eventos_amplitude.event_id IS 'Nuestro id del evento (app_events.event_id).';
COMMENT ON COLUMN capa.v_eventos_amplitude.source IS 'Población: synthetic (simulada) o prototype. Nunca mezcladas.';
COMMENT ON COLUMN capa.v_eventos_amplitude.event_type IS 'El nombre del evento en el plan de Rappi (VIEW_STORE, ADD_TO_CART, LOCAL_SEARCH_NULL_RESULTS…) o MVP_<tipo> si Rappi no tiene uno.';
COMMENT ON COLUMN capa.v_eventos_amplitude.equivalente IS 'Si el evento tiene equivalente en el plan de Rappi (false en MVP_CART_REMOVE, MVP_SUGGESTION_DISMISSED, MVP_REORDER y MVP_OFFER_WITHHELD).';
COMMENT ON COLUMN capa.v_eventos_amplitude.evento_mvp IS 'Nuestro tipo de evento (app_events.type).';
COMMENT ON COLUMN capa.v_eventos_amplitude.uuid IS 'Id de inserción (uuid de Amplitude): el client_event_id de la app o, en los eventos del servidor y los de antes de la migración 043, uno fijo derivado de event_id.';
COMMENT ON COLUMN capa.v_eventos_amplitude.sequence_number IS 'Orden del evento en su sesión según la app (seq); nulo en los eventos del servidor.';
COMMENT ON COLUMN capa.v_eventos_amplitude.session_id IS 'Nuestro id de sesión (texto; en Amplitude es el inicio en milisegundos: session_start_ms).';
COMMENT ON COLUMN capa.v_eventos_amplitude.session_start_ms IS 'Inicio de la sesión en milisegundos desde 1970 (app_sessions.started_at), como el session_id de Amplitude.';
COMMENT ON COLUMN capa.v_eventos_amplitude."timestamp" IS 'Hora del evento en milisegundos desde 1970: la de la app (client_ts) o, sin ella, la de llegada.';
COMMENT ON COLUMN capa.v_eventos_amplitude.user_id IS 'Persona (id seudónimo).';
COMMENT ON COLUMN capa.v_eventos_amplitude.platform IS 'web, ios o android (app_sessions.platform; STORE_PLATFORM en Rappi).';
COMMENT ON COLUMN capa.v_eventos_amplitude.version_name IS 'Versión de la app (app_sessions.app_version; APP_VERSION en Rappi).';
COMMENT ON COLUMN capa.v_eventos_amplitude.event_properties IS 'Propiedades con los nombres de Rappi, en mayúsculas (sin las nulas): CONTEXT (surface), SOURCE y COMPONENT_NAME (origin), COMPONENT_INDEX (position), VERTICAL, STORE_ID, PRODUCT_ID, REQUEST_ID, CART_ID, PRODUCT_VALUE, TOTAL, RESULTS, PRICE, OFFER_VALUE y OPEN (el catálogo fijado al registrar, payload.catalogo), PRODUCT_ID_LIST y STORE_ID_LIST (lo que la lista dejó a la vista) y LAST_POSITION_VIEWED.';
COMMENT ON COLUMN capa.v_eventos_amplitude.user_properties IS 'Propiedades de la persona en esa sesión: EXPERIMENTS (sus variantes, app_sessions.variants) y APP_MODE (el modo de la sesión).';
