"""Cliente HTTP prudente para rappi.cl: se identifica, respeta robots.txt, hace pausas y reintentos y fija la ubicación
de despacho."""

import base64
import contextlib
import json
import logging
import random
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, quote, urljoin, urlparse

import requests

from .. import config
from .astro import MissingContent, Page, ParseError, content_islands, has_components, island_error
from .robots import RobotsPolicy

log = logging.getLogger(__name__)


class StoreUnavailable(Exception):
    """Rappi redirigió una tienda a un listado de tiendas: la sucursal no despacha a la ubicación actual."""


class RestaurantGone(Exception):
    """Rappi redirigió a /restaurantes?restaurantNotFound=true: el restaurante ya no existe.

    No es un error de lectura: el job queda omitido, no fallido."""


class PageNotFound(Exception):
    """La página no existe (p. ej. un sub-pasillo cuyo slug no coincide)."""


class DownloadStopped(Exception):
    """La descarga se detiene entera. No es un error de página (no está en PAGE_ERRORS): ningún pasillo, sucursal ni
    job lo atrapa, y la corrida queda abierta para retomarla más tarde. Si pasa al descubrir, la corrida se cierra como
    fallida (`run_left_open = False`)."""

    run_left_open = True


class PossibleBlock(DownloadStopped):
    """rappi.cl podría estar bloqueando la descarga: demasiados requests (o jobs) seguidos rechazados."""


class LoginRequired(PossibleBlock):
    """rappi.cl redirigió al inicio de sesión: con `logout=guest_limit`, la sesión de invitado llegó a su tope de
    páginas (10 el 25-11-2026). No es una sucursal no disponible: desde ahí toda página pide iniciar sesión. Ni se pide
    /login ni se reinicia la sesión para seguir (sería saltarse el límite): la descarga se detiene como ante un posible
    bloqueo (código 4) y la corrida queda abierta."""


class RobotsDisallowed(DownloadStopped):
    """robots.txt no permite una página a este programa, o no respondió (y entonces se asume que no permite nada). No
    se salta la regla ni se sigue con otras páginas: la descarga se detiene y lo dice."""


# Errores esperables al bajar y leer una página: se registran y se sigue con la siguiente.
PAGE_ERRORS = (PageNotFound, ParseError, requests.RequestException, RuntimeError)
RETRY_STATUSES = (429, 500, 502, 503, 504)
# Las redirecciones se siguen a mano, hasta este tope (RFC 9309 pide al menos 5 para robots.txt): robots.txt se revisa
# antes de pedir cada destino, no después de bajarlo.
MAX_REDIRECTS = 5
BLOCK_STATUSES = (403, 429)


def _retry_after(response: requests.Response) -> float | None:
    """Segundos que pide `Retry-After` (un número o una fecha HTTP), con tope; None si no lo trae o no se entiende."""
    value = (response.headers.get("Retry-After") or "").strip()
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError):
            return None
    return min(max(seconds, 0), config.RETRY_AFTER_MAX_S)


def location_cookie(lat: float, lng: float, city: str, address: str) -> str:
    """Valor de la cookie `currentLocation`: base64 del JSON codificado como URL."""
    payload = {
        "city": city,
        "autoLocation": False,
        "address": address,
        "lat": lat,
        "lng": lng,
        "url": "",
        "active": True,
    }
    return base64.b64encode(quote(json.dumps(payload)).encode()).decode()


def _refuse_login(url: str) -> None:
    target = urlparse(url)
    if target.path.rstrip("/") != config.LOGIN_PATH:
        return
    reason = (parse_qs(target.query).get("logout") or ["sin motivo"])[0]
    detail = "límite de páginas para invitados" if reason == "guest_limit" else f"logout={reason}"
    raise LoginRequired(f"rappi.cl redirigió al inicio de sesión ({detail}): no se pide esa página")


def _is_listing(path: str) -> bool:
    return path.startswith(config.UNAVAILABLE_PATH_PREFIX) or path.rstrip("/") in config.STORE_LISTING_PATHS


def _text(response: requests.Response) -> str:
    """El cuerpo como texto. Sin charset, requests decodifica text/html como Latin-1 y rompe las ñ y las tildes;
    rappi.cl sirve UTF-8."""
    if response.encoding is None or response.encoding.lower() == "iso-8859-1":
        response.encoding = "utf-8"
    return response.text


