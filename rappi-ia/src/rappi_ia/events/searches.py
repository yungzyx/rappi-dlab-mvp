"""Lo que el buscador muestra antes de escribir: las búsquedas recientes de la persona y «Lo más buscado».

- Recientes: las últimas búsquedas de esa persona (sus eventos `search`), sin repetir. «Olvidar» las borra con sus
  eventos y el texto de las consultas se borra a los QUERY_RETENTION_DAYS (events/store.py).
- Lo más buscado: lo que más personas buscaron y encontraron en los últimos TOP_WINDOW_DAYS días, solo de la población
  que se declara (`config.MOTOR_POBLACION`): `synthetic` y `prototype` nunca se mezclan, y la respuesta dice cuál es.
  Una búsqueda entra solo si la hicieron al menos TOP_MIN_PEOPLE personas (nadie ve lo que escribió una sola) y si no es
  algo que la app no propone por su cuenta (`offers/guards.py`: alcohol, salud, bebé, lo sensible).
"""

from psycopg import Connection

from .. import config
from ..catalog.cache import cached
from ..concepts.taxonomy import load_taxonomy
from ..offers.guards import alcohol_in_name, baby_in_name, is_offerable

RECENT_SEARCHES = 6
TOP_SEARCHES = 8
TOP_MIN_PEOPLE = 3
TOP_WINDOW_DAYS = 30
_TOP_POOL = 40  # candidatas antes de las guardias

# Un texto con un dato personal ya tapado al guardarlo («[correo]», «[dirección]») no se vuelve a mostrar.
_REDACTED = "%[%]%"

_RECENT = """
SELECT query FROM (
    SELECT DISTINCT ON (lower(btrim(query))) btrim(query) AS query, ts
    FROM app_events
    WHERE user_id = %(user)s AND type = 'search' AND query IS NOT NULL AND btrim(query) <> ''
      AND query NOT LIKE %(redacted)s
    ORDER BY lower(btrim(query)), ts DESC
) latest
ORDER BY ts DESC
LIMIT %(limit)s"""

_TOP = """
SELECT min(btrim(query)), count(DISTINCT user_id) AS people
FROM app_events
WHERE type = 'search' AND source = %(population)s AND ts >= now() - make_interval(days => %(days)s)
  AND query IS NOT NULL AND btrim(query) <> '' AND query NOT LIKE %(redacted)s
  AND unmet IS NOT TRUE AND coalesce(results, 0) > 0
GROUP BY lower(btrim(query))
HAVING count(DISTINCT user_id) >= %(min_people)s
ORDER BY people DESC, 1
LIMIT %(pool)s"""


def recent_searches(conn: Connection, user_id: str, limit: int = RECENT_SEARCHES) -> list[str]:
    """Las últimas búsquedas de la persona, de la más nueva a la más vieja, sin repetir (sin distinguir mayúsculas)."""
    rows = conn.execute(_RECENT, {"user": user_id, "limit": limit, "redacted": _REDACTED})
    return [query for (query,) in rows]


def top_searches(conn: Connection, population: str | None = None, limit: int = TOP_SEARCHES) -> list[str]:
    """«Lo más buscado» de una población (la declarada si no se da), de la más buscada a la menos. Sale de la caché
    (10 minutos): no cambia con cada búsqueda."""
    population = population or config.MOTOR_POBLACION

    def compute() -> list[str]:
        params = {
            "population": population,
            "days": TOP_WINDOW_DAYS,
            "min_people": TOP_MIN_PEOPLE,
            "pool": _TOP_POOL,
            "redacted": _REDACTED,
        }
        return [query for query, _ in conn.execute(_TOP, params) if _showable(query)]

    return cached(f"top_searches:{population}", conn, compute)[:limit]


def _showable(query: str) -> bool:
    """Si «Lo más buscado» puede mostrar esta búsqueda: nada que el agente no ofrece por su cuenta."""
    from ..retrieval.hybrid import detect_concepts  # import diferido: retrieval importa agent.tools

    if alcohol_in_name("catalog_item", query) or baby_in_name("catalog_item", query):
        return False
    concepts = load_taxonomy().concepts
    return all(c in concepts and is_offerable(concepts[c]) for c in detect_concepts(query))
