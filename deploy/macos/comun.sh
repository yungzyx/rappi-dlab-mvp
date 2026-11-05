# shellcheck shell=bash
# Variables y funciones comunes de los scripts de deploy/macos (se carga con `.`, no se ejecuta).
# El directorio de trabajo (configuración con secretos, archivos servidos, registros y respaldos) vive fuera del repo:
# TUNEL_DIR, por defecto ~/rappi-tunel. Su archivo `tunel.env` sale de deploy/macos/env.example.
set -Eeuo pipefail
# Homebrew (caddy, cloudflared, Postgres): launchd no carga el PATH del usuario. Apple Silicon o Intel.
brew_bin=$(command -v brew || true)
for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
  [ -n "$brew_bin" ] || { [ -x "$candidate" ] && brew_bin=$candidate; }
done
[ -n "$brew_bin" ] || { echo "No encuentro Homebrew (brew) en el PATH, /opt/homebrew ni /usr/local" >&2; exit 1; }
eval "$("$brew_bin" shellenv)"
unset brew_bin candidate

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
# Un comando que falla avisa antes de que set -e corte el script, con el comando (sin expandir: no muestra valores) y
# la línea (en el bash 3.2 de macOS, el de launchd, dentro de una función es la de la función). Solo en el proceso del
# script: el bash 3.2 dispara el trap dentro de un $(…) aunque el fallo esté en un if o un ||, y ahí no es un error.
trap '[ "$BASH_SUBSHELL" -ne 0 ] || avisar "$(basename "$0") falló en la línea $LINENO: $BASH_COMMAND"' ERR
reiniciar() { launchctl kickstart -k "gui/$(id -u)/$LABEL.$1"; }
api_sana() { curl -fsS -o /dev/null --max-time 10 "http://127.0.0.1:$API_PORT/health"; }
