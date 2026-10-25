"""Lectura del JSON de Next.js (`<script id="__NEXT_DATA__">`) que traen todas las páginas de rappi.cl."""

import functools
import json
import re
from collections.abc import Callable

# Sin orden fijo de atributos: un cambio inofensivo del frontend no debe parecer un bloqueo en cada página.
_NEXT_DATA_RE = re.compile(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


class ParseError(Exception):
    """La página no tiene la estructura esperada (Rappi pudo cambiar su frontend)."""


class MissingNextData(ParseError):
    """La página no trae `__NEXT_DATA__`: suele ser una página de desafío (bot) y no la que se pidió."""


def extract_next_data(html: str) -> dict:
    match = _NEXT_DATA_RE.search(html)
    if not match:
        raise MissingNextData("No se encontró <script id='__NEXT_DATA__'> en la página")
    try:
        return json.loads(match.group(1))
    except ValueError as exc:  # página cortada: es un error de esa página, no de toda la tienda
        raise ParseError(f"__NEXT_DATA__ ilegible: {exc}") from exc


def parse_errors[**P, R](parser: Callable[P, R]) -> Callable[P, R]:
    """Un dato con otra forma (falta una clave, otro tipo) es un ParseError de esa página, que se omite y se cuenta, y
    no un KeyError/TypeError/ValueError que tumba el job entero."""

    @functools.wraps(parser)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return parser(*args, **kwargs)
        except (KeyError, TypeError, ValueError) as exc:
            raise ParseError(f"{parser.__name__}: {type(exc).__name__} {exc}") from exc

    return wrapper


def page_props(next_data: dict) -> dict:
    try:
        return next_data["props"]["pageProps"]
    except KeyError as exc:
        raise ParseError("__NEXT_DATA__ sin props.pageProps") from exc


def components(response: dict | None) -> list[dict]:
    """`response.data.components`, la forma en que Rappi entrega bloques de pasillos y productos."""
    return ((response or {}).get("data") or {}).get("components") or []
