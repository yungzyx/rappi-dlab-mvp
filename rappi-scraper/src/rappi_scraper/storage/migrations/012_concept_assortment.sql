-- Capa 2 y eventos: surtido materializado, índice de eventos por fuente y aristas aprendidas por fuente.
-- Ninguna tabla que escribe el scraper cambia de estructura (se puede aplicar con la descarga en curso).

-- v_concept_assortment recorre store_products completo (~120 ms) y Bigotes la consultaba varias veces por
-- mensaje. Se materializa y se refresca al final de `rappi-ia concepts`, que corre después de cada refresh.
CREATE MATERIALIZED VIEW concept_assortment AS
SELECT concept_id, vertical, items::integer AS items FROM v_concept_assortment;
CREATE UNIQUE INDEX concept_assortment_pk ON concept_assortment (concept_id, vertical);

-- Métricas del panel: max(ts) por fuente y las ventanas de 30/60/180 días pasan a ser rangos del índice.
CREATE INDEX app_events_source_ts_idx ON app_events (source, ts);

-- La misma pareja de conceptos puede aprenderse de los datos simulados y de los del prototipo.
ALTER TABLE concept_edges DROP CONSTRAINT concept_edges_pkey;
ALTER TABLE concept_edges ADD PRIMARY KEY (from_concept, to_concept, method, data_source);
