"""Lectura de las páginas de rappi.cl, hechas con Astro desde el 25-11-2026 (antes, Next.js y `__NEXT_DATA__`).

La página que se pide trae poco: el JSON-LD (nombre, marca, coordenadas) y dónde están sus "islas de servidor"
(`/_server-islands/<Nombre>?e=…&p=…`), fragmentos de HTML que el navegador pide después con las cookies de la página.
Esos fragmentos traen el catálogo: componentes `<astro-island>` con sus datos en `props` (JSON escapado en HTML, cada
valor serializado como `[tipo, valor]`) y eventos de analítica (`data-analytics`) con datos del local. El cliente
(`client.get_page`) baja la página y sus islas de contenido, y los parsers leen todo junto.
"""

import functools
import html
import json
import re
from collections.abc import Callable
from dataclasses import dataclass

# Islas de la cabecera, iguales en todas las páginas: no traen catálogo y no se piden.
CHROME_ISLANDS = frozenset(
    {"UserAvatarContent", "SearchInputClientWrapper", "BasketHeaderIconWrapper", "CurrentAddress"}
)

_SERVER_ISLAND_RE = re.compile(r"fetch\('(/_server-islands/([A-Za-z0-9_]+)\?[^']*)'")
_ASTRO_ISLAND_RE = re.compile(r"<astro-island\s([^>]*)>")
_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
_JSON_LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_ANALYTICS_RE = re.compile(r'data-analytics="([^"]*)"')
_CANONICAL_RE = re.compile(r'<link rel="canonical" href="([^"]*)"')


class ParseError(Exception):
    """La página no tiene la estructura esperada (Rappi pudo cambiar su frontend)."""


class MissingContent(ParseError):
    """La página no trae islas de contenido, o una isla llegó sin componentes: suele ser una página de desafío (bot) y
    no la que se pidió."""


@dataclass(frozen=True)
class Page:
    """Una página ya bajada: `path` es adónde llegó (tras las redirecciones) y `html`, la página seguida de sus islas
    de contenido."""

    path: str
    html: str


def parse_errors[**P, R](parser: Callable[P, R]) -> Callable[P, R]:
    """Un dato con otra forma (falta una clave, otro tipo) es un ParseError de esa página, que se omite y se cuenta, y
    no un KeyError/TypeError/ValueError que tumba el job entero."""

    @functools.wraps(parser)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return parser(*args, **kwargs)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ParseError(f"{parser.__name__}: {type(exc).__name__} {exc}") from exc

    return wrapper


def content_islands(page_html: str) -> list[tuple[str, str]]:
    """(nombre, ruta) de las islas de servidor con contenido, en el orden de la página y sin las de la cabecera."""
    seen, islands = set(), []
    for match in _SERVER_ISLAND_RE.finditer(page_html):
        path, name = html.unescape(match.group(1)), match.group(2)
        if name not in CHROME_ISLANDS and path not in seen:
            seen.add(path)
            islands.append((name, path))
    return islands


def island_error(island_html: str) -> tuple[str, str] | None:
    """(código, mensaje) si la isla respondió con su página de error (p. ej. "404", "Location not found")."""
    for event in _events(island_html):
        if event.get("event_name") == "VIEW_ERROR_PAGE":
            props = event.get("event_properties") or {}
            return str(props.get("ERROR_CODE") or ""), str(props.get("ERROR_MESSAGE") or "")
    return None


def has_components(island_html: str) -> bool:
    """Si la isla trae algo de Rappi: componentes o eventos de analítica."""
    return "<astro-island" in island_html or "data-analytics=" in island_html


def components(page: Page, name: str) -> list[dict]:
    """Los `props` de cada `<astro-island>` del componente `name` (`/_astro/<name>.<hash>.js`), ya deserializados."""
    found = []
    for match in _ASTRO_ISLAND_RE.finditer(page.html):
        attrs = dict(_ATTR_RE.findall(match.group(1)))
        if attrs.get("component-url", "").rsplit("/", 1)[-1].split(".", 1)[0] != name:
            continue
        raw = json.loads(html.unescape(attrs.get("props") or "{}"))
        found.append({key: _revive(value) for key, value in raw.items()})
    return found


def _revive(value):
    """Un valor serializado por Astro: `[0, x]` es x (y si x es un objeto, sus valores van serializados igual),
    `[1, [...]]` una lista y `[0]` undefined. Los demás tipos (fecha, Map, Set, URL…) se devuelven tal cual: el scraper
    no los usa."""
    if not isinstance(value, list) or not value:
        return value
    if len(value) < 2:
        return None
    kind, payload = value[0], value[1]
    if kind == 0 and isinstance(payload, dict):
        return {key: _revive(item) for key, item in payload.items()}
    if kind == 1 and isinstance(payload, list):
        return [_revive(item) for item in payload]
    return payload


def json_ld(page: Page, type_: str) -> dict:
    """El primer bloque JSON-LD de ese `@type` ("Store", "Restaurant"), o {}."""
    for match in _JSON_LD_RE.finditer(page.html):
        try:
            data = json.loads(match.group(1))
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == type_:
            return data
    return {}


def analytics(page: Page, event_name: str) -> dict:
    """`event_properties` del primer evento de analítica con ese nombre ("VIEW_STORE", "VIEW_STORE_TYPE"), o {}."""
    for event in _events(page.html):
        if event.get("event_name") == event_name:
            return event.get("event_properties") or {}
    return {}


def canonical_path(page: Page) -> str:
    """La ruta de `<link rel="canonical">`, o adónde llegó la página."""
    match = _CANONICAL_RE.search(page.html)
    if match:
        return re.sub(r"^https?://[^/]+", "", html.unescape(match.group(1))) or page.path
    return page.path


def _events(text: str) -> list[dict]:
    events = []
    for match in _ANALYTICS_RE.finditer(text):
        try:
            event = json.loads(html.unescape(match.group(1)))
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events
