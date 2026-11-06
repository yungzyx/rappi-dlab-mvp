"""Las ofertas del agente: lo que propone en cada momento de la app, desde la base y pasando por las guardias
(rappi_ia/offers). Sin una buena oferta responde 204: el agente no dice nada.

`app.py` incluye este router; las dependencias viven en `deps.py`, así este módulo no importa `app`.
"""

from dataclasses import replace
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from psycopg import Connection
from pydantic import ConfigDict, Field

from .. import config
from ..agent.grouped_search import SpareConnector
from ..events import experiments
from ..events import store as events
from ..events.experiments import HOLDOUT_MOMENTS
from ..offers import autonomy, preferences
from ..offers.engine import Offer, OfferError, PlanOffer, ProfileOffer, home_occasions, kit_stores, make_offer
from ..offers.personal import user_interests
from .deps import Clean, backend_vertical, get_conn, get_services, get_spare_connector
from .identity import owner_in_query, owner_of_body
from .limits import concurrency_cap
from .logs import served_request_id
from .services import Services

router = APIRouter(prefix="/agent", tags=["agent"])

MAX_LINES = 100  # como un pedido (OrderIn)
WITHHELD_HEADER = "X-Offer-Withheld"  # en el 204 de una oferta retenida al grupo de control
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


class OnTopContext(Clean):
    """El pedido en curso: su vertical (código del backend o id de la app; uno de Turbo no tiene OnTop) y lo que
    lleva, que no se vuelve a ofrecer."""

    vertical: str = Field(min_length=1, max_length=64)
    items: list[EntityIn] = Field(min_length=1, max_length=MAX_LINES)


class ProfileContext(Clean):
    """El perfil de gusto que se pide (`offers/perfiles.toml`); sin él, el primero de los de la persona."""

    perfil: str | None = Field(default=None, min_length=1, max_length=64)


class OfferBase(Clean):
    user_id: str | None = Field(default=None, max_length=64)
    # La sesión de la app (la de sus eventos): con ella, una oferta retenida al grupo de control queda registrada en la
    # sesión donde se habría visto. Sin ella, la persona no entra al grupo de control.
    session_id: str | None = Field(default=None, max_length=64)
    # Dónde la pide la app (la pantalla de su `placement`). Desde el buscador (`agent`: un chip, "Repite lo de siempre",
    # "¿Con qué acompaño…?") la pide la persona, y al grupo de control no se le retiene. Sin ella (una app anterior),
    # se retiene como antes.
    surface: Literal[tuple(sorted(events.SURFACES))] | None = None  # type: ignore[valid-type]


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


class OnTopIn(OfferBase):
    moment: Literal["ontop"]
    context: OnTopContext


class ProfileIn(OfferBase):
    moment: Literal["perfil"]
    context: ProfileContext


