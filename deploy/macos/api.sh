#!/usr/bin/env bash
# La API en modo producción, solo en 127.0.0.1 (Caddy la expone en /api detrás de la puerta). Lo corre launchd.
. "$(dirname "$0")/comun.sh"
cd "$REPO_DIR/rappi-ia" || exit 1
export API_ENV=production API_ENABLE_ANALYTICS=1 API_CORS_ORIGINS='' HF_HUB_OFFLINE=1
exec .venv/bin/python -m uvicorn rappi_ia.api.app:app --host 127.0.0.1 --port "$API_PORT" \
  --workers "${API_WORKERS:-2}" --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log
