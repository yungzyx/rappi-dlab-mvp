#!/usr/bin/env bash
# make build deja prototipo-app/dist y dashboard-empresa/dist; esto revisa que no lleven rastros de desarrollo.
# Sale con 1 si encuentra alguno. Qué revisa y por qué:
#  1. Siempre: la dirección de la API local (":8000", "localhost"). Un build de producción habla con "/api" (o con
#     VITE_API_URL); si aparecen, la app quedó apuntando al equipo de quien la construyó.
#     También siempre: la API simulada y el «Panel de la demo» de la demo sin conexión («Prototipo MVP.html», `npm run
#     demo:html`, `vite build --mode demo`): solo entran a dist-demo/, nunca a un build normal ni al de VITE_DEMO=1.
#  2. Salvo con VITE_DEMO=1: los textos de desarrollador y los controles de la demo. La app los deja detrás de
#     `import.meta.env.DEV || VITE_DEMO === '1'`, que Vite pliega al construir, así que en un build normal el código y
#     sus textos desaparecen del bundle: «make mvp», «Levanta el MVP», «No pude conectar» (aviso de
#     ConnectionGate), «Tecla D» y «Modo de la demo» (interruptor). No se revisan «Modo demo» ni «Rappi hoy»: siguen en
#     el bundle porque la fila de Cuenta y las etiquetas se filtran en tiempo de ejecución.
#  Con VITE_DEMO=1 el grupo 2 se omite: ese build deja esos textos a propósito (la demo desplegada, ver docs/despliegue.md).
#  3. Siempre: ningún <script> en línea (sin src) en los HTML. La CSP del servidor (deploy/Caddyfile) los bloquea. Se
#     exceptúa presentacion/mapa-multivertical.html del panel, que Caddy sirve con su propia CSP.
set -euo pipefail
cd "$(dirname "$0")/.."

always=(':8000' 'localhost' 'api-simulada' 'Panel de la demo')
dev_only=('make mvp' 'Levanta el MVP' 'No pude conectar' 'Tecla D' 'Modo de la demo')

patterns=("${always[@]}")
if [ "${VITE_DEMO:-}" = 1 ]; then
  echo "check-dist: VITE_DEMO=1, se omiten los textos de la demo."
else
  patterns+=("${dev_only[@]}")
fi

status=0
for dir in prototipo-app/dist dashboard-empresa/dist; do
  if [ ! -d "$dir" ]; then
    echo "check-dist: falta $dir; corre \`make build\` primero." >&2
    exit 1
  fi
  for pattern in "${patterns[@]}"; do
    if matches=$(grep -rIl -F -e "$pattern" "$dir"); then
      echo "check-dist: «$pattern» aparece en $dir:" >&2
      while IFS= read -r file; do echo "  $file" >&2; done <<< "$matches"
      status=1
    fi
  done
  while IFS= read -r html; do
    if grep -oE '<script[^>]*>' "$html" | grep -qv 'src='; then
      echo "check-dist: $html trae un <script> en línea (la CSP del servidor lo bloquea)." >&2
      status=1
    fi
  done < <(find "$dir" -name '*.html' ! -path '*/presentacion/mapa-multivertical.html')
done

if [ "$status" = 0 ]; then
  echo "check-dist: prototipo-app/dist y dashboard-empresa/dist sin rastros de desarrollo ni scripts en línea."
fi
exit "$status"
