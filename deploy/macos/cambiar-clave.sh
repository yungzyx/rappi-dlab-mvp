#!/usr/bin/env bash
# Cambia la clave de la puerta de acceso de la demo: la pide dos veces sin mostrarla, guarda solo su hash
# (caddy hash-password) en tunel.env y reinicia Caddy. La clave no queda en ningún archivo: guárdala en tu gestor de
# contraseñas. Uso: deploy/macos/cambiar-clave.sh [usuario]   (sin usuario, deja el de tunel.env)
# shellcheck source=deploy/macos/comun.sh
. "$(dirname "$0")/comun.sh"

read -r -s -p "Clave nueva (12 caracteres o más): " clave; echo
read -r -s -p "Repítela: " otra; echo
if [ "$clave" != "$otra" ]; then echo "No coinciden: no cambié nada." >&2; exit 1; fi
if [ "${#clave}" -lt 12 ]; then echo "Muy corta (mínimo 12): no cambié nada." >&2; exit 1; fi
hash=$(printf '%s\n' "$clave" | caddy hash-password)
unset clave otra

python3 - "$TUNEL_DIR/tunel.env" "$hash" "${1:-}" <<'EOF'
import os, sys
ruta, hash_, usuario = sys.argv[1:4]
lineas = [l for l in open(ruta).read().splitlines() if not l.startswith("BASIC_AUTH_HASH=")]
if usuario:
    lineas = [l for l in lineas if not l.startswith("BASIC_AUTH_USER=")] + [f"BASIC_AUTH_USER='{usuario}'"]
lineas.append(f"BASIC_AUTH_HASH='{hash_}'")
tmp = ruta + ".tmp"
with open(tmp, "w") as f:
    f.write("\n".join(lineas) + "\n")
os.chmod(tmp, 0o600)
os.replace(tmp, ruta)
EOF

rm -f "$TUNEL_DIR/credenciales.txt"  # la clave anterior ya no sirve
reiniciar caddy
for _ in $(seq 1 15); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:$CADDY_PORT/")" = 401 ] && break
  sleep 1
done
if [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:$CADDY_PORT/")" = 401 ]; then
  log "Clave cambiada: la puerta ya pide la nueva."
else
  log "Caddy no volvió a responder: revisa $LOG_DIR/caddy.log" >&2
  exit 1
fi
