#!/usr/bin/env bash
# Roles de la base. El entrypoint de la imagen de Postgres lo corre una sola vez, como superusuario, cuando el
# volumen pgdata está vacío. Las claves vienen del archivo de entorno (RAPPI_OWNER_PASSWORD, RAPPI_API_PASSWORD) y
# psql las lee con \getenv: no pasan por la línea de comandos.
#   rappi_owner: dueño de la base y de las tablas; lo usan la migración y los trabajos (restaurar, descargar, respaldar).
#   rappi_api:   la API; lee todo y escribe solo los datos de las personas (los permisos los da deploy/db/grants.sql).
set -euo pipefail

: "${RAPPI_OWNER_PASSWORD:?Falta RAPPI_OWNER_PASSWORD en el archivo de entorno (deploy/.env.example)}"
: "${RAPPI_API_PASSWORD:?Falta RAPPI_API_PASSWORD en el archivo de entorno (deploy/.env.example)}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv owner_password RAPPI_OWNER_PASSWORD
\getenv api_password RAPPI_API_PASSWORD
\getenv db POSTGRES_DB
SET password_encryption = 'scram-sha-256';
CREATE ROLE rappi_owner LOGIN PASSWORD :'owner_password';
CREATE ROLE rappi_api LOGIN PASSWORD :'api_password';

-- rappi_owner es dueño de la base y, con ella, del esquema public (pg_database_owner).
ALTER DATABASE :"db" OWNER TO rappi_owner;
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
-- Solo CONNECT: la API no crea tablas temporales (las usan los trabajos, como rappi_owner).
GRANT CONNECT ON DATABASE :"db" TO rappi_api;

-- pgvector no es una extensión «trusted»: solo un superusuario la crea. Las migraciones y los dumps la piden con
-- IF NOT EXISTS, así que con esto rappi_owner migra y restaura sin ser superusuario. pg_prewarm (migración 034) es la
-- precarga de los índices de la búsqueda al arrancar la API; sin ella la API funciona igual, en frío.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_prewarm;
SQL

echo "init-roles: rappi_owner y rappi_api creados en $POSTGRES_DB."
