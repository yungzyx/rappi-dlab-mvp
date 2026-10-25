-- Motor multivertical (docs/superpowers/specs/2026-10-16-motor-multivertical-design.md, etapa 2): qué vertical conviene
-- sumarle a cada persona y qué ofrecerle. Las tablas de población llevan `data_source` ('synthetic' o 'prototype') y
-- nunca mezclan las dos; las de cada persona (afinidad, recompra) se van con ella (ON DELETE CASCADE).

-- Las corridas del motor quedan en el linaje de las capas.
ALTER TABLE layer_runs DROP CONSTRAINT layer_runs_layer_check;
ALTER TABLE layer_runs ADD CONSTRAINT layer_runs_layer_check CHECK (
    layer IN ('attributes', 'measures', 'brands', 'canonical', 'relations', 'segments', 'motor')
);
COMMENT ON COLUMN capa.layer_runs.layer IS 'measures, brands, canonical, attributes, relations, segments o motor.';
-- El motor sí deja registradas sus corridas en curso y las que fallan (la 026 decía que una corrida fallida no queda).
COMMENT ON COLUMN capa.layer_runs.status IS 'running mientras corre, done al terminar, failed si falló: el motor deja registrada la corrida que falla; las demás capas la deshacen con su transacción y no queda.';

-- Abrir un vertical desde la Home es una señal de afinidad: el CHECK de la 035 más `vertical_open`.
ALTER TABLE app_events DROP CONSTRAINT app_events_type_check;
ALTER TABLE app_events ADD CONSTRAINT app_events_type_check CHECK (type IN (
    'app_open', 'search', 'chat', 'ask', 'view_store', 'view_item', 'cart_add', 'cart_remove', 'checkout_start',
    'order_placed', 'suggestion_shown', 'suggestion_accepted', 'suggestion_dismissed', 'recommendation_click',
    'service_shown', 'service_opened', 'vertical_open'
));
COMMENT ON COLUMN app_events.type IS 'Qué pasó: abrir la app, buscar, preguntar al agente, ver, carro, pedido, sugerencias y servicios del agente, y abrir un vertical.';

CREATE TABLE user_vertical_affinity (
    user_id    text NOT NULL REFERENCES app_users ON DELETE CASCADE,
    vertical   text NOT NULL REFERENCES verticals (code),
    score      real NOT NULL,
    orders     int NOT NULL,
    signals    int NOT NULL,
    last_ts    timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, vertical)
);

CREATE TABLE vertical_transitions (
    data_source   text NOT NULL CHECK (data_source IN ('synthetic', 'prototype')),
    from_vertical text NOT NULL,
    to_vertical   text NOT NULL,
    n             int NOT NULL,
    prob          real NOT NULL,
    run_id        bigint REFERENCES layer_runs (run_id) ON DELETE SET NULL,
    PRIMARY KEY (data_source, from_vertical, to_vertical)
);

CREATE TABLE combo_stats (
    data_source     text NOT NULL CHECK (data_source IN ('synthetic', 'prototype')),
    combo           text NOT NULL,
    user_months     int NOT NULL,
    pct_users       real,
    pct_orders      real,
    orders_per_user real,
    retention_m1    real,
    retention_n     int,           -- meses con M+1 completo: los que cuentan para la retención
    spend_per_user  numeric,
    run_id          bigint REFERENCES layer_runs (run_id) ON DELETE SET NULL,
    PRIMARY KEY (data_source, combo)
);

CREATE TABLE combo_steps (
    data_source text NOT NULL CHECK (data_source IN ('synthetic', 'prototype')),
    from_combo  text NOT NULL,
    to_combo    text NOT NULL,
    users       int NOT NULL,
    prob        real NOT NULL,
    run_id      bigint REFERENCES layer_runs (run_id) ON DELETE SET NULL,
    PRIMARY KEY (data_source, from_combo, to_combo)
);

