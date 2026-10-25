# Demo pública desde un Mac (Cloudflare Tunnel)

Publica el MVP desde un Mac con la base ya cargada, sin servidor ni Docker: la API en modo producción, Caddy con la puerta de acceso y un túnel de Cloudflare con HTTPS. Sirve para pruebas con personas mientras no hay un servidor; para un servidor está [docs/despliegue.md](../../docs/despliegue.md) (y la infraestructura en Oracle Cloud, en `infra/oci/`).

```
visitante ──HTTPS──▶ Cloudflare ──túnel──▶ Caddy 127.0.0.1:8080 (puerta, CSP) ─┬─▶ archivos de la app y el panel
                                                                               └─▶ API 127.0.0.1:8100 (/api)
```

Nada escucha hacia la red: Caddy y la API solo atienden en `127.0.0.1`, y se entra únicamente por el túnel.

## Qué corre

`instalar.sh` deja estos servicios de launchd en `~/Library/LaunchAgents` (etiquetas `cl.rappidlab.*`):

| Servicio | Cuándo | Qué hace |
|---|---|---|
| `api` | siempre (se reinicia si se cae) | `api.sh`: la API con `API_ENV=production`, `/analytics` encendido para el panel, 2 procesos |
| `caddy` | siempre | `caddy.sh`: la puerta (`basic_auth`), las cabeceras y la CSP de `deploy/Caddyfile`, la API en `/api` |
| `tunel` | siempre | `tunel.sh`: túnel rápido (URL `….trycloudflare.com` que cambia en cada inicio) o, con `TUNNEL_TOKEN`, un túnel con nombre y URL fija |
| `vigilante` | cada 5 min | `vigilante.sh`: reinicia lo que lleve dos revisiones caído, anota la URL vigente en `url.txt` y avisa con una notificación, y rota los registros de más de 20 MB |
| `actualizar` | cada 15 min | `actualizar.sh`: si `origin/main` cambió, trae los cambios, instala dependencias si cambiaron, respalda y migra si hay migraciones, construye y reinicia solo la API (la URL no cambia) |
| `respaldo` | 03:30 | `respaldo.sh`: `pg_dump -Fc` de la base, comprobado con `pg_restore --list`; guarda los 3 más nuevos y no respalda si falta espacio |
| `purga` | 04:15 | `purga.sh`: la retención de datos de personas (`rappi-ia purge`) |

## Instalar

1. Una copia de `main` solo para servir (no la de desarrollo): `git worktree add ~/rappi-prod origin/main`, con `make install`, `make -C rappi-ia install-ml` y los `.env` de `rappi-ia` y `rappi-scraper` apuntando a la base.
2. Las herramientas: `brew install caddy cloudflared`.
3. La carpeta de trabajo, fuera del repo: `mkdir -m 700 ~/rappi-tunel` y `~/rappi-tunel/tunel.env` desde [`env.example`](env.example) (modo 600). El hash de la puerta sale de `caddy hash-password`; la clave se guarda aparte.
4. Los archivos servidos la primera vez: `deploy/macos/actualizar.sh --forzar` (o copiar `prototipo-app/dist` y `dashboard-empresa/dist` a `~/rappi-tunel/srv/app` y `srv/panel`).
5. `deploy/macos/instalar.sh` desde la copia de `~/rappi-prod`. La URL queda en `~/rappi-tunel/url.txt`.

Para quitar todo: `deploy/macos/instalar.sh --quitar`. Registros en `~/rappi-tunel/logs/`.

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

Cada persona de la prueba crea una sesión del prototipo: después hay que olvidarlas (`events.store.forget`) para que no cuenten en «Uso del MVP».

## Límites

- **El túnel rápido** no tiene garantía de disponibilidad y su URL cambia en cada inicio. Con una cuenta de Cloudflare y un dominio, `TUNNEL_TOKEN` en `tunel.env` da una URL fija sin cambiar nada más.
- **Depende del Mac:** si se apaga o pierde internet, la demo cae. Para algo permanente, un servidor (`infra/oci/` y [docs/despliegue.md](../../docs/despliegue.md)).
- **Los respaldos quedan en el mismo Mac:** para una copia afuera, sumar un destino (por ejemplo restic, como en el servidor).
