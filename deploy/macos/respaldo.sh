#!/usr/bin/env bash
# Respaldo de la base `rappi` (pg_dump -Fc) en TUNEL_DIR/respaldos. Lo corre launchd cada noche; actualizar.sh lo
# llama con el prefijo "pre-migracion" antes de migrar. Guarda los RESPALDOS_A_GUARDAR más nuevos de cada prefijo.
. "$(dirname "$0")/comun.sh"
prefijo=${1:-nocturno}
base=${RESPALDO_BASE:-rappi}
destino="$RESPALDOS_DIR/${prefijo}_${base}_$(date +%Y%m%d-%H%M%S).dump"

# Hace falta el doble de lo que pesa el último respaldo libre en disco: si no, avisa y no respalda.
ultimo=$(ls -t "$RESPALDOS_DIR"/*.dump 2>/dev/null | head -1 || true)
necesita_kb=$(( ${ultimo:+$(du -k "$ultimo" | cut -f1)}+0 ))
libre_kb=$(df -k "$RESPALDOS_DIR" | awk 'NR==2 {print $4}')
if [ "$libre_kb" -lt $(( necesita_kb * 2 + 5242880 )) ]; then
  avisar "Respaldo omitido: poco espacio en disco ($(( libre_kb / 1048576 )) GB libres)"
  exit 1
fi

pg_dump -Fc --no-owner -d "$base" -f "$destino.tmp"
pg_restore --list "$destino.tmp" > /dev/null   # el archivo se puede leer entero
mv "$destino.tmp" "$destino"
log "respaldo listo: $destino ($(du -h "$destino" | cut -f1))"

ls -t "$RESPALDOS_DIR/${prefijo}_${base}_"*.dump 2>/dev/null | tail -n +$(( ${RESPALDOS_A_GUARDAR:-3} + 1 )) | while read -r viejo; do
  rm -f "$viejo"
  log "respaldo antiguo borrado: $viejo"
done