CREATE TABLE cross_sell_rules (
    data_source   text NOT NULL CHECK (data_source IN ('synthetic', 'prototype')),
    from_concept  text NOT NULL REFERENCES concepts (concept_id) ON DELETE CASCADE,
    from_vertical text NOT NULL,
    to_concept    text NOT NULL REFERENCES concepts (concept_id) ON DELETE CASCADE,
    to_vertical   text NOT NULL,
    users_from    int,
    users_both    int,
    confidence    real,
    lift          real,
    run_id        bigint REFERENCES layer_runs (run_id) ON DELETE SET NULL,
    PRIMARY KEY (data_source, from_concept, from_vertical, to_concept, to_vertical)
);
CREATE INDEX cross_sell_rules_from_idx ON cross_sell_rules (data_source, from_concept);

CREATE TABLE trends (
    data_source text NOT NULL CHECK (data_source IN ('synthetic', 'prototype')),
    scope       text NOT NULL CHECK (scope IN ('vertical', 'concepto', 'producto')),
    vertical    text NOT NULL,
    item_key    text NOT NULL,     -- el vertical, el concepto o «entity_type:entity_id»
    concept_id  text REFERENCES concepts (concept_id) ON DELETE SET NULL,
    entity_type text,
    entity_id   text,
    orders_now  int,
    orders_prev int,
    users_now   int,
    growth      real,
    rank        int,
    window_end  date,
    run_id      bigint REFERENCES layer_runs (run_id) ON DELETE SET NULL,
    PRIMARY KEY (data_source, scope, vertical, item_key)
);

CREATE TABLE replenishment (
    user_id       text NOT NULL REFERENCES app_users ON DELETE CASCADE,
    concept_id    text NOT NULL REFERENCES concepts (concept_id) ON DELETE CASCADE,
    vertical      text,
    orders        int,
    interval_days real,
    cv            real,
    last_ts       timestamptz,
    due_on        date,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, concept_id)
);

-- Contrato estable `capa` (docs/capa-de-datos.md): una vista por tabla, con comentario en español en cada columna.
-- Las dos vistas personales traen la fuente de la persona (`source`, como capa.user_segments): salen de app_users.
CREATE VIEW capa.user_vertical_affinity AS
SELECT t.*, u.source FROM user_vertical_affinity t JOIN app_users u USING (user_id);
CREATE VIEW capa.vertical_transitions AS SELECT * FROM vertical_transitions;
CREATE VIEW capa.combo_stats AS SELECT * FROM combo_stats;
CREATE VIEW capa.combo_steps AS SELECT * FROM combo_steps;
CREATE VIEW capa.cross_sell_rules AS SELECT * FROM cross_sell_rules;
CREATE VIEW capa.trends AS SELECT * FROM trends;
CREATE VIEW capa.replenishment AS
SELECT t.*, u.source FROM replenishment t JOIN app_users u USING (user_id) JOIN concepts c USING (concept_id)
WHERE NOT c.sensitive;

COMMENT ON VIEW capa.user_vertical_affinity IS 'Cuánto le interesa cada vertical a cada persona, con sus pedidos y señales (búsquedas, vistas, aperturas). Ids de persona seudónimos; las filas de la fuente synthetic son simuladas (no son evidencia).';
COMMENT ON VIEW capa.vertical_transitions IS 'Qué vertical pide una persona después de otro, y con qué probabilidad, por fuente de datos.';
COMMENT ON VIEW capa.combo_stats IS 'Por combinación de grupos de verticales usados en un mes (rest, turbo, retail): personas-mes, pedidos, gasto y retención al mes siguiente, medidos en las personas de cada fuente. Es una correlación, no un efecto.';
COMMENT ON VIEW capa.combo_steps IS 'De qué combinación de grupos pasan las personas a cuál al mes siguiente, con cuántas personas y qué probabilidad.';
COMMENT ON VIEW capa.cross_sell_rules IS 'Reglas «quien pide X en un vertical también pide Y en otro»: cuántas personas, confianza y lift. Son asociaciones, no causas.';
COMMENT ON VIEW capa.trends IS 'Lo que crece en pedidos: verticales, conceptos y productos, comparando la ventana reciente con la anterior, con su lugar en el ranking.';
COMMENT ON VIEW capa.replenishment IS 'Qué concepto recompra cada persona y cada cuántos días, con la fecha en que le toca de nuevo. No incluye conceptos sensibles. Ids de persona seudónimos; las filas de la fuente synthetic son simuladas (no son evidencia).';

