#!/usr/bin/env bash
# Espera a que termine `rappi refresh` (scraper) y actualiza la capa de IA con el catálogo nuevo:
# conceptos (con kNN), embeddings de texto, evaluación de la búsqueda (sin guardar τ) y datos simulados del panel.
# Uso:  ./scripts/despues-del-refresh.sh            (en otra pestaña de la Terminal; se puede cerrar con Ctrl+C)
# Variables: RAPPI_IA_PY (el python de rappi-ia, por defecto .venv/bin/python) y RAPPI_IA_DATA_DIR (por defecto data/).
set -euo pipefail
cd "$(dirname "$0")/.."
LOGS=${RAPPI_IA_DATA_DIR:-data}/logs
LOG="$LOGS/despues-del-refresh_$(date +%Y%m%d-%H%M%S).log"
mkdir -p "$LOGS"
echo "Log: $LOG"
# caffeinate (macOS) evita que el equipo se duerma; en Linux no existe ni hace falta.
AWAKE=()
if command -v caffeinate >/dev/null; then AWAKE=(caffeinate -i); fi
# "python -m rappi_scraper refresh" (Terminal), ".venv/bin/rappi refresh" o la tarea semanal completa (launchd). Sin
# pgrep (un contenedor mínimo) no hay cómo verlo: sigue.
while command -v pgrep >/dev/null && pgrep -f "rappi(_scraper)? refresh|refresh-semanal|post-refresh" >/dev/null; do
  echo "$(date +%H:%M) el scraper sigue descargando; reviso de nuevo en 10 min…" | tee -a "$LOG"
  sleep 600
done
echo "$(date +%H:%M) refresh terminado: actualizando rappi-ia" | tee -a "$LOG"
${AWAKE[@]+"${AWAKE[@]}"} make post-refresh PY="${RAPPI_IA_PY:-.venv/bin/python}" 2>&1 | tee -a "$LOG"
