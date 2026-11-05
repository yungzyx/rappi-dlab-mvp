#!/usr/bin/env bash
# Cada 5 minutos (launchd): revisa la API, Caddy y el túnel, y reinicia lo que lleve dos revisiones seguidas caído.
# Anota la URL pública vigente en url.txt (en un túnel rápido cambia en cada inicio) y avisa si cambió. Además rota
# los registros que pasan de 20 MB, para que no llenen el disco.
# shellcheck source=deploy/macos/comun.sh
. "$(dirname "$0")/comun.sh"
ESTADO="$TUNEL_DIR/.vigilante"
mkdir -p "$ESTADO"

todo_bien=1  # pasa a 0 si algo no respondió en esta vuelta
revisar() { # $1 servicio, $2… comando que responde 0 si está bien
  local servicio=$1; shift
  if "$@"; then rm -f "$ESTADO/$servicio"; return; fi
  todo_bien=0
  local fallas=$(( $(cat "$ESTADO/$servicio" 2>/dev/null || echo 0) + 1 ))
  echo "$fallas" > "$ESTADO/$servicio"
  log "$servicio no responde ($fallas)"
  if [ "$fallas" -ge 2 ]; then
    avisar "Reiniciando $servicio: no respondía"
    reiniciar "$servicio"
    rm -f "$ESTADO/$servicio"
  fi
}

caddy_vivo() { # sin la clave responde 401: está vivo y la puerta funciona
  [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:$CADDY_PORT/")" = 401 ]
}
tunel_listo() { curl -fsS -o /dev/null --max-time 10 "http://$TUNEL_METRICAS/ready"; }

revisar api api_sana

# Dos búsquedas chicas mantienen en memoria el modelo de texto de cada proceso de la API (son dos) y los índices: sin
# uso, macOS los manda al disco y la primera búsqueda después de unas horas tardaba 7 a 14 s, o fallaba. Solo leen.
# Llevan el id "vigilante-…" (X-Request-ID) para que el resumen diario (resumen.sh) no las cuente como visitas.
for i in 1 2; do
  curl -fsS -o /dev/null --max-time 30 -H "X-Request-ID: vigilante-$(date +%s)-$i" \
    "http://127.0.0.1:$API_PORT/search?q=agua&limit=1" || true
done
revisar caddy caddy_vivo
revisar tunel tunel_listo

if [ -n "${PUBLIC_URL:-}" ]; then
  echo "$PUBLIC_URL" > "$TUNEL_DIR/url.txt"  # túnel con nombre: la URL es fija
elif [ -z "${TUNNEL_TOKEN:-}" ] && [ -z "${TUNNEL_NAME:-}" ]; then
  url=$(grep -ao 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOG_DIR/tunel.log" 2>/dev/null | tail -1 || true)
  if [ -n "$url" ] && [ "$url" != "$(cat "$TUNEL_DIR/url.txt" 2>/dev/null)" ]; then
    echo "$url" > "$TUNEL_DIR/url.txt"
    avisar "URL pública nueva: $url"
  fi
fi

for f in "$LOG_DIR"/*.log; do
  if [ -f "$f" ] && [ "$(wc -c < "$f")" -gt 20971520 ]; then
    cp "$f" "$f.1" && : > "$f"  # copiar y vaciar: launchd mantiene el archivo abierto
  fi
done

# Latido para un monitor externo (opcional, HEARTBEAT_URL en tunel.env): solo si la API, Caddy y el túnel respondieron.
# Si el Mac se apaga o pierde la red, el latido no llega y el monitor avisa desde afuera. No manda datos de nadie.
if [ "$todo_bien" = 1 ] && [ -n "${HEARTBEAT_URL:-}" ]; then
  curl -fsS -o /dev/null --max-time 10 "$HEARTBEAT_URL" || true
fi
