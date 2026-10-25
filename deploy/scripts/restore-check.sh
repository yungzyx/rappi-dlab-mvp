#!/usr/bin/env bash
# Prueba de restauración: una vez al mes, a mano, en el servidor (docs/despliegue.md). Un respaldo que nunca se
# restauró no está probado.
#   deploy/scripts/restore-check.sh
# Restaura el respaldo más nuevo del volumen de respaldos en una base aparte, rappi_restore_check, corre `rappi-ia
# doctor` contra ella y la elimina: es una copia de prueba, la base de la app no se toca. Crear y eliminar la base (con
# sus extensiones) lo hace el superusuario dentro del contenedor db, porque rappi_owner no crea bases; restaurar y
# revisar, el contenedor jobs como rappi_owner, igual que en el primer despliegue.
# RAPPI_ENV_FILE: el archivo de entorno (por defecto /etc/rappi/rappi.env).
set -euo pipefail
cd "$(dirname "$0")/../.."
CHECK_DB=rappi_restore_check

compose() { docker compose --env-file "${RAPPI_ENV_FILE:-/etc/rappi/rappi.env}" -f deploy/docker-compose.yml "$@"; }
# psql como superusuario por el socket del contenedor db (sin clave); el SQL entra por stdin.
# shellcheck disable=SC2016  # POSTGRES_USER y $1 se expanden en el contenedor
superuser_sql() {
  compose exec -T db sh -c 'exec psql -v ON_ERROR_STOP=1 -q --username "${POSTGRES_USER:-postgres}" --dbname "$1"' \
    sh "$1"
}
drop_check_db() {
  printf 'SET client_min_messages TO warning;\nDROP DATABASE IF EXISTS %s WITH (FORCE);\n' "$CHECK_DB" | superuser_sql postgres
}

drop_check_db  # la de una prueba anterior que se cortó
trap drop_check_db EXIT
echo "CREATE DATABASE $CHECK_DB OWNER rappi_owner;" | superuser_sql postgres
# pgvector, unaccent y pg_prewarm no son extensiones «trusted»: las crea el superusuario, como init-roles.sh en la base
# de la app (un dump que trae una que falta no se restaura como rappi_owner).
echo "CREATE EXTENSION vector; CREATE EXTENSION unaccent; CREATE EXTENSION pg_prewarm;" | superuser_sql "$CHECK_DB"

# En el contenedor jobs: la URL de rappi_owner con la base de prueba (DATABASE_URL termina en /<base>, sin opciones).
# El comentario de las extensiones se salta: las creó el superusuario y rappi_owner no puede cambiarlo.
compose --profile jobs run --rm -T jobs bash -s <<'EN_EL_CONTENEDOR'
set -euo pipefail
export DATABASE_URL="${DATABASE_URL%/*}/rappi_restore_check"
. deploy/scripts/pgpass.sh
list=$(mktemp)
trap 'rm -f "${PGPASSFILE:-}" "$list"' EXIT
pgpass_from_database_url
# Antes de restaurar: la URL derivada tiene que llevar a la base de prueba y nunca a la de la app.
current=$(psql --dbname="$PG_URL" --no-psqlrc -Atc 'SELECT current_database()')
if [ "$current" != rappi_restore_check ]; then
  echo "La conexión derivada de DATABASE_URL lleva a «$current», no a rappi_restore_check: no restauro." >&2
  exit 1
fi
dump=$(ls -t "${RAPPI_DATA_DIR:-/data}"/backups/*.dump | head -n 1)
echo "$(date '+%F %T') restaurando $dump en rappi_restore_check"
pg_restore --list "$dump" | grep -v "COMMENT - EXTENSION" > "$list"
PGOPTIONS="-c maintenance_work_mem=1GB" pg_restore --dbname="$PG_URL" --no-owner --no-privileges --exit-on-error \
  --use-list="$list" "$dump"
rappi-ia doctor
EN_EL_CONTENEDOR
echo "$(date '+%F %T') prueba de restauración bien: el respaldo más nuevo se restaura y la base queda lista."
