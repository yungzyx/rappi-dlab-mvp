"""Catálogo de la app: tiendas, pasillos, productos, restaurantes, ofertas y Home reales con el precio vigente de cada
tienda (solo lectura).

`app.py` incluye este router; `get_conn` y `backend_vertical` viven en `deps.py`, así este módulo no importa `app`.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from psycopg import Connection
from pydantic import Field

from ..catalog.deals import deals
from ..catalog.for_you import store_for_you
from ..catalog.home import home
from ..catalog.restaurants import Filters, Sort, restaurant_menu, restaurants
from ..catalog.stores import BIGINT_MAX, line_prices, product_detail, product_stores, store_page, vertical_stores
from ..catalog.terms import MAX_STORES, store_terms
from .deps import Clean, backend_vertical, get_conn
from .identity import owner_in_query
from .logs import served_request_id

router = APIRouter(prefix="/catalog", tags=["catalog"])

STORE_NOT_FOUND = "Esta tienda no está en el catálogo"
PRODUCT_NOT_FOUND = "Este producto no está en el catálogo"
VERTICAL_NOT_FOUND = "Esta vertical no está en el catálogo"
RESTAURANT_NOT_FOUND = "Este restaurante no está en el catálogo"
MAX_LINES = 100  # como un pedido (OrderIn)


class AvailabilityLineIn(Clean):
    entity_type: Literal["catalog_item", "menu_item"]
    entity_id: str = Field(min_length=1, max_length=64)
    store_id: int | None = Field(default=None, ge=0, le=2**63 - 1)  # la tienda del pedido anterior: su precio manda


class AvailabilityIn(Clean):
    lines: list[AvailabilityLineIn] = Field(min_length=1, max_length=MAX_LINES)


@router.get("/verticals/{vertical}/stores")
def stores_of_vertical(
    vertical: Annotated[str, Path(max_length=64)],
    limit: int = Query(30, ge=1, le=100),
    conn: Connection = Depends(get_conn),
) -> dict:
    """Las tiendas de una vertical (código del backend o id del prototipo), de más a menos ofertas vigentes."""
    code = backend_vertical(vertical)
    if code is None:
        raise HTTPException(404, VERTICAL_NOT_FOUND)
    return {"vertical": code, "stores": vertical_stores(conn, code, limit)}


@router.get("/stores/{store_id}")
def store(
    store_id: int,
    aisle: int | None = None,
    page: int = Query(1, ge=1, le=10_000),
    conn: Connection = Depends(get_conn),
) -> dict:
    """La tienda con sus pasillos y una página de productos de uno (el primero, si no se pide)."""
    reply = store_page(conn, store_id, aisle, page)
    if reply is None:
        raise HTTPException(404, STORE_NOT_FOUND)
    return reply


@router.get("/stores/{store_id}/para-ti", dependencies=[Depends(owner_in_query)])
def store_for_you_tab(
    store_id: int,
    user_id: Annotated[str, Query(min_length=1, max_length=64)],
    conn: Connection = Depends(get_conn),
) -> dict:
    """ "Para ti" en la tienda: lo que tiene de los intereses de la persona, con las guardias de las ofertas (vacío si
    nada calza). `request_id` va en los eventos de lo que se toque."""
    return {**store_for_you(conn, store_id, user_id), "request_id": served_request_id()}


@router.get("/products/{entity_type}/{entity_id}/stores")
def product_store_list(
    entity_type: str,
    entity_id: str,
    store_id: int | None = None,
    sustitutos: bool = False,
    conn: Connection = Depends(get_conn),
) -> dict:
    """Dónde está un producto del catálogo: cada tienda con su precio, tiempo y envío, las marcas "Mejor precio" y "Más
    rápido", la tienda `store_id` (`here`, con "Pocas unidades") y, si ahí está agotado, productos similares.
    `sustitutos=true` los trae aunque esté disponible: los sustitutos del mismo concepto para los cambios en vivo."""
    reply = product_stores(conn, entity_id, store_id, sustitutos) if entity_type == "catalog_item" else None
    if reply is None:
        raise HTTPException(404, PRODUCT_NOT_FOUND)
    return reply


@router.get("/terms")
def terms(
    stores: Annotated[str, Query(max_length=MAX_STORES * 20, pattern=r"^\d{1,19}(,\d{1,19})*$")],
    conn: Connection = Depends(get_conn),
) -> dict:
    """Las condiciones de compra que trae el catálogo para las tiendas del carro (`stores`: ids separados por coma,
    hasta 20): costo de envío, compra mínima y tarifa de servicio. Lo que el catálogo no sabe va en null: la app pone
    su supuesto rotulado."""
    ids = [int(part) for part in stores.split(",")]
    if len(ids) > MAX_STORES:
        raise HTTPException(422, f"Hasta {MAX_STORES} tiendas")
    return {"stores": store_terms(conn, [i for i in ids if i <= BIGINT_MAX])}


@router.get("/products/{entity_type}/{entity_id}")
def product(entity_type: str, entity_id: str, conn: Connection = Depends(get_conn)) -> dict:
    """Un producto (`catalog_item`) con su oferta vigente más barata, o un plato (`menu_item`) con su último precio."""
    reply = product_detail(conn, entity_type, entity_id)
    if reply is None:
        raise HTTPException(404, PRODUCT_NOT_FOUND)
    return reply


@router.post("/availability")
def availability(body: AvailabilityIn, conn: Connection = Depends(get_conn)) -> dict:
    """ "Pídelo de nuevo": cada línea de un pedido anterior con su precio vigente en la misma tienda (`v_latest_offers`,
    o el último precio del plato en `latest_menu_prices`), en el orden pedido. `available: false` (y `price: null`) si
    ya no está a la venta ahí. No dice si la tienda está abierta: el catálogo no lo sabe en vivo."""
    lines = [line.model_dump() for line in body.lines]
    return {
        "lines": [
            {**line, "available": price is not None, "price": price}
            for line, price in zip(lines, line_prices(conn, lines), strict=True)
        ]
    }


@router.get("/restaurants")
def restaurant_list(
    cuisine: Annotated[str | None, Query(max_length=64)] = None,
    sort: Sort = "rating",
    limit: int = Query(30, ge=1, le=100),
    max_eta: int | None = Query(None, ge=1, le=240),
    min_rating: float | None = Query(None, ge=0, le=5, allow_inf_nan=False),
    top: bool = False,
    promo: bool = False,
    conn: Connection = Depends(get_conn),
) -> list[dict]:
    """Los restaurantes con algún plato con precio, de una cocina si se pide, por opiniones, nota, tiempo de entrega o
    envío, con los filtros de la lista: hasta `max_eta` minutos, desde `min_rating`, destacados (`top`) o con platos
    rebajados (`promo`). Los cerrados según su horario publicado van al final."""
    filters = Filters(max_eta=max_eta, min_rating=min_rating, top=top, promo=promo)
    return restaurants(conn, cuisine or None, sort, limit, filters)


@router.get("/restaurants/{store_id}/menu")
def restaurant_menu_page(store_id: int, conn: Connection = Depends(get_conn)) -> dict:
    """El restaurante con su menú por secciones; los populares primero en "Lo más pedido"."""
    reply = restaurant_menu(conn, store_id)
    if reply is None:
        raise HTTPException(404, RESTAURANT_NOT_FOUND)
    return reply


@router.get("/deals")
def deals_list(
    vertical: Annotated[str | None, Query(max_length=64)] = None,
    limit: int = Query(24, ge=1, le=100),
    conn: Connection = Depends(get_conn),
) -> list[dict]:
    """Los productos que bajaron de precio o que su tienda rebajó, de mayor a menor descuento, de tiendas de la ciudad
    de la demo. Una vertical es el código del backend o el id del prototipo; sin ella, no entra farmacia."""
    code = backend_vertical(vertical or None)
    if vertical and code is None:
        raise HTTPException(404, VERTICAL_NOT_FOUND)
    return deals(conn, code, limit, in_city=True)


@router.get("/home")
def home_lists(conn: Connection = Depends(get_conn)) -> dict:
    """Las listas del catálogo para la Home: tiendas cerca de ti, restaurantes rápidos y con envío barato, con el id de
    esta respuesta (`request_id`) para los eventos de lo que se toque en ellas."""
    return {**home(conn), "request_id": served_request_id()}
