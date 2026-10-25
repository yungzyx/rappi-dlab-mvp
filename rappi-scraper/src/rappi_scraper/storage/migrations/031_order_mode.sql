-- El modo de la app en que se hizo cada pedido: en «Rappi hoy» (actual) la app no aprende de la persona, así que esos
-- pedidos no entran a su perfil (marcas que repite, conceptos de sus líneas). Aditivo: los pedidos existentes quedan
-- como 'propuesta', el modo en que se hicieron.

ALTER TABLE app_orders
    ADD COLUMN mode text NOT NULL DEFAULT 'propuesta' CHECK (mode IN ('propuesta', 'actual'));
COMMENT ON COLUMN app_orders.mode IS 'Modo de la app en que se hizo el pedido: propuesta (con el agente, que aprende del pedido) o actual («Rappi hoy», no entra al perfil de la persona).';
