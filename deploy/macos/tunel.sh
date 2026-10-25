#!/usr/bin/env bash
# Túnel de Cloudflare hacia Caddy, con HTTPS de Cloudflare. Lo corre launchd. Tres modos:
#   TUNNEL_NAME   un túnel con nombre de una cuenta de Cloudflare (`cloudflared tunnel login`, `tunnel create` y
#                 `tunnel route dns`; la credencial queda en ~/.cloudflared): URL fija, la de PUBLIC_URL.
#   TUNNEL_TOKEN  lo mismo, con el token de un túnel creado en el panel de Cloudflare.
#   ninguno       un túnel rápido sin cuenta: la URL ….trycloudflare.com cambia en cada inicio y el vigilante la anota.
. "$(dirname "$0")/comun.sh"
if [ -n "${TUNNEL_TOKEN:-}" ]; then
  exec cloudflared tunnel --no-autoupdate --metrics "$TUNEL_METRICAS" run --token "$TUNNEL_TOKEN"
fi
if [ -n "${TUNNEL_NAME:-}" ]; then
  exec cloudflared tunnel --no-autoupdate --metrics "$TUNEL_METRICAS" run --url "http://127.0.0.1:$CADDY_PORT" "$TUNNEL_NAME"
fi
exec cloudflared tunnel --no-autoupdate --metrics "$TUNEL_METRICAS" --url "http://127.0.0.1:$CADDY_PORT"
