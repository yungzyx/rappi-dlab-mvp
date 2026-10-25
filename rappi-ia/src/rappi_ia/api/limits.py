"""Límites para que la API aguante carga: cupos por ruta cara, tamaño máximo del cuerpo y requests por IP.

Todo vive en la memoria del proceso: con varios workers, cada uno cuenta lo suyo.
"""

import math
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable

import anyio
from fastapi import HTTPException
from fastapi.responses import JSONResponse

BUSY = "Hay mucha gente ahora; intenta en unos segundos."
TOO_MANY = "Demasiadas solicitudes; espera un momento."
TOO_LARGE = "Solicitud demasiado grande"
BUSY_RETRY_S = 2
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def busy() -> HTTPException:
    return HTTPException(503, BUSY, headers={"Retry-After": str(BUSY_RETRY_S)})


class ConcurrencyCap:
    """Dependencia de una ruta: a lo más `limit` requests adentro a la vez. Sin `wait_s`, el siguiente recibe 503 al
    tiro; con `wait_s`, hace fila (en orden de llegada) hasta esos segundos: el panel pide muchas métricas juntas. Se
    declara en `dependencies=[…]` de la ruta, que FastAPI resuelve antes que los parámetros: un request sin cupo no
    pide conexión. Es async: vive en el event loop (un semáforo de anyio), sin ocupar un hilo, también mientras espera;
    un request cancelado en la fila no se queda con un cupo."""

    def __init__(self, name: str, limit: int, wait_s: float = 0):
        self.name = name
        self.limit = limit
        self.wait_s = wait_s
        self.slots = anyio.Semaphore(limit, max_value=limit)

    async def __call__(self):
        if not await self.acquire():
            raise busy()
        try:
            yield
        finally:
            self.slots.release()

    async def acquire(self, wait_s: float | None = None) -> bool:
        """¿Consiguió un cupo? Espera a lo más `wait_s` (por defecto, el de este cupo)."""
        wait_s = self.wait_s if wait_s is None else wait_s
        if wait_s <= 0:
            try:
                self.slots.acquire_nowait()
            except anyio.WouldBlock:
                return False
            return True
        with anyio.move_on_after(wait_s):
            await self.slots.acquire()
            return True
        return False

    def acquire_keeping(self, reserve: int) -> bool:
        """Un cupo sin esperar, solo si después quedan al menos `reserve` libres. Corre en el event loop (desde un hilo,
        con `anyio.from_thread.run_sync`). No le quita el cupo a nadie en la fila: si alguien espera, no hay libres."""
        if self.slots.value <= reserve:
            return False
        self.slots.acquire_nowait()
        return True

    def release(self) -> None:
        self.slots.release()


def concurrency_cap(name: str, limit: int, wait_s: float = 0) -> ConcurrencyCap:
    return ConcurrencyCap(name, limit, wait_s)


class MaxBodySize:
    """Middleware ASGI: 413 si el cuerpo pasa de `max_bytes`, por el Content-Length declarado o contando lo que llega
    (Starlette lee el JSON entero a memoria antes de validarlo)."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.max_bytes:
            await JSONResponse(status_code=413, content={"detail": TOO_LARGE})(scope, receive, send)
            return
        received = 0

        async def counted():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # FastAPI deja pasar un HTTPException al leer el cuerpo: lo responde su manejador de errores
                    raise HTTPException(413, TOO_LARGE)
            return message

        await self.app(scope, counted, send)


class _Window:
    """Conteos de una IP en la ventana de un minuto actual y en la anterior (todos y escrituras)."""

    __slots__ = ("window", "current", "previous", "writes", "previous_writes")

    def __init__(self, window: int):
        self.window = window
        self.current = self.previous = self.writes = self.previous_writes = 0

    def roll(self, window: int) -> None:
        if window == self.window:
            return
        recent = window == self.window + 1
        self.previous = self.current if recent else 0
        self.previous_writes = self.writes if recent else 0
        self.current = self.writes = 0
        self.window = window


class RateLimit:
    """Middleware ASGI: requests por minuto de cada IP con una ventana deslizante (el conteo del minuto anterior pesa
    según cuánto queda de él), y aparte las escrituras. Pasado el tope responde 429 con Retry-After; lo rechazado no
    cuenta. Recuerda a lo más `max_clients` IPs: las que llevan más tiempo sin pedir nada se olvidan primero.

    Con otra ventana (`window_s`) y sin `app`, cuenta otra cosa por IP con `wait()`: las personas nuevas por día de
    `POST /session`."""

    WINDOW_S = 60.0

    def __init__(
        self,
        app,
        per_minute: int,
        writes_per_minute: int,
        exempt: Iterable[str] = (),
        max_clients: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
        window_s: float = WINDOW_S,
    ):
        self.app = app
        self.per_minute = per_minute
        self.writes_per_minute = writes_per_minute
        self.exempt = frozenset(exempt)
        self.max_clients = max_clients
        self.clock = clock
        self.window_s = window_s
        self.clients: OrderedDict[str, _Window] = OrderedDict()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        retry = self.wait(client[0] if client else "", scope["method"] in WRITE_METHODS)
        if retry:
            reply = JSONResponse(status_code=429, content={"detail": TOO_MANY}, headers={"Retry-After": str(retry)})
            await reply(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def wait(self, host: str, write: bool) -> int:
        """Segundos que debe esperar esta IP (0 = pasa, y se cuenta). Corre en el event loop: sin candado."""
        if host in self.exempt or (self.per_minute <= 0 and (self.writes_per_minute <= 0 or not write)):
            return 0
        now = self.clock()
        window = int(now // self.window_s)
        counts = self.clients.get(host)
        if counts is None:
            counts = self.clients[host] = _Window(window)
            if len(self.clients) > self.max_clients:
                self.clients.popitem(last=False)
        else:
            self.clients.move_to_end(host)
            counts.roll(window)
        elapsed = now - window * self.window_s
        retry = _retry_after(counts.previous, counts.current, self.per_minute, elapsed, self.window_s)
        if write:
            writes = _retry_after(counts.previous_writes, counts.writes, self.writes_per_minute, elapsed, self.window_s)
            retry = max(retry, writes)
        if retry:
            return retry
        counts.current += 1
        counts.writes += write
        return 0


def _retry_after(previous: int, current: int, limit: int, elapsed: float, window_s: float) -> int:
    """0 si cabe uno más; si no, los segundos (enteros, pasado el borde) hasta que el conteo estimado (el anterior,
    ponderado por lo que queda de su minuto, más el actual) quede bajo el tope."""
    if limit <= 0 or previous * (window_s - elapsed) / window_s + current < limit:
        return 0
    if current >= limit:  # ni el minuto actual solo cabe: hasta el próximo, y que el de ahora pese menos
        wait = window_s - elapsed + window_s * (1 - limit / current)
    else:
        wait = window_s - elapsed - window_s * (limit - current) / previous
    return math.floor(wait) + 1
