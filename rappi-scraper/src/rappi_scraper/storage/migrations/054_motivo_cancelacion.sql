-- El motivo de una cancelación (`app_orders.cancel_reason`, migración 050) era texto libre: la API solo acepta los
-- códigos de CANCEL_REASONS (rappi_ia/events/store.py) al recibir `order_cancelled`, pero la base no lo revisaba. Ahora
-- un CHECK con esos mismos códigos; nula sigue valiendo (un pedido que no se canceló). Si se suma un motivo en
-- CANCEL_REASONS, va también aquí, en una migración nueva (un test compara los dos).
-- Solo el CHECK y el comentario de la columna: no cambia ni borra datos (las filas de antes ya pasaron por la API).

ALTER TABLE app_orders ADD CONSTRAINT app_orders_cancel_reason_check
    CHECK (cancel_reason IS NULL OR cancel_reason IN ('direccion', 'pago', 'demora', 'productos', 'ya_no', 'otro'));
COMMENT ON COLUMN app_orders.cancel_reason IS 'Por qué lo canceló, según la persona: un código de events/store.py (CANCEL_REASONS): direccion, pago, demora, productos, ya_no u otro. Nula si no se canceló.';
