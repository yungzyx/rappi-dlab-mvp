#!/usr/bin/env bash
# Respaldo de la base `rappi` (pg_dump -Fc) en TUNEL_DIR/respaldos. Lo corre launchd cada noche; actualizar.sh lo
# llama con el prefijo "pre-migracion" antes de migrar. Cuando el respaldo terminó bien, retencion.sh manda a la
# Papelera los antiguos de los dos tipos (RESPALDOS_NOCTURNOS_A_GUARDAR y RESPALDOS_PRE_MIGRACION_A_GUARDAR).
# shellcheck source=deploy/macos/comun.sh
. "$(dirname "$0")/comun.sh"
prefijo=${1:-nocturno}
base=${RESPALDO_BASE:-rappi}
destino="$RESPALDOS_DIR/${prefijo}_${base}_$(date +%Y%m%d-%H%M%S).dump"
trap 'rm -f "$destino.tmp"' EXIT  # si pg_dump o la revisión fallan, no deja un .tmp de ~2 GB

# Hace falta el doble de lo que pesa el último respaldo libre en disco, más 5 GB: si no, avisa y no respalda.
if ! falta=$(disco_para_respaldo); then
  avisar "Respaldo omitido: $falta"
  exit 1
fi

pg_dump -Fc --no-owner -d "$base" -f "$destino.tmp"
pg_restore --list "$destino.tmp" > /dev/null   # el archivo se puede leer entero
mv "$destino.tmp" "$destino"
log "respaldo listo: $destino ($(du -h "$destino" | cut -f1))"

# Recién aquí, con el respaldo nuevo en su lugar: si algo de lo anterior falló, set -e ya cortó el script.
codigo=0
"$(dirname "$0")/retencion.sh" "$destino" || codigo=$?
case $codigo in
  0) ;;
  3) avisar "Respaldos antiguos en $RESPALDOS_DIR/para-borrar (no hay trash): siguen ocupando disco" ;;
  *) avisar "Retención de respaldos omitida (código $codigo): ver el registro del respaldo" ;;
esac
