-- Capa de perfiles, etapa 4 (docs/superpowers/specs/2026-10-06-capa-perfiles-design.md §3.7): segmentos de usuario.
-- Las reglas viven en segments.toml; aquí quedan su definición sembrada y qué segmentos tiene cada persona.
CREATE TABLE segment_defs (
    segment_id    text PRIMARY KEY,
    name          text NOT NULL,
    family        text NOT NULL,
    sensitive     boolean NOT NULL DEFAULT false,
    description   text NOT NULL DEFAULT '',
    rule          jsonb NOT NULL,
    rules_version text NOT NULL
);

CREATE TABLE user_segments (
    user_id     text NOT NULL REFERENCES app_users (user_id) ON DELETE CASCADE,
    segment_id  text NOT NULL REFERENCES segment_defs (segment_id) ON DELETE CASCADE,
    score       real NOT NULL,
    level       text NOT NULL CHECK (level IN ('bajo', 'medio', 'alto')),
    signals     integer NOT NULL,      -- señales distintas que cuentan
    evidence    jsonb NOT NULL DEFAULT '{}',  -- los 3 conceptos o atributos que más aportan y las fechas extremas
    first_seen  timestamptz,
    last_signal timestamptz,
    source      text NOT NULL DEFAULT 'regla' CHECK (source IN ('regla', 'curado')),
    run_id      bigint REFERENCES layer_runs (run_id) ON DELETE SET NULL,
    PRIMARY KEY (user_id, segment_id)
);
CREATE INDEX user_segments_segment_idx ON user_segments (segment_id, level);

CREATE TABLE user_segment_history (
    week       date NOT NULL,          -- lunes de la semana
    user_id    text NOT NULL REFERENCES app_users (user_id) ON DELETE CASCADE,
    segment_id text NOT NULL REFERENCES segment_defs (segment_id) ON DELETE CASCADE,
    score      real NOT NULL,
    level      text NOT NULL CHECK (level IN ('bajo', 'medio', 'alto')),
    PRIMARY KEY (week, user_id, segment_id)
);

COMMENT ON TABLE segment_defs IS 'Segmentos de usuario por comportamiento (compra sin gluten, hamburguesero…), sembrados desde segments.toml. Los sensibles se nombran por conducta y se marcan.';
COMMENT ON TABLE user_segments IS 'Segmentos de cada persona con puntaje, nivel y evidencia. Tabla interna: las vistas `capa` no exponen filas por usuario de segmentos sensibles.';
COMMENT ON TABLE user_segment_history IS 'Foto semanal de los segmentos de cada persona (cómo cambian en el tiempo).';
