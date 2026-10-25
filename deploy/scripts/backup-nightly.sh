#!/usr/bin/env bash
# Respaldo nocturno del servidor (deploy/systemd/rappi-backup.timer, todos los días 04:15), dentro del contenedor jobs:
#   docker compose -f deploy/docker-compose.yml --profile jobs run --rm jobs bash deploy/scripts/backup-nightly.sh
# 1. pg_dump de la base de DATABASE_URL a nocturno_<fecha>.dump en el volumen de respaldos, revisado con
#    `pg_restore --list` antes de contarlo. Quedan los 3 nocturnos más nuevos; los semanales de `rappi refresh`
#    (rappi_*.dump) y los de antes de migrar (pre-migracion_*.dump) tienen su propia rotación y no se tocan.
# 2. La copia fuera del equipo con restic (RESTIC_REPOSITORY y RESTIC_PASSWORD, y las credenciales del almacenamiento):
#    7 diarios y 4 semanales. El repositorio se crea una vez a mano (`restic init`, ver docs/despliegue.md).
# Sin RESTIC_REPOSITORY respalda solo en el volumen y sale con 2: el timer queda en rojo hasta que haya copia afuera.
set -euo pipefail

: "${DATABASE_URL:?Falta DATABASE_URL (en el contenedor jobs es la de rappi_owner)}"
BACKUPS=${RAPPI_DATA_DIR:-/data}/backups
KEEP=3
PG_DUMP=${PG_DUMP:-pg_dump}
case $PG_DUMP in
  */*) PG_RESTORE=${PG_DUMP%/*}/pg_restore ;;  # el pg_restore de la misma versión
  *) PG_RESTORE=pg_restore ;;
esac

# La clave, en un archivo de claves temporal que se borra al salir (pgpass.sh); pg_dump recibe la URL sin ella.
# shellcheck source=deploy/scripts/pgpass.sh
. "$(dirname "$0")/pgpass.sh"
partial=""
trap 'rm -f "${PGPASSFILE:-}" ${partial:+"$partial"}' EXIT
pgpass_from_database_url

mkdir -p "$BACKUPS"
# Un volcado cortado de golpe (SIGKILL, apagado) no corre el trap y deja su .part. Los de más de 6 horas (el límite de
# rappi-backup.service) son de esos; uno más nuevo puede ser de otro respaldo en curso.
find "$BACKUPS" -maxdepth 1 -name 'nocturno_*.dump.part' -mmin +360 -exec rm -f {} +
target=$BACKUPS/nocturno_$(date +%Y%m%d-%H%M%S).dump
partial=$target.part
# Primero a .part: un volcado cortado (disco lleno, corte) nunca pasa por bueno ni expulsa a uno sano.
"$PG_DUMP" -Fc --file="$partial" --dbname="$PG_URL"
"$PG_RESTORE" --list "$partial" > /dev/null
mv "$partial" "$target"
partial=""
echo "$(date '+%F %T') respaldo en $target"

# Rotación: quedan los KEEP más nuevos por fecha de modificación (no por nombre: con otra zona horaria o un reloj
# corregido, el nombre de uno nuevo puede quedar «antes» que los anteriores). El recién hecho nunca se borra.
for dump in "$BACKUPS"/nocturno_*.dump; do
  [ "$dump" != "$target" ] || continue
  newer=0
  for other in "$BACKUPS"/nocturno_*.dump; do
    if [ "$other" -nt "$dump" ]; then newer=$((newer + 1)); fi
  done
  if [ "$newer" -ge "$KEEP" ]; then rm -f "$dump"; fi
done

if [ -z "${RESTIC_REPOSITORY:-}" ]; then
  echo "Sin copia fuera del equipo: define RESTIC_REPOSITORY (docs/despliegue.md)." >&2
  exit 2
fi
# Un host fijo (cada `docker compose run` es un contenedor con otro nombre) y una etiqueta: así `forget` agrupa todos
# los respaldos nocturnos aunque cada uno sea un archivo con otro nombre.
restic backup --host rappi --tag nocturno "$target"
restic forget --host rappi --tag nocturno --group-by host,tags --keep-daily 7 --keep-weekly 4 --prune
echo "$(date '+%F %T') copia fuera del equipo al día"
