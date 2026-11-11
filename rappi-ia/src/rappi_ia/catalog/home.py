"""Las listas de la Home: tiendas cerca de ti, restaurantes rápidos y restaurantes con envío barato, y de qué fecha son
los precios del catálogo. Solo lectura, consultas parametrizadas."""

from psycopg import Connection
from rappi_scraper.storage.search import MIN_PRICE

from .. import config
from .cache import cached
from .dates import catalog_dates
from .hours import closed_last
from .restaurants import restaurants, with_hours
from .stores import (
    CURRENT_OFFERS,
    IN_DEMO_CITY,
    OWN_VERTICAL,
    STORE_STATE,
    demo_places,
    downloaded_cte,
    not_pushed_params,
    store_card,
)

NEARBY_STORES = 6
FAST_RESTAURANTS = 2
LOW_FEE_RESTAURANTS = 6

# Las tiendas con ofertas vigentes más cercanas al punto, con coordenadas, de la ciudad de la demo (`IN_DEMO_CITY`) y
# sin las que no se empujan (farmacia, restaurantes, sex shops, smoking shops: ver `stores.NOT_PUSHED_*`). La distancia
# es la del círculo máximo (haversine).
# Las tiendas se ordenan y se cortan solo con las que tienen alguna oferta vigente (el EXISTS se detiene en la primera):
# así una cercana sin ofertas no ocupa un lugar y los productos se cuentan solo para las que quedan. Cada tarjeta es la
# que da `vertical_stores`.
_NEARBY = f"""
WITH {downloaded_cte(False)},
nearest AS MATERIALIZED (
    SELECT d.store_id, d.format_run_id,
           2 * asin(sqrt(sin(radians(s.lat - %(lat)s) / 2) ^ 2
                         + cos(radians(%(lat)s)) * cos(radians(s.lat)) * sin(radians(s.lng - %(lng)s) / 2) ^ 2)) AS km
    FROM downloaded d
    JOIN stores s ON s.store_id = d.store_id
    WHERE s.lat IS NOT NULL AND s.lng IS NOT NULL AND {IN_DEMO_CITY} AND EXISTS (SELECT 1 {CURRENT_OFFERS})
    ORDER BY km, d.store_id
    LIMIT %(limit)s
)
SELECT s.store_id, btrim(coalesce(b.name, s.name)), s.raw->>'image', s.raw->>'eta_value', o.products, {OWN_VERTICAL},
       {STORE_STATE}
FROM nearest d
CROSS JOIN LATERAL (SELECT count(DISTINCT sp.master_product_id) AS products {CURRENT_OFFERS}) o
JOIN stores s ON s.store_id = d.store_id
LEFT JOIN brands b ON b.brand_id = s.brand_id
ORDER BY d.km, d.store_id"""


def home(conn: Connection) -> dict:
    """Lo que la Home muestra del catálogo: `nearby_stores` (las tiendas más cercanas al punto fijo de la demo),
    `fast_restaurants` (los de menor tiempo de entrega; uno sin tiempo no es rápido) y `low_fee_restaurants` (los de
    menor costo de envío). Una lista sin datos queda vacía. `catalogo` dice de qué fecha son los precios, en todo el
    catálogo y por vertical (catalog/dates.py). Sale de la caché del catálogo (catalog/cache.py); el estado de cada
    restaurante según su horario publicado se compara con la hora de cada request, y los cerrados van al final."""
    lists = cached("home", conn, lambda: _home(conn), refresh=_home)
    return {
        **lists,
        "fast_restaurants": with_hours(lists["fast_restaurants"]),
        "low_fee_restaurants": with_hours(lists["low_fee_restaurants"]),
    }


def _home(conn: Connection) -> dict:
    fast = restaurants(conn, sort="eta", limit=FAST_RESTAURANTS)
    return {
        "nearby_stores": _nearby_stores(conn, config.MVP_HOME_LAT, config.MVP_HOME_LNG, NEARBY_STORES),
        "fast_restaurants": [card for card in fast if card["eta"]],
        "low_fee_restaurants": restaurants(conn, sort="fee", limit=LOW_FEE_RESTAURANTS),
        "catalogo": catalog_dates(conn),
    }


def _nearby_stores(conn: Connection, lat: float, lng: float, limit: int) -> list[dict]:
    params = {"lat": lat, "lng": lng, "limit": limit, "min_price": MIN_PRICE, "places": demo_places()}
    params |= not_pushed_params()
    return closed_last([store_card(*row) for row in conn.execute(_NEARBY, params)])
