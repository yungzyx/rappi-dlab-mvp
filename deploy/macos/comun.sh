# shellcheck shell=bash
# Variables y funciones comunes de los scripts de deploy/macos (se carga con `.`, no se ejecuta).
# El directorio de trabajo (configuración con secretos, archivos servidos, registros y respaldos) vive fuera del repo:
# TUNEL_DIR, por defecto ~/rappi-tunel. Su archivo `tunel.env` sale de deploy/macos/env.example.
set -euo pipefail
eval "$(/opt/homebrew/bin/brew shellenv)"

TUNEL_DIR=${TUNEL_DIR:-$HOME/rappi-tunel}
[ -f "$TUNEL_DIR/tunel.env" ] || { echo "Falta $TUNEL_DIR/tunel.env (ver deploy/macos/env.example)" >&2; exit 1; }
set -a
# shellcheck disable=SC1091
. "$TUNEL_DIR/tunel.env"
set +a

REPO_DIR=${REPO_DIR:?REPO_DIR en tunel.env: la copia del repo que se sirve}
SRV_DIR="$TUNEL_DIR/srv"
LOG_DIR="$TUNEL_DIR/logs"
RESPALDOS_DIR="$TUNEL_DIR/respaldos"
API_PORT=${API_PORT:-8100}
CADDY_PORT=${CADDY_PORT:-8080}
TUNEL_METRICAS=${TUNEL_METRICAS:-127.0.0.1:20241}
LABEL=${LABEL:-cl.rappidlab}
mkdir -p "$LOG_DIR" "$RESPALDOS_DIR" "$SRV_DIR"

log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }
avisar() { # notificación de macOS (en la sesión del usuario) además del registro
  log "$*"
  osascript -e "display notification \"${*//\"/}\" with title \"Demo rappi-dlab\"" >/dev/null 2>&1 || true
}
reiniciar() { launchctl kickstart -k "gui/$(id -u)/$LABEL.$1"; }
api_sana() { curl -fsS -o /dev/null --max-time 10 "http://127.0.0.1:$API_PORT/health"; }
