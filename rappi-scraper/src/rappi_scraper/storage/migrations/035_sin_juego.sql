-- El juego y el pasaporte salen del proyecto (16-10-2026); su historia está en rappi-evolucion-proyecto, etiqueta
-- etapa-12-pasaporte-y-juego. Se borran los eventos del juego, las tres tablas (tarjetas, ligas a conceptos y progreso
-- de cada persona) y los dos tipos de evento de la 029: el CHECK vuelve a los 16 tipos anteriores.
DELETE FROM app_events WHERE type IN ('game_round_finished', 'game_card_discovered');

DROP TABLE game_state, knowledge_card_concepts, knowledge_cards;

ALTER TABLE app_events DROP CONSTRAINT app_events_type_check;
ALTER TABLE app_events ADD CONSTRAINT app_events_type_check CHECK (type IN (
    'app_open', 'search', 'chat', 'ask', 'view_store', 'view_item', 'cart_add', 'cart_remove', 'checkout_start',
    'order_placed', 'suggestion_shown', 'suggestion_accepted', 'suggestion_dismissed', 'recommendation_click',
    'service_shown', 'service_opened'
));
COMMENT ON COLUMN app_events.type IS 'Qué pasó: abrir la app, buscar, preguntar al agente, ver, carro, pedido, y sugerencias y servicios del agente.';
