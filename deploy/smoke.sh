#!/usr/bin/env bash
# Prueba de humo del stack desplegado: deploy/smoke.sh https://el-dominio
# Revisa la puerta de acceso, la API lista (con la búsqueda semántica), las cabeceras de seguridad, que lo servido no
# apunte a :8000 ni cargue nada que la CSP bloquee, que la app lleve el aviso de demo no oficial, que rappi_api no pueda
# borrar tablas, que ningún servicio (jobs incluido) tenga valores de ejemplo y que todo el stack esté sano.
# Sale con 0 o dice qué falló.
#
# Necesita la clave de la puerta en claro en BASIC_AUTH_PASSWORD (no se guarda en el servidor; se pasa a curl por la
# entrada estándar, nunca en la línea de comandos). El usuario sale de BASIC_AUTH_USER o del archivo de entorno.
# Corre desde cualquier carpeta, en el servidor (usa `docker compose`). Con un host localhost acepta la CA interna de
# Caddy (curl -k). COMPOSE cambia el comando de compose (por defecto, el de deploy/ con deploy/.env).
set -uo pipefail

url="${1:?Uso: deploy/smoke.sh https://el-dominio}"
url="${url%/}"
here="$(cd "$(dirname "$0")" && pwd)"
read -r -a compose <<<"${COMPOSE:-docker compose -f $here/docker-compose.yml}"

failures=()
fail() { failures+=("$1"); echo "  ✗ $1"; }
pass() { echo "  ✓ $1"; }

insecure=()
case "$url" in https://localhost* | https://127.0.0.1*) insecure=(-k) ;; esac

# Usuario de la puerta: el del entorno o el del contenedor de Caddy (que lo recibe del archivo de entorno).
user="${BASIC_AUTH_USER:-$("${compose[@]}" exec -T web printenv BASIC_AUTH_USER 2>/dev/null)}"
if [ -z "$user" ] || [ -z "${BASIC_AUTH_PASSWORD:-}" ]; then
  echo "smoke: falta BASIC_AUTH_PASSWORD (la clave de la puerta, en claro) o no se encontró BASIC_AUTH_USER." >&2
  exit 2
fi

# curl con credenciales: el usuario y la clave van en un archivo de configuración por la entrada estándar.
authed() { printf 'user = "%s:%s"\n' "$user" "$BASIC_AUTH_PASSWORD" | curl -sS ${insecure[@]+"${insecure[@]}"} -K - "$@"; }
anon() { curl -sS ${insecure[@]+"${insecure[@]}"} "$@"; }

echo "Puerta de acceso"
for path in / /api/health /panel /panel/; do
  code=$(anon -o /dev/null -w '%{http_code}' "$url$path")
  if [ "$code" = 401 ]; then pass "$path sin credenciales: 401"; else fail "$path sin credenciales dio $code (se esperaba 401)"; fi
done

echo "API"
health=$(authed -w '\n%{http_code}' "$url/api/health")
code="${health##*$'\n'}"
body="${health%$'\n'*}"
if [ "$code" = 200 ] && grep -q '"busqueda_semantica":true' <<<"$body"; then
  pass "/api/health: 200 con búsqueda semántica"
else
  fail "/api/health dio $code sin la búsqueda semántica lista: $body"
fi

echo "Cabeceras"
headers=$(authed -o /dev/null -D - "$url/")
for header in "strict-transport-security: max-age=31536000" \
  "content-security-policy: default-src 'self'; img-src 'self' https://images.rappi.cl data:; connect-src 'self'; frame-ancestors 'none'" \
  "x-content-type-options: nosniff" "referrer-policy: no-referrer" "x-robots-tag: noindex, nofollow" \
  "permissions-policy: camera=(), microphone=(), geolocation=()" "cache-control: no-cache"; do
  if grep -qiF "$header" <<<"$headers"; then pass "${header%%:*}"; else fail "falta la cabecera «$header» en /"; fi
done
if grep -qi '^server:' <<<"$headers"; then fail "/ dice su servidor (cabecera Server)"; else pass "sin cabecera Server"; fi
api_headers=$(authed -o /dev/null -D - "$url/api/live")
if grep -qi '^server:' <<<"$api_headers"; then fail "/api/live dice su servidor (cabecera Server)"; else pass "/api sin cabecera Server"; fi
if grep -qi '^content-security-policy:' <<<"$api_headers"; then pass "/api con CSP"; else fail "/api sin CSP"; fi

echo "Lo servido"
index=$(authed "$url/")
assets=$(grep -oE '/assets/[^"]+\.(js|css)' <<<"$index" | sort -u)
if [ -z "$assets" ]; then
  fail "index.html no carga ningún archivo de /assets/"
else
  first=$(head -n 1 <<<"$assets")
  cache=$(authed -o /dev/null -D - "$url$first")
  if grep -qi 'cache-control: private, max-age=31536000, immutable' <<<"$cache"; then
    pass "/assets/ se guarda un año"
  else
    fail "$first sin Cache-Control inmutable"
  fi
