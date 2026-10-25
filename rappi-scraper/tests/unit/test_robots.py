"""El scraper se identifica y respeta robots.txt: contra el robots.txt real de rappi.cl (guardado en tests/fixtures) y
contra un servidor HTTP local falso. Nada sale a internet."""

import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from urllib.parse import urlsplit

import pytest
import requests
from protego import Protego

from conftest import FIXTURES_DIR
from rappi_scraper import config
from rappi_scraper.pipeline.discover import CHAIN_SITEMAP, PARTNER_SITEMAP, VERTICAL_LISTINGS
from rappi_scraper.scraping import client as client_module
from rappi_scraper.scraping.client import DownloadStopped, RappiClient, RobotsDisallowed
from rappi_scraper.scraping.robots import CACHE_SECONDS, RETRY_SECONDS, RobotsPolicy

AGENT = "rappi-dlab-scraper"
RAPPI_ROBOTS = (FIXTURES_DIR / "robots.txt").read_text(encoding="utf-8")
# Los de requests, antes de que `_no_network` (conftest) los reemplace: el servidor falso los usa, solo hacia 127.0.0.1.
_REAL_REQUEST, _REAL_GET = requests.Session.request, requests.Session.get


# ---------------------------------------------------------------- User-Agent


def test_user_agent_names_the_program_and_its_version_not_a_browser():
    ua = config.user_agent(AGENT, "")
    assert ua == f"{AGENT}/{version('rappi-scraper')} (prototipo de investigacion dLab, no afiliado a Rappi)"
    assert "Mozilla" not in ua and "Chrome" not in ua
    assert config.user_agent(AGENT, "mailto:equipo@example.cl").startswith(
        f"{AGENT}/{version('rappi-scraper')} (+mailto:equipo@example.cl; "
    )
    assert RappiClient()._session.headers["User-Agent"] == config.USER_AGENT


def test_project_and_contact_come_from_the_environment():
    clean = {k: v for k, v in os.environ.items() if not k.startswith("RAPPI_UA_")} | {"RAPPI_ENV_FILE": os.devnull}
    code = "from rappi_scraper import config; print(config.UA_PROJECT); print(config.USER_AGENT)"

    def run(**env):
        return subprocess.run(
            [sys.executable, "-c", code], env={**clean, **env}, capture_output=True, text=True, check=True
        ).stdout.splitlines()

    assert run()[0] == AGENT
    project, ua = run(RAPPI_UA_PROJECT="otro-equipo", RAPPI_UA_CONTACT="https://example.cl/bot")
    assert project == "otro-equipo"
    assert ua.startswith("otro-equipo/") and "(+https://example.cl/bot; " in ua


# ---------------------------------------------------------------- el robots.txt de rappi.cl (24-10-2026)


def test_everything_the_scraper_asks_rappi_cl_for_is_allowed():
    """Listados, sitemaps de restaurantes, tiendas, pasillos, sub-pasillos y restaurantes (rutas como las de los
    fixtures). Si un robots.txt nuevo prohíbe alguna, el scraper se detendría ahí: este test lo avisa antes."""
    rules = Protego.parse(RAPPI_ROBOTS)
    paths = [
        *VERTICAL_LISTINGS.values(),
        "/tiendas/900017335-lider-hiper-tobalaba",
        "/tiendas/900017335-lider-hiper-tobalaba/lacteos-y-huevos",
        "/tiendas/900017335-lider-hiper-tobalaba/lacteos-y-huevos/yogurt",
        "/restaurantes/384-rincon-venezolano",
        "/restaurantes/delivery/1833-vapiano",
    ]
    urls = [config.BASE_URL + p for p in paths] + [CHAIN_SITEMAP.format(0), PARTNER_SITEMAP.format(3)]
    assert [u for u in urls if not rules.can_fetch(u, AGENT)] == []


def test_what_rappi_cl_forbids_stays_forbidden():
    rules = Protego.parse(RAPPI_ROBOTS)
    for path in ("/login", "/checkout", "/api/ms/x", "/tiendas/900-farmacias-san-pablo-centro", "/x(route:carro)"):
        assert not rules.can_fetch(config.BASE_URL + path, AGENT), path
    # GPTBot tiene prohibido todo; el scraper no es GPTBot y no se rige por ese grupo.
    assert not rules.can_fetch(config.BASE_URL + "/tiendas/tipo/market", "GPTBot")


# ---------------------------------------------------------------- la política, sin red


def test_rules_are_read_once_per_site_and_again_after_a_day():
    fetched = []
    now = [0.0]

    def fetch(url):
        fetched.append(url)
        return "User-agent: *\nDisallow: /privado\n"

    policy = RobotsPolicy(AGENT, fetch, clock=lambda: now[0])
    assert policy.denial("https://a.example/uno") is None
    assert policy.denial("https://a.example/dos") is None
    assert "no permite /privado" in policy.denial("https://a.example/privado/x")
    assert policy.denial("https://b.example/uno") is None
    assert fetched == ["https://a.example/robots.txt", "https://b.example/robots.txt"]

    now[0] = CACHE_SECONDS + 1
    policy.denial("https://a.example/uno")
    assert fetched[-1] == "https://a.example/robots.txt" and len(fetched) == 3


def test_the_group_of_the_program_wins_over_the_generic_one():
    text = "User-agent: *\nDisallow: /\n\nUser-agent: rappi-dlab-scraper\nAllow: /tiendas/\nDisallow: /\n"
    policy = RobotsPolicy(AGENT, lambda url: text)
    assert policy.denial("https://a.example/tiendas/1") is None
    assert policy.denial("https://a.example/restaurantes/1") is not None


