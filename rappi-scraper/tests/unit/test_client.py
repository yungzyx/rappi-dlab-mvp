import base64
import json
from urllib.parse import unquote

import pytest
import requests

from rappi_scraper import config
from rappi_scraper.scraping import client as client_module
from rappi_scraper.scraping.client import (
    PageNotFound,
    PossibleBlock,
    RappiClient,
    RestaurantGone,
    StoreUnavailable,
    location_cookie,
)
from rappi_scraper.scraping.robots import RobotsPolicy

NEXT_DATA_HTML = '<script id="__NEXT_DATA__" type="application/json">{"props": {"pageProps": {}}}</script>'


class _Response:
    def __init__(self, status_code: int, url: str = config.BASE_URL + "/x", text: str = NEXT_DATA_HTML, headers=None):
        self.status_code = status_code
        self.url = url
        self.text = text
        self.headers = headers or {}
        self.encoding = "utf-8"
        self.is_redirect = False  # las redirecciones las prueba test_robots.py, contra un servidor falso

    def raise_for_status(self):
        raise requests.HTTPError(f"HTTP {self.status_code}")


@pytest.fixture
def client(monkeypatch):
    """Cliente sin pausas reales (quedan en `sleeps`; la pausa al azar entre requests vale 0); `responses` define lo que
    devuelve cada GET, en orden. Sin robots.txt que pedir: aquí todo está permitido (test_robots.py lo prueba)."""
    c = RappiClient()
    c._robots = RobotsPolicy(config.UA_PROJECT, lambda url: None)
    c.responses = []
    c.calls = 0
    c.sleeps = []
    monkeypatch.setattr(client_module.time, "sleep", c.sleeps.append)
    monkeypatch.setattr(client_module.random, "uniform", lambda _a, _b: 0)

    def fake_get(url, timeout, allow_redirects=True):
        c.calls += 1
        item = c.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(c._session, "get", fake_get)
    return c


def test_location_cookie_roundtrip():
    cookie = location_cookie(-33.4, -70.6, "Santiago", "Av. Ñuñoa 1")
    payload = json.loads(unquote(base64.b64decode(cookie).decode()))
    assert payload["lat"] == -33.4
    assert payload["address"] == "Av. Ñuñoa 1"


def test_clear_location_removes_cookie_and_is_idempotent():
    client = RappiClient()
    client.set_location(-33.4, -70.6, "Santiago", "x")
    client.clear_location()
    assert "currentLocation" not in client._session.cookies
    client.clear_location()


def test_404_raises_page_not_found_without_retry(client):
    client.responses = [_Response(404)]
    with pytest.raises(PageNotFound):
        client.get_next_data("/tiendas/1")
    assert client.calls == 1


def test_retries_on_5xx_and_network_errors_then_succeeds(client):
    client.responses = [_Response(503), requests.ConnectionError("caída"), _Response(200)]
    assert client.get_next_data("/tiendas/1") == {"props": {"pageProps": {}}}
    assert client.calls == 3


def test_gives_up_after_max_retries(client):
    client.responses = [_Response(502)] * config.MAX_RETRIES
    with pytest.raises(RuntimeError):
        client.get_next_data("/tiendas/1")
    assert client.calls == config.MAX_RETRIES


def test_other_4xx_raises_http_error(client):
    client.responses = [_Response(403)]
    with pytest.raises(requests.HTTPError):
        client.get_next_data("/tiendas/1")


def test_redirect_to_store_listing_means_store_unavailable(client):
    client.responses = [_Response(200, url=config.BASE_URL + "/tiendas/tipo/market")]
    with pytest.raises(StoreUnavailable):
        client.get_next_data("/tiendas/1-jumbo")


def test_listing_pages_are_not_treated_as_unavailable(client):
    client.responses = [_Response(200, url=config.BASE_URL + "/tiendas/tipo/rappimall-parent")]
    assert client.get_next_data("/tiendas/tipo/super")


def test_redirect_to_restaurant_not_found_means_restaurant_gone(client):
    """Visto en la corrida del 27-09: 91 restaurantes cerrados salían como "página sin fallback"."""
    client.responses = [_Response(200, url=config.BASE_URL + "/restaurantes?restaurantNotFound=true")]
    with pytest.raises(RestaurantGone):
        client.get_next_data("/restaurantes/900057334-papas-truck-talca")


def _waits(client) -> list[float]:
    """Pausas de espera entre intentos (sin las pausas al azar entre requests, que en los tests valen 0)."""
    return [s for s in client.sleeps if s]


def test_retry_after_is_honoured(client):
    """Ante un 429 rappi.cl dice cuánto esperar: se respeta (con tope), en vez del backoff propio."""
    client.responses = [
        _Response(429, headers={"Retry-After": "120"}),
        _Response(429, headers={"Retry-After": "86400"}),  # un día: se espera el tope, no un día
        _Response(200),
    ]
    assert client.get_next_data("/tiendas/1") == {"props": {"pageProps": {}}}
    assert _waits(client) == [120, config.RETRY_AFTER_MAX_S]


def test_no_sleep_after_last_attempt(client):
    """El backoff crece (exponencial) y no se duerme después del último intento: la URL ya se da por perdida."""
    client.responses = [_Response(502)] * config.MAX_RETRIES
    with pytest.raises(RuntimeError):
        client.get_next_data("/tiendas/1")
    backoff = config.RETRY_BACKOFF_SECONDS
    assert _waits(client) == [backoff * 2**i for i in range(config.MAX_RETRIES - 1)]


def test_request_block_streak_raises_possible_block(client):
    """403, 429 y páginas de desafío seguidas (contadas por request, no por job) detienen la descarga."""
    client.responses = [_Response(403)] * (config.BLOCK_STREAK_REQUESTS - 1) + [_Response(200, text="<p>captcha</p>")]
    for _ in range(config.BLOCK_STREAK_REQUESTS - 1):
        with pytest.raises(requests.HTTPError):
            client.get_next_data("/tiendas/1")
    with pytest.raises(PossibleBlock):
        client.get_next_data("/tiendas/1")
    assert client.calls == config.BLOCK_STREAK_REQUESTS


def test_a_good_page_resets_the_block_streak(client):
    n = config.BLOCK_STREAK_REQUESTS - 1
    client.responses = [_Response(403)] * n + [_Response(200)] + [_Response(403)] * n
    for i in range(2 * n + 1):
        if i == n:
            client.get_next_data("/tiendas/1")
            continue
        with pytest.raises(requests.HTTPError):
            client.get_next_data("/tiendas/1")


def test_utf8_without_charset(client):
    """`requests` decodifica text/html sin charset como Latin-1: las ñ y las tildes llegaban rotas."""
    html = '<script id="__NEXT_DATA__" type="application/json">{"name": "Ñuñoa café"}</script>'
    response = requests.Response()
    response.status_code = 200
    response.url = config.BASE_URL + "/tiendas/1"
    response.headers["Content-Type"] = "text/html"
    response._content = html.encode("utf-8")
    response.encoding = requests.utils.get_encoding_from_headers(response.headers)
    assert response.encoding == "ISO-8859-1"  # lo que haría requests
    client.responses = [response]

    assert client.get_next_data("/tiendas/1") == {"name": "Ñuñoa café"}
