"""Cliente fino de Jev (TypeSafe «System One», docs.typesafe.ai): preguntas tipadas sobre un estado.

Una llamada lleva un `state` (texto, objeto o lista) y varias preguntas con nombre; la API devuelve una respuesta
por pregunta. Hay tres tipos: `noul` (probabilidad 0..1 de que algo sea cierto), `choice` (una opción entre
varias) y `score` (nivel ordenado). Es opcional: sin `TYPESAFE_API_KEY`, `client_or_none()` da `None`.

Una pregunta que falla (red, clave mala, respuesta rara) da `None`; nunca corta la corrida ni lanza. El tope de
llamadas cuenta cada intento HTTP, reintentos incluidos, para que una corrida no pueda gastar más de lo previsto.
"""

import json
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import requests

from . import config

log = logging.getLogger(__name__)

URL = "https://api.typesafe.ai/v1/systemone"
_TYPE_KEY = "type"  # nombre del campo que dice el tipo de la pregunta (único lugar donde vive)
_RETRY_STATUSES = {408, 429, 500, 502, 503, 504, 529}
_RETRIES = 2
_BACKOFF = 0.5  # segundos; se duplica en cada reintento
_MAX_WAIT = 30.0
_sleep = time.sleep  # los tests lo reemplazan para no esperar
# Jev queda apagado hasta que el piloto pasa y la persona sube este archivo (el piloto escribe una propuesta).
ADOPTION_FILE = Path(__file__).resolve().parent / "eval" / "jev-adopcion.json"
DEFAULT_T_AUTO = 0.85  # confianza mínima para mapear una categoría sin revisión, mientras el piloto no fije otra
VARIANTS = ("es", "en")  # idioma de las instrucciones al etiquetar categorías; el piloto mide los dos y elige


def Noul(instructions: str, criteria: dict | None = None) -> dict:  # noqa: N802 (constructor de pregunta)
    """Pregunta de sí/no con probabilidad. `criteria` opcional: {"true": ..., "false": ...}."""
    question = {_TYPE_KEY: "noul", "instructions": instructions}
    if criteria:
        question["criteria"] = criteria
    return question


def Choice(instructions: str, criteria: dict) -> dict:  # noqa: N802
    """Elegir una opción: `criteria` mapea cada opción (hasta 255) a su descripción."""
    return {_TYPE_KEY: "choice", "instructions": instructions, "criteria": criteria}


def Score(instructions: str, criteria: list[str]) -> dict:  # noqa: N802
    """Nivel ordenado: `criteria` lista los niveles de menor a mayor (de 2 a 10)."""
    return {_TYPE_KEY: "score", "instructions": instructions, "criteria": criteria}


@dataclass
class JevAnswer:
    noul: float | None = None
    choice: str | None = None
    score: float | None = None
    probabilities: dict[str, float] = field(default_factory=dict)
    # En choice y score la devuelve la API; en noul no, y se calcula como |2p - 1| (0 = indeciso, 1 = seguro).
    confidence: float | None = None


@dataclass
class JevStats:
    requests: int = 0  # llamadas HTTP, reintentos incluidos
    input_tokens: int = 0
    failures: int = 0  # preguntas que terminaron en None (sin contar las que el tope impidió)
    stopped_by_cap: bool = False


