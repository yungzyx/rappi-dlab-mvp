"""Restaurantes del catálogo: tarjetas con portada, nota, tiempo de entrega y envío, y su menú por secciones. Solo
lectura, consultas parametrizadas.

Un restaurante es una tienda de la vertical `restaurantes`. Se lista y se abre solo si tiene al menos un plato con
precio, y el precio de un plato es su último precio (como lo muestra el agente): uno de relleno (bajo `MIN_PRICE`) o sin
dato cuenta como desconocido y el plato no sale. La base no guarda logos de restaurantes, así que la portada es la foto
de uno de sus platos: un plato popular, o el primero con foto.
"""

from dataclasses import dataclass
from typing import Literal

from psycopg import Connection
from rappi_scraper.storage.search import MIN_PRICE

from ..agent.tools import clp
from ..concepts.taxonomy import load_taxonomy
from . import hours as clock
from .cache import cached
from .hours import closed_last, normalize_schedule, restaurant_hours
from .stores import BIGINT_MAX, IN_DEMO_CITY, demo_places, like_pattern, normalized_sql, product_card

POPULAR_SECTION = "Lo más pedido"

Sort = Literal["recommended", "rating", "eta", "fee"]

# "Destacados" es una regla propia de la demo, no la de Rappi (su "Súper" no se publica): nota desde 4,5 con al menos
# TOP_MIN_REVIEWS opiniones. La app lo rotula así.
TOP_MIN_RATING = 4.5
TOP_MIN_REVIEWS = 100


@dataclass(frozen=True)
class Filters:
    """Lo que acota la lista (lo que no se pide es None o False): hasta `max_eta` minutos, desde `min_rating` de nota,
    solo los destacados (`top`) o solo los que tienen algún plato rebajado (`promo`)."""

    max_eta: int | None = None
    min_rating: float | None = None
    top: bool = False
    promo: bool = False

    def key(self) -> str:
        return f"{self.max_eta}:{self.min_rating}:{int(self.top)}:{int(self.promo)}"


# Los minutos de entrega son el primer número del texto ("35 min"); un texto vacío o sin número, o 0, es desconocido.
_ETA_MINUTES = r"NULLIF(substring(d.eta from '\d+')::numeric, 0)"

# Cada orden desempata por la nota y por el id: la lista es siempre la misma. Lo desconocido va al final (un local sin
# tiempo no es "el más rápido", ni uno sin nota "el mejor").
_ORDER = {
    # Recomendado: más opiniones primero (las deja quien pidió: la señal de volumen que publica Rappi), luego la nota.
    "recommended": "d.review_count DESC NULLS LAST, d.rating DESC NULLS LAST, s.store_id",
    "rating": "d.rating DESC NULLS LAST, d.review_count DESC NULLS LAST, s.store_id",
    "eta": f"{_ETA_MINUTES} ASC NULLS LAST, d.rating DESC NULLS LAST, s.store_id",
    "fee": "d.delivery_cost ASC NULLS LAST, d.rating DESC NULLS LAST, s.store_id",
}

# Algún plato con precio rebajado (su último precio bajo el de lista): "Con promociones".
_DISCOUNTED_DISH = """EXISTS (SELECT 1 FROM menu_items mi JOIN latest_menu_prices p ON p.item_id = mi.item_id
                  WHERE mi.store_id = {alias}.store_id AND p.price >= %(min_price)s AND p.real_price > p.price)"""

