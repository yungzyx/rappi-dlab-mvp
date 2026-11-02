#!/usr/bin/env bash
# Caddy con la puerta de acceso, en 127.0.0.1:CADDY_PORT (solo el túnel entra desde afuera). Lo corre launchd.
# shellcheck source=deploy/macos/comun.sh
. "$(dirname "$0")/comun.sh"
export SRV_DIR API_PORT CADDY_PORT
exec caddy run --config "$(dirname "$0")/Caddyfile" --adapter caddyfile
