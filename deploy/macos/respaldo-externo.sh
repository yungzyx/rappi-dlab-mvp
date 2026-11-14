#!/usr/bin/env bash
# Copia fuera del equipo (opcional y apagada): copia el respaldo más nuevo de TUNEL_DIR/respaldos a la carpeta
# RESPALDO_EXTERNO_DIR (un disco externo o una carpeta sincronizada) y comprueba que la copia tenga el mismo tamaño y
# la misma suma SHA-256 antes de darle su nombre final. Sin RESPALDO_EXTERNO_DIR no hace nada. No crea la carpeta: si
# no existe (un disco sin montar), avisa y no copia, para no llenar el disco interno con una carpeta que solo parecía
# externa. No borra nada en el destino. No viene programado: se corre a mano o se suma a launchd (README).
# El respaldo trae los datos de las personas del prototipo: el destino tiene que ser privado.
# Uso: deploy/macos/respaldo-externo.sh
# shellcheck source=deploy/macos/comun.sh
. "$(dirname "$0")/comun.sh"
destino_dir=${RESPALDO_EXTERNO_DIR:-}
if [ -z "$destino_dir" ]; then
  log "Sin RESPALDO_EXTERNO_DIR en tunel.env: no copio nada"
  exit 0
fi
[ -d "$destino_dir" ] || { avisar "Copia externa: no existe $destino_dir (¿el disco no está conectado?)"; exit 1; }

# shellcheck disable=SC2012 # los nombres los arma respaldo.sh (sin espacios ni saltos de línea)
ultimo=$(ls -t "$RESPALDOS_DIR"/*.dump 2>/dev/null | head -1 || true)
[ -n "$ultimo" ] || { avisar "Copia externa: no hay respaldos en $RESPALDOS_DIR"; exit 1; }
copia="$destino_dir/$(basename "$ultimo")"
suma() { shasum -a 256 "$1" | cut -d' ' -f1; }
bytes() { wc -c < "$1" | tr -d ' '; }

original=$(suma "$ultimo")
if [ -f "$copia" ] && [ "$(suma "$copia")" = "$original" ]; then
  log "Copia externa al día: $copia"
  exit 0
fi
trap 'rm -f "$copia.tmp"' EXIT  # una copia cortada o que no calza no queda a medias en el destino
cp "$ultimo" "$copia.tmp"
if [ "$(bytes "$copia.tmp")" != "$(bytes "$ultimo")" ] || [ "$(suma "$copia.tmp")" != "$original" ]; then
  avisar "Copia externa: $(basename "$ultimo") no quedó igual en $destino_dir (tamaño o suma distintos)"
  exit 1
fi
mv "$copia.tmp" "$copia"
log "Copia externa lista: $copia ($(du -h "$copia" | cut -f1), sha256 $original)"