COMMENT ON COLUMN capa.user_vertical_affinity.user_id IS 'Id seudónimo de la persona.';
COMMENT ON COLUMN capa.user_vertical_affinity.vertical IS 'Vertical (código de la tabla verticals).';
COMMENT ON COLUMN capa.user_vertical_affinity.score IS 'Afinidad con el vertical: pedidos y señales, con menos peso cuanto más viejos.';
COMMENT ON COLUMN capa.user_vertical_affinity.orders IS 'Pedidos de la persona en ese vertical en los últimos 180 días.';
COMMENT ON COLUMN capa.user_vertical_affinity.signals IS 'Señales en los últimos 180 días, pedidos incluidos (pedidos, búsquedas, vistas y aperturas del vertical).';
COMMENT ON COLUMN capa.user_vertical_affinity.last_ts IS 'Última vez que la persona hizo algo en ese vertical.';
COMMENT ON COLUMN capa.user_vertical_affinity.updated_at IS 'Cuándo se recalculó esta fila.';
COMMENT ON COLUMN capa.user_vertical_affinity.source IS 'synthetic (simulada) o prototype (usuarios del prototipo).';

COMMENT ON COLUMN capa.vertical_transitions.data_source IS 'Fuente de las personas: synthetic (simulada) o prototype. Nunca mezcladas.';
COMMENT ON COLUMN capa.vertical_transitions.from_vertical IS 'Vertical del pedido de partida.';
COMMENT ON COLUMN capa.vertical_transitions.to_vertical IS 'Vertical del pedido siguiente.';
COMMENT ON COLUMN capa.vertical_transitions.n IS 'Cuántas veces ocurrió el paso.';
COMMENT ON COLUMN capa.vertical_transitions.prob IS 'Probabilidad del paso entre todos los que salen de ese vertical (0 a 1).';
COMMENT ON COLUMN capa.vertical_transitions.run_id IS 'Corrida del motor que lo calculó (capa.layer_runs).';

COMMENT ON COLUMN capa.combo_stats.data_source IS 'Fuente de las personas: synthetic (simulada) o prototype. Nunca mezcladas.';
COMMENT ON COLUMN capa.combo_stats.combo IS 'Grupos de verticales usados en el mes, en el orden rest, turbo, retail, unidos por «+»; «ninguna» si no hubo pedidos.';
COMMENT ON COLUMN capa.combo_stats.user_months IS 'Personas-mes con esa combinación.';
COMMENT ON COLUMN capa.combo_stats.pct_users IS 'Porcentaje de las personas-mes (0 a 100).';
COMMENT ON COLUMN capa.combo_stats.pct_orders IS 'Porcentaje de los pedidos (0 a 100).';
COMMENT ON COLUMN capa.combo_stats.orders_per_user IS 'Pedidos por persona en el mes.';
COMMENT ON COLUMN capa.combo_stats.retention_m1 IS 'Fracción (0 a 1) que vuelve a pedir al mes siguiente.';
COMMENT ON COLUMN capa.combo_stats.retention_n IS 'Meses con el mes siguiente completo: los únicos que cuentan para la retención.';
COMMENT ON COLUMN capa.combo_stats.spend_per_user IS 'Gasto por persona en el mes, en pesos chilenos.';
COMMENT ON COLUMN capa.combo_stats.run_id IS 'Corrida del motor que lo calculó (capa.layer_runs).';

COMMENT ON COLUMN capa.combo_steps.data_source IS 'Fuente de las personas: synthetic (simulada) o prototype. Nunca mezcladas.';
COMMENT ON COLUMN capa.combo_steps.from_combo IS 'Combinación de grupos en el mes de partida.';
COMMENT ON COLUMN capa.combo_steps.to_combo IS 'Combinación de grupos en el mes siguiente.';
COMMENT ON COLUMN capa.combo_steps.users IS 'Personas que hicieron el paso.';
COMMENT ON COLUMN capa.combo_steps.prob IS 'Probabilidad del paso entre las personas que partían de esa combinación (0 a 1).';
COMMENT ON COLUMN capa.combo_steps.run_id IS 'Corrida del motor que lo calculó (capa.layer_runs).';

