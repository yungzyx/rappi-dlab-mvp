from pathlib import Path

import pytest
import requests

from rappi_scraper.scraping.client import RestaurantGone, StoreUnavailable
from rappi_scraper.scraping.next_data import ParseError, extract_next_data
from rappi_scraper.storage.db import connect, database_url, migrate

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_page(name: str) -> dict:
    """`__NEXT_DATA__` de una página real guardada en tests/fixtures/<name>.html."""
    return extract_next_data((FIXTURES_DIR / f"{name}.html").read_text(encoding="utf-8"))


def restaurant_block(data: dict) -> dict:
    """El bloque del restaurante dentro del `__NEXT_DATA__` de su página."""
    return next(v for k, v in data["props"]["pageProps"]["fallback"].items() if k.startswith('@"restaurant/'))


def with_top_section(data: dict, products: list[dict], corridor_id: int = 99999) -> dict:
    """La página del restaurante con un pasillo «Más vendidos» arriba que repite `products`, como lo manda Rappi: el
    mismo plato, con su id y el corridorId del pasillo popular."""
    copies = [{**p, "corridorId": corridor_id} for p in products]
    restaurant_block(data)["corridors"].insert(0, {"name": "Más vendidos", "products": copies})
    return data


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

    def set_location(self, *args):
        pass

    def clear_location(self):
        pass

    def get_next_data(self, path: str) -> dict:
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
            return load_page(self.pages[path])
        depth = path.count("/")  # /tiendas/x -> tienda, /tiendas/x/a -> pasillo, /tiendas/x/a/b -> sub-pasillo
        return load_page({2: "store", 3: "aisle", 4: "subaisle"}[depth])


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
