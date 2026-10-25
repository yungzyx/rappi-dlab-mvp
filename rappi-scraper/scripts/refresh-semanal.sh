#!/usr/bin/env bash
# Tarea semanal (domingos 03:00): descarga y capa de IA, en orden. En macOS la programa launchd (`make schedule`); en
# un servidor Linux, el timer de systemd deploy/systemd/rappi-refresh.timer, dentro del contenedor jobs.
#   1. rappi migrate (migraciones pendientes, p. ej. tras un git pull; en producción solo las revisa) y rappi refresh:
#      tiendas, restaurantes, búsqueda, reportes y respaldo.
#   2. Si rappi-ia está instalado al lado: conceptos, embeddings, evaluación, datos simulados y purga.
# La evaluación no guarda τ (eval/thresholds.json está en git: recalibrar es a mano, con `make eval GUARDAR_TAU=1`).
# Las opciones pasan a `rappi refresh`: tras `retry-failed`, `refresh-semanal.sh --resume-only` retoma solo lo reencolado.
# Variables: RAPPI_BIN (por defecto .venv/bin/rappi), RAPPI_IA_PY (el python de rappi-ia, por defecto su .venv) y
# RAPPI_DATA_DIR (por defecto data/). Compatible con el bash 3.2 de macOS: sin mapfile ni arreglos asociativos.
set -euo pipefail
cd "$(dirname "$0")/.."
DATA=${RAPPI_DATA_DIR:-data}
LOGS=$DATA/logs
RAPPI_BIN=${RAPPI_BIN:-.venv/bin/rappi}
mkdir -p "$LOGS"
# caffeinate (macOS) evita que el equipo se duerma a mitad de la descarga; en Linux no existe ni hace falta.
AWAKE=()
if command -v caffeinate >/dev/null; then AWAKE=(caffeinate -i); fi

# launchd escribe siempre en los mismos dos archivos: pasados 10 MB se copian a .1 (pisando el .1 anterior) y se
# vacían. Copiar y vaciar, no mover: launchd ya los abrió para esta ejecución y su salida debe quedar en el archivo vivo.
for launchd_log in "$LOGS"/launchd.*.log; do
  if [ -f "$launchd_log" ] && [ "$(wc -c < "$launchd_log")" -gt 10485760 ]; then
    cp "$launchd_log" "$launchd_log.1" && : > "$launchd_log"
  fi
done

# ¿El PID es una tarea semanal viva? (No el de esta misma: en un contenedor nuevo el script vuelve a ser el mismo PID.)
# Sin ps (el contenedor jobs no lo trae) basta con que el PID esté vivo; como no se puede comprobar que sea la tarea
# semanal, la ejecución se omite pero lo anota en ultimo-estado.txt (already_running), para que no pase inadvertido.
unverified_pid=""
weekly_running() {
  [ -n "$1" ] && [ "$1" != "$$" ] && kill -0 "$1" 2>/dev/null || return 1
  if command -v ps >/dev/null; then
    ps -p "$1" -o command= 2>/dev/null | grep -q refresh-semanal
  else
    unverified_pid=$1
  fi
}
# Creado o cambiado hace menos de 1 o 2 minutos (find redondea los minutos distinto en macOS y en Linux).
young() { [ -n "$(find "$1" -maxdepth 0 -mmin -2 2>/dev/null)" ]; }
# Existe y es de hace más de 2 o 3 minutos. Si desapareció recién no es viejo: otra ejecución lo soltó.
old() { [ -n "$(find "$1" -maxdepth 0 -mmin +2 2>/dev/null)" ]; }
# El candado existe y es de una ejecución viva, o de una que acaba de crearlo y todavía no escribe su PID.
lock_held() {
  local pid
  [ -d "$LOCK" ] || return 1
  pid=$(cat "$LOCK/pid" 2>/dev/null || true)
  if [ -z "$pid" ]; then young "$LOCK"; else weekly_running "$pid"; fi
}
interrupted() {  # candado de una ejecución que murió sin su trap (apagado, corte de luz)
  echo "$(date '+%F %T') interrumpida: la ejecución anterior no terminó (apagado o corte de luz)" \
    >> "$LOGS/ultimo-estado.txt"
}
already_running() {
  echo "$(date '+%F %T') ya hay una actualización semanal en curso; se omite"
  if [ -n "$unverified_pid" ]; then
    echo "$(date '+%F %T') se omite: el candado es del PID $unverified_pid, que está vivo, y sin ps no se puede" \
      "comprobar que sea la tarea semanal" >> "$LOGS/ultimo-estado.txt"
  fi
  exit 0
}

# Una sola actualización a la vez. El candado de antes era un archivo con el PID: el de una tarea antigua todavía en
# curso también cuenta; si su proceso ya no existe, se anota y se borra.
OLD_LOCK=$DATA/refresh-semanal.pid
if [ -f "$OLD_LOCK" ]; then
  if weekly_running "$(cat "$OLD_LOCK")"; then already_running; fi
  interrupted
  rm -f "$OLD_LOCK"
