#!/usr/bin/env bash
# Chequeo de un comando justo antes de cada participante de la prueba con usuarios (docs/prueba-usuarios.md, sección
# 3): /health, la swap, el disco libre, la fecha del catálogo, si los despliegues están en pausa y 8 búsquedas variadas
# contra la API local con su tiempo y el máximo. Avisa si la API no está lista, si una búsqueda falla o pasa de 1 s, o
# si los despliegues no están en pausa (sale con 1). El RSS y el footprint de cada proceso de la API van como dato: con
# la mayor parte en swap, la primera búsqueda tarda segundos. Solo lee: no pausa los despliegues ni escribe en la base.
# Las búsquedas llevan el id "vigilante-chequeo-…" (X-Request-ID): el resumen diario las cuenta como mantención, no
# como visitas. Uso: deploy/macos/chequeo-sesion.sh
# shellcheck source=deploy/macos/comun.sh
. "$(dirname "$0")/comun.sh"
LENTA_MS=1000
BUSQUEDAS=("leche" "pizza" "sushi" "coca cola" "detergente" "hamburguesa" "pan integral" "chocolte")
base=${RESPALDO_BASE:-rappi}  # la misma base que respalda respaldo.sh
problemas=()

salud=$(curl -sS --max-time 10 "http://127.0.0.1:$API_PORT/health" 2>/dev/null || true)
if grep -q '"ok": *true' <<< "$salud"; then
  echo "API: lista ($salud)"
else
  echo "API: no está lista (${salud:-no responde})"
  problemas+=("la API no está lista")
fi

echo "Swap: $(sysctl -n vm.swapusage 2>/dev/null || echo 'no disponible')"
echo "Disco: $(df -h "$TUNEL_DIR" | awk 'NR==2 {print $4 " libres de " $2}')"
catalogo=$(PGOPTIONS='-c default_transaction_read_only=on' psql -X -qAt -d "$base" -c "
  SELECT string_agg(CASE kind WHEN 'stores' THEN 'tiendas' ELSE 'restaurantes' END || ' '
                    || to_char(fin AT TIME ZONE 'America/Santiago', 'DD-MM-YYYY'), ' · ' ORDER BY kind DESC)
  FROM (SELECT kind, max(finished_at) AS fin FROM scrape_runs
        WHERE status = 'done' AND kind IN ('stores', 'restaurants') GROUP BY kind) t" 2>/dev/null || true)
echo "Catálogo: ${catalogo:-no pude leer la base $base}"

if [ -e "$TUNEL_DIR/pausa-actualizar" ]; then
  echo "Despliegues: en pausa"
else
  echo "Despliegues: no están en pausa (touch $TUNEL_DIR/pausa-actualizar)"
  problemas+=("los despliegues no están en pausa")
fi

# Dato, no criterio: el RSS (lo que está en memoria) sobre el footprint (lo que usa el proceso, también en swap).
padre=$(pgrep -f "rappi_ia.api.app:app.*--port $API_PORT( |\$)" | head -1 || true)
procesos=$( [ -z "$padre" ] || pgrep -P "$padre" -f spawn_main || true)
[ -n "$procesos" ] || echo "Procesos de la API: no los encuentro"
for pid in $procesos; do
  rss_kb=$(ps -o rss= -p "$pid" 2>/dev/null | tr -d ' ' || true)
  footprint=$(top -l 1 -stats mem -pid "$pid" 2>/dev/null | tail -1 | tr -d ' +-' || true)
  footprint_mb=$(LC_ALL=C awk -v f="$footprint" 'BEGIN {
    n = f + 0; u = substr(f, length(f)); if (u == "G") n *= 1024; else if (u == "K") n /= 1024; else if (u != "M") n = 0
    printf "%d", n }')
  if [ -n "$rss_kb" ] && [ "$footprint_mb" -gt 0 ]; then
    echo "Proceso $pid de la API: RSS $(( rss_kb / 1024 )) MB, footprint $footprint_mb MB (RSS/footprint $(( rss_kb * 100 / 1024 / footprint_mb )) %)"
  else
    echo "Proceso $pid de la API: RSS ${rss_kb:-?} KB, footprint ${footprint:-no disponible}"
  fi
done

# Los dos procesos se reparten las búsquedas: pueden caer todas en el mismo, así que esto no asegura calentar ambos.
echo "Búsquedas (cada una por separado; la primera después de un rato sin uso suele ser la lenta):"
maximo=0
i=0
for q in "${BUSQUEDAS[@]}"; do
  i=$(( i + 1 ))
  medida=$(curl -sS -o /dev/null --max-time 30 -w '%{http_code} %{time_total}' \
    -H "X-Request-ID: vigilante-chequeo-$(date +%s)-$i" --get --data-urlencode "q=$q" \
    "http://127.0.0.1:$API_PORT/search" 2>/dev/null || true)
  codigo=${medida%% *}
  ms=$(LC_ALL=C awk -v s="${medida#* }" 'BEGIN { printf "%d", s * 1000 }')
  [ "$ms" -le "$maximo" ] || maximo=$ms
  if [ "$codigo" != 200 ]; then
    echo "  $q: falló (${codigo:-sin respuesta})"
    problemas+=("la búsqueda \"$q\" falló")
  elif [ "$ms" -gt "$LENTA_MS" ]; then
    echo "  $q: $ms ms (más de 1 s)"
    problemas+=("la búsqueda \"$q\" tardó $ms ms")
  else
    echo "  $q: $ms ms"
  fi
done
echo "Máximo: $maximo ms"

if [ ${#problemas[@]} -eq 0 ]; then
  echo "Listo para la sesión"
else
  echo "Revisar antes de la sesión:"
  printf '  - %s\n' "${problemas[@]}"
  exit 1
fi
