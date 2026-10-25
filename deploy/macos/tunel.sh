#!/usr/bin/env bash
# Túnel de Cloudflare hacia Caddy, con HTTPS de Cloudflare. Sin TUNNEL_TOKEN es un túnel rápido (sin cuenta): la URL
# ….trycloudflare.com cambia en cada inicio y el vigilante la anota en url.txt. Con TUNNEL_TOKEN (un túnel con nombre
# creado en una cuenta de Cloudflare, con un dominio propio) la URL es fija. Lo corre launchd.
. "$(dirname "$0")/comun.sh"
if [ -n "${TUNNEL_TOKEN:-}" ]; then
  exec cloudflared tunnel --no-autoupdate --metrics "$TUNEL_METRICAS" run --token "$TUNNEL_TOKEN"
fi
exec cloudflared tunnel --no-autoupdate --metrics "$TUNEL_METRICAS" --url "http://127.0.0.1:$CADDY_PORT"
