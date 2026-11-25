-- El juicio a mano de la muestra de búsqueda (los pares de rappi_ia/eval/planilla-busqueda-ids.json), hecho a ciegas
-- en "Juzgar la búsqueda" del panel. Un juicio vigente por par y juez: volver a juzgar lo reemplaza. El juez es un
-- rótulo corto ("J1"), nunca un nombre ni un correo. No guarda datos de personas del prototipo (ni user_id, ni
-- session_id, ni data_source): va entero en el respaldo de entrega. `rappi-ia eval-human --desde-base` lo lee.

CREATE TABLE search_judgments (
    pair_id    text NOT NULL CHECK (pair_id ~ '^P[0-9a-f]{10}$'),
    judge      text NOT NULL DEFAULT '' CHECK (judge ~ '^[A-Za-z0-9_-]{0,16}$'),
    level      smallint NOT NULL CHECK (level IN (0, 1, 2)),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (pair_id, judge)
);
COMMENT ON TABLE search_judgments IS 'Juicio a mano, a ciegas, de los pares (consulta, resultado) de la muestra de búsqueda: uno vigente por par y juez (rappi_ia/eval/human_judgments.py).';
COMMENT ON COLUMN search_judgments.pair_id IS 'Id del par en planilla-busqueda-ids.json (eval/sheets.py: pair_id): la vertical, la consulta y el producto.';
COMMENT ON COLUMN search_judgments.judge IS 'Rótulo del juez ("J1"; vacío si no se puso), nunca un nombre ni un correo: letras, números, - y _, hasta 16.';
COMMENT ON COLUMN search_judgments.level IS '2 "sirve", 1 "a medias", 0 "no sirve" (eval/sheets.py: VERDICTS).';
COMMENT ON COLUMN search_judgments.created_at IS 'Cuándo se juzgó el par por primera vez.';
COMMENT ON COLUMN search_judgments.updated_at IS 'Cuándo cambió el juicio por última vez.';
