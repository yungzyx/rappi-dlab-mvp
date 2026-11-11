# Demo desde un Mac (Cloudflare Tunnel, con puerta de acceso)

Publica el MVP desde un Mac con la base ya cargada, sin servidor ni Docker: la API en modo producción, Caddy con la puerta de acceso y un túnel de Cloudflare con HTTPS. Sirve para pruebas con personas mientras no hay un servidor; para un servidor está [docs/despliegue.md](../../docs/despliegue.md).

```
visitante ──HTTPS──▶ Cloudflare ──túnel──▶ Caddy 127.0.0.1:8080 (puerta, CSP) ─┬─▶ archivos de la app y el panel
                                                                               └─▶ API 127.0.0.1:8100 (/api)
```

Nada escucha hacia la red: Caddy y la API solo atienden en `127.0.0.1`, y se entra únicamente por el túnel.

## Qué corre

`instalar.sh` deja estos servicios de launchd en `~/Library/LaunchAgents` (etiquetas `cl.rappidlab.*`):

| Servicio | Cuándo | Qué hace |
|---|---|---|
| `api` | siempre (se reinicia si se cae) | `api.sh`: la API con `API_ENV=production`, `/analytics` encendido para el panel, 2 procesos; el modelo de texto solo de la caché (`HF_HUB_OFFLINE=1`) y, sin él, no está lista (`API_REQUIRE_SEMANTIC=1`: `/health` da 503 y el vigilante avisa), como en el servidor |
| `caddy` | siempre | `caddy.sh`: la puerta (`basic_auth`), las cabeceras y la CSP (las de `deploy/Caddyfile`, copiadas en `deploy/macos/Caddyfile`: el CI revisa que sean las mismas), la API en `/api` |
| `tunel` | siempre | `tunel.sh`: un túnel con nombre y URL fija (`TUNNEL_NAME` o `TUNNEL_TOKEN`) o, sin ellos, un túnel rápido (URL `….trycloudflare.com` que cambia en cada inicio) |
| `vigilante` | cada 5 min | `vigilante.sh`: reinicia lo que lleve dos revisiones caído, hace dos búsquedas chicas para que el modelo de texto no salga de la memoria (con el id `vigilante-…`, que el resumen cuenta aparte), anota la URL vigente en `url.txt` y avisa con una notificación, rota los registros de más de 20 MB y, si todo respondió, llama a `HEARTBEAT_URL` (opcional, ver Límites) |
| `actualizar` | cada 15 min | `actualizar.sh`: si `origin/main` no es lo último desplegado (`~/rappi-tunel/desplegado.txt`), trae los cambios, instala dependencias si cambiaron, respalda y migra si hay migraciones, construye y reinicia la API (la URL no cambia). Si cambiaron, reinicia Caddy (antes valida el Caddyfile; si no valida, avisa y deja el anterior) o el túnel con nombre (el rápido cambiaría de URL: solo avisa), y avisa si cambió `instalar.sh`. Si un paso falla, avisa y la vuelta siguiente lo reintenta (sin volver a respaldar: se queda el respaldo de antes del primer intento). Si solo cambiaron archivos `.md` (fuera de un `public/`, que se copia a lo servido), trae los cambios y anota el commit sin construir ni reiniciar (nada se construye ni se sirve desde ellos). Mientras exista `~/rappi-tunel/pausa-actualizar` no hace nada (ver "Pausar los despliegues") |
| `respaldo` | 03:30 | `respaldo.sh`: `pg_dump -Fc` de la base, comprobado con `pg_restore --list`; guarda los 3 más nuevos y no respalda si falta espacio |
| `purga` | 04:15 | `purga.sh`: la retención de datos de personas (`rappi-ia purge`); anota sus tres cifras y avisa si falla |
| `resumen` | 08:00 | `resumen.sh`: el resumen de la API del día anterior (`rappi-ia resumen-api`: peticiones por ruta, promedio y máximo, las de más de 1 s, los errores 5xx con su `request_id` y las personas nuevas del prototipo, contadas en el registro (`POST /session`) y, entre paréntesis, las que siguen en la base: "Borrar mis datos" borra la fila). La mantención del vigilante va en una línea aparte y no cuenta en las cifras. Lee la copia rotada (`api.log.1`) solo si es de los dos últimos días. Lo deja en `RESUMEN_API_TXT` (por defecto `~/rappi-tunel/resumen-api.txt`) y avisa con una línea. Solo lee el registro y la base |

## Instalar

1. Una copia de `main` solo para servir (no la de desarrollo): `git worktree add ~/rappi-prod origin/main`, con `make install`, `make -C rappi-ia install-ml` y los `.env` de `rappi-ia` y `rappi-scraper` apuntando a la base.
2. Las herramientas: `brew install caddy cloudflared` (los scripts encuentran Homebrew en el PATH, en `/opt/homebrew` o en `/usr/local`).
3. La carpeta de trabajo, fuera del repo: `mkdir -m 700 ~/rappi-tunel` y `~/rappi-tunel/tunel.env` desde [`env.example`](env.example) (modo 600). El hash de la puerta sale de `caddy hash-password`; la clave se guarda aparte.
4. Los archivos servidos la primera vez: `deploy/macos/actualizar.sh --forzar` (o copiar `prototipo-app/dist` y `dashboard-empresa/dist` a `~/rappi-tunel/srv/app` y `srv/panel`).
5. `deploy/macos/instalar.sh` desde la copia de `~/rappi-prod`. Si el modelo de texto no está en la caché de Hugging Face (en el commit fijado en `rappi-ia/src/rappi_ia/config.py`), primero lo descarga (una vez, ~1 GB); después instala y arranca los servicios. La URL queda en `~/rappi-tunel/url.txt`.