class JevClient:
    def __init__(self, api_key: str, model: str, max_requests: int, parallel: int, timeout: float = 30):
        self._api_key = api_key
        self.model = model
        self.max_requests = max_requests
        self.parallel = max(1, parallel)
        self.timeout = timeout
        self.stats = JevStats()
        self._lock = threading.Lock()

    def ask(self, state, questions: dict[str, dict]) -> dict[str, JevAnswer] | None:
        """Nunca lanza: cualquier fallo se cuenta, se anota (solo la clase del error) y da None."""
        try:
            body = {"state": state, "model": self.model, "questions": questions}
            response = self._post(body)  # cuenta sus propios fallos
            if response is None:
                return None
            try:
                payload = response.json()
                answers = {name: _parse_answer(questions[name], payload["answers"][name]) for name in questions}
                input_tokens = int((payload.get("usage") or {}).get("input_tokens") or 0)
            except (ValueError, KeyError, TypeError, AttributeError):
                log.warning("Jev respondió algo que no se entiende; se ignora esta pregunta")
                self._count_failure()
                return None
            with self._lock:
                self.stats.input_tokens += input_tokens
            return answers
        except Exception as exc:  # noqa: BLE001 - una pregunta mala no debe cortar la corrida
            log.warning("Fallo inesperado al preguntarle a Jev (%s)", type(exc).__name__)
            self._count_failure()
            return None

    def ask_many(self, items: list[tuple]) -> list[dict[str, JevAnswer] | None]:
        """Varias preguntas en paralelo, en el mismo orden; las que fallan dan None."""
        if not items:
            return []
        with ThreadPoolExecutor(max_workers=self.parallel) as pool:
            return list(pool.map(lambda item: self.ask(*item), items))

    def _post(self, body: dict) -> requests.Response | None:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        for attempt in range(_RETRIES + 1):
            if not self._reserve():
                if attempt > 0:  # ya había fallado una vez: esta pregunta se queda sin respuesta
                    self._count_failure()
                return None
            wait = _BACKOFF * 2**attempt
            try:
                response = requests.post(URL, headers=headers, json=body, timeout=self.timeout)
            except requests.RequestException as exc:
                log.warning("Jev: error de conexión (%s)", type(exc).__name__)
            else:
                if response.status_code == 200:
                    return response
                if response.status_code not in _RETRY_STATUSES:
                    log.warning("Jev respondió %s; no se reintenta", response.status_code)
                    self._count_failure()
                    return None
                log.warning("Jev respondió %s", response.status_code)
                wait = _retry_after(response, wait)
            if attempt < _RETRIES:
                _sleep(wait)
        self._count_failure()
        return None

    def _reserve(self) -> bool:
        """Cuenta una llamada si el tope lo permite."""
        with self._lock:
            if self.stats.requests >= self.max_requests:
                if not self.stats.stopped_by_cap:
                    log.warning("Jev: se llegó al tope de %s llamadas; el resto queda sin respuesta", self.max_requests)
                self.stats.stopped_by_cap = True
                return False
            self.stats.requests += 1
            return True

    def _count_failure(self) -> None:
        with self._lock:
            self.stats.failures += 1


def _retry_after(response, default: float) -> float:
    """Segundos de Retry-After entre 0 y _MAX_WAIT; si no sirve (NaN, negativo, texto), la espera por defecto."""
    try:
        seconds = float(response.headers.get("Retry-After"))
    except (TypeError, ValueError):
        return default
    if not math.isfinite(seconds) or seconds < 0:
        return default
    return max(0.0, min(seconds, _MAX_WAIT))


def _parse_answer(question: dict, raw: dict) -> JevAnswer:
    kind = question[_TYPE_KEY]
    if kind == "noul":
        p = float(raw["noul"])
        return JevAnswer(noul=p, probabilities={"true": p, "false": 1 - p}, confidence=abs(2 * p - 1))
    probabilities = {str(k): float(v) for k, v in (raw.get("probabilities") or {}).items()}
    confidence = raw.get("confidence")
    confidence = float(confidence) if confidence is not None else None
    if kind == "choice":
        return JevAnswer(choice=str(raw["choice"]), probabilities=probabilities, confidence=confidence)
    if kind == "score":
        return JevAnswer(score=float(raw["score"]), probabilities=probabilities, confidence=confidence)
    raise ValueError(f"tipo de pregunta desconocido: {kind}")


@dataclass(frozen=True)
class Adoption:
    """Qué roles de Jev se adoptaron tras el piloto, con qué umbral y para qué versión del modelo."""

    categorias: bool = False
    juez: bool = False
    t_auto: float = DEFAULT_T_AUTO
    model_version: str | None = None
    variante: str = VARIANTS[0]  # idioma de las instrucciones con que pasó el piloto de categorías


def load_adoption(path: Path | None = None) -> Adoption:
    """Lee `eval/jev-adopcion.json`. Sin archivo, o con uno que no se entiende, no hay nada adoptado."""
    path = path or ADOPTION_FILE
    if not path.exists():
        return Adoption()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        adoption = Adoption(
            categorias=raw.get("categorias", False),
            juez=raw.get("juez", False),
            t_auto=float(raw.get("t_auto", DEFAULT_T_AUTO)),
            model_version=raw.get("model_version"),
            variante=raw.get("variante", VARIANTS[0]),
        )
        valid = (
            isinstance(adoption.categorias, bool)
            and isinstance(adoption.juez, bool)
            and 0 < adoption.t_auto <= 1
            and (adoption.model_version is None or isinstance(adoption.model_version, str))
            and adoption.variante in VARIANTS
        )
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        log.warning("%s no se entiende: Jev queda sin adoptar", path.name)
        return Adoption()
    return adoption


def client_or_none() -> JevClient | None:
    """El cliente si hay TYPESAFE_API_KEY; si no, None y el proceso sigue sin Jev."""
    if not config.TYPESAFE_API_KEY:
        return None
    return JevClient(config.TYPESAFE_API_KEY, config.JEV_MODEL, config.JEV_MAX_REQUESTS, config.JEV_PARALLEL)
