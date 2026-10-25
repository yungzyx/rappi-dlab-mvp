#!/usr/bin/env bash
# make mvp: levanta la API de rappi-ia (:8000), la app (:5174) y el panel (:5175) sobre la base real, en un solo
# comando, y avisa cuando responden. Ctrl-C detiene los tres.
# No descarga nada de rappi.cl: usa la base `rappi` que ya está en este equipo (ver docs/instalacion.md).
# Con LAN=1 la API y la app quedan en la red local (para el iPhone; sin puerta de acceso, aunque los datos de cada
# persona piden su token firmado: solo en una red de confianza).
# La app y el panel buscan la API en el host desde el que se abrió la página (puerto 8000).
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/mvp-lib.sh
source scripts/mvp-lib.sh

IA=rappi-ia/.venv/bin/rappi-ia

need_command npm "instala Node (la versión de .nvmrc) o revisa tu PATH, y vuelve a correr \`make mvp\`."
need_command curl "instálalo o revisa tu PATH."
need_dir rappi-ia/.venv "corre \`make install install-ml\` en rappi-ia."
need_dir prototipo-app/node_modules "corre \`npm ci\` en prototipo-app."
need_dir dashboard-empresa/node_modules "corre \`npm ci\` en dashboard-empresa."
exit_if_missing
# Una carpeta .venv que existe pero no arranca: se movió el proyecto (los .venv guardan rutas absolutas).
"$IA" --help >/dev/null 2>&1 || fail "El .venv de rappi-ia no funciona (¿se movió la carpeta?): corre \`make install install-ml\` en rappi-ia."
require_free_ports 8000 5174 5175

echo "Revisando la base…"
"$IA" doctor # imprime su propio mensaje; si la base no está lista, termina con 1 y el script se detiene
# Se niega a migrar la base real con migraciones de una rama sin fusionar (MIGRATE=1 lo fuerza; ver
# `rappi-ia check-migrations`); si se niega, termina con 1 y el script se detiene antes de migrar.
"$IA" check-migrations
make -s --no-print-directory -C rappi-ia migrate

if [ "${LAN:-}" = 1 ]; then
  SERVE=serve-lan
  HOST_FLAG=--host
else
  SERVE=serve
  HOST_FLAG=
fi

install_traps
start api make --no-print-directory -C rappi-ia "$SERVE"
start app npm --prefix prototipo-app run dev -- --port 5174 --strictPort $HOST_FLAG
start panel npm --prefix dashboard-empresa run dev -- --port 5175 --strictPort $HOST_FLAG

# Con los modelos locales la API tarda en arrancar (la primera vez descarga el modelo e5, ~1 GB): sin límite de tiempo mientras siga
# viva, avisando cada 15 s. Espera /live y no /health: con la base vacía o sin preparar /health da 503 y la espera no terminaría.
# La app y el panel responden en un par de segundos.
wait_for_url "La API" http://localhost:8000/live 0 api "cargando modelos"
# Las listas del catálogo de la Home, en segundo plano y sin importar si falla (en frío, /catalog/home tarda ~3 s). No
# es `make warm` entero: ese pregunta al agente, que puede llamar a Claude.
make -s --no-print-directory -C rappi-ia warm-catalog >/dev/null 2>&1 &
wait_for_url "La app" http://localhost:5174 30 app
wait_for_url "El panel" http://localhost:5175 30 panel
echo "MVP listo: app http://localhost:5174 · panel http://localhost:5175 · API http://localhost:8000/docs"
echo "Ctrl-C detiene los tres."

while all_alive; do sleep 1; done
fail "El proceso [$DEAD] se detuvo (mira su registro más arriba); detengo el resto."
