#!/usr/bin/env bash
# Resumen de la API del día anterior (cada mañana, launchd): peticiones por ruta, lentas, errores 5xx y personas nuevas
# del prototipo (rappi-ia resumen-api; solo lee el registro y la base). Lo deja en RESUMEN_API_TXT (por defecto
# TUNEL_DIR/resumen-api.txt) y avisa con su segunda línea, la que dice lo que importa.
# shellcheck source=deploy/macos/comun.sh
. "$(dirname "$0")/comun.sh"
cd "$REPO_DIR/rappi-ia" || exit 1
destino=${RESUMEN_API_TXT:-$TUNEL_DIR/resumen-api.txt}
.venv/bin/python -m rappi_ia resumen-api --log "$LOG_DIR/api.log" --log "$LOG_DIR/api.log.1" > "$destino.tmp"
mv "$destino.tmp" "$destino"
avisar "API de ayer: $(sed -n 2p "$destino")"
