"""Catálogo de la app: tiendas, pasillos, productos, restaurantes, ofertas y Home reales con el precio vigente de cada
tienda (solo lectura).

`app.py` incluye este router; `get_conn` y `backend_vertical` viven en `deps.py`, así este módulo no importa `app`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from psycopg import Connection

from ..catalog.deals import deals
from ..catalog.home import home
from ..catalog.restaurants import Sort, restaurant_menu, restaurants
from ..catalog.stores import product_detail, store_page, vertical_stores
from .deps import backend_vertical, get_conn

router = APIRouter(prefix="/catalog", tags=["catalog"])

STORE_NOT_FOUND = "Esta tienda no está en el catálogo"
PRODUCT_NOT_FOUND = "Este producto no está en el catálogo"
VERTICAL_NOT_FOUND = "Esta vertical no está en el catálogo"
RESTAURANT_NOT_FOUND = "Este restaurante no está en el catálogo"


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


@router.get("/products/{entity_type}/{entity_id}")
def product(entity_type: str, entity_id: str, conn: Connection = Depends(get_conn)) -> dict:
    """Un producto (`catalog_item`) con su oferta vigente más barata, o un plato (`menu_item`) con su último precio."""
    reply = product_detail(conn, entity_type, entity_id)
    if reply is None:
        raise HTTPException(404, PRODUCT_NOT_FOUND)
    return reply


@router.get("/restaurants")
def restaurant_list(
    cuisine: Annotated[str | None, Query(max_length=64)] = None,
    sort: Sort = "rating",
    limit: int = Query(30, ge=1, le=100),
    conn: Connection = Depends(get_conn),
) -> list[dict]:
    """Los restaurantes con algún plato con precio, de una cocina si se pide, por nota, tiempo de entrega o envío."""
    return restaurants(conn, cuisine or None, sort, limit)


@router.get("/restaurants/{store_id}/menu")
def restaurant_menu_page(store_id: int, conn: Connection = Depends(get_conn)) -> dict:
    """El restaurante con su menú por secciones; los populares primero en «Lo más pedido»."""
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
    """Los productos que bajaron de precio o que su tienda rebajó, de mayor a menor descuento. Una vertical es el código
    del backend o el id del prototipo; sin ella, no entra farmacia."""
    code = backend_vertical(vertical or None)
    if vertical and code is None:
        raise HTTPException(404, VERTICAL_NOT_FOUND)
    return deals(conn, code, limit)


@router.get("/home")
def home_lists(conn: Connection = Depends(get_conn)) -> dict:
    """Las listas del catálogo para la Home: tiendas cerca de ti, restaurantes rápidos y con envío barato."""
    return home(conn)
