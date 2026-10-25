-- Escalera fina (docs/superpowers/plans/2026-10-16-etapa-7-escalera-fina.md): las combinaciones de la población se
-- guardan en dos niveles. «grueso» son los grupos de la tabla de Rappi (rest, turbo, retail), como en la 036; «fino»,
-- las verticales del catálogo (y los servicios RappiFavor y RappiTravel) una por una. Las filas que ya había son gruesas.

ALTER TABLE combo_stats ADD COLUMN nivel text NOT NULL DEFAULT 'grueso' CHECK (nivel IN ('grueso', 'fino'));
ALTER TABLE combo_stats DROP CONSTRAINT combo_stats_pkey;
ALTER TABLE combo_stats ADD PRIMARY KEY (data_source, nivel, combo);

ALTER TABLE combo_steps ADD COLUMN nivel text NOT NULL DEFAULT 'grueso' CHECK (nivel IN ('grueso', 'fino'));
ALTER TABLE combo_steps DROP CONSTRAINT combo_steps_pkey;
ALTER TABLE combo_steps ADD PRIMARY KEY (data_source, nivel, from_combo, to_combo);

-- Las vistas `SELECT *` de la 036 fijaron sus columnas al crearse: se recrean para sumar `nivel`, que queda al final.
-- CREATE OR REPLACE conserva los comentarios de las demás columnas y los permisos de la vista.
CREATE OR REPLACE VIEW capa.combo_stats AS SELECT * FROM combo_stats;
CREATE OR REPLACE VIEW capa.combo_steps AS SELECT * FROM combo_steps;

COMMENT ON VIEW capa.combo_stats IS 'Por combinación de verticales usadas en un mes, en dos niveles (grueso: grupos rest, turbo, retail; fino: verticales una por una): personas-mes, pedidos, gasto y retención al mes siguiente, medidos en las personas de cada fuente. Es una correlación, no un efecto.';
COMMENT ON VIEW capa.combo_steps IS 'De qué combinación pasan las personas a cuál al mes siguiente, en dos niveles (grueso: grupos; fino: verticales), con cuántas personas y qué probabilidad.';

COMMENT ON COLUMN capa.combo_stats.combo IS 'Combinación usada en el mes, unida por «+»; «ninguna» si no hubo pedidos. Gruesa: grupos en el orden rest, turbo, retail. Fina: verticales en el orden restaurantes, turbo, supermercado, conveniencia, mall, chocolateria, farmacia, licores, favor, travel.';
COMMENT ON COLUMN capa.combo_stats.nivel IS 'grueso (grupos de la tabla de Rappi: rest, turbo, retail) o fino (verticales una por una, más RappiFavor y RappiTravel).';
COMMENT ON COLUMN capa.combo_steps.from_combo IS 'Combinación en el mes de partida, del mismo nivel que la fila.';
COMMENT ON COLUMN capa.combo_steps.to_combo IS 'Combinación en el mes siguiente, del mismo nivel que la fila.';
COMMENT ON COLUMN capa.combo_steps.nivel IS 'grueso (grupos de la tabla de Rappi: rest, turbo, retail) o fino (verticales una por una, más RappiFavor y RappiTravel).';
