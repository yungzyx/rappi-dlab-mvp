#!/usr/bin/env bash
# Pone la demo pública al día con origin/main sin cambiar la URL: trae los cambios, instala dependencias si cambiaron,
# respalda la base si hay migraciones pendientes y migra, construye la app y el panel, cambia los archivos servidos de
# una vez y reinicia la API, y Caddy o el túnel si cambiaron sus archivos. Compara origin/main con el último commit que
# quedó desplegado (TUNEL_DIR/desplegado.txt, se escribe cuando la API vuelve), no con HEAD: si un paso falla, avisa y
# la vuelta siguiente lo reintenta. Si solo cambiaron archivos .md, trae los cambios y anota el commit sin construir ni
# reiniciar. Mientras exista TUNEL_DIR/pausa-actualizar no hace nada (la prueba con usuarios, docs/prueba-usuarios.md).
# Uso: deploy/macos/actualizar.sh [--forzar]   (--forzar actualiza aunque esté al día o en pausa, y construye siempre)
# shellcheck source=deploy/macos/comun.sh
. "$(dirname "$0")/comun.sh"

# Todo dentro de main, que se llama en la última línea: el merge reescribe este archivo mientras corre, y bash lo lee
# de a poco.
main() {
  if [ -e "$TUNEL_DIR/pausa-actualizar" ] && [ "${1:-}" != "--forzar" ]; then
    log "Pausado: existe $TUNEL_DIR/pausa-actualizar (se borra para reanudar)"
    exit 0
  fi
  cd "$REPO_DIR" || exit 1
  # Se escribe en un .tmp y se mueve: si la escritura falla (disco lleno), desplegado.txt queda como estaba.
  anotar_desplegado() { git rev-parse HEAD > "$TUNEL_DIR/desplegado.txt.tmp" && mv "$TUNEL_DIR/desplegado.txt.tmp" "$TUNEL_DIR/desplegado.txt"; }
  [ -z "$(git status --porcelain --untracked-files=no)" ] || { log "La copia $REPO_DIR tiene cambios sin commit: no actualizo"; exit 1; }

  git fetch -q origin main
  objetivo=$(git rev-parse origin/main)
  # La primera vez, lo que ya estaba servido: así un fallo en esta misma vuelta también se reintenta.
  [ -f "$TUNEL_DIR/desplegado.txt" ] || anotar_desplegado
  desplegado=$(cat "$TUNEL_DIR/desplegado.txt")
  # Vacío o con un commit que no existe, cada vuelta moriría en el git diff hasta que alguien lo borre a mano.
  git rev-parse -q --verify "$desplegado^{commit}" > /dev/null || {
    log "desplegado.txt no es un commit: comparo con HEAD"
    desplegado=$(git rev-parse HEAD)
  }
  if [ "$desplegado" = "$objetivo" ] && [ "${1:-}" != "--forzar" ]; then
    log "Al día ($(git log -1 --format='%h %s'))"
    exit 0
  fi
  # Desde lo desplegado: un reintento los vuelve a ver. Sin renombres: un .js que pasa a .md nombra los dos.
  cambios=$(git diff --name-only --no-renames "$desplegado" "$objetivo")
  [ "$(git rev-parse HEAD)" = "$objetivo" ] || git merge --ff-only -q origin/main
  log "De $(git rev-parse --short "$desplegado") a $(git log -1 --format='%h %s')"
  # Nada se construye ni se sirve desde los .md (ni la app, ni el panel, ni la API): sin build ni reinicio. Salvo los de
  # un public/, que vite copia a dist.
  if [ "${1:-}" != "--forzar" ] && [ -n "$cambios" ] && ! grep -qv '\.md$' <<< "$cambios" \
      && ! grep -q '/public/' <<< "$cambios"; then
    anotar_desplegado
    log "Solo cambió documentación (.md): sin construir ni reiniciar"
    exit 0
  fi

  if grep -qE '(requirements.*\.txt|pyproject\.toml|package-lock\.json)$' <<< "$cambios"; then
    log "Cambiaron dependencias: make install"
    make -s install
    make -s -C rappi-ia install-ml
  fi

  if ! rappi-ia/.venv/bin/python -m rappi_ia migrate --solo-revisar > /dev/null 2>&1; then
    # Un respaldo por despliegue pendiente: desplegado.txt solo se escribe cuando todo sale bien, así que un
    # respaldo más nuevo es de un intento anterior de esta misma tanda. Un reintento conserva ese, el de antes de
    # migrar (cada migración va en su transacción: un intento puede dejar la base a medias, y respaldo.sh solo guarda
    # los RESPALDOS_A_GUARDAR más nuevos).
    if [ -n "$(find "$RESPALDOS_DIR" -name 'pre-migracion_*.dump' -newer "$TUNEL_DIR/desplegado.txt")" ]; then
      log "Hay migraciones pendientes: ya hay un respaldo de este despliegue, no respaldo de nuevo"
    else
      log "Hay migraciones pendientes: respaldo antes de migrar"
      "$(dirname "$0")/respaldo.sh" pre-migracion
    fi
    rappi-ia/.venv/bin/python -m rappi_ia migrate  # sin (cd …): en el bash 3.2 un fallo en un subshell no avisaría
  fi

  make -s build
  rm -rf "$SRV_DIR.nuevo" && mkdir -p "$SRV_DIR.nuevo"
  cp -R prototipo-app/dist "$SRV_DIR.nuevo/app"
  cp -R dashboard-empresa/dist "$SRV_DIR.nuevo/panel"
  rm -rf "$SRV_DIR.viejo"
  [ -d "$SRV_DIR/app" ] && mv "$SRV_DIR" "$SRV_DIR.viejo"
  mv "$SRV_DIR.nuevo" "$SRV_DIR"
  rm -rf "$SRV_DIR.viejo"

  if grep -qE '^deploy/macos/(Caddyfile|caddy\.sh)$' <<< "$cambios"; then
    # BASIC_AUTH_* ya vienen exportados de tunel.env (comun.sh)
    if SRV_DIR=$SRV_DIR API_PORT=$API_PORT CADDY_PORT=$CADDY_PORT \
        caddy validate --config deploy/macos/Caddyfile --adapter caddyfile > /dev/null; then
      reiniciar caddy
    else
      avisar "El Caddyfile nuevo no valida: Caddy sigue con el anterior"
    fi
  fi
  if grep -qx 'deploy/macos/tunel.sh' <<< "$cambios"; then
    if [ -n "${PUBLIC_URL:-}" ]; then
      reiniciar tunel
    else
      avisar "Cambió tunel.sh: reinicia el túnel a mano (el túnel rápido cambiará de URL)"
    fi
  fi
  if grep -qx 'deploy/macos/instalar.sh' <<< "$cambios"; then
    avisar "Cambió instalar.sh: correr deploy/macos/instalar.sh"
  fi

  reiniciar api
  for _ in $(seq 1 60); do api_sana && break; sleep 3; done
  if api_sana; then
    anotar_desplegado
    avisar "Demo actualizada a $(git log -1 --format='%h')"
  else
    avisar "La API no volvió después de actualizar"
    exit 1
  fi
}

main "$@"; exit