# Las tarjetas de los restaurantes con algún plato con precio, en un orden, de una cocina o de un local, o cuyo nombre o
# cocina contiene lo buscado (`name`, un patrón de LIKE ya normalizado); con los filtros de la lista (los que no se
# piden son NULL o false). Sin local, solo los de una comuna de la ciudad de la demo (`stores.IN_DEMO_CITY`; la comuna
# se compara normalizada como en `text.normalize`: sin tildes, mayúsculas ni signos): la Home y la lista de
# restaurantes no muestran locales de Valparaíso a quien está en Providencia. El orden y el corte se hacen antes de
# buscar la portada y las cocinas, que solo se buscan para los que quedan. El EXISTS se detiene en el primer plato con
# precio.
_CARDS = """
WITH ranked AS (
    SELECT s.store_id, s.name, d.rating, d.eta, d.delivery_cost, d.review_count, d.schedules,
           row_number() OVER (ORDER BY {order}) AS pos
    FROM stores s
    JOIN store_verticals v ON v.store_id = s.store_id AND v.vertical = 'restaurantes'
    LEFT JOIN restaurant_details d ON d.store_id = s.store_id
    WHERE (%(store_id)s::bigint IS NULL OR s.store_id = %(store_id)s)
      AND (%(store_id)s::bigint IS NOT NULL
           OR {in_city})
      AND (%(cuisine)s::text IS NULL
           OR EXISTS (SELECT 1 FROM restaurant_cuisines rc WHERE rc.store_id = s.store_id AND rc.cuisine = %(cuisine)s))
      AND (%(name)s::text IS NULL OR {name_s} LIKE %(name)s
           OR EXISTS (SELECT 1 FROM restaurant_cuisines rc WHERE rc.store_id = s.store_id AND {name_rc} LIKE %(name)s))
      AND (%(max_eta)s::numeric IS NULL OR {eta} <= %(max_eta)s)
      AND (%(min_rating)s::numeric IS NULL OR d.rating >= %(min_rating)s)
      AND (%(min_reviews)s::int IS NULL OR d.review_count >= %(min_reviews)s)
      AND (NOT %(promo)s OR {discounted_s})
      AND EXISTS (SELECT 1 FROM menu_items mi JOIN latest_menu_prices p ON p.item_id = mi.item_id
                  WHERE mi.store_id = s.store_id AND p.price >= %(min_price)s)
    ORDER BY pos
    LIMIT %(limit)s
)
SELECT r.store_id, r.name, r.rating, r.eta, r.delivery_cost, cover.image_url,
       ARRAY(SELECT rc.cuisine FROM restaurant_cuisines rc WHERE rc.store_id = r.store_id ORDER BY rc.cuisine),
       r.review_count, r.schedules, {discounted_r}
FROM ranked r
LEFT JOIN LATERAL (
    SELECT mi.image_url
    FROM menu_items mi
    JOIN menu_sections ms ON ms.store_id = mi.store_id AND ms.section_id = mi.section_id
    WHERE mi.store_id = r.store_id AND mi.image_url <> ''
    ORDER BY mi.is_popular DESC, ms.position, ms.section_id, mi.rappi_item_id, mi.item_id
    LIMIT 1
) cover ON true
ORDER BY r.pos"""

# Los platos con precio de un restaurante, una fila por cada sección donde está el plato, por la posición de la sección
# y, dentro de ella, por el id que les dio Rappi (que no guarda el orden de los platos). Rappi repite un plato en "Más
# vendidos" y en la suya: `section_id` es la última y las demás van en `extra_section_ids` (migración 040). Es una
# fila por par plato-sección aunque el arreglo traiga repetidos o la propia sección.
_MENU = """
SELECT ms.section_id, ms.name, mi.item_id::text, mi.name, p.price, p.real_price, NULLIF(mi.image_url, ''),
       mi.is_popular, ic.concept_id
FROM menu_items mi
JOIN menu_sections ms ON ms.store_id = mi.store_id
                     AND (ms.section_id = mi.section_id OR ms.section_id = ANY(mi.extra_section_ids))
JOIN latest_menu_prices p ON p.item_id = mi.item_id  -- su último precio, desempatado por corrida
LEFT JOIN item_concepts ic ON ic.entity_type = 'menu_item' AND ic.entity_id = mi.item_id::text
WHERE mi.store_id = %(store_id)s AND p.price >= %(min_price)s
ORDER BY ms.position, ms.section_id, mi.rappi_item_id, mi.item_id"""


def restaurants(
    conn: Connection,
    cuisine: str | None = None,
    sort: Sort = "rating",
    limit: int = 30,
    filters: Filters | None = None,
    now=None,
) -> list[dict]:
    """Las tarjetas de los restaurantes con algún plato con precio de la ciudad de la demo (`config.PROFILE_CITY`), de
    una cocina si se pide, con los `filters` de la lista, por más opiniones (`recommended`), mejor nota (`rating`),
    menor tiempo de entrega (`eta`) o menor costo de envío (`fee`). Los cerrados a la hora local (`now`, la de Santiago
    si no se da) van al final, sin cambiar el orden de los demás. Sin cocina sale de la caché del catálogo
    (catalog/cache.py): la consulta recorre todos los platos y la lista solo cambia con una corrida; el horario se
    compara después, con la hora de cada request. Con cocina (texto libre) no se guarda: cada texto distinto sería una
    entrada más, sin tope."""

    filters = filters or Filters()

    def compute() -> list[dict]:
        rows = _card_rows(conn, sort=sort, cuisine=cuisine, limit=limit, filters=filters)
        return [_card(*row) for row in rows]

    cards = compute() if cuisine is not None else cached(f"restaurants:{sort}:{limit}:{filters.key()}", conn, compute)
    return with_hours(cards, now)


def search_restaurants(conn: Connection, q: str, limit: int = 10, now=None) -> list[dict]:
    """Los restaurantes de la ciudad de la demo cuyo nombre o alguna cocina contiene lo buscado (sin tildes ni
    mayúsculas), por nota; los cerrados al final. Vacío si la consulta no tiene al menos dos letras."""
    pattern = like_pattern(q)
    if pattern is None:
        return []
    return with_hours([_card(*row) for row in _card_rows(conn, sort="rating", name=pattern, limit=limit)], now)


