#!/usr/bin/env bash
# Corre un comando con el candado de la base de prueba: `with-test-db-lock.sh <comando>...`.
# `make test`, `make contract` y `make mvp-check` borran y vuelven a sembrar rappi_ia_test; si dos coinciden, fallan al
# azar. El candado es un directorio (mkdir es atómico en macOS y en Linux) con el pid de quien lo tiene, en la carpeta
# común de git (.git/rappi-ia-test-db.lock): todos los worktrees del repositorio usan la misma base, así que comparten
# el candado. Fuera de git (una copia suelta), es rappi-ia/.test-db.lock. Si el proceso que lo tiene ya no existe (se
# mató con kill -9, se apagó el equipo), el candado se toma: se mueve a un nombre propio (mv es atómico: si dos lo
# intentan, el que pierde avisa que está ocupado y sale con 1), se borra y se vuelve a crear.
# Correr pytest directamente no pasa por aquí.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
if COMMON="$(git -C "$HERE" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" && [ -d "$COMMON" ]; then
  LOCK="$COMMON/rappi-ia-test-db.lock"
else
  LOCK="$(cd "$HERE/.." && pwd)/.test-db.lock"
fi
held=0

release() {
  if [ "$held" = 1 ]; then rm -rf "$LOCK"; fi
}
# El trap va antes de cualquier mkdir: si algo falla después de crear el candado, no queda uno sin dueño.
trap release EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

busy() {
  echo "Otra prueba está usando rappi_ia_test; espera a que termine." >&2
  echo "Si ningún proceso la usa, borra el candado: rm -rf $LOCK" >&2
  exit 1
}

take() { # take: crea el candado y de inmediato escribe el pid
  mkdir "$LOCK" 2>/dev/null || return 1
  held=1
  echo "$$" >"$LOCK/pid"
}

if ! take; then
  owner=$(cat "$LOCK/pid" 2>/dev/null || true)
  # Sin pid todavía = quien lo tomó está justo escribiéndolo: se considera ocupado.
  if [ -z "$owner" ] || kill -0 "$owner" 2>/dev/null; then busy; fi
  stale="$LOCK.stale.$$"
  mv "$LOCK" "$stale" 2>/dev/null || busy # otro lo está tomando: este pierde
  if [ "$(cat "$stale/pid" 2>/dev/null || true)" != "$owner" ]; then
    # Entre leer el pid y mover llegó otro dueño: se le devuelve su candado.
    mv "$stale" "$LOCK" 2>/dev/null || rm -rf "$stale"
    busy
  fi
  rm -rf "$stale"
  take || busy
fi

"$@"
