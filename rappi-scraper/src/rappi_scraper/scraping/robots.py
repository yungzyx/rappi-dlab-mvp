"""robots.txt de cada sitio del que se descarga: se consulta antes de cada página y se respeta (RFC 9309).

- Se busca el grupo del nombre del programa (`config.UA_PROJECT`, el del User-Agent) y, si no hay, el de `*`.
- Si el sitio no tiene robots.txt (cualquier 4xx: un 404, o el 403 de un bucket S3 que no lo publica), no hay reglas.
- Si no responde (5xx o la red, tras los reintentos del cliente), se asume que no permite nada; pero si ya se había
  leído, se sigue con esa copia (RFC 9309 §2.4) y se vuelve a pedir en RETRY_SECONDS.
- Lo leído vale CACHE_SECONDS: una descarga dura días, así que se vuelve a pedir.
"""

import logging
import time
from collections.abc import Callable
from urllib.parse import urlsplit

import requests
from protego import Protego

log = logging.getLogger(__name__)

# RFC 9309 §2.4: una copia guardada no se usa más de 24 horas, salvo que el robots.txt nuevo no responda.
CACHE_SECONDS = 24 * 3600
RETRY_SECONDS = 3600


class RobotsPolicy:
    """Reglas de robots.txt por origen. `fetch(url)` devuelve el texto del robots.txt, None si el sitio no tiene, o
    lanza `requests.RequestException` o `RuntimeError` si no respondió (eso no se guarda: se vuelve a pedir)."""

    def __init__(
        self,
        agent: str,
        fetch: Callable[[str], str | None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.agent = agent
        self._fetch = fetch
        self._clock = clock
        self._cache: dict[str, tuple[float, Protego]] = {}

    def denial(self, url: str) -> str | None:
        """Por qué no se puede bajar `url` (robots.txt no lo permite o no respondió); None si se puede."""
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        cached = self._cache.get(origin)
        if cached and self._clock() - cached[0] < CACHE_SECONDS:
            rules = cached[1]
        else:
            try:
                text = self._fetch(f"{origin}/robots.txt")
            except (requests.RequestException, RuntimeError) as exc:  # 5xx o la red, tras los reintentos del cliente
                if not cached:
                    return f"robots.txt de {parts.netloc} no respondió ({exc}): se asume que no permite nada"
                log.warning("robots.txt de %s no respondió (%s): sigo con la copia anterior", parts.netloc, exc)
                rules = cached[1]
                self._cache[origin] = (self._clock() - CACHE_SECONDS + RETRY_SECONDS, rules)
            else:
                log.info("robots.txt de %s: %s", parts.netloc, "no existe, sin reglas" if text is None else "leído")
                rules = Protego.parse(text or "")
                self._cache[origin] = (self._clock(), rules)
        if rules.can_fetch(url, self.agent):
            return None
        return f"robots.txt de {parts.netloc} no permite {parts.path or '/'} a {self.agent}"
