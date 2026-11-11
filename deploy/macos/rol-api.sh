#!/usr/bin/env bash
# La API con su propio rol en vez del superusuario del Mac (una vez; idempotente): crea API_DB_ROLE (por defecto
# rappi_api) si no existe y le da los permisos de deploy/db/grants.sql en la base de la copia que se sirve (lee todo y
# escribe solo los datos de las personas), con `rappi-ia deploy-migrate`. Después reinicia la API, que arranca con ese
# rol (api.sh). Con Postgres de Homebrew la conexión local es "trust": el rol no lleva clave. Si hay migraciones
# pendientes no hace nada: primero `actualizar.sh` (respalda y migra).
# Uso: deploy/macos/rol-api.sh [--sin-reiniciar]
# shellcheck source=deploy/macos/comun.sh
. "$(dirname "$0")/comun.sh"
cd "$REPO_DIR" || exit 1
role=${API_DB_ROLE:-rappi_api}
[[ "$role" =~ ^[a-z_][a-z0-9_]*$ ]] || { echo "API_DB_ROLE no es un nombre de rol válido: $role" >&2; exit 1; }

psql -X -Atq -d postgres -c "SELECT 1" > /dev/null || { echo "Postgres no responde: no hago nada." >&2; exit 1; }
if ! rappi-ia/.venv/bin/python -m rappi_ia migrate --solo-revisar > /dev/null 2>&1; then
  echo "Hay migraciones pendientes: corre deploy/macos/actualizar.sh --forzar y después este script." >&2
  exit 1
fi
if [ "$(psql -X -Atq -d postgres -c "SELECT 1 FROM pg_roles WHERE rolname = '$role'")" = 1 ]; then
  log "El rol $role ya existe"
else
  psql -X -q -v ON_ERROR_STOP=1 -d postgres -c "CREATE ROLE $role LOGIN"
  log "Rol $role creado"
fi
DB_API_ROLE=$role rappi-ia/.venv/bin/python -m rappi_ia deploy-migrate --sin-respaldo
log "Permisos de $role aplicados"
if [ "${1:-}" != "--sin-reiniciar" ]; then
  reiniciar api
  for _ in $(seq 1 60); do api_sana && break; sleep 3; done
  # Que de verdad se conecte con el rol: una sesión de la API con ese usuario en la base.
  if api_sana && [ "$(psql -X -Atq -d postgres -c "SELECT count(*) > 0 FROM pg_stat_activity WHERE usename = '$role'")" = t ]; then
    log "La API volvió con el rol $role"
  else
    avisar "La API no volvió con el rol $role (revisa /health y ~/rappi-tunel/logs/api.log)"
    exit 1
  fi
fi
