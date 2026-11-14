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
| `respaldo` | 03:30 | `respaldo.sh`: `pg_dump -Fc` de la base, comprobado con `pg_restore --list`; no respalda si falta espacio y, cuando el respaldo terminó bien, `retencion.sh` manda a la Papelera los antiguos (ver "Respaldos") |
| `purga` | 04:15 | `purga.sh`: la retención de datos de personas (`rappi-ia purge`); anota sus tres cifras y avisa si falla |
| `resumen` | 08:00 | `resumen.sh`: el resumen de la API del día anterior (`rappi-ia resumen-api`: peticiones por ruta, promedio y máximo, las de más de 1 s, los errores 5xx con su `request_id` y las personas nuevas del prototipo, contadas en el registro (`POST /session`) y, entre paréntesis, las que siguen en la base: "Borrar mis datos" borra la fila). La mantención del vigilante va en una línea aparte y no cuenta en las cifras. Lee la copia rotada (`api.log.1`) solo si es de los dos últimos días. Lo deja en `RESUMEN_API_TXT` (por defecto `~/rappi-tunel/resumen-api.txt`) y avisa con una línea. Si el disco no alcanza para el próximo respaldo, lo agrega al final y lo avisa aparte. Solo lee el registro y la base |

## Instalar

1. Una copia de `main` solo para servir (no la de desarrollo): `git worktree add ~/rappi-prod origin/main`, con `make install`, `make -C rappi-ia install-ml` y los `.env` de `rappi-ia` y `rappi-scraper` apuntando a la base.
2. Las herramientas: `brew install caddy cloudflared` (los scripts encuentran Homebrew en el PATH, en `/opt/homebrew` o en `/usr/local`).
3. La carpeta de trabajo, fuera del repo: `mkdir -m 700 ~/rappi-tunel` y `~/rappi-tunel/tunel.env` desde [`env.example`](env.example) (modo 600). El hash de la puerta sale de `caddy hash-password`; la clave se guarda aparte.
4. Los archivos servidos la primera vez: `deploy/macos/actualizar.sh --forzar` (o copiar `prototipo-app/dist` y `dashboard-empresa/dist` a `~/rappi-tunel/srv/app` y `srv/panel`).
5. `deploy/macos/instalar.sh` desde la copia de `~/rappi-prod`. Si el modelo de texto no está en la caché de Hugging Face (en el commit fijado en `rappi-ia/src/rappi_ia/config.py`), primero lo descarga (una vez, ~1 GB); después instala y arranca los servicios. La URL queda en `~/rappi-tunel/url.txt`.

6. El rol de la API: `deploy/macos/rol-api.sh`. Crea `rappi_api` (o `API_DB_ROLE`) en el Postgres del Mac, le da los permisos de [`deploy/db/grants.sql`](../db/grants.sql) (lee todo y escribe solo los datos de las personas) y reinicia la API, que desde entonces se conecta con ese rol en vez del usuario del Mac (`api.sh` lo pone en `PGUSER`). Con Postgres de Homebrew la conexión local es "trust": el rol no lleva clave, y el límite es contra un error de la API, no contra alguien con acceso al Mac. Cada actualización vuelve a aplicar los permisos (`deploy-migrate` con `DB_API_ROLE`). Si Postgres no responde al arrancar, la API espera (launchd la relanza) en vez de entrar como el usuario del Mac. **Después de restaurar la base o de cambiar la de `DATABASE_URL`, volver a correr `rol-api.sh`:** un respaldo restaurado sin permisos deja al rol sin poder leer. Sin el rol, todo sigue como antes.

Para cambiar la clave de la puerta: `deploy/macos/cambiar-clave.sh` (la pide dos veces sin mostrarla, guarda solo su hash y reinicia Caddy). Para quitar todo: `deploy/macos/instalar.sh --quitar`. Registros en `~/rappi-tunel/logs/`.

## Pausar los despliegues y chequear antes de una sesión

Para la prueba con usuarios ([docs/prueba-usuarios.md](../../docs/prueba-usuarios.md), secciones 3 y 6):

