"""Las ofertas del agente: lo que propone en cada momento de la app, desde la base y pasando por las guardias
(rappi_ia/offers). Sin una buena oferta responde 204: el agente no dice nada.

`app.py` incluye este router; las dependencias viven en `deps.py`, así este módulo no importa `app`.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from psycopg import Connection
from pydantic import ConfigDict, Field

from .. import config
from ..agent.grouped_search import SpareConnector
from ..offers.engine import OfferError, home_occasions, make_offer
from ..offers.personal import user_interests
from .deps import Clean, get_conn, get_services, get_spare_connector
from .identity import owner_in_query, owner_of_body
from .limits import concurrency_cap
from .services import Services

router = APIRouter(prefix="/agent", tags=["agent"])

MAX_LINES = 100  # como un pedido (OrderIn)
OFFER_CAP = concurrency_cap("offer", config.API_MAX_CONCURRENT_OFFER, wait_s=config.API_CAP_WAIT_S)


class EntityIn(Clean):
    entity_type: Literal["catalog_item", "menu_item"]
    entity_id: str = Field(min_length=1, max_length=64)


class PlanContext(Clean):
    occasion: str = Field(min_length=1, max_length=64)


class CartContext(Clean):
    product: EntityIn


class CheckoutContext(Clean):
    cart: list[EntityIn] = Field(min_length=1, max_length=MAX_LINES)


class NoResultContext(Clean):
    query: str = Field(min_length=1, max_length=200)


class NextOrderContext(Clean):
    items: list[EntityIn] = Field(min_length=1, max_length=MAX_LINES)


class ToTryContext(Clean):
    """Sin datos: las verticales ya probadas salen de los pedidos de la persona (un contexto con campos recibe un
    422)."""

    model_config = ConfigDict(extra="forbid")


class RepeatContext(Clean):
    """Sin datos: lo que le toca repetir sale de los pedidos de la persona (la tabla `replenishment` del motor)."""

    model_config = ConfigDict(extra="forbid")


class WinbackContext(Clean):
    """Sin datos: lo que dejó de pedir sale de los pedidos de la persona y de lo que ya se le mostró
    (`offers/winback.py`)."""

    model_config = ConfigDict(extra="forbid")


class ProfileContext(Clean):
    """El perfil de gusto que se pide (`offers/perfiles.toml`); sin él, el primero de los de la persona."""

    perfil: str | None = Field(default=None, min_length=1, max_length=64)


class OfferBase(Clean):
    user_id: str | None = Field(default=None, max_length=64)


class PlanIn(OfferBase):
    moment: Literal["plan"]
    context: PlanContext


class CartIn(OfferBase):
    moment: Literal["carrito"]
    context: CartContext


class CheckoutIn(OfferBase):
    moment: Literal["checkout"]
    context: CheckoutContext


class NoResultIn(OfferBase):
    moment: Literal["sin_resultado"]
    context: NoResultContext


class NextOrderIn(OfferBase):
    moment: Literal["proximo_pedido"]
    context: NextOrderContext


class ToTryIn(OfferBase):
    moment: Literal["vertical_por_probar"]
    context: ToTryContext


class RepeatIn(OfferBase):
    moment: Literal["recompra"]
    context: RepeatContext


class WinbackIn(OfferBase):
    moment: Literal["volver"]
    context: WinbackContext


class ProfileIn(OfferBase):
    moment: Literal["perfil"]
    context: ProfileContext


OfferIn = Annotated[
    PlanIn | CartIn | CheckoutIn | NoResultIn | NextOrderIn | ToTryIn | RepeatIn | WinbackIn | ProfileIn,
    Field(discriminator="moment"),
]


@router.post(
    "/offer",
    responses={204: {"description": "Sin una buena oferta para este momento"}},
    dependencies=[Depends(OFFER_CAP)],
)
def offer(
    body: OfferIn,
    request: Request,
    conn: Connection = Depends(get_conn),
    svc: Services = Depends(get_services),
    spare: SpareConnector = Depends(get_spare_connector),
):
    """La oferta de un momento: `{ moment, text, products, vertical, prototype_vertical, reason, actions }`, o 204.
    El momento `perfil` tiene su forma: `{ moment, text, perfil, escalera, viaje, reason, actions }` (la escalera de
    un perfil de gusto: `offers/profiles.py`; sus peldaños se buscan a la vez con las conexiones del pool que sobran,
    `spare`, como `/search`). Una ocasión o un perfil que no existe, o una ocasión que el agente no arma (guagua,
    enfermo), es un 422."""
    owner_of_body(request, body.user_id)
    context = body.context.model_dump()
    try:
        found = make_offer(conn, svc.embedder, body.moment, context, body.user_id, spare)
    except OfferError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(status_code=204) if found is None else found.to_dict()


@router.get("/plans", dependencies=[Depends(owner_in_query)])
def plans(
    user_id: Annotated[str | None, Query(max_length=64)] = None, conn: Connection = Depends(get_conn)
) -> list[dict]:
    """Las ocasiones que el agente arma como kit, para la Home: `[{ id, name, emoji }]`. Con `user_id` de alguien del
    prototipo, las que coinciden con lo que le gusta van primero y traen su `reason` (`text` y `basis`)."""
    return home_occasions(conn, user_interests(conn, user_id))
