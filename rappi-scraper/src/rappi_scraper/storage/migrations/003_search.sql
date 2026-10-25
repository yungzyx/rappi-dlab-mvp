-- Documentos para búsqueda (texto hoy, embeddings después), aislados por vertical.
-- Cada vertical es su propia partición: índices y búsquedas nunca mezclan verticales.

CREATE TABLE search_documents (
    vertical        text NOT NULL REFERENCES verticals,
    entity_type     text NOT NULL,            -- 'catalog_item' | 'menu_item' | 'store'
    entity_id       text NOT NULL,
    content         text NOT NULL,            -- texto estable (sin precios) para embeddings
    metadata        jsonb NOT NULL DEFAULT '{}', -- precios, tiendas, subvertical…
    content_hash    text NOT NULL,
    tsv             tsvector GENERATED ALWAYS AS (to_tsvector('spanish', content)) STORED,
    embedding       vector,                   -- dimensión según el modelo elegido
    embedding_model text,
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (vertical, entity_type, entity_id)
) PARTITION BY LIST (vertical);

CREATE TABLE search_documents_supermercado PARTITION OF search_documents FOR VALUES IN ('supermercado');
CREATE TABLE search_documents_conveniencia PARTITION OF search_documents FOR VALUES IN ('conveniencia');
CREATE TABLE search_documents_turbo        PARTITION OF search_documents FOR VALUES IN ('turbo');
CREATE TABLE search_documents_mall         PARTITION OF search_documents FOR VALUES IN ('mall');
CREATE TABLE search_documents_farmacia     PARTITION OF search_documents FOR VALUES IN ('farmacia');
CREATE TABLE search_documents_licores      PARTITION OF search_documents FOR VALUES IN ('licores');
CREATE TABLE search_documents_chocolateria PARTITION OF search_documents FOR VALUES IN ('chocolateria');
CREATE TABLE search_documents_restaurantes PARTITION OF search_documents FOR VALUES IN ('restaurantes');

CREATE INDEX search_documents_tsv_idx ON search_documents USING gin (tsv);
-- Índices HNSW por partición se crean cuando se elija el modelo de embeddings, p. ej.:
-- CREATE INDEX ON search_documents_mall USING hnsw ((embedding::vector(1536)) vector_cosine_ops)
--     WHERE embedding_model = 'text-embedding-3-small';