OfferIn = Annotated[
    PlanIn | CartIn | CheckoutIn | NoResultIn | NextOrderIn | ToTryIn | RepeatIn | WinbackIn | OnTopIn | ProfileIn,
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
    """La oferta de un momento: `{ moment, text, products, vertical, prototype_vertical, reason, actions, request_id }`,
    o 204 (`request_id`: el id de esta respuesta, que la app repite en los eventos de la oferta).
    El momento `ontop` suma `plazo_min` (el plazo para sumar sus productos al pedido en curso, un supuesto), y el
    `plan`, `stores`: sus tiendas, un pedido cada una, con lo que suma el kit y si llega a la compra mínima del
    catálogo (`below_min`, `missing`).
    Grupo de control (`ofertas_control`, con OFFERS_CONTROL_PCT): a quien está en `control`, una oferta de los momentos
    que Mochi propone solo (HOLDOUT_MOMENTS, fuera del buscador: `surface` distinta de `agent`) no se le muestra (204
    con `X-Offer-Withheld: 1`) y queda como impresión contrafactual (`offer_withheld`, con lo que habría mostrado; una
    por sesión, origen, concepto y vertical); hace falta `user_id` y `session_id`.
    El momento `perfil` tiene su forma: `{ moment, text, perfil, escalera, viaje, reason, actions }` (la escalera de
    un perfil de gusto: `offers/profiles.py`; sus peldaños se buscan a la vez con las conexiones del pool que sobran,
    `spare`, como `/search`). Una ocasión o un perfil que no existe, o una ocasión que el agente no arma (guagua,
    enfermo), es un 422."""
    owner_of_body(request, body.user_id)
    context = body.context.model_dump()
    if body.moment == "ontop":
        context["vertical"] = backend_vertical(context["vertical"])
    mine = preferences.load(conn, body.user_id)  # su dieta y alergias filtran; sus favoritas ordenan
    conn.commit()  # esa lectura no queda abierta mientras la oferta calcula sus vectores (como en `/search`)
    try:
        with preferences.applied(mine):
            found = make_offer(conn, svc.embedder, body.moment, context, body.user_id, spare)
    except OfferError as exc:
        raise HTTPException(422, str(exc)) from exc
    found = _with_preferences(found, mine)
    if isinstance(found, PlanOffer) and mine:  # lo que su dieta sacó del kit ya no suma en su tienda
        found = replace(found, stores=kit_stores(conn, found.products))
    if body.moment == "recompra":
        found = _with_auto_order(conn, found, body.user_id)
    if found is None:
        return Response(status_code=204)
    request_id = served_request_id()
    if _withheld(conn, body, found, request_id):
        # Para la app: no es que no haya oferta. La Home no pide "¿Volvemos a…?" en lugar de una recompra retenida,
        # que en tratamiento se habría mostrado.
        return Response(status_code=204, headers={WITHHELD_HEADER: "1"})
    return {**found.to_dict(), "request_id": request_id}


def _withheld(conn: Connection, body, found: Offer | ProfileOffer, request_id: str | None) -> bool:
    """Si la oferta se retiene (la persona está en el grupo de control): entonces queda registrada como `offer_withheld`
    en su sesión, con lo que habría mostrado en `app_event_items` (concepto y vertical incluidos), y la respuesta es un
    204 como el de un momento sin oferta. Un plan o un perfil nunca se retienen, ni lo que la persona pide en el
    buscador (`surface` `agent`), ni una oferta sin persona o sin sesión. La misma oferta (origen, concepto y vertical,
    la clave con que la app cuenta una mostrada) se anota una vez por sesión: la Home la vuelve a pedir cada vez que
    queda arriba, y en tratamiento se cuenta una sola mostrada."""
    if (
        body.moment not in HOLDOUT_MOMENTS
        or body.surface == experiments.ASKED_SURFACE
        or not body.user_id
        or not body.session_id
        or isinstance(found, ProfileOffer)
    ):
        return False
    try:
        events.ensure_user(conn, body.user_id)
    except ValueError:  # un id de otra población (simulada): no entra al experimento
        return False
    variant = experiments.offers_variant(conn, body.user_id)
    if variant != experiments.CONTROL:
        conn.commit()  # su asignación (tratamiento), si era la primera vez
        return False
    concept = found.reason.get("concept")
    origin = f"agent-{body.moment}"
    seen = conn.execute(  # un concepto aún sin sembrar queda nulo en el evento (`events.record`): se compara igual
        """SELECT 1 FROM app_events
           WHERE user_id = %s AND session_id = %s AND type = 'offer_withheld' AND origin = %s
             AND concept_id IS NOT DISTINCT FROM (SELECT concept_id FROM concepts WHERE concept_id = %s)
             AND vertical IS NOT DISTINCT FROM %s
           LIMIT 1""",
        (body.user_id, body.session_id, origin, concept, found.vertical),
    ).fetchone()
    if seen:
        conn.commit()
        return True
    withheld = events.Event(
        user_id=body.user_id,
        session_id=body.session_id,
        type="offer_withheld",
        vertical=found.vertical,
        concept_id=concept,
        results=len(found.products),
        payload={"moment": body.moment, "experiment": experiments.OFFERS_CONTROL, "variant": variant},
        surface=body.surface,
        origin=origin,
        request_id=request_id,
        items=[
            {
                "position": position,
                "entity_type": product["entity_type"],
                "entity_id": product["entity_id"],
                "concept_id": product.get("concept"),
                "vertical": product.get("vertical"),
            }
            for position, product in enumerate(found.products[: events.MAX_EVENT_ITEMS])
        ],
    )
    events.record(conn, [withheld], source="prototype")
    conn.commit()
    return True


def _with_preferences(found: Offer | ProfileOffer | None, mine: preferences.Preferences) -> Offer | ProfileOffer | None:
    """La oferta con lo que salió por otro camino que `search_products` (la recompra, lo más pedido, los peldaños que
    se buscan en paralelo) también filtrado por su dieta y alergias. Si no queda nada de lo que traía, no hay oferta:
    un 204, como cualquier momento sin una buena. La razón no cambia: nunca es una preferencia."""
    if found is None or not mine:
        return found
    if isinstance(found, ProfileOffer):
        steps = []
        for step in found.steps:
            kept = preferences.keep_dicts(mine, step["products"])
            if kept or not step["products"]:
                steps.append({**step, "products": kept})
        return replace(found, steps=steps) if steps else None
    kept = preferences.keep_dicts(mine, found.products)
    if found.products and not kept:
        return None
    return replace(found, products=kept)


def _with_auto_order(conn: Connection, found: Offer | None, user_id: str | None) -> Offer | None:
    """La recompra de una tienda donde la persona deja que Mochi pida solo ("Pedir por mí", offers/autonomy.py) suma
    "Pídelo por mí": le pide a Mochi lo de siempre ahí (`ask`), que vuelve a revisar cada límite antes de pedir."""
    mine = autonomy.load(conn, user_id)
    if found is None or mine is None or not found.products:
        return found
    store_id = found.products[0].get("store_id")
    store = next((s for s in autonomy.ordered_stores(conn, user_id) if s["id"] == store_id), None)
    if store is None or store_id not in mine.store_ids:
        return found
    action = {"label": autonomy.ASK_LABEL, "ask": autonomy.ASK_TEXT.format(store=store["name"])}
    return replace(found, actions=[*found.actions, action])


@router.get("/plans", dependencies=[Depends(owner_in_query)])
def plans(
    user_id: Annotated[str | None, Query(max_length=64)] = None, conn: Connection = Depends(get_conn)
) -> list[dict]:
    """Las ocasiones que el agente arma como kit, para la Home: `[{ id, name, emoji }]`. Con `user_id` de alguien del
    prototipo, las que coinciden con lo que le gusta van primero y traen su `reason` (`text` y `basis`)."""
    return home_occasions(conn, user_interests(conn, user_id))
