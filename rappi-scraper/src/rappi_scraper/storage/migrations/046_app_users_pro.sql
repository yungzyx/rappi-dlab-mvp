-- Rappi Pro de cada persona (checkout de la fase 3, docs/investigacion/app-rappi-2026-10-25.md): el checkout ya no da
-- envío gratis a todo el mundo, así que cada persona es Pro o no. En las simuladas lo sortea el generador (un supuesto
-- propio, coherente con su combinación de verticales: quien combina más grupos es Pro más seguido); en las del
-- prototipo es lo último que dijo la app al pedir (`POST /orders`, campo `pro`). NULL = sin dato (las filas de antes).
-- Aditiva: nadie la lee todavía para una cifra.
ALTER TABLE app_users ADD COLUMN pro boolean;
COMMENT ON COLUMN app_users.pro IS 'Si la persona es Rappi Pro. Simuladas: supuesto del generador (events/synth.py, PRO_SHARE por cantidad de grupos del arquetipo), no un dato de Rappi. Prototipo: lo que la app dijo en su último pedido. NULL = sin dato.';