- **Pausa:** `touch ~/rappi-tunel/pausa-actualizar`. Mientras exista, `actualizar.sh` solo anota "Pausado" y sale: lo que se fusione a `main` no llega a la demo, no se reinicia la API ni se toma un respaldo antes de migrar. `deploy/macos/actualizar.sh --forzar` actualiza igual. Para reanudar, `rm ~/rappi-tunel/pausa-actualizar`: la vuelta siguiente despliega lo pendiente. En la prueba, recién después de `rappi-ia olvidar`.
- **Chequeo:** `deploy/macos/chequeo-sesion.sh`, justo antes de cada participante. Solo lee: `/health`, la swap, el disco libre, la fecha del catálogo (la última corrida terminada de tiendas y de restaurantes), si los despliegues están en pausa, el grupo de control ("Grupo de control: N %": `OFFERS_CONTROL_PCT` calculado como la API, de `tunel.env` o, si no lo define, del `.env` de `rappi-ia` de la copia que se sirve) y 8 búsquedas variadas contra la API local, con el tiempo de cada una y el máximo. Sale con 1 y lo lista en "Revisar antes de la sesión" si la API no está lista, si una búsqueda falla o pasa de 1 s, si no hay pausa, si el grupo de control no está en 0 o no lo pudo leer, o si el disco no alcanza para el próximo respaldo. Es el valor con que arranca la API: la que corre lo tomó al reiniciarse. De esos archivos no imprime ninguna clave, solo ese número y, si no pudo leer la base, su nombre. El RSS y el footprint de cada proceso de la API van como dato (con la mayor parte en swap, la primera búsqueda tarda segundos), no como criterio. Sus búsquedas llevan el id `vigilante-chequeo-…`, así que el resumen diario las cuenta en la línea de mantención del vigilante, no como visitas. No pausa los despliegues ni calienta con seguridad los dos procesos: las búsquedas pueden caer todas en el mismo.

## Respaldos

Quedan en `~/rappi-tunel/respaldos/`, ~2 GB cada uno: `nocturno_rappi_<fecha>.dump` (cada noche) y `pre-migracion_rappi_<fecha>.dump` (antes de cada despliegue con migraciones).

- **Retención:** `retencion.sh`, que `respaldo.sh` llama solo cuando el respaldo nuevo terminó bien (`pg_dump`, `pg_restore --list` y el archivo en su nombre final; si algo falla antes, no corre). Deja los `RESPALDOS_NOCTURNOS_A_GUARDAR` nocturnos (3; también vale `RESPALDOS_A_GUARDAR`, el nombre anterior) y los `RESPALDOS_PRE_MIGRACION_A_GUARDAR` de antes de migrar (2) más nuevos, de los dos tipos en cada respaldo, y saca los `.dump.tmp` de esos tipos con más de un día (de un respaldo cortado de golpe). Lo que saca va a la **Papelera** (`trash`, que trae macOS); si no hay `trash` o falla, a `respaldos/para-borrar/`, y avisa. Nunca borra, nunca saca el respaldo recién hecho (siempre queda al menos uno de cada tipo) y no toca otros archivos de la carpeta. No saca nada, y avisa, si el respaldo nuevo está vacío o mide menos de la mitad del anterior, o si una cantidad no es un entero mayor que 0.
- **La Papelera no libera el disco:** lo que la retención manda ahí sigue ocupando espacio hasta vaciarla. Vaciarla a mano o encender "Eliminar ítems de la Papelera después de 30 días" (Finder → Ajustes → Avanzado).
- **Aviso de disco:** el respaldo pide libre el doble del último respaldo más 5 GB; si no está, no respalda y avisa. El resumen diario y el chequeo de antes de una sesión dicen "poco espacio en disco" con ese mismo umbral, antes de que un respaldo se omita.
- **Copia fuera del equipo (apagada):** `respaldo-externo.sh` copia el respaldo más nuevo a `RESPALDO_EXTERNO_DIR` (una carpeta de un disco externo o una carpeta sincronizada) y comprueba que la copia tenga el mismo tamaño y la misma suma SHA-256 antes de darle su nombre final. Sin la variable no hace nada; si la carpeta no existe (el disco no está conectado), avisa y no copia; no borra nada en el destino. **El respaldo trae los datos de las personas del prototipo (sus búsquedas, eventos y pedidos de prueba): el destino tiene que ser privado**, no una carpeta compartida, y lo que "Borrar mis datos" u `olvidar` borran de la base sigue en esas copias hasta que se borran allá. Para encenderla:
  1. Elegir el destino y crear la carpeta (por ejemplo `/Volumes/<disco>/rappi-respaldos`, o una carpeta de iCloud Drive o de otro servicio que sincronice solo con la cuenta propia).
  2. En `~/rappi-tunel/tunel.env`: `RESPALDO_EXTERNO_DIR="/Volumes/<disco>/rappi-respaldos"`.
  3. Probarla a mano: `deploy/macos/respaldo-externo.sh` (dice "Copia externa lista" con la suma, o "al día" si ya estaba).
  4. Si se quiere cada día, después del respaldo nocturno, sumarle un servicio de launchd (por ejemplo a las 05:00) en `instalar.sh`; no viene programada. El destino no rota: borrar allá las copias viejas.

## Requisitos del Mac

- **Que no se duerma** (Ajustes del Sistema → Energía) y que **arranque solo tras un corte de luz**.
- **Inicio de sesión automático** del usuario: los servicios son de launchd del usuario y arrancan al iniciar su sesión.
- Espacio para los respaldos: ~2 GB cada uno, 5 con la retención por defecto (~10 GB), más el doble del último y 5 GB libres para el siguiente, más lo que esté en la Papelera sin vaciar.

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
- **Los respaldos quedan en el mismo Mac** mientras no se encienda la copia fuera del equipo (`respaldo-externo.sh`, ver "Respaldos"): si el disco del Mac se pierde, se pierden con él.
