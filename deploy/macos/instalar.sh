#!/usr/bin/env bash
# Instala (o reinstala) los servicios de launchd de la demo pública en ~/Library/LaunchAgents y los arranca:
#   api, caddy y tunel   siempre arriba (launchd los reinicia si se caen y los arranca al iniciar sesión)
#   vigilante            cada 5 minutos
#   actualizar           cada 15 minutos: si main cambió, la demo se actualiza sola (despliegue continuo)
#   respaldo             cada noche a las 03:30
#   purga                cada día a las 04:15
# Uso: deploy/macos/instalar.sh            (desinstalar: deploy/macos/instalar.sh --quitar)
# shellcheck source=deploy/macos/comun.sh
. "$(dirname "$0")/comun.sh"
DIR=$(cd "$(dirname "$0")" && pwd)
AGENTS="$HOME/Library/LaunchAgents"
UID_GUI="gui/$(id -u)"
mkdir -p "$AGENTS"

servicios=(api caddy tunel vigilante actualizar respaldo purga)

quitar() {
  for s in "${servicios[@]}"; do
    launchctl bootout "$UID_GUI/$LABEL.$s" 2>/dev/null || true
    # bootout vuelve antes de que el servicio termine de cerrarse: registrarlo de nuevo antes falla con "5: I/O error".
    for _ in $(seq 1 30); do launchctl print "$UID_GUI/$LABEL.$s" > /dev/null 2>&1 || break; sleep 1; done
    rm -f "$AGENTS/$LABEL.$s.plist"
  done
}

plist() { # $1 servicio, $2 bloque de cuándo corre (KeepAlive o calendario)
  cat > "$AGENTS/$LABEL.$1.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL.$1</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$DIR/$1.sh</string></array>
  <key>EnvironmentVariables</key><dict><key>TUNEL_DIR</key><string>$TUNEL_DIR</string></dict>
  <key>StandardOutPath</key><string>$LOG_DIR/$1.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/$1.log</string>
  $2
</dict>
</plist>
EOF
  plutil -lint -s "$AGENTS/$LABEL.$1.plist"
}

# El modelo de texto en la caché de Hugging Face, en el commit fijado en config.py: la API corre con HF_HUB_OFFLINE=1 y
# API_REQUIRE_SEMANTIC=1 (api.sh), así que sin él /health da 503. Si falta, se descarga una vez, como lo deja
# deploy/Dockerfile.api en la imagen. Antes de bajar los servicios: una reinstalación no deja la demo caída mientras baja.
if [ "${1:-}" != "--quitar" ]; then
  modelo='from rappi_ia import config; from sentence_transformers import SentenceTransformer; SentenceTransformer(config.TEXT_EMBEDDING_MODEL, revision=config.TEXT_EMBEDDING_REVISION, device="cpu")'
  if ! HF_HUB_OFFLINE=1 "$REPO_DIR/rappi-ia/.venv/bin/python" -c "$modelo" > /dev/null 2>&1; then
    log "Descargando el modelo de texto a la caché de Hugging Face"
    HF_HUB_OFFLINE=0 "$REPO_DIR/rappi-ia/.venv/bin/python" -c "$modelo"
  fi
  log "Modelo de texto en la caché"
fi

quitar
rm -rf "$TUNEL_DIR/.vigilante"  # los contadores de fallas de una instalación anterior no cuentan
[ "${1:-}" = "--quitar" ] && { log "Servicios quitados"; exit 0; }

siempre='<key>RunAtLoad</key><true/><key>KeepAlive</key><true/><key>ThrottleInterval</key><integer>10</integer>'
plist api "$siempre"
plist caddy "$siempre"
plist tunel "$siempre"
# Sin RunAtLoad: la primera revisión a los 5 minutos, cuando la API ya cargó el modelo.
plist vigilante '<key>StartInterval</key><integer>300</integer>'
plist actualizar '<key>StartInterval</key><integer>900</integer>'
plist respaldo '<key>StartCalendarInterval</key><dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>30</integer></dict>'
plist purga '<key>StartCalendarInterval</key><dict><key>Hour</key><integer>4</integer><key>Minute</key><integer>15</integer></dict>'

for s in "${servicios[@]}"; do
  launchctl bootstrap "$UID_GUI" "$AGENTS/$LABEL.$s.plist"
done
log "Servicios instalados: ${servicios[*]} (registros en $LOG_DIR)"
