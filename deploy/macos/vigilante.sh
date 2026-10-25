#!/usr/bin/env bash
# Cada 5 minutos (launchd): revisa la API, Caddy y el túnel, y reinicia lo que lleve dos revisiones seguidas caído.
# Anota la URL pública vigente en url.txt (en un túnel rápido cambia en cada inicio) y avisa si cambió. Además rota
# los registros que pasan de 20 MB, para que no llenen el disco.
. "$(dirname "$0")/comun.sh"
ESTADO="$TUNEL_DIR/.vigilante"
mkdir -p "$ESTADO"

revisar() { # $1 servicio, $2… comando que responde 0 si está bien
  local servicio=$1; shift
  if "$@"; then rm -f "$ESTADO/$servicio"; return; fi
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
revisar caddy caddy_vivo
revisar tunel tunel_listo

if [ -z "${TUNNEL_TOKEN:-}" ]; then
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
