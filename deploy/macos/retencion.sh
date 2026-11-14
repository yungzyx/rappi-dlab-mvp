#!/usr/bin/env bash
# Retención de los respaldos de respaldo.sh, que la llama solo después de que un respaldo nuevo terminó bien:
#   deploy/macos/retencion.sh <el respaldo recién terminado>
# En la carpeta de ese respaldo deja los RESPALDOS_PRE_MIGRACION_A_GUARDAR (2) `pre-migracion_<base>_*.dump` y los
# RESPALDOS_NOCTURNOS_A_GUARDAR (RESPALDOS_A_GUARDAR o 3) `nocturno_<base>_*.dump` más nuevos (por fecha de
# modificación) de la misma base, y saca los `.dump.tmp` de esos dos tipos con más de un día (de un respaldo cortado
# de golpe). Lo que saca va a la Papelera con `trash`; sin `trash`, o si falla, a `para-borrar/` en la misma carpeta.
# Nunca borra, nunca saca el respaldo recién hecho y no toca otros archivos (los `rappi_*.dump` de la descarga semanal,
# los de otra base, uno hecho a mano). No respalda: no carga comun.sh ni tunel.env (las variables llegan del entorno).
# Sale con 0 si terminó, 2 si no sacó nada porque algo no calza (el respaldo nuevo no existe, está vacío, mide menos
# de la mitad del anterior, o una cantidad no es un entero mayor que 0) y 3 si algo quedó en para-borrar/.
set -euo pipefail
log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }
omitir() { log "Retención omitida: $*"; exit 2; }
bytes() { wc -c < "$1" | tr -d ' '; }

nuevo=${1:?Uso: retencion.sh <respaldo recién terminado>}
dir=$(dirname "$nuevo")
nombre=$(basename "$nuevo")
fecha='_[0-9]{8}-[0-9]{6}\.dump$'  # la que pone respaldo.sh: _AAAAMMDD-HHMMSS.dump
patron="^(nocturno|pre-migracion)_(.+)$fecha"
[[ $nombre =~ $patron ]] || omitir "$nombre no es un respaldo nocturno ni pre-migracion de respaldo.sh"
base=${BASH_REMATCH[2]}
[ -f "$nuevo" ] || omitir "no existe $nuevo"
[ -s "$nuevo" ] || omitir "$nuevo está vacío"

guardar_nocturno=${RESPALDOS_NOCTURNOS_A_GUARDAR:-${RESPALDOS_A_GUARDAR:-3}}
guardar_pre=${RESPALDOS_PRE_MIGRACION_A_GUARDAR:-2}
for n in "$guardar_nocturno" "$guardar_pre"; do
  [[ $n =~ ^[1-9][0-9]*$ ]] || omitir "la cantidad a guardar \"$n\" no es un entero mayor que 0"
done

# Los respaldos de un tipo y de esta base, del más nuevo al más viejo. El nombre exacto: con la base `rappi`, el
# patrón `nocturno_rappi_*` también tomaría los de `rappi_staging`.
respaldos() {
  local f resto
  # shellcheck disable=SC2012 # los nombres los arma respaldo.sh (sin espacios ni saltos de línea)
  ls -t "$dir/$1_${base}_"*.dump 2>/dev/null | while read -r f; do
    resto=${f#"$dir/$1_${base}"}
    [[ $resto =~ ^$fecha ]] && [ -f "$f" ] && echo "$f"
  done || true
}

# Tamaño razonable: al menos la mitad del más nuevo de los otros (un volcado cortado que pasó por bueno no expulsa a
# los sanos). La base solo crece entre respaldos; si se achica de verdad, la retención espera y lo dice.
anterior=""
while read -r f; do
  [ "$f" != "$nuevo" ] && [ -s "$f" ] || continue
  if [ -z "$anterior" ] || [ "$f" -nt "$anterior" ]; then anterior=$f; fi
done < <(respaldos nocturno; respaldos pre-migracion)
if [ -n "$anterior" ] && [ $(( $(bytes "$nuevo") * 2 )) -lt "$(bytes "$anterior")" ]; then
  omitir "$nuevo ($(bytes "$nuevo") bytes) mide menos de la mitad de $anterior ($(bytes "$anterior") bytes)"
fi

a_para_borrar=0
sacar() {
  if command -v trash > /dev/null 2>&1 && trash "$1"; then
    log "a la Papelera: $1"
  else
    mkdir -p "$dir/para-borrar"
    [ ! -e "$dir/para-borrar/$(basename "$1")" ] || { log "ya hay uno igual en para-borrar/, lo dejo: $1"; return; }
    mv "$1" "$dir/para-borrar/"
    log "sin trash: movido a $dir/para-borrar/ (sigue ocupando disco hasta borrarlo a mano): $(basename "$1")"
    a_para_borrar=1
  fi
}

for tipo in nocturno pre-migracion; do
  guardar=$guardar_nocturno
  [ "$tipo" = nocturno ] || guardar=$guardar_pre
  while read -r f; do
    [ "$f" = "$nuevo" ] || sacar "$f"
  done < <(respaldos "$tipo" | tail -n +$(( guardar + 1 )))
done
# Más de un día (1440 minutos; -mtime redondea distinto en el find de macOS y en el de Linux).
while read -r f; do
  sacar "$f"
done < <(find "$dir" -maxdepth 1 -type f \( -name 'nocturno_*.dump.tmp' -o -name 'pre-migracion_*.dump.tmp' \) \
           -mmin +1440)

[ "$a_para_borrar" = 0 ] || exit 3
