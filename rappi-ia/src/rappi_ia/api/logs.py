"""Registros de la API: con hora, nivel y el id de cada request, y sin datos de personas.

uvicorn solo configura sus propios loggers: sin esto, los `log.info` de `rappi_ia.*` se perdían y los avisos salían sin
hora ni contexto. La línea de acceso de uvicorn (`--no-access-log` en todos los arranques) lleva la ruta con el id y la
query; la de aquí lleva la plantilla de la ruta (`/profile/{user_id}`), el estado y los milisegundos.
"""

import contextvars
import logging
import re
import time
import uuid

from fastapi import HTTPException
from starlette.requests import Request

FORMAT = "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"
NO_REQUEST = "-"
NO_ROUTE = "<sin ruta>"  # un 404: la ruta que pidieron puede traer cualquier cosa, así que no se registra
QUIET_WHEN_OK = frozenset({"/live", "/health"})  # el chequeo del orquestador cada pocos segundos: solo a nivel DEBUG
REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")  # lo que manda un proxy; otra cosa se descarta (no se cuelan saltos)

request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default=NO_REQUEST)
log = logging.getLogger(__name__)
_HANDLER_MARK = "_rappi_ia_api_handler"


def configure_logging(level: str = "INFO") -> None:
    """Un handler en la raíz con el formato de la API (varias llamadas dejan uno solo) y `level` para todos los
    loggers. Cada registro lleva `request_id`, también los de librerías y los de una tarea después de responder."""
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, _HANDLER_MARK, False)]:
        root.removeHandler(handler)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(FORMAT))
    setattr(handler, _HANDLER_MARK, True)
    root.addHandler(handler)
    root.setLevel(level)
    # Las peticiones a huggingface.co y a Claude (una línea por llamada) taparían lo que importa.
    for noisy in ("httpx", "httpx2", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.DEBUG if root.level == logging.DEBUG else logging.WARNING)
    _stamp_records_with_request_id()


_previous_factory = logging.getLogRecordFactory()


def _stamp_records_with_request_id() -> None:
    if getattr(logging.getLogRecordFactory(), "stamps_request_id", False):
        return

    def factory(*args, **kwargs):
        record = _previous_factory(*args, **kwargs)
        record.request_id = request_id.get()
        return record

    factory.stamps_request_id = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


def route_template(source) -> str:
    """La plantilla de la ruta que atendió el request (`/profile/{user_id}`): lo único de la URL que se registra."""
    scope = source.scope if isinstance(source, Request) else source
    route = scope.get("route")
    return getattr(route, "path_format", None) or NO_ROUTE


def rejected(exc: Exception, *private: str) -> HTTPException:
    """400 genérico para una entrada que la capa de datos rechazó (un `ValueError`). Su mensaje puede nombrar a la
    persona («El usuario X es de otra fuente») y servir de sonda para ver qué ids existen: al cliente no le llega; al
    log sí, con los valores de `private` (ids) cambiados por `<id>`."""
    detail = str(exc)
    for value in filter(None, private):
        detail = detail.replace(value, "<id>")
    log.warning("Solicitud no válida: %s", detail)
    return HTTPException(400, "Solicitud no válida")


class AccessLog:
    """Middleware ASGI, el más externo: le da un id a cada request (el de `X-Request-ID` si viene bien formado, y lo
    devuelve en la respuesta) y deja una línea al terminar con método, plantilla de ruta, estado y milisegundos. Sin
    query, sin ids de personas y sin IP."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(REQUEST_ID_HEADER.lower().encode(), b"").decode("latin-1")
        rid = incoming if REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex[:12]
        token = request_id.set(rid)
        start = time.perf_counter()
        status = 500
        finished = False

        def finish() -> None:
            nonlocal finished
            if finished:
                return
            finished = True
            template = route_template(scope)
            if status >= 500:
                level = logging.WARNING
            elif template in QUIET_WHEN_OK and status < 400:
                level = logging.DEBUG
            else:
                level = logging.INFO
            log.log(level, "%s %s %d %.0f ms", scope["method"], template, status, (time.perf_counter() - start) * 1000)

        async def send_with_id(message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message = {**message, "headers": [*message.get("headers", []), (b"x-request-id", rid.encode())]}
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                finish()  # al terminar la respuesta, no la tarea en segundo plano que viene después

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            finish()
            request_id.reset(token)
