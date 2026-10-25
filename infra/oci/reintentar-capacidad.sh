#!/usr/bin/env bash
# Reintenta crear la máquina A1 cuando OCI responde «Out of host capacity» (común en las cuentas Always Free).
# Prueba primero la forma completa (4 OCPU, 24 GB) y, si no hay, una de 2 OCPU y 12 GB que después se agranda con
# `terraform apply -var ocpus=4 -var memory_gb=24`. Renueva la sesión de la CLI en cada vuelta (dura una hora y se
# puede renovar hasta 24 h). Uso: ./reintentar-capacidad.sh [minutos entre intentos, 5] [horas máximas, 23]
set -uo pipefail
cd "$(dirname "$0")" || exit 1
PROFILE=${OCI_PROFILE:-RAPPI}
PAUSA=$(( ${1:-5} * 60 ))
FIN=$(( $(date +%s) + ${2:-23} * 3600 ))
intento=0

avisar() { # registro y notificación de macOS (si existe osascript)
  echo "$(date '+%F %T') $*"
  command -v osascript > /dev/null && osascript -e "display notification \"$*\" with title \"Oracle Cloud\"" > /dev/null 2>&1 || true
}

probar() { # $1 OCPU, $2 GB
  terraform apply -input=false -auto-approve -no-color -var "ocpus=$1" -var "memory_gb=$2" > ultimo-intento.log 2>&1
}

while [ "$(date +%s)" -lt "$FIN" ]; do
  intento=$((intento + 1))
  oci session refresh --profile "$PROFILE" > /dev/null 2>&1 || { avisar "La sesión de OCI venció: correr oci session authenticate"; exit 2; }
  for forma in "4 24" "2 12"; do
    set -- $forma
    if probar "$1" "$2"; then
      avisar "Intento $intento: máquina creada con $1 OCPU y $2 GB"
      terraform output -no-color
      exit 0
    fi
    if ! grep -q "Out of host capacity" ultimo-intento.log; then
      echo "$(date '+%F %T') intento $intento: error distinto de capacidad, se detiene (ver ultimo-intento.log)"
      tail -20 ultimo-intento.log
      exit 1
    fi
  done
  echo "$(date '+%F %T') intento $intento: sin capacidad; otro en $((PAUSA / 60)) min"
  sleep "$PAUSA"
done
avisar "Se acabó el tiempo sin capacidad"
exit 3
