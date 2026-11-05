#!/usr/bin/env bash
# Retención de datos de personas (cada día, launchd): el texto de las búsquedas a los 90 días y las personas del
# prototipo sin actividad a los 180 (rappi-ia purge; ver docs/despliegue.md, "Qué se guarda y cuánto tiempo").
# shellcheck source=deploy/macos/comun.sh
. "$(dirname "$0")/comun.sh"
cd "$REPO_DIR/rappi-ia" || exit 1
salida=$(.venv/bin/python -m rappi_ia purge 2>&1) || { log "$salida"; avisar "La purga falló"; exit 1; }
while IFS= read -r linea; do log "purga: $linea"; done <<< "$salida"
