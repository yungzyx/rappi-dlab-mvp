-- Etapa 2 (rappi-ia): caché de embeddings de texto, embeddings de imágenes y búsqueda léxica sin tildes ni ñ.

CREATE EXTENSION IF NOT EXISTS unaccent;

-- Un vector por texto y modelo: el mismo producto en varios verticales tiene el mismo texto y se embebe una vez.
-- Desde aquí se copia a search_documents.embedding (donde vive el HNSW de cada partición).
CREATE TABLE text_embeddings (
    content_hash    text NOT NULL,
    embedding_model text NOT NULL,
    embedding       vector NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (content_hash, embedding_model)
);

-- Vectores de las fotos de productos y platos (la imagen no se guarda).
CREATE TABLE image_embeddings (
    image_url       text NOT NULL,
    embedding_model text NOT NULL,
    embedding       vector,  -- NULL si la descarga falló o es un placeholder
    status          text NOT NULL CHECK (status IN ('ok', 'error', 'placeholder')),
    error           text,
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (image_url, embedding_model)
);

-- unaccent no es IMMUTABLE (depende del diccionario): este envoltorio con diccionario fijo sí se puede
-- usar en una columna generada.
CREATE FUNCTION es_unaccent(text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
    RETURN public.unaccent('public.unaccent'::regdictionary, $1);

-- "panales" encuentra "pañales" y "cafe" encuentra "café" (el tsv original conserva la ñ a propósito).
ALTER TABLE search_documents
    ADD COLUMN tsv_unaccent tsvector GENERATED ALWAYS AS (to_tsvector('spanish', es_unaccent(content))) STORED;
CREATE INDEX search_documents_tsv_unaccent_idx ON search_documents USING gin (tsv_unaccent);
