-- 062: el contador de las guardias de ofertas. Cuántos candidatos sacaron las guardias (rappi-ia/src/rappi_ia/offers/
-- guards.py) al armar lo que Mochi propone por su cuenta, por día, población, momento y motivo: sin persona ni
-- producto. Lo escribe la API (offers/blocked.py) y lo lee el panel (/analytics/guardias).
CREATE TABLE guard_blocks (
    day date NOT NULL,
    source text NOT NULL CHECK (source IN ('synthetic', 'prototype')),
    moment text NOT NULL CHECK (moment <> ''),
    reason text NOT NULL CHECK (reason IN ('alcohol', 'mas18', 'farmacia', 'bebe', 'salud')),
    blocked integer NOT NULL CHECK (blocked > 0),
    PRIMARY KEY (day, source, moment, reason)
);

COMMENT ON TABLE guard_blocks IS
    'Lo que Mochi no ofreció: candidatos que las guardias de ofertas sacaron, agregados por día, población, momento y motivo, sin persona ni producto (offers/blocked.py).';
COMMENT ON COLUMN guard_blocks.day IS 'Día en hora de Chile.';
COMMENT ON COLUMN guard_blocks.source IS 'Población: synthetic o prototype; nunca se mezclan. Hoy solo la API escribe, con prototype.';
COMMENT ON COLUMN guard_blocks.moment IS 'Momento de la oferta (el de POST /agent/offer), pregunta (/agent/ask) o para_ti (/recommendations).';
COMMENT ON COLUMN guard_blocks.reason IS 'Motivo: alcohol, mas18 (tabaco, vapeo, bienestar sexual o marca +18 de la tienda), farmacia, bebe o salud.';
COMMENT ON COLUMN guard_blocks.blocked IS 'Candidatos sacados ese día (un producto buscado dos veces cuenta dos).';
