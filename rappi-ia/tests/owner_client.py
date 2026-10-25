"""Un TestClient que actúa como dueño de los ids que manda, para los tests que no prueban la identidad firmada.

Firma con el secreto de los tests el `user_id` de la ruta (`/profile/{user_id}`, `/gustos`, `/verticales`), de la
query o del cuerpo JSON y lo pone en X-User-Token, como hace la app con su sesión. Una petición que ya trae su
cabecera la manda tal cual. Los tests de la identidad (test_ownership.py) usan el TestClient de siempre.
"""

import re
from urllib.parse import parse_qs, unquote, urlsplit

from fastapi.testclient import TestClient

from rappi_ia.api import identity

USER_IN_PATH = re.compile(r"^/profile/([^/]+)(?:/gustos|/verticales)?$")


def claimed_user(url, params=None, json=None) -> str | None:
    parts = urlsplit(str(url))
    match = USER_IN_PATH.match(parts.path)
    if match:
        return unquote(match.group(1))
    query = {**parse_qs(parts.query), **{k: [v] for k, v in (params or {}).items()}}
    if query.get("user_id"):
        return str(query["user_id"][-1])
    user_id = json.get("user_id") if isinstance(json, dict) else None
    return user_id if isinstance(user_id, str) else None


class OwnerClient(TestClient):
    def request(self, method, url, *, params=None, json=None, headers=None, **kwargs):
        headers = dict(headers or {})
        user_id = claimed_user(url, params, json)
        if user_id is not None and not any(name.lower() == identity.TOKEN_HEADER.lower() for name in headers):
            headers[identity.TOKEN_HEADER] = identity.sign(user_id)
        return super().request(method, url, params=params, json=json, headers=headers, **kwargs)
