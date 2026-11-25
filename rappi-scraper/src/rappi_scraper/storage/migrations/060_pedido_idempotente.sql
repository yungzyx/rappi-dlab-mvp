-- Un pedido se guarda una sola vez: la app manda en POST /orders una clave por pedido (`client_order_id`, como el
-- `client_event_id` de los eventos), y un reenvío con la misma clave (la respuesta se perdió en el camino, pero Postgres
-- ya lo había guardado) devuelve el pedido guardado en vez de crear otra compra que contaría dos veces en las métricas
-- y la recompra. Es por persona. Los pedidos de antes, los simulados y los de un cliente que no la manda quedan con la
-- clave nula, que no choca con nada. Solo agrega la columna y su restricción: no cambia ni borra datos.

ALTER TABLE app_orders
    ADD COLUMN client_order_id text,
    ADD CONSTRAINT app_orders_client_order_id_key UNIQUE (user_id, client_order_id);

COMMENT ON COLUMN app_orders.client_order_id IS 'La clave del pedido que genera la app (una por pedido, en POST /orders): un reenvío con la misma clave devuelve este pedido y no crea otro. Única por persona; nula en los pedidos de antes de la migración 060, en los simulados y en los de un cliente que no la manda.';
