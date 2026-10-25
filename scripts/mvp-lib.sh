#!/usr/bin/env bash
# Funciones comunes de mvp.sh y mvp-check.sh (se cargan con `source`; no se ejecuta sola). Compatible con bash 3.2.
#
# Cada proceso se lanza con `start` en su propio grupo de procesos (set -m): al detenerlo se manda la señal al grupo
# entero, así también mueren los procesos nietos (npm → vite, make → uvicorn) y no queda ningún puerto ocupado.

set -m # un grupo de procesos por cada trabajo en segundo plano

STARTED="" # "etiqueta:pid" de lo lanzado con start, separado por espacios
LAST_PID=""
DEAD=""
MISSING=0

fail() {
  echo "$*" >&2
  exit 1
}

need_command() { # need_command <comando> <qué hacer si falta>
  if ! command -v "$1" >/dev/null 2>&1; then fail "Falta $1: $2"; fi
}

need_dir() { # need_dir <carpeta> <qué hacer si falta>: avisa de todas las que faltan antes de salir
  if [ ! -d "$1" ]; then
    echo "Falta $1: $2" >&2
    MISSING=1
  fi
}

exit_if_missing() {
  if [ "$MISSING" != 0 ]; then exit 1; fi
}

port_busy() { # port_busy <puerto>: algo escucha en localhost (IPv4 o IPv6); bash puro, sin lsof, sirve en macOS y Linux
  (exec 3<>"/dev/tcp/localhost/$1") 2>/dev/null
}

require_free_ports() { # require_free_ports <puerto>...: sale con 1 si alguno está ocupado
  local port busy=0
  for port in "$@"; do
    if port_busy "$port"; then
      echo "El puerto $port ya está en uso (¿quedó un \`make serve\` o \`npm run dev\` abierto?)" >&2
      busy=1
    fi
  done
  if [ "$busy" != 0 ]; then exit 1; fi
}

prefix_lines() { # prefix_lines <etiqueta>: antepone [etiqueta] a cada línea que llega por la entrada estándar
  local tag=$1 line
  while IFS= read -r line || [ -n "$line" ]; do
    printf '[%s] %s\n' "$tag" "$line"
  done
}

start() { # start <etiqueta> <comando>...: lo deja corriendo con su salida prefijada; su pid queda en LAST_PID
  local tag=$1
  shift
  # El lector ignora las señales: al detener el proceso sigue vivo hasta mostrar su última línea (termina solo al cerrarse
  # la tubería).
  "$@" </dev/null > >(
    trap '' INT TERM HUP
    prefix_lines "$tag"
  ) 2>&1 &
  LAST_PID=$!
  disown "$LAST_PID" # bash 3.2 avisa «Terminated» de cada trabajo que muere por una señal; aquí lo detenemos a propósito
  STARTED="$STARTED $tag:$LAST_PID"
}

group_alive() { # group_alive <pid>: quedan procesos en el grupo que lanzó start
  kill -0 -- "-$1" 2>/dev/null
}

stop_pids() { # stop_pids <pid>...: TERM al grupo, hasta 10 s de espera y después KILL
  local pid tries=0 alive
  for pid in "$@"; do kill -TERM -- "-$pid" 2>/dev/null || true; done
  while [ "$tries" -lt 100 ]; do
    alive=0
    for pid in "$@"; do
      if group_alive "$pid"; then alive=1; fi
    done
    if [ "$alive" = 0 ]; then
      sleep 0.2 # deja que los lectores impriman lo último
      return 0
    fi
    sleep 0.1
    tries=$((tries + 1))
  done
  for pid in "$@"; do kill -KILL -- "-$pid" 2>/dev/null || true; done
}

stop_one() { # stop_one <etiqueta>: detiene un solo proceso (el resto sigue)
  local entry
  for entry in $STARTED; do
    if [ "${entry%%:*}" = "$1" ]; then
      stop_pids "${entry#*:}"
      STARTED=${STARTED/ $entry/}
    fi
  done
}

stop_all() { # va en el trap de EXIT: seguro de llamar varias veces y con Ctrl-C repetido
  trap '' INT TERM HUP
  local entry pids=""
  for entry in $STARTED; do pids="$pids ${entry#*:}"; done
  STARTED=""
  if [ -z "$pids" ]; then return 0; fi
  echo
  echo "Deteniendo…"
  # shellcheck disable=SC2086
  stop_pids $pids
}

install_traps() {
  trap 'exit 130' INT
  trap 'exit 143' TERM
  trap 'exit 129' HUP
  trap stop_all EXIT
}

# shellcheck disable=SC2034 # DEAD lo leen los scripts que cargan esta biblioteca
all_alive() { # 0 mientras sigan vivos todos los procesos de start; si uno murió, deja su etiqueta en DEAD
  local entry
  for entry in $STARTED; do
    if ! kill -0 "${entry#*:}" 2>/dev/null; then
      DEAD=${entry%%:*}
      return 1
    fi
  done
}

PROGRESS_EVERY=${PROGRESS_EVERY:-15} # segundos entre avisos de wait_for_url cuando espera sin límite

# wait_for_url <nombre> <url> <segundos> <etiqueta del proceso> [aviso]
# Espera a que la URL responda y sale con 1 si el proceso se detiene o si pasan los segundos. Con 0 segundos no hay
# límite: espera mientras el proceso siga vivo y cada 15 s avisa «[mvp] <nombre> sigue arrancando (<aviso>)…» (la API
# tarda minutos la primera vez, cuando descarga los modelos).
wait_for_url() {
  local name=$1 url=$2 limit=$3 tag=$4 hint=${5:-} seconds=0 entry pid=""
  for entry in $STARTED; do
    if [ "${entry%%:*}" = "$tag" ]; then pid=${entry#*:}; fi
  done
  while ! curl -fs -o /dev/null --max-time 2 "$url"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      fail "$name se detuvo antes de quedar listo: mira el registro [$tag] más arriba."
    fi
    if [ "$limit" != 0 ] && [ "$seconds" -ge "$limit" ]; then
      fail "$name no respondió en $limit s ($url): mira el registro [$tag] más arriba."
    fi
    sleep 1
    seconds=$((seconds + 1))
    if [ "$limit" = 0 ] && [ $((seconds % PROGRESS_EVERY)) = 0 ]; then
      echo "[mvp] $name sigue arrancando${hint:+ ($hint)}…"
    fi
  done
}
