#!/usr/bin/env bash
# Retención de datos de personas (cada día, launchd): el texto de las búsquedas a los 90 días y las personas del
# prototipo sin actividad a los 180 (rappi-ia purge; ver docs/despliegue.md, «Qué se guarda y cuánto tiempo»).
. "$(dirname "$0")/comun.sh"
cd "$REPO_DIR/rappi-ia" || exit 1
log "purga: $(.venv/bin/python -m rappi_ia purge 2>&1 | tail -1)"
