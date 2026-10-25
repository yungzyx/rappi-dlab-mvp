-- Jev (el modelo de juicio de TypeSafe) entra al proceso semanal, siempre como ayuda opcional: dos cambios aditivos.
-- 1) `eval_judgments`: caché de los juicios que Jev emite sobre pares (consulta, producto o plato) al evaluar la
--    búsqueda, para no volver a pagar por el mismo par si el modelo no cambió.
-- 2) El método `jev` en `category_map` e `item_concepts`: mapeos de categorías nuevas propuestos por Jev. Es un método
--    de máquina, distinto de `curado` (una persona) y de `llm`: se ven y se filtran aparte. No se borra ni se cambia
--    ninguna fila existente.

CREATE TABLE eval_judgments (
    query         text NOT NULL,
    vertical      text NOT NULL,
    entity_type   text NOT NULL CHECK (entity_type IN ('catalog_item', 'menu_item')),
    entity_id     text NOT NULL,
    judge         text NOT NULL CHECK (judge IN ('jev')),
    model_version text NOT NULL,
    score         real NOT NULL CHECK (score BETWEEN 0 AND 1),
    probabilities jsonb,
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (query, vertical, entity_type, entity_id, judge, model_version)
);
COMMENT ON TABLE eval_judgments IS 'Caché de juicios de relevancia de un modelo (hoy solo Jev) sobre pares consulta-producto o consulta-plato de la evaluación de búsqueda. La clave incluye la versión del modelo: otra versión es otro juicio.';
COMMENT ON COLUMN eval_judgments.query IS 'Consulta evaluada, tal como se escribió.';
COMMENT ON COLUMN eval_judgments.vertical IS 'Vertical en la que se evaluó la consulta.';
COMMENT ON COLUMN eval_judgments.entity_type IS 'Qué se juzgó: un producto del catálogo (catalog_item) o un plato (menu_item).';
COMMENT ON COLUMN eval_judgments.entity_id IS 'Identificador del producto o plato juzgado.';
COMMENT ON COLUMN eval_judgments.judge IS 'Quién juzgó. Por ahora solo jev.';
COMMENT ON COLUMN eval_judgments.model_version IS 'Versión del modelo que emitió el juicio; al cambiar, los juicios anteriores dejan de valer.';
COMMENT ON COLUMN eval_judgments.score IS 'Puntaje de relevancia de 0 a 1.';
COMMENT ON COLUMN eval_judgments.probabilities IS 'Probabilidades que devolvió el modelo por etiqueta, tal cual, para revisar el juicio.';
COMMENT ON COLUMN eval_judgments.created_at IS 'Cuándo se emitió el juicio.';

ALTER TABLE category_map DROP CONSTRAINT category_map_method_check;
ALTER TABLE category_map ADD CONSTRAINT category_map_method_check
    CHECK (method IN ('curado', 'llm', 'regla', 'embedding', 'jev'));
COMMENT ON COLUMN category_map.method IS 'Cómo se decidió el mapeo: curado (una persona), llm (agentes revisados), regla, embedding o jev (propuesto por el modelo Jev, sin revisión humana).';

ALTER TABLE item_concepts DROP CONSTRAINT item_concepts_method_check;
ALTER TABLE item_concepts ADD CONSTRAINT item_concepts_method_check
    CHECK (method IN ('curado', 'llm', 'regla', 'embedding', 'jev'));
COMMENT ON COLUMN item_concepts.method IS 'Cómo se asignó el concepto: curado, llm, regla, embedding o jev (heredado de un mapeo de categoría propuesto por Jev).';
