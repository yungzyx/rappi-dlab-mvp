-- Capa de perfiles, etapa 3 (docs/superpowers/specs/2026-10-06-capa-perfiles-design.md §3.6): grafo de conocimiento.
-- Una sola tabla de aristas con tipo de relación y de nodo, para conceptos, atributos, segmentos, marcas, verticales…
-- `concept_edges` pasa a ser una vista de las aristas `complementa` entre conceptos, con los mismos nombres de columna:
-- quien la lee o escribe sigue funcionando.
CREATE TABLE relation_defs (
    relation    text PRIMARY KEY,
    name        text NOT NULL,
    from_kinds  text[] NOT NULL,
    to_kinds    text[] NOT NULL,
    is_symmetric boolean NOT NULL DEFAULT false,
    description text NOT NULL DEFAULT ''
);
INSERT INTO relation_defs (relation, name, from_kinds, to_kinds, is_symmetric, description)
VALUES ('complementa', 'Complementa', ARRAY['concept'], ARRAY['concept'], false,
        'Quien lleva X suele querer Y: base de la sugerencia entre verticales.');

CREATE TABLE knowledge_edges (
    from_kind   text NOT NULL DEFAULT 'concept'
        CHECK (from_kind IN ('concept', 'group', 'attribute', 'segment', 'brand', 'vertical', 'occasion', 'service', 'canonical', 'term')),
    from_id     text NOT NULL,
    relation    text NOT NULL DEFAULT 'complementa' REFERENCES relation_defs (relation),
    to_kind     text NOT NULL DEFAULT 'concept'
        CHECK (to_kind IN ('concept', 'group', 'attribute', 'segment', 'brand', 'vertical', 'occasion', 'service', 'canonical', 'term')),
    to_id       text NOT NULL,
    weight      real NOT NULL CHECK (weight BETWEEN 0 AND 1),
    method      text NOT NULL CHECK (method IN ('curado', 'coocurrencia', 'derivado')),
    data_source text NOT NULL DEFAULT 'curado' CHECK (data_source IN ('curado', 'synthetic', 'prototype', 'catalogo')),
    support     integer,        -- usuarios o ítems que respaldan la arista
    evidence    text,
    run_id      bigint REFERENCES layer_runs (run_id) ON DELETE SET NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (from_kind, from_id, relation, to_kind, to_id, method, data_source)
);
CREATE INDEX knowledge_edges_to_idx ON knowledge_edges (to_kind, to_id, relation);
CREATE INDEX knowledge_edges_relation_idx ON knowledge_edges (relation, method);

INSERT INTO knowledge_edges (from_id, to_id, method, weight, support, data_source, updated_at)
SELECT from_concept, to_concept, method, weight, support, data_source, updated_at FROM concept_edges;
DROP TABLE concept_edges;

CREATE VIEW concept_edges AS
SELECT from_id AS from_concept, to_id AS to_concept, method, weight, support, data_source, updated_at
FROM knowledge_edges
WHERE relation = 'complementa' AND from_kind = 'concept' AND to_kind = 'concept'
WITH CHECK OPTION;

COMMENT ON TABLE relation_defs IS 'Vocabulario de relaciones del grafo de conocimiento (complementa, sustituye, tiene_atributo…), sembrado desde relations.toml.';
COMMENT ON TABLE knowledge_edges IS 'Grafo de conocimiento: aristas con tipo de relación entre nodos de cualquier tipo (concepto, atributo, segmento, marca, vertical…), con peso, método y evidencia.';
COMMENT ON VIEW concept_edges IS 'Compatibilidad: las aristas `complementa` entre conceptos de knowledge_edges, con las columnas de la tabla antigua.';

CREATE VIEW capa.knowledge_edges AS
SELECT e.from_kind, e.from_id, e.relation, d.name AS relation_name, e.to_kind, e.to_id, e.weight, e.method,
       e.data_source, e.support, e.evidence
FROM knowledge_edges e JOIN relation_defs d USING (relation)
WHERE e.data_source <> 'synthetic';  -- lo aprendido de datos simulados no es evidencia

COMMENT ON VIEW capa.knowledge_edges IS 'Grafo de conocimiento sin las aristas aprendidas de datos simulados (no son evidencia).';
