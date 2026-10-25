-- Vocabulario del catálogo para corregir errores de tipeo en la búsqueda (rappi_ia/retrieval/spelling.py): cada
-- palabra de los documentos de búsqueda, sin tildes ni ñ y en minúsculas, por vertical, con en cuántos documentos
-- está y cómo la escribe el catálogo. Una búsqueda en la que nada calza todas las palabras cambia cada palabra que la
-- vertical casi no tiene por la más parecida que sí tiene («nutela» → «nutella») y vuelve a buscar con las reglas de
-- siempre.
-- pg_trgm es una extensión «trusted»: la crea el dueño de la base sin ser superusuario (rappi_owner en producción),
-- así que no va en deploy/db/init-roles.sh. El comentario lo puede poner solo su dueño: si un superusuario ya la había
-- creado, se salta, como en la 034.
-- La tabla la rearma build_search_documents (rappi_scraper/storage/search.py) en la misma transacción que los
-- documentos, con la función de abajo: la definición de qué es una palabra vive solo aquí.

CREATE EXTENSION IF NOT EXISTS pg_trgm;
DO $$
BEGIN
    COMMENT ON EXTENSION pg_trgm IS 'Similitud de trigramas: candidatas para corregir errores de tipeo con search_vocabulary (migración 041).';
EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'pg_trgm: no se pudo comentar (%); la búsqueda funciona igual', SQLERRM;
END
$$;

CREATE TABLE search_vocabulary (
    vertical text NOT NULL REFERENCES verticals(code),
    word text NOT NULL,
    display text NOT NULL,
    docs integer NOT NULL,
    PRIMARY KEY (vertical, word)
);
CREATE INDEX search_vocabulary_word_trgm_idx ON search_vocabulary USING gin (word gin_trgm_ops);

COMMENT ON TABLE search_vocabulary IS 'Palabras de search_documents por vertical (sin tildes ni ñ, en minúsculas, de 2 a 40 letras), para corregir errores de tipeo en la búsqueda. La rearma build_search_documents con refresh_search_vocabulary().';
COMMENT ON COLUMN search_vocabulary.vertical IS 'Vertical de los documentos donde aparece la palabra.';
COMMENT ON COLUMN search_vocabulary.word IS 'La palabra sin tildes ni ñ: es_unaccent de cada pedazo de lower(content) partido en lo que no es letra ni número.';
COMMENT ON COLUMN search_vocabulary.display IS 'Cómo la escribe el catálogo (la forma en minúsculas más común, con tildes y ñ): la que muestra la corrección.';
COMMENT ON COLUMN search_vocabulary.docs IS 'En cuántos documentos de la vertical aparece (una vez por documento).';

CREATE FUNCTION refresh_search_vocabulary() RETURNS void
LANGUAGE sql
BEGIN ATOMIC
    DELETE FROM search_vocabulary;
    INSERT INTO search_vocabulary (vertical, word, display, docs)
    SELECT d.vertical, w.word, mode() WITHIN GROUP (ORDER BY w.token), count(*)
    FROM search_documents d,
         LATERAL (SELECT es_unaccent(token) AS word, min(token) AS token
                  FROM regexp_split_to_table(lower(d.content), '[^[:alnum:]]+') AS token
                  WHERE length(token) BETWEEN 2 AND 40
                  GROUP BY 1) w
    GROUP BY d.vertical, w.word;
END;
COMMENT ON FUNCTION refresh_search_vocabulary() IS 'Rearma search_vocabulary desde search_documents (unos 20 s con el catálogo completo).';

SELECT refresh_search_vocabulary();
ANALYZE search_vocabulary;