class RappiClient:
    """Cliente de rappi.cl. `TIMEOUT_SECONDS` es por operación de socket (conectar, cada lectura), no un plazo total:
    una respuesta que gotea bytes sin parar no tiene tope. Se acepta así: las páginas de Rappi llegan enteras o se
    cortan, y una que se corta cae en el reintento."""

    def __init__(self) -> None:
        self._blocked_streak = 0  # requests seguidos rechazados (403, 429, desafío)
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": config.USER_AGENT,
                "Accept-Language": "es-CL,es;q=0.9",
            }
        )
        self._robots = RobotsPolicy(config.UA_PROJECT, self._robots_txt)
        if not config.UA_CONTACT:
            log.warning("Sin RAPPI_UA_CONTACT: el User-Agent dice quién descarga, pero no a quién escribirle")

    def set_location(self, lat: float, lng: float, city: str, address: str) -> None:
        self.clear_location()  # rappi.cl devuelve la suya en cada página: con dos, no se sabe cuál lee
        self._session.cookies.set(
            "currentLocation",
            location_cookie(lat, lng, city, address),
            domain="www.rappi.cl",
        )

    def clear_location(self) -> None:
        """Quita la ubicación de despacho, también la que deja rappi.cl en cada página."""
        for cookie in [c for c in self._session.cookies if c.name == "currentLocation"]:
            with contextlib.suppress(KeyError):
                self._session.cookies.clear(cookie.domain, cookie.path, cookie.name)

    def get_content(self, url: str) -> bytes:
        """Descarga una URL y devuelve el cuerpo en bytes (p. ej. sitemaps .xml.gz)."""
        content = self._request(url).content
        self._blocked_streak = 0
        return content

    def get_json(self, url: str) -> dict:
        """Descarga una URL y devuelve un JSON."""
        data = self._request(url).json()
        self._blocked_streak = 0
        return data

    def get_page(self, path: str) -> Page:
        """Descarga una página de rappi.cl y sus islas de contenido (en la misma sesión: las islas leen las cookies que
        deja la página). Una página sin islas, o una isla sin componentes, cuenta para el detector de bloqueos, igual
        que un 403; una isla que responde con su página de error es un ParseError de esa página."""
        response = self._request(config.BASE_URL + path)
        final = urlparse(response.url)
        if _is_listing(final.path) and not _is_listing(urlparse(path).path):
            self._blocked_streak = 0
            raise StoreUnavailable(f"{path} redirigió a {final.path}")
        if config.RESTAURANT_NOT_FOUND_QUERY in final.query:
            self._blocked_streak = 0
            raise RestaurantGone(f"{path} ya no existe en Rappi")
        page_html = _text(response)
        islands = content_islands(page_html)
        if not islands:
            self._count_rejection(path, "página sin islas de contenido")
            raise MissingContent("La página no trae islas de contenido (/_server-islands/...)")
        parts = [page_html]
        for name, island_path in islands:
            island_html = _text(self._request(config.BASE_URL + island_path))
            error = island_error(island_html)
            if error:
                code, message = error
                if code == "404":  # el sitio respondió: no es un rechazo
                    self._blocked_streak = 0
                else:
                    self._count_rejection(path, f"la isla {name} respondió {code}")
                raise ParseError(f"La isla {name} respondió {code}: {message}")
            if not has_components(island_html):
                self._count_rejection(path, f"la isla {name} llegó sin componentes")
                raise MissingContent(f"La isla {name} llegó sin componentes")
            parts.append(island_html)
        self._blocked_streak = 0
        return Page(final.path, "\n".join(parts))

    def _count_rejection(self, url: str, reason: str) -> None:
        self._blocked_streak += 1
        if self._blocked_streak >= config.BLOCK_STREAK_REQUESTS:
            raise PossibleBlock(
                f"posible bloqueo: {self._blocked_streak} requests seguidos rechazados (último: {reason} en {url})"
            )

    def _robots_txt(self, url: str) -> str | None:
        """El robots.txt de un sitio, con los mismos reintentos que una página; None si no existe (cualquier 4xx)."""
        try:
            text = self._request(url, check_robots=False).content.decode("utf-8", errors="replace")
        except PageNotFound:
            text = None
        except requests.HTTPError as exc:
            if exc.response is None or not 400 <= exc.response.status_code < 500:
                raise
            text = None
        self._blocked_streak = 0  # el sitio respondió
        return text

    def _check_robots(self, url: str) -> None:
        reason = self._robots.denial(url)
        if reason:
            raise RobotsDisallowed(f"{reason}: la descarga se detiene sin bajar esa página")

    def _get(self, url: str, check_robots: bool) -> requests.Response:
        """Un GET que sigue las redirecciones a mano: con `check_robots`, cada destino pasa por robots.txt antes de
        pedirlo. La respuesta final trae en `url` adónde llegó (así se ve una tienda que redirige al listado)."""
        response = self._session.get(url, timeout=config.TIMEOUT_SECONDS, allow_redirects=False)
        for _ in range(MAX_REDIRECTS):
            if not response.is_redirect:
                return response
            url = urljoin(response.url, response.headers["Location"])
            response.close()
            _refuse_login(url)  # antes de robots.txt: no es una página que haga falta, es el sitio diciendo que no
            if check_robots:
                self._check_robots(url)
            response = self._session.get(url, timeout=config.TIMEOUT_SECONDS, allow_redirects=False)
        if response.is_redirect:
            raise requests.TooManyRedirects(f"más de {MAX_REDIRECTS} redirecciones hasta {url}")
        return response

    def _request(self, url: str, check_robots: bool = True) -> requests.Response:
        if check_robots:
            self._check_robots(url)
        for attempt in range(1, config.MAX_RETRIES + 1):
            time.sleep(random.uniform(*config.REQUEST_DELAY_RANGE))
            wait = None
            try:
                response = self._get(url, check_robots)
            except requests.RequestException as exc:
                log.warning("Error de red en %s (intento %d): %s", url, attempt, exc)
            else:
                if response.status_code == 404:
                    self._blocked_streak = 0
                    raise PageNotFound(url)
                if response.status_code < 400:
                    return response
                if response.status_code in BLOCK_STATUSES:
                    self._count_rejection(url, f"HTTP {response.status_code}")
                if response.status_code not in RETRY_STATUSES:
                    response.raise_for_status()
                log.warning("HTTP %d en %s (intento %d)", response.status_code, url, attempt)
                wait = _retry_after(response)
            if attempt < config.MAX_RETRIES:  # tras el último intento la URL ya se da por perdida: no se espera
                time.sleep(wait if wait is not None else config.RETRY_BACKOFF_SECONDS * 2 ** (attempt - 1))
        raise RuntimeError(f"No se pudo descargar {url} tras {config.MAX_RETRIES} intentos")