fi
served="$index"
for asset in $assets; do served+=$'\n'$(authed "$url$asset"); done
if grep -qF ':8000' <<<"$served"; then fail "lo servido menciona :8000"; else pass "ningún :8000 en lo servido"; fi
# El aviso fijo de la Home (DemoDisclaimer), con o sin VITE_DEMO: viaja en el JavaScript de la app.
if grep -qF 'Demo no oficial · prototipo independiente, no afiliado a Rappi' <<<"$served"; then
  pass "el aviso «Demo no oficial» está en la app"
else
  fail "falta el aviso «Demo no oficial» en la app servida"
fi
# Lo que la CSP bloquearía en index.html: scripts en línea y scripts u hojas de estilo de otro origen.
if grep -oE '<script[^>]*>' <<<"$index" | grep -qv 'src='; then
  fail "index.html trae un script en línea (la CSP lo bloquea)"
else
  pass "sin scripts en línea"
fi
if grep -qE '<(script|link)[^>]+(src|href)="(https?:)?//' <<<"$index"; then
  fail "index.html carga scripts u hojas de estilo de otro origen (la CSP los bloquea)"
else
  pass "scripts y estilos del mismo origen"
fi

echo "Base"
# Como rappi_api, con su clave (dentro del contenedor de la base: no pasa por este equipo). El DROP va dentro de una
# transacción que siempre se deshace: si el rol pudiera borrar la tabla (eso es lo que falla), no la borra.
# shellcheck disable=SC2016 # las variables se expanden adentro del contenedor, no aquí
drop=$("${compose[@]}" exec -T db sh -c \
  'PGPASSWORD="$RAPPI_API_PASSWORD" psql -h 127.0.0.1 -U rappi_api -d "${POSTGRES_DB:-rappi}" -v ON_ERROR_STOP=1 \
     -c BEGIN -c "DROP TABLE app_events" -c ROLLBACK' 2>&1)
if grep -q 'must be owner' <<<"$drop"; then
  pass "rappi_api no puede borrar app_events"
else
  fail "rappi_api y DROP TABLE app_events: $drop"
fi
# Como superusuario (socket local del contenedor): ninguna tabla es de rappi_api ni de un rol suyo, y no puede crear
# objetos en public ni en capa.
# shellcheck disable=SC2016 # la variable se expande adentro del contenedor, no aquí
roles=$("${compose[@]}" exec -T db sh -c 'psql -U postgres -d "${POSTGRES_DB:-rappi}" -At' 2>&1 <<'SQL'
SELECT count(*) FROM pg_tables
 WHERE schemaname IN ('public', 'capa') AND pg_has_role('rappi_api', tableowner, 'MEMBER');
SELECT has_schema_privilege('rappi_api', 'public', 'CREATE') OR has_schema_privilege('rappi_api', 'capa', 'CREATE');
SQL
)
if [ "$roles" = $'0\nf' ]; then
  pass "ninguna tabla es de rappi_api y no puede crear en public ni capa"
else
  fail "rappi_api es dueño de tablas o puede crear en public o capa: $roles"
fi

echo "Entorno"
# Ningún servicio quedó con un valor de ejemplo (deploy/.env.example). Se muestran los nombres, nunca los valores. Los
# que corren se leen por dentro (exec); jobs, que no corre, en un contenedor desechable sin dependencias. Si el entorno
# no se puede leer, es un fallo (no un «sin cambiar-esto»).
check_env() {  # check_env <servicio> <comando de compose que corre un comando en ese servicio...>
  local service=$1 left
  shift
  if ! left=$("$@" sh -c 'env | grep -F cambiar-esto | cut -d= -f1' </dev/null 2>/dev/null); then
    fail "no se pudo leer el entorno de $service"
  elif [ -n "$left" ]; then
    fail "$service tiene «cambiar-esto» en: $(tr '\n' ' ' <<<"$left")"
  else
    pass "$service sin «cambiar-esto»"
  fi
}
while read -r service; do
  check_env "$service" "${compose[@]}" exec -T "$service"
done < <("${compose[@]}" ps --format '{{.Service}}')
check_env jobs "${compose[@]}" run --rm --no-deps -T jobs

echo "Stack"
ps=$("${compose[@]}" ps --format '{{.Service}} {{.Status}}')
if [ -z "$ps" ]; then
  fail "docker compose ps no muestra servicios"
else
  while read -r service status; do
    if [[ "$status" == *"(healthy)"* ]]; then pass "$service sano"; else fail "$service: $status"; fi
  done <<<"$ps"
fi

if [ "${#failures[@]}" -gt 0 ]; then
  echo "smoke: ${#failures[@]} problema(s):" >&2
  printf '  - %s\n' "${failures[@]}" >&2
  exit 1
fi
echo "smoke: todo bien."
