import html
import json
from pathlib import Path

import pytest
import requests

from rappi_scraper.scraping.astro import Page, ParseError, canonical_path, components
from rappi_scraper.scraping.client import RestaurantGone, StoreUnavailable
from rappi_scraper.storage.db import connect, database_url, migrate

FIXTURES_DIR = Path(__file__).parent / "fixtures"
# Rutas de pasillo: /tiendas/<vertical>/<formato>/<id>-<slug>/sub_aisles?aisle_id=N
AISLE_MARK = "/sub_aisles?aisle_id="


def load_page(name: str, path: str = "") -> Page:
    """Una página real guardada en tests/fixtures/<name>.html (la página y sus islas, reducidas), como la devuelve
    `RappiClient.get_page`."""
    page = Page(path, (FIXTURES_DIR / f"{name}.html").read_text(encoding="utf-8"))
    return Page(path or canonical_path(page), page.html)


def astro_island(name: str, props: dict) -> str:
    """Un `<astro-island>` con `props` serializados como los manda Astro (`[0, valor]`, `[1, [lista]]`)."""

    def serialize(value):
        if isinstance(value, list):
            return [1, [serialize(v) for v in value]]
        if isinstance(value, dict):
            return [0, {k: serialize(v) for k, v in value.items()}]
        return [0, value]

    attr = html.escape(json.dumps({k: serialize(v) for k, v in props.items()}, ensure_ascii=False), quote=True)
    return f'<astro-island component-url="/_astro/{name}.x.js" props="{attr}"></astro-island>'


def menu_sections(page: Page) -> list[dict]:
    """Los carruseles del menú de un restaurante (secciones, "Populares" y "Para Ti"), en orden."""
    return [props["component"] for props in components(page, "DynamicListRestaurantProductsCarousel")]


def with_section(page: Page, section_id: int, title: str, entries: list[dict], first: bool = False) -> Page:
    """La página del restaurante con una sección más del menú (`entries`: los platos como los trae un carrusel)."""
    island = astro_island(
        "DynamicListRestaurantProductsCarousel",
        {"component": {"id": section_id, "type": "rest_products_carousel", "title": title, "items": entries}},
    )
    if not first:
        return Page(page.path, page.html + "\n" + island)
    head, sep, tail = page.html.partition("<astro-island")
    return Page(page.path, head + island + sep + tail)


class FakeClient:
    """Sirve fixtures según la ruta. `unavailable`, `failing_once` y `failing` simulan tiendas caídas y errores
    (una vez o siempre); `blocked`, un rappi.cl que responde 403 a todo."""

    def __init__(
        self, pages: dict[str, str] | None = None, unavailable=(), failing_once=(), gone=(), blocked=False, failing=()
    ):
        self.pages = pages or {}
        self.blocked = blocked
        self.unavailable = set(unavailable)
        self.gone = set(gone)
        self.failing_once = set(failing_once)
        self.failing = set(failing)
        self.requested: list[str] = []
        self.locations: list[tuple | None] = []  # la ubicación con que se pidió cada página

    def set_location(self, lat, lng, city, address):
        self.locations.append((lat, lng, city))

    def clear_location(self):
        self.locations.append(None)

    def get_page(self, path: str) -> Page:
        self.requested.append(path)
        if self.blocked:
            raise requests.HTTPError(f"403 Client Error: Forbidden for url: https://www.rappi.cl{path}")
        if path in self.unavailable:
            raise StoreUnavailable(path)
        if path in self.gone:
            raise RestaurantGone(path)
        if path in self.failing_once:
            self.failing_once.discard(path)
            raise ParseError("respuesta incompleta")
        if path in self.failing:
            raise ParseError("respuesta incompleta")
        if path in self.pages:
            return load_page(self.pages[path], path)
        return load_page("aisle" if AISLE_MARK in path else "store", path)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Ningún test sale a la red: un cliente real que se colara fallaría en vez de descargar de rappi.cl."""

    def refuse(*args, **kwargs):
        pytest.fail("los tests corren sin red: usa FakeClient o un `_session.get` falso")

    monkeypatch.setattr(requests.Session, "request", refuse)
    monkeypatch.setattr(requests.Session, "get", refuse)


@pytest.fixture(autouse=True)
def _no_real_database(monkeypatch):
    """Sin DATABASE_URL (la base real, del .env): el candado de descargas no se conecta a ella y un comando que la
    pidiera falla en vez de tocarla. Los tests usan DATABASE_URL_TEST."""
    monkeypatch.delenv("DATABASE_URL", raising=False)


@pytest.fixture
def page():
    return load_page


@pytest.fixture
def db():
    """Conexión a `rappi_test` con el esquema recreado desde cero para cada test."""
    try:
        url = database_url("DATABASE_URL_TEST")
    except RuntimeError:
        pytest.skip("DATABASE_URL_TEST no configurada")
    if not url.rstrip("/").endswith("rappi_test"):
        pytest.fail(f"Por seguridad los tests solo borran la base rappi_test, no {url}")
    with connect(url) as conn:
        conn.execute("DROP SCHEMA IF EXISTS capa CASCADE")
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        conn.commit()
        migrate(conn)
        yield conn
