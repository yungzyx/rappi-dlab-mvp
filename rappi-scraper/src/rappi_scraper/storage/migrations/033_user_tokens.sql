-- Identidad anónima firmada (A-C2, F-I1): la API firma el id de cada persona del prototipo (`POST /session`) y desde
-- ahí exige ese token para leer, escribir o borrar sus datos. Un id de antes de la firma (sin token) la app lo puede
-- reclamar una sola vez, para no perder lo que ya tenía; esta columna dice si ya se reclamó. Aditivo: las filas
-- existentes quedan en NULL (reclamables una vez si son del prototipo; las simuladas nunca se reclaman).

ALTER TABLE app_users ADD COLUMN token_issued_at timestamptz;
COMMENT ON COLUMN app_users.token_issued_at IS 'Cuándo la API firmó la sesión de este id (POST /session, o el primer dato que llegó con su token). NULL: un id del prototipo de antes de la identidad firmada, que la app puede reclamar una sola vez; en los usuarios simulados siempre NULL.';
