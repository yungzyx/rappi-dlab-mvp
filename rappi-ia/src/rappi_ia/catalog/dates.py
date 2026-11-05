"""De qué fecha son los precios del catálogo, por vertical: lo que la app y el panel dicen junto a los precios. Solo
lectura.

Sale de las ofertas vigentes (`v_latest_offers`, la única definición de oferta vigente) y, en restaurantes, del último
precio de cada plato (`latest_menu_prices`): los mismos precios que muestra la app, cada uno con el día en que se bajó,
sea cual sea el estado de su corrida (una que sigue abierta también deja precios vigentes). Las fechas son días en
hora de Chile.
"""

from psycopg import Connection

_DATES = """
WITH prices AS (
    SELECT v.vertical, o.scraped_at
    FROM v_latest_offers o
    JOIN v_store_verticals v ON v.store_id = o.store_id
    WHERE o.current
    UNION ALL
    SELECT 'restaurantes', p.scraped_at
    FROM latest_menu_prices p
)
SELECT vertical,
       (min(scraped_at) AT TIME ZONE 'America/Santiago')::date,
       (max(scraped_at) AT TIME ZONE 'America/Santiago')::date
FROM prices
GROUP BY vertical
ORDER BY vertical"""


def catalog_dates(conn: Connection) -> dict:
    """`{desde, hasta, verticales}`: el día del precio más antiguo y del más nuevo que muestra el catálogo
    ('AAAA-MM-DD'), y lo mismo por vertical (`{vertical: {desde, hasta}}`, con el código del backend). Sin precios,
    `desde` y `hasta` son None y `verticales` queda vacío."""
    verticals = {
        vertical: {"desde": first.isoformat(), "hasta": last.isoformat()}
        for vertical, first, last in conn.execute(_DATES)
    }
    return {
        "desde": min((day["desde"] for day in verticals.values()), default=None),
        "hasta": max((day["hasta"] for day in verticals.values()), default=None),
        "verticales": verticals,
    }
