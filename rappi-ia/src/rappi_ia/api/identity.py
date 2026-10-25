"""Identidad anónima firmada: un id que aparece en un log ya no basta para leer, escribir ni borrar datos de alguien.

`POST /session` da a cada navegador un id del prototipo y su token, `<id>.<HMAC-SHA256 del id, en base64url>`, firmado
con API_SECRET. Las rutas con datos de una persona (`/profile/{user_id}`, el `user_id` de una
query o de un cuerpo) exigen la cabecera X-User-Token de ese mismo id: sin token, 401; con el de otro, 403. Sin
`user_id`, una ruta sigue anónima. Se decide siempre sobre el id ya validado, el mismo que usa la ruta: no sobre el
JSON crudo (la limpieza de `Clean` puede cambiar sus claves) ni sobre otro lugar del request. No es una cuenta: el
token solo prueba que este navegador recibió ese id.
"""

import base64
import functools
import hashlib
import hmac
import os
import re
import secrets
from pathlib import Path
from typing import Annotated

import fastapi
from fastapi import HTTPException, Query, Request
from psycopg import Connection

from .. import config

TOKEN_HEADER = "X-User-Token"
MIN_SECRET_BYTES = 32
PROTOTYPE_ID = re.compile(r"proto-[0-9a-f]{16}")  # el id que genera la app (src/api/user.js) y el que da /session
NO_SESSION = "Falta la sesión"
NOT_ALLOWED = "No autorizado"


def load_secret(value: str | None, production: bool, path: Path) -> bytes:
    """El secreto que firma los tokens: la variable API_SECRET o, solo en local, el archivo `path` (se crea una vez,
    modo 0600). En producción, sin la variable, la API no arranca."""
    if value is None:
        if production:
            raise RuntimeError("Falta API_SECRET (ver docs/despliegue.md).")
        key = _local_secret(path).encode()
        if len(key) < MIN_SECRET_BYTES:
            raise RuntimeError(f"{path} está vacío o es muy corto: bórralo y la API crea otro al arrancar.")
        return key
    key = value.encode()
    if len(key) < MIN_SECRET_BYTES:
        raise RuntimeError(f"API_SECRET debe tener al menos {MIN_SECRET_BYTES} bytes (`openssl rand -hex 32`).")
    return key


def _local_secret(path: Path) -> str:
    """Lee el secreto local o lo crea. Se escribe aparte y se enlaza con su nombre (falla si ya existe): dos procesos
    que arrancan a la vez terminan con el mismo secreto, nunca con uno a medio escribir."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        draft = path.with_name(f".{path.name}.{os.getpid()}")
        draft.unlink(missing_ok=True)  # uno que quedó de otro arranque con el mismo pid (en un contenedor se repite)
        fd = os.open(draft, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w") as file:
                file.write(secrets.token_hex(32))
            os.link(draft, path)
        except FileExistsError:
            pass  # otro proceso lo creó primero: vale el suyo
        finally:
            draft.unlink(missing_ok=True)
    return path.read_text().strip()


@functools.cache
def secret() -> bytes:
    """El secreto de este proceso (lo pide el arranque de la API, así un error se ve al tiro)."""
    return load_secret(config.API_SECRET, config.API_PRODUCTION, config.API_SECRET_FILE)


def _signature(user_id: str, key: bytes) -> str:
    digest = hmac.new(key, user_id.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def sign(user_id: str, key: bytes | None = None) -> str:
    """El token de `user_id`: `<id>.<firma>`."""
    return f"{user_id}.{_signature(user_id, key or secret())}"


def verify(token: str | None, key: bytes | None = None) -> str | None:
    """El id que firma `token`, o None si no es un token de esta API (roto, alterado o de otro secreto)."""
    user_id, dot, signature = (token or "").rpartition(".")
    if not user_id or not dot:
        return None
    expected = _signature(user_id, key or secret())
    return user_id if hmac.compare_digest(expected.encode(), signature.encode("utf-8", "replace")) else None


def current_user(request: Request) -> str | None:
    """El id de la cabecera X-User-Token, si su firma es válida."""
    return verify(request.headers.get(TOKEN_HEADER))


def require_user(user_id: str, current: str | None) -> None:
    """401 sin sesión (o con un token que no es de esta API), 403 si el token es de otra persona. No registra nada:
    ni el id ni el token llegan a los logs."""
    if current is None:
        raise HTTPException(401, NO_SESSION)
    if current != user_id:
        raise HTTPException(403, NOT_ALLOWED)


async def owner_in_path(request: Request, user_id: Annotated[str, fastapi.Path()]) -> None:
    """Dependencia de las rutas `…/{user_id}`: el id de la ruta, ya leído como lo lee la ruta, debe ser el del token.
    Va en `dependencies=[…]`, antes que la conexión: un request ajeno no ocupa ninguna."""
    require_user(user_id, current_user(request))


async def owner_in_query(request: Request, user_id: Annotated[str | None, Query()] = None) -> None:
    """Lo mismo para `?user_id=`; sin él, la ruta sigue anónima."""
    if user_id is not None:
        require_user(user_id, current_user(request))


def owner_of_body(request: Request, user_id: str | None) -> None:
    """Las rutas con `user_id` en el cuerpo lo revisan al empezar, sobre el modelo ya validado (y limpio)."""
    if user_id is not None:
        require_user(user_id, current_user(request))


# ── Sesiones ─────────────────────────────────────────────────────────────────
def claim_legacy(conn: Connection, legacy_user_id: str | None) -> str | None:
    """El id viejo de este navegador, si tiene el formato del prototipo, existe con `source = 'prototype'` y nunca
    recibió token: se marca (lo reclama una sola vez). Si no, None."""
    if legacy_user_id is None or not PROTOTYPE_ID.fullmatch(legacy_user_id):
        return None
    row = conn.execute(
        """UPDATE app_users SET token_issued_at = now()
           WHERE user_id = %s AND source = 'prototype' AND token_issued_at IS NULL
           RETURNING user_id""",
        (legacy_user_id,),
    ).fetchone()
    return row[0] if row else None


def create_user(conn: Connection) -> str:
    """Una persona nueva del prototipo, con el token ya emitido (nunca reclamable como id viejo)."""
    user_id = f"proto-{secrets.token_hex(8)}"
    conn.execute("INSERT INTO app_users (user_id, source, token_issued_at) VALUES (%s, 'prototype', now())", (user_id,))
    return user_id
