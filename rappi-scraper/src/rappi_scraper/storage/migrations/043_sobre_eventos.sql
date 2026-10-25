-- Sobre de cada evento de la app (docs/investigacion/app-rappi-2026-10-25.md, docs/capa-de-datos.md): lo que la app de
-- Rappi manda con cada evento y a nuestros eventos les faltaba. Todo es aditivo y nulo en las filas de antes.
-- - Id, hora y orden del cliente (`client_event_id`, `client_ts`, `seq`): un lote que se reintenta no duplica nada y el
--   orden fino de una sesión no depende de cuándo llegó el lote. `ts` sigue siendo la hora de llegada.
-- - Desde dónde (`surface`, `origin`, `position`): la pantalla, el bloque y el lugar en su lista de lo que se tocó, se
--   vio o se agregó. `origin` reemplaza a `payload.origen`; las filas de antes lo siguen teniendo en el payload, así que
--   quien lea el origen lee `coalesce(origin, payload ->> 'origen')`.
-- - La respuesta que lo originó (`request_id`): el id que la API pone en cada respuesta que ordena cosas (/search,
--   /agent/offer, /agent/ask, /recommendations, /profile/{id}/verticales, /catalog/home), el mismo X-Request-ID de su
--   línea en el log.
-- Y una tabla de sesiones (`app_sessions`): versión de la app, plataforma, modo y entrada, una vez por sesión en vez de
-- repetirlas en cada evento.

ALTER TABLE app_events
    ADD COLUMN client_event_id uuid,
    ADD COLUMN client_ts timestamptz,
    ADD COLUMN seq integer CHECK (seq >= 0),
    ADD COLUMN surface text CHECK (surface IN (
        'home', 'search', 'store', 'vertical', 'restaurants', 'turbo', 'deals', 'favorites', 'list', 'agent', 'cart',
        'checkout', 'tracking', 'orders'
    )),
    ADD COLUMN origin text CHECK (origin ~ '^[a-z0-9_-]{1,40}$'),
    ADD COLUMN position smallint CHECK (position BETWEEN 0 AND 999),
    ADD COLUMN request_id text CHECK (request_id ~ '^[A-Za-z0-9._-]{1,64}$');

-- Un reintento del mismo evento no entra dos veces (`ON CONFLICT DO NOTHING`); los eventos sin id (los del servidor y
-- los de antes) no se deduplican.
CREATE UNIQUE INDEX app_events_client_event_idx ON app_events (user_id, client_event_id)
    WHERE client_event_id IS NOT NULL;
CREATE INDEX app_events_request_idx ON app_events (request_id) WHERE request_id IS NOT NULL;

COMMENT ON COLUMN app_events.ts IS 'Hora en que el evento llegó a la API (o la del pedido, en order_placed). La hora en que pasó en la app es client_ts.';
COMMENT ON COLUMN app_events.client_event_id IS 'Id que la app le da a cada evento (uuid): reintentar un lote no lo duplica. Equivale al uuid (insert_id) de Amplitude. Nulo en los eventos del servidor y en los de antes de la migración 043.';
COMMENT ON COLUMN app_events.client_ts IS 'Hora del evento según la app. Solo se guarda si está a menos de 24 horas de ts; si no, queda nula.';
COMMENT ON COLUMN app_events.seq IS 'Orden del evento dentro de su sesión según la app (0, 1, 2…): ordena los eventos de un mismo lote.';
COMMENT ON COLUMN app_events.surface IS 'Pantalla donde estaba lo que se tocó, se vio o se agregó (home, search, store, agent, checkout…). Equivale a CONTEXT en la app de Rappi.';
COMMENT ON COLUMN app_events.origin IS 'Bloque o lista de donde salió (accesos, resultados, pasillo, para-ti, agent-<momento>…). Equivale a SOURCE o COMPONENT_NAME en Rappi. Antes de la migración 043 iba en payload.origen: leer coalesce(origin, payload ->> ''origen'').';
COMMENT ON COLUMN app_events.position IS 'Lugar en la lista que devolvió la API o que muestra la pantalla (0 = el primero). Equivale a COMPONENT_INDEX o INDEX en Rappi.';
COMMENT ON COLUMN app_events.request_id IS 'Id de la respuesta de la API de donde salió lo que se tocó (el request_id de /search, /agent/offer, /agent/ask, /recommendations, /profile/{id}/verticales o /catalog/home, igual al X-Request-ID del log). En una búsqueda es su id (search_id). Equivale a REQUEST_ID en Rappi.';

CREATE TABLE app_sessions (
    user_id     text NOT NULL REFERENCES app_users ON DELETE CASCADE,
    session_id  text NOT NULL,
    started_at  timestamptz NOT NULL,
    app_version text CHECK (app_version ~ '^[A-Za-z0-9._+-]{1,32}$'),
    platform    text CHECK (platform IN ('web', 'ios', 'android')),
    mode        text CHECK (mode IN ('propuesta', 'actual')),
    entry       text CHECK (entry IN ('directa', 'enlace', 'push')),
    source      text NOT NULL CHECK (source IN ('synthetic', 'prototype')),
    PRIMARY KEY (user_id, session_id)
);

COMMENT ON TABLE app_sessions IS 'Una fila por sesión de la app (30 minutos sin actividad la cierran): nace con su primer evento. Datos de personas: está en PERSON_TABLES (rappi_ia/delivery.py) y se borra con la persona («Olvidar» y la purga de inactivas, en cascada).';
COMMENT ON COLUMN app_sessions.user_id IS 'Persona (id seudónimo).';
COMMENT ON COLUMN app_sessions.session_id IS 'El session_id de sus eventos.';
COMMENT ON COLUMN app_sessions.started_at IS 'Hora del primer evento de la sesión que llegó (su client_ts, o la llegada si no la trae).';
COMMENT ON COLUMN app_sessions.app_version IS 'Versión de la app que la abrió (APP_VERSION en Rappi).';
COMMENT ON COLUMN app_sessions.platform IS 'web, ios o android (STORE_PLATFORM en Rappi). El prototipo es web.';
COMMENT ON COLUMN app_sessions.mode IS 'Modo de la app al empezar la sesión: propuesta (el prototipo con Mochi) o actual («Rappi hoy»).';
COMMENT ON COLUMN app_sessions.entry IS 'Cómo se abrió: directa, enlace (con una ruta o parámetros en la dirección) o push.';
COMMENT ON COLUMN app_sessions.source IS 'Población: synthetic (generador con semilla) o prototype. Nunca se mezclan.';
