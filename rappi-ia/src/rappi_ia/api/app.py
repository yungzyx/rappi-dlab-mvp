"""API de rappi-ia: el agente (texto), búsqueda, perfil, eventos del prototipo y métricas del panel.

make serve   →   http://localhost:8000/docs
"""

import json
import logging
import re
import threading
import time
from contextlib import asynccontextmanager, nullcontext
from dataclasses import replace
from importlib.metadata import version
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg import Connection, DataError, Error, OperationalError
from psycopg.errors import QueryCanceled, UndefinedTable
from psycopg_pool import PoolTimeout
from pydantic import Field, ValidationError, field_validator

from .. import config
from ..agent.grouped_search import SpareConnector, search_grouped
from ..agent.rappi_agent import PROTOTYPE_VERTICALS, Context
from ..agent.tools import VERTICAL_LABELS, search_products, suggest_complement
from ..analytics import queries
from ..concepts.taxonomy import load_taxonomy
from ..db import pending_migrations
from ..events import store as events
from ..layers.segments import recalculate_user_segments
from ..motor.build import refresh_user, refresh_user_conn
from ..motor.home import home_verticals
from ..motor.predict import next_verticals
from ..offers.engine import most_ordered
from ..offers.guards import is_offerable, offerable_vertical
from ..offers.profiles import active_profiles, person_city
from ..retrieval.hybrid import MODES
from ..text import contract_articles
from . import deps, identity, prewarm
from .agent import router as agent_router
from .catalog import router as catalog_router
from .deps import (
    Clean,
    backend_vertical,
    get_analytics_conn,
    get_conn,
    get_connector,
    get_services,
    get_spare_connector,
)
from .identity import owner_in_path, owner_in_query, owner_of_body
from .limits import TOO_MANY, MaxBodySize, RateLimit, busy, concurrency_cap
from .logs import AccessLog, configure_logging, rejected, route_template
from .services import Services, services

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Carga los modelos antes de «startup complete»: si no, los paga la primera petición (el /health del prototipo,
    que se rinde a los 1,5 s y la app muestra «Sin conexión»). El pool de conexiones vive lo mismo que la app.
    Nunca migra: en local lo hacen `make serve` y `make mvp` antes de arrancarla; en producción, `rappi-ia
    deploy-migrate` (con respaldo antes). Mientras falten migraciones, /health da 503 `migraciones_pendientes`."""
    configure_logging(config.LOG_LEVEL)
    identity.secret()  # sin API_SECRET en producción, la API no arranca
    deps.open_pool()
    try:
        start = time.perf_counter()
        await run_in_threadpool(services)
        # uvicorn solo muestra sus propios loggers: así la duración queda junto a «Application startup complete»
        logging.getLogger("uvicorn.error").info("Servicios cargados en %.1f s", time.perf_counter() - start)
        prewarm.start()  # en su hilo: ni el arranque ni /health la esperan
        yield
    finally:
        await run_in_threadpool(deps.close_pool)


# Con API_DOCS apagado (producción) no hay /docs, /redoc ni /openapi.json: el esquema no se publica.
app = FastAPI(
    title="rappi-ia",
    version=version("rappi-ia"),
    description="El agente, búsqueda por vertical y panel empresa",
    lifespan=lifespan,
    docs_url="/docs" if config.API_DOCS else None,
    redoc_url="/redoc" if config.API_DOCS else None,
    openapi_url="/openapi.json" if config.API_DOCS else None,
)


def cors_origin_regex(allow_lan: bool) -> str:
    """Solo este equipo por defecto. La red local (iPhone) se abre con API_ALLOW_LAN=1 (`make serve-lan`): fuera de los
    datos de cada persona (que piden su token) la API es abierta, así que solo en una red de confianza. Redes
    privadas: 192.168/16, 10/8 y 172.16/12 (el hotspot del iPhone da 172.20.10.x), más nombres `.local` (Bonjour)."""
    hosts = r"localhost|127\.0\.0\.1"
    if allow_lan:
        hosts += (
            r"|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+"
            r"|[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.local"
        )
    return rf"http://({hosts}):51\d\d"


# En producción no hay patrón: los orígenes son exactamente los de API_CORS_ORIGINS (ni localhost:51xx ni la red local).
CORS_ORIGIN_REGEX = None if config.API_PRODUCTION else cors_origin_regex(config.API_ALLOW_LAN)


def origin_allowed(origin: str) -> bool:
    return origin in config.API_CORS_ORIGINS or (
        CORS_ORIGIN_REGEX is not None and re.fullmatch(CORS_ORIGIN_REGEX, origin) is not None
    )


def is_same_origin(origin: str, host: str | None) -> bool:
    """¿El Origin es el propio sitio? Con la API detrás del mismo dominio (proxy en /api), el navegador manda Origin
    igual a la página, o sea al Host de la petición. Se compara solo el host y el puerto (tras un proxy con TLS la API
    ve http y el navegador manda https). Un navegador no deja a una página ajena fingir el Host; un cliente que no es
    un navegador puede mandar lo que quiera, pero también puede omitir el Origin."""
    parts = urlsplit(origin)
    return bool(host) and parts.scheme in ("http", "https") and parts.netloc.lower() == host.lower()


# Sin tope por IP: en local, este equipo (la demo y `make mvp-check`). En producción nadie: tras un proxy que no pasa la
# IP del cliente, todos llegarían como 127.0.0.1.
NO_LIMIT_HOSTS = () if config.API_PRODUCTION else ("127.0.0.1", "::1")

# Dentro de CORS (se agregan antes: el último queda por fuera), así un 413 o un 429 lleva sus cabeceras y la app lo lee.
app.add_middleware(MaxBodySize, max_bytes=config.API_MAX_BODY_BYTES)
app.add_middleware(
    RateLimit,
    per_minute=config.API_RATE_PER_MIN,
    writes_per_minute=config.API_RATE_WRITE_PER_MIN,
    exempt=NO_LIMIT_HOSTS,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.API_CORS_ORIGINS,
    allow_origin_regex=CORS_ORIGIN_REGEX,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["content-type", identity.TOKEN_HEADER.lower()],
)
app.add_middleware(AccessLog)  # el más externo: también los 413 y 429 llevan su id y su línea


def _is_health(request: Request) -> bool:
    """/health responde en su forma de readiness (`{"ok": false, "motivos": [...]}`) también cuando falla la base."""
    return route_template(request) == "/health"


@app.exception_handler(QueryCanceled)
async def query_too_slow(request: Request, exc: QueryCanceled) -> JSONResponse:
    """Una consulta que pasó el statement_timeout (es un OperationalError, pero la base sí responde): 504, no «Sin
    conexión»."""
    log.warning("Consulta cancelada por tiempo en %s (%s)", route_template(request), _db_error(exc))
    return JSONResponse(status_code=504, content={"detail": "La consulta tardó demasiado"})


@app.exception_handler(PoolTimeout)
async def no_free_connection(request: Request, exc: PoolTimeout) -> JSONResponse:
    """Ninguna conexión libre a tiempo. Si nadie tiene una ocupada, es que Postgres no responde (el pool no logra
    conectarse); si no, la API está llena: 503 con Retry-After."""
    if deps.connections_in_use() == 0:
        return await database_unavailable(request, exc)
    log.warning("Sin conexiones libres en %s", route_template(request))
    error = busy()
    content = {"ok": False, "motivos": ["saturada"]} if _is_health(request) else {"detail": error.detail}
    return JSONResponse(status_code=error.status_code, content=content, headers=error.headers)


@app.exception_handler(OperationalError)
async def database_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
    """Postgres caído o sin respuesta: un 503 claro y rápido (la app muestra «Sin conexión»), no un 500."""
    log.error("Base de datos no disponible: %s", exc)
    content = {"ok": False, "motivos": ["base"]} if _is_health(request) else {"detail": "Base de datos no disponible"}
    return JSONResponse(status_code=503, content=content)


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 sin repetir la entrada: un NaN o un texto enorme en `input` no se puede volver a mandar como JSON (500)."""
    errors = [{"type": e.get("type"), "loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})


def _db_error(exc: Error) -> str:
    """Un error de Postgres para el log: su clase y su sqlstate. El texto no, porque puede traer la fila que falló
    («Failing row contains (…)») con lo que escribió la persona."""
    return f"{type(exc).__name__} (sqlstate {exc.sqlstate})"


@app.exception_handler(DataError)
async def invalid_data(request: Request, exc: DataError) -> JSONResponse:
    """Un valor que Postgres no acepta (un \x00 en un parámetro de la URL): es un error de quien pide, no un 500."""
    log.warning("Dato inválido en %s: %s", route_template(request), _db_error(exc))
    return JSONResponse(status_code=400, content={"detail": "Dato inválido"})


EMPTY_VERTICAL_FALLBACK = {"turbo": "conveniencia"}  # mismo tipo de tienda (minimarket con entrega rápida)
MAX_BEACON_BYTES = 512_000  # 200 eventos caben de sobra
MAX_EVENT_VALUE = 100_000_000  # un evento con valor (cart_add) es una línea del carro: el mismo tope que su precio

# Cupos por ruta cara (config.API_MAX_CONCURRENT_*): el de /agent/offer vive en agent.py. /agent/ask y /agent/offer
# hacen una fila corta (API_CAP_WAIT_S); la búsqueda y los pedidos rechazan al tiro; el panel pide ~16 métricas a la
# vez y hace fila hasta su tope (el mismo que su statement_timeout).
ASK_CAP = concurrency_cap("ask", config.API_MAX_CONCURRENT_ASK, wait_s=config.API_CAP_WAIT_S)
SEARCH_CAP = concurrency_cap("search", config.API_MAX_CONCURRENT_SEARCH)
ORDERS_CAP = concurrency_cap("orders", config.API_MAX_CONCURRENT_ORDERS)
ANALYTICS_CAP = concurrency_cap(
    "analytics", config.API_MAX_CONCURRENT_ANALYTICS, wait_s=config.API_TIMEOUT_ANALYTICS_MS / 1000
)
# Personas nuevas por día de cada IP (`POST /session`): el mismo conteo por IP que el límite de requests, en un día.
# `/session` corre en el threadpool (no en el event loop, como el middleware): su conteo va con candado.
NEW_USERS = RateLimit(
    None, per_minute=config.API_NEW_USERS_PER_IP_DAY, writes_per_minute=0, exempt=NO_LIMIT_HOSTS, window_s=86_400
)
_new_users_lock = threading.Lock()

# Textos cortos de la URL (ids, conceptos, verticales, cocinas): el SQL va con parámetros, pero sin tope se aceptaba
# un texto de cualquier largo.
ShortQuery = Annotated[str, Query(max_length=64)]
ShortPath = Annotated[str, Path(max_length=64)]


# ── Modelos ──────────────────────────────────────────────────────────────────
class PreviousTurnIn(Clean):
    """El pedido anterior de la conversación: un seguimiento («talla g», «más barata») se lee sobre él."""

    query: str = Field(default="", max_length=200)
    concepts: list[Annotated[str, Field(max_length=64)]] = Field(default_factory=list, max_length=10)
    vertical: str | None = Field(default=None, max_length=64)
    product_ids: list[Annotated[str, Field(max_length=64)]] = Field(default_factory=list, max_length=24)


class AskIn(Clean):
    message: str = Field(min_length=1, max_length=500)
    vertical: str | None = Field(default=None, max_length=64)
    user_id: str | None = Field(default=None, max_length=64)
    session_id: str | None = Field(default=None, max_length=64)
    profile: dict[str, Annotated[float, Field(allow_inf_nan=False)]] | None = Field(default=None, max_length=200)
    shown_topics: list[Annotated[str, Field(max_length=64)]] = Field(default_factory=list, max_length=50)
    mode: Literal["propuesta", "actual"] = "propuesta"
    previous: PreviousTurnIn | None = None


MAX_PAYLOAD_KEYS = 10
MAX_PAYLOAD_BYTES = 2048


class EventIn(Clean):
    type: str = Field(max_length=64)
    session_id: str = Field(max_length=64)
    vertical: str | None = Field(default=None, max_length=64)
    concept_id: str | None = Field(default=None, max_length=64)
    entity_type: Literal["catalog_item", "menu_item", "store"] | None = None
    entity_id: str | None = Field(default=None, max_length=64)
    cart_id: str | None = Field(default=None, max_length=64)
    query: str | None = Field(default=None, max_length=500)
    modality: Literal["texto"] | None = None
    results: int | None = Field(default=None, ge=0, le=1_000_000)
    unmet: bool | None = None
    value: float | None = Field(default=None, le=MAX_EVENT_VALUE, allow_inf_nan=False)
    payload: dict = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def small_payload(cls, payload: dict) -> dict:
        """El payload no pasa por la redacción ni la purga: solo datos chicos (origen, servicio, cantidad…)."""
        if len(payload) > MAX_PAYLOAD_KEYS or len(json.dumps(payload, allow_nan=False)) > MAX_PAYLOAD_BYTES:
            raise ValueError("payload demasiado grande")
        return payload


class EventsIn(Clean):
    user_id: str = Field(max_length=64)
    events: list[EventIn] = Field(max_length=200)


class BeaconIn(EventsIn):
    """El beacon no manda cabeceras (sendBeacon): el token de la persona va en el cuerpo."""

    token: str | None = Field(default=None, max_length=200)


class SessionIn(Clean):
    legacy_user_id: str | None = Field(default=None, max_length=64)


class OrderLineIn(Clean):
    entity_type: Literal["catalog_item", "menu_item"]
    entity_id: str = Field(max_length=64)
    concept_id: str | None = Field(default=None, max_length=64)
    store_id: int | None = Field(default=None, ge=0, le=2**63 - 1)  # la tienda de donde se agregó: su precio manda
    qty: int = Field(default=1, ge=1, le=99)
    # Se ignora: el precio de cada línea sale del catálogo. Queda para no romper a un cliente que lo manda.
    unit_price: float | None = Field(default=None, ge=0, le=100_000_000, allow_inf_nan=False)
    from_suggestion: bool = False


class OrderIn(Clean):
    user_id: str = Field(max_length=64)
    session_id: str = Field(max_length=64)
    cart_id: str = Field(max_length=64)
    vertical: str = Field(max_length=64)
    lines: list[OrderLineIn] = Field(min_length=1, max_length=100)
    mode: Literal["propuesta", "actual"] = "propuesta"  # en «Rappi hoy» (actual) el pedido no entra al perfil


# ── Agente ──────────────────────────────────────────────────────────────────
@app.get("/live")
def live() -> dict:
    """Liveness del contenedor: el proceso responde. No toca la base ni los servicios (si Postgres cae, no hay nada que
    reiniciar en la API)."""
    return {"ok": True}


def _count_documents(conn: Connection) -> int:
    """Estimación de las estadísticas de Postgres: contar las ~250 mil filas leía ~390 MB en cada chequeo (el prototipo
    lo pide cada 30 s y se rinde a los 1,5 s). Sin estadísticas todavía (base recién creada), se cuenta. Sin la tabla
    (migraciones pendientes), no hay documentos."""
    try:
        with conn.transaction():
            return (
                conn.execute(
                    """SELECT coalesce(sum(greatest(c.reltuples, 0)), 0)::bigint FROM pg_inherits i
                   JOIN pg_class c ON c.oid = i.inhrelid WHERE i.inhparent = 'search_documents'::regclass"""
                ).fetchone()[0]
                or conn.execute("SELECT count(*) FROM search_documents").fetchone()[0]
            )
    except UndefinedTable:
        return 0


@app.get("/health")
def health(conn: Connection = Depends(get_conn), svc: Services = Depends(get_services)):
    """Readiness: 200 si la API puede atender (`ok`, documentos y capacidades), o 503 con `motivos`, códigos de lo que
    falta (`base`, `saturada`, `sin_documentos`, `migraciones_pendientes`, `busqueda_semantica`): nunca texto de una
    excepción ni rutas. La app lo cuenta como «sin conexión»."""
    documents = _count_documents(conn)
    reasons = []
    if pending_migrations(conn):
        reasons.append("migraciones_pendientes")
    if documents == 0:
        reasons.append("sin_documentos")
    if config.API_REQUIRE_SEMANTIC and svc.embedder is None:
        reasons.append("busqueda_semantica")
    if reasons:
        log.warning("La API no está lista: %s", ", ".join(reasons))
        return JSONResponse(status_code=503, content={"ok": False, "motivos": reasons})
    return {"ok": True, "documentos": documents, "capacidades": svc.capabilities}


@app.post("/agent/ask", dependencies=[Depends(ASK_CAP)])
def ask(
    body: AskIn, request: Request, conn: Connection = Depends(get_conn), svc: Services = Depends(get_services)
) -> dict:
    owner_of_body(request, body.user_id)
    ctx = _context(conn, body.vertical, body.user_id, body.profile, body.shown_topics, body.mode)
    if body.previous and body.previous.concepts:
        previous = body.previous.model_dump()
        previous["vertical"] = backend_vertical(previous["vertical"])
        ctx = replace(ctx, previous=previous)
    try:
        response = svc.agent.reply(conn, body.message, ctx)
    except ValueError as exc:
        raise rejected(exc, body.user_id) from exc
    _log_ask(conn, body.user_id, body.session_id, body.message, response, "texto", body.mode)
    return response


GROUPED_SEARCH_LIMIT = 6  # por grupo
VERTICAL_SEARCH_LIMIT = 10


@app.get("/search", dependencies=[Depends(SEARCH_CAP)])
def search(
    q: str = Query(min_length=1, max_length=200),
    vertical: ShortQuery | None = None,
    current: ShortQuery | None = None,
    price_max: float | None = Query(None, ge=0, allow_inf_nan=False),
    limit: int | None = Query(None, ge=1, le=50),
    mode: str = Query("hibrido"),
    correct: bool = True,
    conn: Connection = Depends(get_conn),
    svc: Services = Depends(get_services),
    spare: SpareConnector = Depends(get_spare_connector),
) -> dict:
    """Con `vertical`, busca solo ahí. Sin `vertical`, en las verticales que corresponden a la consulta (más la de la
    pantalla, `current`) y agrupa: `limit` es por grupo. Las verticales se buscan en paralelo con las conexiones del
    pool que sobran (`spare`, sin tomar su reserva); sin ninguna, en serie. Si queda «sin resultado», corrige los
    errores de tipeo y vuelve a buscar: `corrected_query` dice qué se buscó (null si nada); `correct=false` busca tal
    cual."""
    if mode not in MODES:
        raise HTTPException(400, f"mode debe ser uno de {MODES}")
    if vertical is None:
        grouped = search_grouped(
            conn,
            q,
            svc.embedder,
            backend_vertical(current),
            limit or GROUPED_SEARCH_LIMIT,
            price_max,
            mode,
            spare,
            correct,
        )
        return grouped.to_dict()
    code = backend_vertical(vertical)
    try:
        outcome = search_products(
            conn, code, q, None, svc.embedder, price_max, k=limit or VERTICAL_SEARCH_LIMIT, mode=mode, correct=correct
        )
    except ValueError as exc:
        raise rejected(exc) from exc
    return {
        "vertical": code,
        "products": [p.to_dict() for p in outcome.products],
        "unmet": outcome.result.unmet,
        "unmet_reason": outcome.result.unmet_reason,
        "corrected_query": outcome.corrected_query,
    }


@app.get("/recommendations", dependencies=[Depends(owner_in_query)])
def recommendations(
    user_id: ShortQuery,
    vertical: ShortQuery | None = None,
    limit: int = Query(3, ge=1, le=6),
    conn: Connection = Depends(get_conn),
    svc: Services = Depends(get_services),
) -> dict:
    """ "Para ti, de otras tiendas": intereses del usuario → complementos → productos de otro vertical. Si quedan filas
    libres, una más con lo más pedido de la vertical que mejor le calza (`_top_row`)."""
    interests = list(events.profile(conn, user_id))
    taxonomy = load_taxonomy()
    # La razón nombra el interés («Por tu interés en…»): el agente no nombra por su cuenta alcohol, salud ni lo
    # sensible, así que esos intereses no son fuente de una fila (como en `RappiAgent._top_interest`). El perfil los
    # conserva.
    sources = [c for c in interests if c in taxonomy.concepts and is_offerable(taxonomy.concepts[c])]
    shown: set[str] = set()
    rows = []
    for concept in sources[:4]:
        suggestion = suggest_complement(conn, [concept], backend_vertical(vertical), svc.embedder, shown)
        if suggestion:
            shown.add(suggestion.concept)
            interest = taxonomy.concepts[concept]
            rows.append(
                {
                    # En el inicio no hay carro: la razón es el interés aprendido, no "porque llevas".
                    "reason": f"Por tu interés en {interest.emoji} {interest.name.lower()}",
                    "concept": suggestion.concept,
                    "vertical": suggestion.vertical,
                    "prototype_vertical": PROTOTYPE_VERTICALS.get(suggestion.vertical),
                    "products": [p.to_dict() for p in suggestion.products],
                }
            )
        if len(rows) >= limit:
            break
    taken = {row["vertical"] for row in rows}
    if len(rows) < limit and (top := _top_row(conn, user_id, backend_vertical(vertical), taken)):
        rows.append(top)
    return {"user_id": user_id, "interests": interests[:5], "rows": rows}


TOP_REASON = "Lo más pedido estas semanas en {vertical}"


def _top_row(conn: Connection, user_id: str, current: str | None, taken: set[str]) -> dict | None:
    """«Lo más pedido en…»: la primera vertical, en el orden de la predicción para la persona (`next_verticals`), que el
    agente puede proponer (nunca Farmacia ni Licores), que no es la de la pantalla ni la de otra fila y que tiene algo
    que mostrar: hasta tres de los productos que más pide la población ahí (`trends`), con el precio de esa vertical,
    las guardias de las ofertas y las reglas de lo destacado, con los platos de su ciudad
    (`offers.engine.most_ordered`). La fila no tiene concepto; su `basis` dice la fuente."""
    population = config.MOTOR_POBLACION
    city = person_city(conn, user_id)
    for score in next_verticals(conn, user_id, population):
        vertical = score.vertical
        if not offerable_vertical(vertical) or vertical == current or vertical in taken:
            continue
        if products := most_ordered(conn, vertical, population, city):
            label = VERTICAL_LABELS.get(vertical, vertical)
            return {
                "kind": "lo_mas_pedido",
                "reason": contract_articles(TOP_REASON.format(vertical=label)),
                "concept": None,
                "vertical": vertical,
                "prototype_vertical": PROTOTYPE_VERTICALS.get(vertical),
                "products": products,
                "basis": [{"kind": "lo_mas_pedido", "id": vertical, "source": f"poblacion:{population}"}],
            }
    return None


# ── Sesión, perfil y eventos ────────────────────────────────────────────────
@app.post("/session")
def new_session(body: SessionIn, request: Request, conn: Connection = Depends(get_conn)) -> dict:
    """El id de este navegador y su token (X-User-Token). Un id viejo de la app (de antes de la identidad firmada) se
    reclama una sola vez y conserva lo que ya tenía; si no, una persona nueva, con un tope por IP al día (429)."""
    user_id = identity.claim_legacy(conn, body.legacy_user_id)
    if user_id is None:
        client = request.client
        with _new_users_lock:
            retry = NEW_USERS.wait(client.host if client else "", write=False)
        if retry:
            conn.rollback()
            raise HTTPException(429, TOO_MANY, headers={"Retry-After": str(retry)})
        user_id = identity.create_user(conn)
    conn.commit()
    return {"user_id": user_id, "token": identity.sign(user_id)}


@app.get("/profile/{user_id}", dependencies=[Depends(owner_in_path)])
def get_profile(user_id: ShortPath, conn: Connection = Depends(get_conn)) -> dict:
    taxonomy = load_taxonomy()
    scores = events.profile(conn, user_id)
    return {
        "user_id": user_id,
        "interests": [
            {"concept": c, "label": taxonomy.concepts[c].label, "score": s}
            for c, s in scores.items()
            if c in taxonomy.concepts
        ],
    }


@app.get("/profile/{user_id}/gustos", dependencies=[Depends(owner_in_path)])
def tastes(user_id: ShortPath, conn: Connection = Depends(get_conn)) -> dict:
    """Los perfiles de gusto de la persona (`offers/profiles.py`): `{ perfiles: [{ id, nombre, emoji, nivel, principal,
    por_que, basis }] }`, el principal primero; la lista va vacía sin perfiles. «Olvidar» borra o recalcula sus
    segmentos, y el perfil se va con ellos."""
    return {"perfiles": [profile.to_dict() for profile in active_profiles(conn, user_id)]}


@app.get("/profile/{user_id}/verticales", dependencies=[Depends(owner_in_path)])
def home_shortcuts(user_id: ShortPath, conn: Connection = Depends(get_conn)) -> dict:
    """El orden de los accesos de la Home (`motor/home.py`): `{ fixed, order: [{ id, score, reason }], personalized }`.
    Restaurantes y Turbo van fijos; los otros seis se ordenan por lo que la persona más usa."""
    return home_verticals(conn, user_id)


@app.delete("/profile/{user_id}", dependencies=[Depends(owner_in_path)])
def forget(user_id: ShortPath, concept: ShortQuery | None = None, conn: Connection = Depends(get_conn)) -> dict:
    deleted = events.forget(conn, user_id, concept)
    refresh_user_conn(conn, user_id)  # la afinidad y la recompra, sin lo que olvidó
    conn.commit()
    return {"user_id": user_id, "concept": concept, "eventos_borrados": deleted}


@app.post("/events")
def post_events(body: EventsIn, request: Request, conn: Connection = Depends(get_conn)) -> dict:
    owner_of_body(request, body.user_id)
    return {"guardados": _save_events(lambda: nullcontext(conn), body)}


@app.post("/events/beacon", status_code=204)
async def post_events_beacon(request: Request, connector=Depends(get_connector)) -> None:
    """Lo que queda en cola al cerrar la pestaña (navigator.sendBeacon). Llega como text/plain, que no necesita
    preflight de CORS; el contenido es el mismo JSON de /events, más el token de la persona (`token`: sendBeacon no
    manda cabeceras). Valida el origen, el tamaño y el token antes de pedir una conexión: una página ajena no gasta
    las del pool."""
    origin = request.headers.get("origin")
    # text/plain no tiene preflight: sin esta revisión, cualquier página abierta podía escribir eventos
    if origin and not origin_allowed(origin) and not is_same_origin(origin, request.headers.get("host")):
        raise HTTPException(403, "Origen no permitido")
    raw = await request.body()
    if len(raw) > MAX_BEACON_BYTES:
        raise HTTPException(413, "Demasiados eventos")
    try:
        body = BeaconIn.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(422, "Eventos inválidos") from exc
    identity.require_user(body.user_id, identity.verify(body.token))
    await run_in_threadpool(_save_events, connector, body)


def _save_events(connect, body: EventsIn) -> int:
    """`connect()` da la conexión (la del request, o una del pool para el beacon): se pide después de revisar los
    tipos."""
    if any(e.type not in events.CLIENT_EVENT_TYPES for e in body.events):
        raise HTTPException(400, "Tipo de evento no permitido")
    with connect() as conn:
        try:
            n = events.record(
                conn,
                [
                    events.Event(user_id=body.user_id, **{**e.model_dump(), "vertical": backend_vertical(e.vertical)})
                    for e in body.events
                ],
                source="prototype",
            )
        except ValueError as exc:
            raise rejected(exc, body.user_id) from exc
        conn.commit()
    return n


# Alcance `function`: la conexión, su turno y el cupo se sueltan al terminar el endpoint. Con el de siempre (`request`)
# FastAPI los suelta después de las tareas en segundo plano, y el recálculo pediría una segunda conexión con la primera
# todavía tomada.
@app.post("/orders", dependencies=[Depends(ORDERS_CAP, scope="function")])
def post_order(
    body: OrderIn,
    request: Request,
    background: BackgroundTasks,
    conn: Connection = Depends(get_conn, scope="function"),
    connector=Depends(get_connector),
) -> dict:
    """Guarda el pedido con el precio del catálogo en la tienda de cada línea (las que no tienen precio vigente quedan
    fuera y se cuentan en `lineas_omitidas`) y, ya respondido, recalcula los segmentos y el motor (afinidad y recompra)
    de esa persona (solo lo suyo, con otra conexión del pool, ya devuelta la del pedido)."""
    owner_of_body(request, body.user_id)
    vertical = backend_vertical(body.vertical)
    if vertical is None:  # un pedido es de una tienda: sin vertical del catálogo no se puede guardar
        raise HTTPException(400, f"Vertical desconocido: {body.vertical}")
    lines, skipped = events.catalog_prices(conn, [line.model_dump() for line in body.lines])
    if not lines:  # sin decir cuál: la respuesta no sirve para sondear el catálogo
        raise HTTPException(400, "Producto no disponible")
    try:
        order_id = events.record_order(
            conn, body.user_id, body.session_id, body.cart_id, vertical, lines, source="prototype", mode=body.mode
        )
    except ValueError as exc:  # un usuario de otra fuente (simulado)
        raise rejected(exc, body.user_id) from exc
    conn.commit()
    if skipped:
        log.warning("Pedido %s: %d línea(s) sin precio vigente quedaron fuera", order_id, skipped)
    background.add_task(recalculate_user_segments, connector, body.user_id)
    background.add_task(refresh_user, connector, body.user_id)
    return {"order_id": order_id, "lineas_omitidas": skipped}


@app.get("/concepts")
def concepts() -> dict:
    taxonomy = load_taxonomy()
    return {
        "version": taxonomy.version,
        "concepts": [
            {"id": c.id, "name": c.name, "emoji": c.emoji, "group": c.parent, "sensitive": c.sensitive}
            for c in taxonomy.concepts.values()
        ],
    }


# ── Panel empresa ────────────────────────────────────────────────────────────
ANALYTICS = {
    "kpis": queries.kpis,
    "weekly": queries.weekly,
    "opportunities": queries.opportunities,
    "trends": queries.trends,
    "funnel": queries.funnel,
    "cohorts": queries.cohorts,
    "rhythm": queries.rhythm_histogram,
    "at-risk": queries.at_risk,
    "suggestions": queries.suggestions,
    "services": queries.services,
    "offers": queries.offers,
    "volver": queries.winback,
    "unmet": queries.unmet,
    "multi-vertical": queries.multi_vertical_retention,
    "affinity": queries.affinity,
    "assortment": queries.assortment_vs_demand,
    "combos": queries.combos,
    "motor": queries.motor,
    "home": queries.home,
}


# El panel: solo si API_ENABLE_ANALYTICS (apagado en producción, donde estas rutas responden 404). Se incluye al final.
analytics_router = APIRouter(prefix="/analytics", dependencies=[Depends(ANALYTICS_CAP)])


@analytics_router.get("/catalog")
def analytics_catalog(conn: Connection = Depends(get_analytics_conn)) -> dict:
    return {"source": "catalogo_real", "data": queries.catalog_health(conn)}


@analytics_router.get("/{name}")
def analytics(
    name: str, source: Literal["synthetic", "prototype"] = "synthetic", conn: Connection = Depends(get_analytics_conn)
) -> dict:
    if name not in ANALYTICS:
        raise HTTPException(404, f"Métrica desconocida: {name}")
    return {"source": source, "data": ANALYTICS[name](conn, source)}


# ── Auxiliares ───────────────────────────────────────────────────────────────
def _context(conn, vertical, user_id, profile, shown_topics, mode) -> Context:
    if profile is None and user_id and mode == "propuesta":
        profile = events.profile(conn, user_id)
    vertical = _searchable(conn, backend_vertical(vertical))
    return Context(vertical, profile or {}, list(shown_topics), mode, user_id=user_id)


def _searchable(conn: Connection, vertical: str | None) -> str | None:
    """Un vertical todavía sin documentos (Turbo, antes de que termine la descarga) haría que todo diera "no está"
    y se anotara como demanda: se usa el más parecido o, si tampoco tiene, el agente deduce el vertical del mensaje."""
    for candidate in (vertical, EMPTY_VERTICAL_FALLBACK.get(vertical)):
        if (
            candidate
            and conn.execute(
                "SELECT EXISTS (SELECT 1 FROM search_documents WHERE vertical = %s)", (candidate,)
            ).fetchone()[0]
        ):
            return candidate
    return None


def _log_ask(conn, user_id, session_id, text, response, modality, mode) -> None:
    """Registra la consulta (redactada) para tendencias y demanda no satisfecha. En "Rappi hoy" no se aprende."""
    if not user_id or not session_id:
        return
    concepts = response.get("intent", {}).get("concepts") or []
    event = events.Event(
        user_id=user_id,
        session_id=session_id,
        type="ask",
        vertical=response.get("vertical"),
        concept_id=concepts[0] if concepts and mode == "propuesta" else None,
        query=text,
        modality=modality,
        results=len(response.get("products", [])),
        unmet=bool(response.get("unmet")),
        payload={"mode": mode, "intent": response.get("intent", {}).get("kind")},
    )
    try:
        with conn.transaction():  # un error deja la conexión lista para lo que sigue
            events.record(conn, [event], source="prototype")
    except ValueError:  # un id de usuario simulado: la respuesta sale igual, no se registra
        return
    except Error as exc:  # registrar es secundario: la respuesta ya está calculada y sale igual
        log.warning("No se pudo registrar la consulta; la respuesta sale igual (%s)", _db_error(exc))
        return
    conn.commit()


if config.API_ENABLE_ANALYTICS:
    app.include_router(analytics_router)
app.include_router(catalog_router)
app.include_router(agent_router)