def with_hours(cards: list[dict], now=None) -> list[dict]:
    """Cada tarjeta (sin tocar las de la caché) con su estado a la hora `now` según el horario publicado; los cerrados
    al final."""
    moment = now or clock.now_local()
    return closed_last([{**card, "hours": restaurant_hours(card["schedule"], moment)} for card in cards])


def restaurant_menu(conn: Connection, store_id: int, now=None) -> dict | None:
    """El restaurante con su menú: una sección por cada una de las suyas con platos con precio, en el orden de
    `menu_sections.position`, y en cada una todos sus platos: uno que Rappi repite ("Más vendidos" y la suya) sale en
    las dos. Los platos populares abren el menú en la sección "Lo más pedido", una vez cada uno, y siguen en la suya.
    La tarjeta trae su estado a la hora `now` (`hours`). `None` si no existe, no es un restaurante o no tiene platos
    con precio."""
    if not 0 <= store_id <= BIGINT_MAX:
        return None
    rows = _card_rows(conn, sort="rating", store_id=store_id, limit=1)
    if not rows:
        return None
    full_name = rows[0][1]
    taxonomy = load_taxonomy()
    sections: dict[int, dict] = {}
    dishes: dict[str, dict] = {}
    popular: list[dict] = []
    for section_id, section, entity_id, name, price, real, image, is_popular, concept_id in conn.execute(
        _MENU, {"store_id": store_id, "min_price": MIN_PRICE}
    ):
        dish = dishes.get(entity_id)
        if dish is None:
            dish = dishes[entity_id] = product_card(
                (entity_id, name, price, real, image, None, False, concept_id),
                "restaurantes",
                full_name,
                store_id,
                taxonomy,
                "menu_item",
            ).to_dict()
            if is_popular:
                popular.append(dish)
        sections.setdefault(section_id, {"name": section.strip(), "items": []})["items"].append(dish)
    first = [{"name": POPULAR_SECTION, "items": popular}] if popular else []
    return {"restaurant": with_hours([_card(*rows[0])], now)[0], "sections": first + list(sections.values())}


def _card_rows(
    conn: Connection,
    sort: Sort,
    cuisine: str | None = None,
    store_id: int | None = None,
    limit: int = 30,
    filters: Filters | None = None,
    name: str | None = None,
) -> list[tuple]:
    filters = filters or Filters()
    top = filters.top
    params = {
        "store_id": store_id,
        "cuisine": cuisine,
        "name": name,
        "limit": limit,
        "min_price": MIN_PRICE,
        "places": demo_places(),
        "max_eta": filters.max_eta,
        "min_rating": max(filters.min_rating or 0, TOP_MIN_RATING if top else 0) or None,
        "min_reviews": TOP_MIN_REVIEWS if top else None,
        "promo": filters.promo,
    }
    query = _CARDS.format(
        order=_ORDER[sort],
        eta=_ETA_MINUTES,
        discounted_s=_DISCOUNTED_DISH.format(alias="s"),
        discounted_r=_DISCOUNTED_DISH.format(alias="r"),
        name_s=normalized_sql("s.name"),
        name_rc=normalized_sql("rc.cuisine"),
        in_city=IN_DEMO_CITY,
    )
    return conn.execute(query, params).fetchall()


def _card(
    store_id: int,
    full_name: str,
    rating,
    eta: str | None,
    fee,
    cover: str | None,
    cuisines: list[str],
    reviews: int | None,
    schedules,
    promo: bool,
) -> dict:
    name, area = _split_name(full_name)
    return {
        "id": store_id,
        "name": name,
        "area": area,
        # El nombre que muestra la app: el mismo de sus platos (`store`), del carro y de sus pedidos, con el área.
        "display_name": full_name.strip(),
        "cover": cover,
        "rating": float(rating) if rating is not None else None,
        "reviews": reviews,
        "eta": (eta.strip() or None) if eta else None,
        "fee": clp(float(fee)) if fee is not None else None,
        "cuisines": cuisines,
        # Algún plato rebajado: la marca "Con promociones" (no es una promo de la tienda, que Rappi no publica aquí).
        "promo": bool(promo),
        # El horario publicado el día de la descarga (`hours` lo compara con la hora local de cada request).
        "schedule": normalize_schedule(schedules),
    }


def _split_name(full_name: str) -> tuple[str, str]:
    """ "Vapiano - Las Condes" es el local "Vapiano" del área "Las Condes": separa en el último " - " y recorta los
    espacios; sin él, el nombre queda entero y no hay área."""
    before, separator, after = full_name.strip().rpartition(" - ")
    return (before.strip(), after.strip()) if separator else (after, "")