Para cambiar la clave de la puerta: `deploy/macos/cambiar-clave.sh` (la pide dos veces sin mostrarla, guarda solo su hash y reinicia Caddy). Para quitar todo: `deploy/macos/instalar.sh --quitar`. Registros en `~/rappi-tunel/logs/`.

## Pausar los despliegues y chequear antes de una sesión

Para la prueba con usuarios ([docs/prueba-usuarios.md](../../docs/prueba-usuarios.md), secciones 3 y 6):

- **Pausa:** `touch ~/rappi-tunel/pausa-actualizar`. Mientras exista, `actualizar.sh` solo anota "Pausado" y sale: lo que se fusione a `main` no llega a la demo, no se reinicia la API ni se toma un respaldo antes de migrar. `deploy/macos/actualizar.sh --forzar` actualiza igual. Para reanudar, `rm ~/rappi-tunel/pausa-actualizar`: la vuelta siguiente despliega lo pendiente. En la prueba, recién después de `rappi-ia olvidar`.
- **Chequeo:** `deploy/macos/chequeo-sesion.sh`, justo antes de cada participante. Solo lee: `/health`, la swap, el disco libre, la fecha del catálogo (la última corrida terminada de tiendas y de restaurantes), si los despliegues están en pausa, el grupo de control ("Grupo de control: N %": `OFFERS_CONTROL_PCT` calculado como la API, de `tunel.env` o, si no lo define, del `.env` de `rappi-ia` de la copia que se sirve) y 8 búsquedas variadas contra la API local, con el tiempo de cada una y el máximo. Sale con 1 y lo lista en "Revisar antes de la sesión" si la API no está lista, si una búsqueda falla o pasa de 1 s, si no hay pausa o si el grupo de control no está en 0 o no lo pudo leer. Es el valor con que arranca la API: la que corre lo tomó al reiniciarse. De esos archivos no imprime ninguna clave, solo ese número y, si no pudo leer la base, su nombre. El RSS y el footprint de cada proceso de la API van como dato (con la mayor parte en swap, la primera búsqueda tarda segundos), no como criterio. Sus búsquedas llevan el id `vigilante-chequeo-…`, así que el resumen diario las cuenta en la línea de mantención del vigilante, no como visitas. No pausa los despliegues ni calienta con seguridad los dos procesos: las búsquedas pueden caer todas en el mismo.

## Requisitos del Mac

- **Que no se duerma** (Ajustes del Sistema → Energía) y que **arranque solo tras un corte de luz**.
- **Inicio de sesión automático** del usuario: los servicios son de launchd del usuario y arrancan al iniciar su sesión.
- Espacio para los respaldos (~2 GB cada uno).

## Capacidad medida

Con [`prueba-carga.py`](prueba-carga.py) (personas simuladas, cada una con su IP y su sesión: Home, búsqueda en todas las verticales, una pregunta a Mochi y una búsqueda por vertical, con pausas de 1 a 3 s), contra la API de un Mac mini con 16 GB y 2 procesos, sobre el catálogo real:

| Personas a la vez | Requests/s | Mochi p95 | Búsqueda p95 | Errores |
|---:|---:|---:|---:|---|
| 10 | 5 | 0,5 s | 0,5 s | 0 |
| 60 | 33 | 0,2 s | 0,09 s | 0 |
| 120 | 62 | 0,2 s | 0,1 s | 0 |
| 200 | 96 | 0,75 s | 0,17 s | 3,7 % de las búsquedas con 503 (el cupo de búsquedas a la vez) |

Cada persona de la prueba crea una sesión del prototipo: después hay que olvidarlas (`events.store.forget`) para que no cuenten en "Uso del MVP".

## Límites

- **El túnel rápido** no tiene garantía de disponibilidad y su URL cambia en cada inicio. Para una URL fija, con una cuenta de Cloudflare y un dominio: `cloudflared tunnel login` (autoriza el dominio en el navegador), `cloudflared tunnel create <nombre>`, `cloudflared tunnel route dns <nombre> <dominio>`, y en `tunel.env` `TUNNEL_NAME=<nombre>` y `PUBLIC_URL=https://<dominio>`. La credencial del túnel queda en `~/.cloudflared/`, fuera del repo.
- **Depende del Mac:** si se apaga o pierde internet, la demo cae. Para algo permanente, un servidor ([docs/despliegue.md](../../docs/despliegue.md)).
- **Los avisos son notificaciones del Mac** (y una línea en su registro): cuando un trabajo falla, cuando el vigilante reinicia algo o cuando la URL cambia. Sin red, ninguno sale del Mac; solo avisa un monitor externo: `HEARTBEAT_URL` en `tunel.env` (healthchecks.io u otro, que avisa si el vigilante deja de llamarla) o, con un túnel con nombre, la notificación de salud del túnel en el panel de Cloudflare.
- **Los respaldos quedan en el mismo Mac:** para una copia afuera, sumar un destino (por ejemplo restic, como en el servidor).
