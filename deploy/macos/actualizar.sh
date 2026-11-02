#!/usr/bin/env bash
# Pone la demo pública al día con origin/main sin cambiar la URL: trae los cambios, instala dependencias si cambiaron,
# respalda la base si hay migraciones pendientes y migra, construye la app y el panel, cambia los archivos servidos de
# una vez y reinicia solo la API (el túnel sigue igual). Uso: deploy/macos/actualizar.sh [--forzar]
# shellcheck source=deploy/macos/comun.sh
. "$(dirname "$0")/comun.sh"
cd "$REPO_DIR" || exit 1
[ -z "$(git status --porcelain --untracked-files=no)" ] || { log "La copia $REPO_DIR tiene cambios sin commit: no actualizo"; exit 1; }

git fetch -q origin main
antes=$(git rev-parse HEAD)
if [ "$antes" = "$(git rev-parse origin/main)" ] && [ "${1:-}" != "--forzar" ]; then
  log "Al día ($(git log -1 --format='%h %s'))"
  exit 0
fi
cambios=$(git diff --name-only "$antes" origin/main)
git merge --ff-only -q origin/main
log "De $(git rev-parse --short "$antes") a $(git log -1 --format='%h %s')"

if grep -qE '(requirements.*\.txt|pyproject\.toml|package-lock\.json)$' <<< "$cambios"; then
  log "Cambiaron dependencias: make install"
  make -s install && make -s -C rappi-ia install-ml
fi

if ! rappi-ia/.venv/bin/python -m rappi_ia migrate --solo-revisar > /dev/null 2>&1; then
  log "Hay migraciones pendientes: respaldo antes de migrar"
  "$(dirname "$0")/respaldo.sh" pre-migracion
  (cd rappi-ia && .venv/bin/python -m rappi_ia migrate)
fi

make -s build
rm -rf "$SRV_DIR.nuevo" && mkdir -p "$SRV_DIR.nuevo"
cp -R prototipo-app/dist "$SRV_DIR.nuevo/app"
cp -R dashboard-empresa/dist "$SRV_DIR.nuevo/panel"
rm -rf "$SRV_DIR.viejo"
[ -d "$SRV_DIR/app" ] && mv "$SRV_DIR" "$SRV_DIR.viejo"
mv "$SRV_DIR.nuevo" "$SRV_DIR"
rm -rf "$SRV_DIR.viejo"

reiniciar api
for _ in $(seq 1 60); do api_sana && break; sleep 3; done
if api_sana; then
  avisar "Demo actualizada a $(git log -1 --format='%h')"
else
  avisar "La API no volvió después de actualizar"
  exit 1
fi
