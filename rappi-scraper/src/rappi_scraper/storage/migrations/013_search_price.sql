-- Precio de cada documento como columna (antes se leía del JSON `metadata` en cada fila). La búsqueda vectorial
-- de rappi-ia filtra por tope de precio: con la columna indexada puede contar cuántos califican y, si son pocos,
-- revisarlos todos en vez de recorrer el índice HNSW (que corta en hnsw.max_scan_tuples y devolvería de menos).
ALTER TABLE search_documents
    ADD COLUMN price_min numeric
    GENERATED ALWAYS AS (coalesce((metadata ->> 'precio_min')::numeric, (metadata ->> 'precio')::numeric)) STORED;
CREATE INDEX search_documents_price_idx ON search_documents (vertical, price_min);