def test_if_the_renewal_does_not_answer_the_previous_copy_is_kept_and_asked_again_later():
    """Una descarga de días no se detiene porque robots.txt no respondió justo al renovarlo (RFC 9309 §2.4)."""
    now, answers = [0.0], ["User-agent: *\nDisallow: /privado\n", RuntimeError("caído"), "User-agent: *\nDisallow: /\n"]

    def fetch(url):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    policy = RobotsPolicy(AGENT, fetch, clock=lambda: now[0])
    assert policy.denial("https://a.example/uno") is None
    now[0] = CACHE_SECONDS + 1
    assert policy.denial("https://a.example/uno") is None  # no respondió: sigue la copia de antes
    assert "no permite /privado" in policy.denial("https://a.example/privado")
    now[0] += RETRY_SECONDS + 1
    assert policy.denial("https://a.example/uno") is not None  # la nueva ya no permite nada
    assert answers == []


def test_no_robots_txt_means_no_rules_and_an_unreachable_one_means_nothing_is_allowed():
    assert RobotsPolicy(AGENT, lambda url: None).denial("https://a.example/x") is None

    calls = []

    def down(url):
        calls.append(url)
        raise RuntimeError("No se pudo descargar tras 3 intentos")

    policy = RobotsPolicy(AGENT, down)
    assert "no respondió" in policy.denial("https://a.example/x")
    assert "no respondió" in policy.denial("https://a.example/x")
    assert len(calls) == 2  # no se guarda: se vuelve a pedir


# ---------------------------------------------------------------- el cliente contra un servidor falso


class _FakeSite(BaseHTTPRequestHandler):
    """robots.txt según `robots` (texto o código HTTP); /redirige va a /privado; todo lo demás responde 200."""

    robots: str | int = "User-agent: *\nDisallow: /privado\n"
    requested: list[str] = []

    def do_GET(self):  # noqa: N802 (nombre de http.server)
        self.requested.append(self.path)
        if self.path == "/robots.txt" and isinstance(self.robots, int):
            self._send(self.robots, b"")
        elif self.path == "/robots.txt":
            self._send(200, self.robots.encode())
        elif self.path == "/redirige":
            self.send_response(302)
            self.send_header("Location", "/privado/pagina")
            self.end_headers()
        else:
            self._send(200, b"{}")

    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def site(monkeypatch):
    """Un sitio en 127.0.0.1 y un cliente sin pausas: devuelve (cliente, url base, rutas pedidas). La red sigue cerrada
    para cualquier otro destino."""

    def loopback_only(real):
        def call(self, *args, **kwargs):
            url = kwargs.get("url") or args[-1]
            if urlsplit(url).hostname != "127.0.0.1":
                pytest.fail(f"los tests corren sin red: {url}")
            return real(self, *args, **kwargs)

        return call

    monkeypatch.setattr(requests.Session, "request", loopback_only(_REAL_REQUEST))
    monkeypatch.setattr(requests.Session, "get", loopback_only(_REAL_GET))
    monkeypatch.setattr(client_module.time, "sleep", lambda s: None)
    monkeypatch.setattr(client_module.random, "uniform", lambda _a, _b: 0)
    _FakeSite.requested = []
    _FakeSite.robots = "User-agent: *\nDisallow: /privado\n"
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeSite)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield RappiClient(), f"http://127.0.0.1:{server.server_port}", _FakeSite.requested
    server.shutdown()
    server.server_close()


def test_the_client_asks_for_robots_txt_first_and_once(site):
    client, base, requested = site
    assert client.get_json(base + "/uno") == {}
    assert client.get_json(base + "/dos") == {}
    assert requested == ["/robots.txt", "/uno", "/dos"]


def test_a_forbidden_page_stops_the_download_without_asking_for_it(site):
    client, base, requested = site
    with pytest.raises(RobotsDisallowed, match=f"no permite /privado/x a {config.UA_PROJECT}") as stopped:
        client.get_json(base + "/privado/x")
    assert isinstance(stopped.value, DownloadStopped)  # la corrida queda abierta, como con un posible bloqueo
    assert requested == ["/robots.txt"]


def test_a_redirect_to_a_forbidden_page_stops_before_asking_for_it(site):
    client, base, requested = site
    with pytest.raises(RobotsDisallowed, match="/privado/pagina"):
        client.get_json(base + "/redirige")
    assert requested == ["/robots.txt", "/redirige"]  # el destino nunca se pidió


def test_an_allowed_redirect_is_followed(site):
    client, base, requested = site
    _FakeSite.robots = "User-agent: *\nDisallow: /nada\n"
    assert client.get_json(base + "/redirige") == {}
    assert requested == ["/robots.txt", "/redirige", "/privado/pagina"]


@pytest.mark.parametrize("status", [404, 403])
def test_a_site_without_robots_txt_has_no_rules(site, status):
    """El 403 es lo que responde el bucket S3 de los metadatos de tiendas: no publica robots.txt (RFC 9309, 4xx)."""
    client, base, requested = site
    _FakeSite.robots = status
    assert client.get_json(base + "/privado/x") == {}
    assert requested == ["/robots.txt", "/privado/x"]


def test_a_robots_txt_that_does_not_answer_stops_the_download(site):
    client, base, requested = site
    _FakeSite.robots = 503
    with pytest.raises(RobotsDisallowed, match="no respondió"):
        client.get_json(base + "/uno")
    assert requested == ["/robots.txt"] * config.MAX_RETRIES  # los reintentos de siempre; la página, nunca
