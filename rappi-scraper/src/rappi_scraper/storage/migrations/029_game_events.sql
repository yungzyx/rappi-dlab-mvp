-- El juego deja huella en el panel: dos tipos de evento nuevos, `game_round_finished` (payload: vertical_juego,
-- estrellas, aciertos, preguntas) y `game_card_discovered` (payload: vertical_juego, tarjeta). Es aditiva: se agregan los
-- tipos y se conservan los 16 anteriores, sin borrar ni cambiar ninguna fila. La tarjeta va en el payload y no en
-- `entity_type`, cuyo CHECK no se toca.
ALTER TABLE app_events DROP CONSTRAINT app_events_type_check;
ALTER TABLE app_events ADD CONSTRAINT app_events_type_check CHECK (type IN (
    'app_open', 'search', 'chat', 'ask', 'view_store', 'view_item', 'cart_add', 'cart_remove', 'checkout_start',
    'order_placed', 'suggestion_shown', 'suggestion_accepted', 'suggestion_dismissed', 'recommendation_click',
    'service_shown', 'service_opened', 'game_round_finished', 'game_card_discovered'
));
COMMENT ON COLUMN app_events.type IS 'Qué pasó: abrir la app, buscar, preguntar al agente, ver, carro, pedido, sugerencias y servicios del agente, y el juego (`game_round_finished`: ronda terminada; `game_card_discovered`: tarjeta nueva). Los eventos del juego no suman interés al perfil.';
