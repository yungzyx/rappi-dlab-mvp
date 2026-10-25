"""Configuración: URLs de Rappi, cómo se presenta el scraper, ritmo de requests y rutas del proyecto.

Se ajustan con variables de entorno (o en `.env`) sin tocar código: RAPPI_UA_PROJECT y RAPPI_UA_CONTACT (el
User-Agent) y el ritmo de requests, RAPPI_DELAY_MIN, RAPPI_DELAY_MAX, RAPPI_TIMEOUT, RAPPI_MAX_RETRIES y
RAPPI_RETRY_BACKOFF.
"""

import os
from importlib.metadata import version
from pathlib import Path

from dotenv import load_dotenv

# Rutas absolutas desde la raíz del proyecto: funcionan sin importar desde dónde se ejecute.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# El .env de siempre (rappi-scraper/.env) o el que diga RAPPI_ENV_FILE (en un servidor, /etc/rappi/rappi.env).
load_dotenv(os.environ.get("RAPPI_ENV_FILE") or PROJECT_ROOT / ".env")

# Datos descargados, registros y respaldos: por defecto rappi-scraper/data; en un contenedor, RAPPI_DATA_DIR (un
# volumen, fuera del código).
DATA_DIR = Path(os.environ.get("RAPPI_DATA_DIR") or PROJECT_ROOT / "data")
EXPORT_DIR = DATA_DIR / "exports"


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


BASE_URL = "https://www.rappi.cl"
STORES_METADATA_URL = (
    "https://cpgs-br.s3.amazonaws.com/web-assets/public/indexedData/country/cl/storefronts-metadata.json"
)


def user_agent(project: str, contact: str) -> str:
    """El User-Agent: un programa con nombre y versión, no un navegador. Sin contacto, igual dice quién descarga."""
    about = "prototipo de investigacion dLab, no afiliado a Rappi"  # sin tildes: va en una cabecera HTTP
    contact_part = f"+{contact}; " if contact else ""
    return f"{project}/{version('rappi-scraper')} ({contact_part}{about})"


# Cómo se presenta ante rappi.cl. RAPPI_UA_PROJECT es también el nombre con que se buscan sus reglas en robots.txt;
# RAPPI_UA_CONTACT (una URL o un correo) le dice a Rappi a quién escribir.
UA_PROJECT = os.environ.get("RAPPI_UA_PROJECT", "").strip() or "rappi-dlab-scraper"
UA_CONTACT = os.environ.get("RAPPI_UA_CONTACT", "").strip()
USER_AGENT = user_agent(UA_PROJECT, UA_CONTACT)

# Ritmo prudente: pausa aleatoria entre requests (segundos) y reintentos ante 429/5xx, con espera exponencial
# (10, 20, 40 s…) o la que pida rappi.cl en `Retry-After`, hasta un tope.
REQUEST_DELAY_RANGE = (_env_float("RAPPI_DELAY_MIN", 1.5), _env_float("RAPPI_DELAY_MAX", 3.0))
TIMEOUT_SECONDS = _env_float("RAPPI_TIMEOUT", 30)
MAX_RETRIES = int(_env_float("RAPPI_MAX_RETRIES", 3))
RETRY_BACKOFF_SECONDS = _env_float("RAPPI_RETRY_BACKOFF", 10)
RETRY_AFTER_MAX_S = 900
# Requests seguidos rechazados (403, 429 o página de desafío sin __NEXT_DATA__): la descarga se detiene (PossibleBlock)
# sin esperar a que fallen jobs enteros, que con 19 pasillos y 3 intentos por página tardaban casi una hora.
BLOCK_STREAK_REQUESTS = 20

# Si una sucursal no está disponible, cuántas otras de la misma marca probar.
MAX_BRANCH_ATTEMPTS = 3
# Fracción máxima de páginas (pasillos y sub-pasillos) omitidas para dar una tienda por bajada. Más que esto y el job
# falla: un catálogo a medias pasaría a ser la corrida vigente del formato y escondería lo que no se leyó.
SKIPPED_PAGES_MAX = 0.05

# Intentos por job: 1 + una pasada automática de reintento al final de la corrida
# (cubre errores transitorios de Rappi como 502 o páginas incompletas).
MAX_JOB_ATTEMPTS = 2
# Jobs seguidos que fallan sin respuesta útil de rappi.cl (403, 429, red, página de desafío): la corrida se detiene.
MAX_CONSECUTIVE_FAILURES = 10
# Los jobs de esa racha vuelven a la cola mientras lleven menos de 4 intentos: así resisten un bloqueo en la pasada de
# reintento y otro la semana siguiente. Si la misma racha se repite semana tras semana es un error fijo de esos jobs,
# no un bloqueo: quedan 'failed' y la corrida sigue.
MAX_BLOCKED_JOB_ATTEMPTS = MAX_JOB_ATTEMPTS + 2

# Rappi redirige aquí cuando la tienda no despacha a la ubicación configurada.
UNAVAILABLE_PATH_PREFIX = "/tiendas/tipo/"
# Rappi redirige a /restaurantes?restaurantNotFound=true cuando el restaurante ya no existe (cerró o se dio de baja).
RESTAURANT_NOT_FOUND_QUERY = "restaurantNotFound=true"

# Cuánto espera cada sentencia de una migración por un candado de tabla antes de fallar (lock_timeout de Postgres): un
# ALTER detrás de una transacción larga dejaba en fila a todas las consultas de esa tabla mientras esperaba.
MIGRATE_LOCK_TIMEOUT = os.environ.get("MIGRATE_LOCK_TIMEOUT", "10s")
