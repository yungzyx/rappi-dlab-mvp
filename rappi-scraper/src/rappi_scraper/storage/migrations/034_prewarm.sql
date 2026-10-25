-- Precarga de los índices de la búsqueda (latencia de /search en frío). La primera búsqueda en una vertical leía del
-- disco su índice HNSW (restaurantes, ~740 MB) y su índice de texto sin tildes: hasta un segundo por vertical. Al
-- arrancar, la API los lee en un hilo aparte con pg_prewarm(…, 'read') (rappi_ia/api/prewarm.py, API_PREWARM).
-- pg_prewarm no es una extensión «trusted»: solo un superusuario la crea. En local migra el superusuario; en producción
-- migra rappi_owner y la crea deploy/db/init-roles.sh (en un volumen ya inicializado, a mano: docs/despliegue.md). Es
-- opcional, así que esta migración nunca falla por ella: sin permiso, o en un Postgres sin contrib (sin la extensión:
-- feature_not_supported desde Postgres 15, undefined_file antes), la deja como estaba y la API funciona igual, sin
-- precarga. El comentario lo puede poner solo el dueño de la extensión (quien la creó), así que va en el mismo bloque:
-- en producción, donde la creó el superusuario, el comentario no queda.

DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_prewarm;
    COMMENT ON EXTENSION pg_prewarm IS 'Precarga de relaciones: al arrancar, la API lee los índices HNSW y de texto sin tildes de search_documents (rappi_ia/api/prewarm.py).';
EXCEPTION WHEN insufficient_privilege OR feature_not_supported OR undefined_file THEN
    RAISE NOTICE 'pg_prewarm: no se pudo crear o comentar (%); la API funciona igual, sin precarga', SQLERRM;
END
$$;
