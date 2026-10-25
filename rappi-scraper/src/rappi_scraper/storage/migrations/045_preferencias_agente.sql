-- Preferencias explícitas de cada persona con el agente (Mochi): lo que dice de sí misma, por chat («soy vegetariano»,
-- «no como maní», «mi tienda favorita es…») o en el panel del asistente. La app de Rappi guarda algo parecido en su
-- agente (alergias, dietas y cocinas favoritas: docs/investigacion/app-rappi-2026-10-25.md).
-- Reglas (rappi_ia/offers/preferences.py y offers/preferencias.toml):
-- - La dieta y las alergias solo filtran lo que Mochi muestra (respuestas, sugerencias y ofertas), por el nombre del
--   producto. Nunca son la razón (`reason`) de una oferta y no entran a segmentos, perfiles de gusto, el motor ni el
--   panel de negocio: una alergia es un dato de salud.
-- - Las cocinas y tiendas favoritas solo ordenan lo que ya se iba a mostrar. Ninguna sube una vertical: Licores y
--   Farmacia siguen subiendo solo por señales propias de la persona.
-- Es una tabla de personas: está en PERSON_TABLES (rappi_ia/delivery.py) y se borra con la persona («Olvidar» y la
-- purga de inactivas, en cascada). «Olvida mis preferencias» la vacía para esa persona.

CREATE TABLE agent_preferences (
    user_id    text NOT NULL REFERENCES app_users ON DELETE CASCADE,
    kind       text NOT NULL CHECK (kind IN ('dieta', 'alergia', 'cocina', 'tienda')),
    value      text NOT NULL CHECK (length(value) BETWEEN 1 AND 64),
    source     text NOT NULL CHECK (source IN ('synthetic', 'prototype')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, kind, value)
);

COMMENT ON TABLE agent_preferences IS 'Preferencias explícitas de cada persona con el agente: dieta y alergias (solo filtran lo que se muestra, por el nombre del producto; nunca son la razón de una oferta ni entran a segmentos, perfiles, motor o panel) y cocinas y tiendas favoritas (solo ordenan). Datos de personas: está en PERSON_TABLES (rappi_ia/delivery.py) y se borra con la persona («Olvidar» y la purga de inactivas, en cascada).';
COMMENT ON COLUMN agent_preferences.user_id IS 'Persona (id seudónimo).';
COMMENT ON COLUMN agent_preferences.kind IS 'dieta (vegetariano, vegano), alergia (maní, mariscos, gluten, lactosa), cocina (un concepto de comida) o tienda (una tienda o cadena del catálogo).';
COMMENT ON COLUMN agent_preferences.value IS 'La opción: el id de offers/preferencias.toml (dieta y alergia), el id del concepto (cocina) o el nombre de la tienda o cadena como está en el catálogo (tienda).';
COMMENT ON COLUMN agent_preferences.source IS 'Población: synthetic (generador con semilla) o prototype. Nunca se mezclan.';
COMMENT ON COLUMN agent_preferences.created_at IS 'Cuándo la persona la dijo o la marcó.';
