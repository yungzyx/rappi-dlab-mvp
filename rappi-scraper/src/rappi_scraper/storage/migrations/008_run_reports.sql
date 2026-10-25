-- Reporte de cada corrida (conteos y validaciones de calidad), para comparar corridas en el tiempo.
ALTER TABLE scrape_runs ADD COLUMN report jsonb;