COMMENT ON COLUMN capa.cross_sell_rules.data_source IS 'Fuente de las personas: synthetic (simulada) o prototype. Nunca mezcladas.';
COMMENT ON COLUMN capa.cross_sell_rules.from_concept IS 'Concepto de partida (concept_id).';
COMMENT ON COLUMN capa.cross_sell_rules.from_vertical IS 'Vertical donde se pide el concepto de partida.';
COMMENT ON COLUMN capa.cross_sell_rules.to_concept IS 'Concepto que se pide además (concept_id).';
COMMENT ON COLUMN capa.cross_sell_rules.to_vertical IS 'Vertical donde se pide el segundo concepto.';
COMMENT ON COLUMN capa.cross_sell_rules.users_from IS 'Personas que pidieron el concepto de partida.';
COMMENT ON COLUMN capa.cross_sell_rules.users_both IS 'Personas que pidieron los dos.';
COMMENT ON COLUMN capa.cross_sell_rules.confidence IS 'users_both / users_from: de quienes piden el primero, la fracción que pide el segundo (0 a 1).';
COMMENT ON COLUMN capa.cross_sell_rules.lift IS 'Cuántas veces más probable es pedir el segundo habiendo pedido el primero que en toda la población.';
COMMENT ON COLUMN capa.cross_sell_rules.run_id IS 'Corrida del motor que lo calculó (capa.layer_runs).';

COMMENT ON COLUMN capa.trends.data_source IS 'Fuente de las personas: synthetic (simulada) o prototype. Nunca mezcladas.';
COMMENT ON COLUMN capa.trends.scope IS 'Qué crece: vertical, concepto o producto.';
COMMENT ON COLUMN capa.trends.vertical IS 'Vertical donde crece.';
COMMENT ON COLUMN capa.trends.item_key IS 'Identifica lo que crece: el vertical, el concepto o «entity_type:entity_id».';
COMMENT ON COLUMN capa.trends.concept_id IS 'Concepto de lo que crece, si tiene.';
COMMENT ON COLUMN capa.trends.entity_type IS 'catalog_item (producto) o menu_item (plato), cuando el alcance es producto.';
COMMENT ON COLUMN capa.trends.entity_id IS 'Id del producto o del plato, como texto, cuando el alcance es producto.';
COMMENT ON COLUMN capa.trends.orders_now IS 'Pedidos en la ventana reciente.';
COMMENT ON COLUMN capa.trends.orders_prev IS 'Pedidos en la ventana anterior, del mismo largo.';
COMMENT ON COLUMN capa.trends.users_now IS 'Personas distintas que pidieron en la ventana reciente.';
COMMENT ON COLUMN capa.trends.growth IS 'Crecimiento entre las dos ventanas: (ahora − antes) / max(antes, 5); con 5 o más pedidos antes, 0,5 = 50 % más pedidos.';
COMMENT ON COLUMN capa.trends.rank IS 'Lugar en el ranking de su alcance y vertical (1 = el más pedido en la ventana actual).';
COMMENT ON COLUMN capa.trends.window_end IS 'Último día de la ventana reciente.';
COMMENT ON COLUMN capa.trends.run_id IS 'Corrida del motor que lo calculó (capa.layer_runs).';

COMMENT ON COLUMN capa.replenishment.user_id IS 'Id seudónimo de la persona.';
COMMENT ON COLUMN capa.replenishment.concept_id IS 'Concepto que recompra (concept_id).';
COMMENT ON COLUMN capa.replenishment.vertical IS 'Vertical donde lo suele pedir.';
COMMENT ON COLUMN capa.replenishment.orders IS 'Días distintos con compra del concepto.';
COMMENT ON COLUMN capa.replenishment.interval_days IS 'Días típicos entre un pedido y el siguiente.';
COMMENT ON COLUMN capa.replenishment.cv IS 'Variación de ese intervalo (desviación sobre media): cuanto más bajo, más regular.';
COMMENT ON COLUMN capa.replenishment.last_ts IS 'Último pedido de ese concepto.';
COMMENT ON COLUMN capa.replenishment.due_on IS 'Día en que le toca pedirlo de nuevo.';
COMMENT ON COLUMN capa.replenishment.updated_at IS 'Cuándo se recalculó esta fila.';
COMMENT ON COLUMN capa.replenishment.source IS 'synthetic (simulada) o prototype (usuarios del prototipo).';
