#!/usr/bin/env bash
# La API en modo producción, solo en 127.0.0.1 (Caddy la expone en /api detrás de la puerta). Lo corre launchd.
# El modelo de texto sale de la caché, sin consultar huggingface.co (HF_HUB_OFFLINE=1; instalar.sh lo deja ahí), y sin
# él la API no está lista (API_REQUIRE_SEMANTIC=1: /health da 503 y el vigilante avisa), igual que en el servidor.
# shellcheck source=deploy/macos/comun.sh
. "$(dirname "$0")/comun.sh"
cd "$REPO_DIR/rappi-ia" || exit 1
# Con su propio rol (rol-api.sh) si existe: lee todo y escribe solo los datos de las personas. Sin él, como antes, con
# el usuario del Mac. El rol va en PGUSER: la URL de los .env (postgresql:///rappi) no nombra usuario.
role=${API_DB_ROLE:-rappi_api}
if [ "$(psql -X -Atq -d postgres -c "SELECT 1 FROM pg_roles WHERE rolname = '$role'" 2>/dev/null)" = 1 ]; then
  export PGUSER=$role
else
  log "Sin el rol $role: la API usa el usuario del Mac (deploy/macos/rol-api.sh lo crea)"
fi
export API_ENV=production API_ENABLE_ANALYTICS=1 API_CORS_ORIGINS='' HF_HUB_OFFLINE=1 API_REQUIRE_SEMANTIC=1
exec .venv/bin/python -m uvicorn rappi_ia.api.app:app --host 127.0.0.1 --port "$API_PORT" \
  --workers "${API_WORKERS:-2}" --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log
