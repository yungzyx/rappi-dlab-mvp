-- Las personas del prototipo borradas ("Borrar mis datos", `rappi-ia olvidar` o la purga de inactivos) no vuelven: un
-- lote de eventos atrasado o una pestaña vieja con su token llegaba a `ensure_user`, que volvía a crear el mismo id y
-- guardaba datos bajo él (el token se valida solo por su firma). Aquí queda el SHA-256 del id, no el id: con eso
-- `ensure_user` y `GET /session` lo rechazan (401, la app pide una sesión nueva). Sin plazo: una fila por persona
-- borrada. No va en el respaldo de entrega (PERSON_TABLES de rappi_ia/delivery.py).

CREATE TABLE forgotten_users (
    id_hash      bytea PRIMARY KEY,
    forgotten_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE forgotten_users IS 'Personas del prototipo borradas ("Borrar mis datos", olvidar o la purga): el SHA-256 de su id, nunca el id. Su token deja de servir y el id no se vuelve a crear (events/store.py: ensure_user).';
COMMENT ON COLUMN forgotten_users.id_hash IS 'sha256 del user_id en UTF-8 (events/store.py: _id_hash).';