fi
# El candado es un directorio (mkdir es atómico) con el PID adentro. Si ese proceso ya no existe o es otro programa con
# el mismo PID, quedó de una ejecución que murió: lo recupera una sola de las que partan a la vez, la que tome
# RECOVERING (otro mkdir). Esa vuelve a revisar el candado antes de borrarlo, porque otra pudo recuperarlo recién. Solo
# un RECOVERING que sigue ahí y tiene más de 2 minutos quedó de una ejecución que murió justo ahí y se borra; si
# desaparece mientras se revisa, otra lo soltó (y otra pudo tomarlo ya): esta se omite. Soltarlo tolera que ya no esté.
LOCK=$DATA/refresh-semanal.lock
RECOVERING=$LOCK.recuperando
if ! mkdir "$LOCK" 2>/dev/null; then
  if lock_held; then already_running; fi
  if ! mkdir "$RECOVERING" 2>/dev/null; then
    if ! old "$RECOVERING"; then already_running; fi
    rm -rf "$RECOVERING"
    mkdir "$RECOVERING" 2>/dev/null || already_running
  fi
  if lock_held; then
    rmdir "$RECOVERING" 2>/dev/null || true
    already_running
  fi
  if [ -d "$LOCK" ]; then
    interrupted
    rm -rf "$LOCK"
  fi
  mkdir "$LOCK" 2>/dev/null || { rmdir "$RECOVERING" 2>/dev/null || true; already_running; }
  rmdir "$RECOVERING" 2>/dev/null || true
fi
echo $$ > "$LOCK/pid"
# Una línea por ejecución en ultimo-estado.txt (la muestra `make schedule-status`): un fallo del domingo no queda
# escondido en launchd.err.log ni en el diario de systemd.
nota=""
finish() {
  local rc=$?
  # Solo el candado propio: si otra ejecución lo recuperó (este proceso quedó colgado), es de ella.
  if [ "$(cat "$LOCK/pid" 2>/dev/null || true)" = "$$" ]; then rm -rf "$LOCK"; fi
  echo "$(date '+%F %T') exit=$rc${nota:+ ($nota)}" >> "$LOGS/ultimo-estado.txt"
}
trap finish EXIT
# Con una señal (Ctrl-C, launchctl bootout, systemctl stop) sale con su código y el trap EXIT suelta el candado.
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
if command -v pgrep >/dev/null && pgrep -f "rappi(_scraper)? (refresh|discover|scrape-)|post-refresh" >/dev/null; then
  echo "$(date '+%F %T') hay una descarga o una actualización de rappi-ia en curso; se omite"  # lanzada a mano
  nota="omitida: había una descarga o una actualización en curso"
  exit 0
fi
# Antes de descargar: una migración pendiente haría fallar el refresh al final (tras un día de descarga), y el
# `migrate` de post-refresh nunca llegaría a correr. En producción (API_ENV=production) no migra sin respaldo: solo
# revisa, y si falta una se detiene (las aplica el despliegue: `docker compose run --rm migrate`, que respalda antes).
if [ "${API_ENV:-}" = production ]; then "$RAPPI_BIN" migrate --solo-revisar; else "$RAPPI_BIN" migrate; fi
# Código 3: todo terminó salvo el respaldo (quedan los anteriores). Código 5: los restaurantes no se actualizaron
# (tiendas, búsqueda y respaldo sí; con el sitemap caído y una corrida anterior se usa su lista y sale con 0). Código
# 6: las dos cosas. En los tres la capa de IA corre igual, pero queda anotado. Código 4: posible bloqueo de rappi.cl;
# código 7: robots.txt no permite una página (o no respondió). Con esos dos se detiene aquí. Los avisos que no cambian
# el código (restaurantes bajados con la lista de una corrida anterior, con 0 o 3) los deja `rappi refresh` como marcas
# fijas en RAPPI_REFRESH_NOTES; se borra antes para no anotar los de otra semana.
export RAPPI_REFRESH_NOTES=$LOGS/refresh-avisos.txt
rm -f "$RAPPI_REFRESH_NOTES"
refresh_rc=0
${AWAKE[@]+"${AWAKE[@]}"} "$RAPPI_BIN" refresh "$@" || refresh_rc=$?
if [ "$refresh_rc" -eq 3 ]; then
  nota="respaldo fallido: se conservan los anteriores"
elif [ "$refresh_rc" -eq 5 ]; then
  nota="restaurantes sin actualizar"
elif [ "$refresh_rc" -eq 6 ]; then
  nota="restaurantes sin actualizar; respaldo fallido: se conservan los anteriores"
elif [ "$refresh_rc" -eq 4 ]; then
  nota="detenida: posible bloqueo"
  exit "$refresh_rc"
elif [ "$refresh_rc" -eq 7 ]; then
  nota="detenida: robots.txt no permite una página o no respondió"
  exit "$refresh_rc"
elif [ "$refresh_rc" -ne 0 ]; then
  exit "$refresh_rc"
fi
if grep -qx restaurantes_con_lista_anterior "$RAPPI_REFRESH_NOTES" 2>/dev/null; then
  nota="${nota:+$nota; }restaurantes con la lista de la corrida anterior"
fi
# El python de rappi-ia: RAPPI_IA_PY (en el contenedor, el del sistema) o su .venv, si está instalado al lado.
if [ -n "${RAPPI_IA_PY:-}" ] || [ -x ../rappi-ia/.venv/bin/python ]; then
  echo "$(date '+%F %T') refresh terminado: actualizando rappi-ia"
  ${AWAKE[@]+"${AWAKE[@]}"} make -C ../rappi-ia post-refresh PY="${RAPPI_IA_PY:-.venv/bin/python}"
fi
