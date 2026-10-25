-- Etapa 4 del MVP: las tarjetas de conocimiento del juego viven en la base, ligadas a conceptos, y el progreso de cada
-- persona se guarda en el servidor. Las tarjetas las carga `rappi-ia knowledge` desde knowledge.json; las ligas a
-- conceptos, desde card_concepts.toml (propuestas de una regla, revisadas una por una).
CREATE TABLE knowledge_cards (
    card_id      text PRIMARY KEY,
    vertical     text NOT NULL CHECK (vertical IN (
        'supermercado', 'conveniencia', 'turbo', 'licores', 'chocolateria', 'restaurantes', 'farmacia', 'mall', 'viajes'
    )),
    kind         text NOT NULL CHECK (kind IN ('dato', 'pregunta')),
    -- Se verifica al final de la transacción: cambiar el orden de varias tarjetas a la vez no choca a mitad de camino.
    position     integer NOT NULL UNIQUE DEFERRABLE INITIALLY DEFERRED,
    title        text,
    text         text,
    question     text,
    options      jsonb,
    answer       smallint,
    explanation  text,
    source_title text NOT NULL,
    source_url   text NOT NULL CHECK (source_url LIKE 'https://%'),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT knowledge_cards_dato_check CHECK (kind <> 'dato' OR (title IS NOT NULL AND text IS NOT NULL)),
    CONSTRAINT knowledge_cards_pregunta_check CHECK (
        kind <> 'pregunta'
        OR (question IS NOT NULL AND options IS NOT NULL AND answer IS NOT NULL AND explanation IS NOT NULL)
    )
);

CREATE TABLE knowledge_card_concepts (
    card_id    text NOT NULL REFERENCES knowledge_cards (card_id) ON DELETE CASCADE,
    concept_id text NOT NULL REFERENCES concepts (concept_id) ON DELETE CASCADE,
    method     text NOT NULL CHECK (method IN ('regla', 'manual')),
    PRIMARY KEY (card_id, concept_id)
);
CREATE INDEX knowledge_card_concepts_concept_idx ON knowledge_card_concepts (concept_id);

CREATE TABLE game_state (
    user_id    text PRIMARY KEY REFERENCES app_users (user_id) ON DELETE CASCADE,
    state      jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE knowledge_cards IS 'Tarjetas de conocimiento del juego (datos y preguntas), cargadas desde knowledge.json por `rappi-ia knowledge`; las que salen del archivo se borran.';
COMMENT ON COLUMN knowledge_cards.card_id IS 'Identificador estable de la tarjeta: «vertical-NN» (supermercado-01).';
COMMENT ON COLUMN knowledge_cards.vertical IS 'Vertical del pasaporte a la que pertenece la tarjeta (viajes no tiene catálogo).';
COMMENT ON COLUMN knowledge_cards.kind IS 'Tipo de tarjeta: dato (se lee) o pregunta (se responde con tres alternativas).';
COMMENT ON COLUMN knowledge_cards.position IS 'Lugar de la tarjeta en el archivo; ordena las listas.';
COMMENT ON COLUMN knowledge_cards.title IS 'Título corto del dato (solo datos).';
COMMENT ON COLUMN knowledge_cards.text IS 'Texto del dato (solo datos).';
COMMENT ON COLUMN knowledge_cards.question IS 'Enunciado de la pregunta (solo preguntas).';
COMMENT ON COLUMN knowledge_cards.options IS 'Las tres alternativas de la pregunta, como lista JSON (solo preguntas).';
COMMENT ON COLUMN knowledge_cards.answer IS 'Posición (0 a 2) de la alternativa correcta (solo preguntas).';
COMMENT ON COLUMN knowledge_cards.explanation IS 'Explicación que se muestra después de responder (solo preguntas).';
COMMENT ON COLUMN knowledge_cards.source_title IS 'Título de la fuente que respalda la tarjeta.';
COMMENT ON COLUMN knowledge_cards.source_url IS 'Dirección https de la fuente que respalda la tarjeta.';
COMMENT ON COLUMN knowledge_cards.updated_at IS 'Última vez que `rappi-ia knowledge` escribió la tarjeta.';

COMMENT ON TABLE knowledge_card_concepts IS 'Conceptos de los que habla cada tarjeta: propuestas de una regla de palabras clave, revisadas una por una (card_concepts.toml).';
COMMENT ON COLUMN knowledge_card_concepts.card_id IS 'Tarjeta ligada.';
COMMENT ON COLUMN knowledge_card_concepts.concept_id IS 'Concepto del que habla la tarjeta.';
COMMENT ON COLUMN knowledge_card_concepts.method IS 'Origen de la liga: regla (la propuso la regla y se aceptó) o manual (se agregó a mano).';

COMMENT ON TABLE game_state IS 'Progreso del juego de cada persona (álbum, sellos, racha), guardado por la API como un documento.';
COMMENT ON COLUMN game_state.user_id IS 'Persona dueña del progreso (app_users).';
COMMENT ON COLUMN game_state.state IS 'Documento JSON con el progreso del juego.';
COMMENT ON COLUMN game_state.updated_at IS 'Última vez que se guardó el progreso.';
