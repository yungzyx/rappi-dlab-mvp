-- El agente de la app registra sus preguntas como `ask` (antes `chat`). Se agrega el tipo nuevo y se conserva `chat`:
-- los eventos ya guardados y los clientes que aún lo mandan siguen siendo válidos. No se borra ni se cambia ninguna fila.
ALTER TABLE app_events DROP CONSTRAINT app_events_type_check;
ALTER TABLE app_events ADD CONSTRAINT app_events_type_check CHECK (type IN (
    'app_open', 'search', 'chat', 'ask', 'view_store', 'view_item', 'cart_add', 'cart_remove', 'checkout_start',
    'order_placed', 'suggestion_shown', 'suggestion_accepted', 'suggestion_dismissed', 'recommendation_click',
    'service_shown', 'service_opened'
));
