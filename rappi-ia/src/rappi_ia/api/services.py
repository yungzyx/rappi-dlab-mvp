"""Servicios compartidos por la API, cargados una vez. Cada capacidad es opcional: si falta un modelo o un extra,
la API sigue funcionando y /health lo informa con el código de lo que falta (el detalle, que puede traer rutas o texto
de una excepción, solo va al log)."""

import logging
import os
import threading
from dataclasses import dataclass, field
from functools import cache

from .. import config
from ..agent.compose import TemplateComposer, default_composer
from ..agent.rappi_agent import RappiAgent
from ..embeddings.base import TextEmbedder

log = logging.getLogger(__name__)


@dataclass
class Services:
    agent: RappiAgent
    embedder: TextEmbedder | None = None
    # código (busqueda_semantica, redaccion_llm) → detalle, que solo va al log
    missing: dict[str, str] = field(default_factory=dict)

    @property
    def capabilities(self) -> dict:
        """Lo que /health publica: el nombre del modelo solo en local, y de lo que falta solo el código."""
        model = None
        if self.embedder:
            model = True if config.API_PRODUCTION else self.embedder.model_name
        return {
            "busqueda_semantica": model,
            "redaccion": self.agent.composer.name,
            "faltantes": sorted(self.missing),
        }


_LOCK = threading.Lock()


def services() -> Services:
    """Carga una sola vez aunque lleguen varias peticiones a la vez (FastAPI atiende en hilos)."""
    with _LOCK:
        return _load_services()


@cache
def _load_services() -> Services:
    """`RAPPI_IA_LIGHT=1` evita cargar modelos (tests, o un equipo sin el extra `ml`)."""
    light = os.environ.get("RAPPI_IA_LIGHT") == "1"
    missing: dict[str, str] = {}
    embedder = None
    if not light:
        try:
            from ..embeddings.models import text_embedder

            embedder = text_embedder()
        except ImportError as exc:
            missing["busqueda_semantica"] = f"falta el extra ml ({exc.name})"
        except OSError as exc:  # p. ej. un modelo de .env que no está en caché, con HF_HUB_OFFLINE=1 (make serve)
            missing["busqueda_semantica"] = f"no se pudo cargar el modelo: {exc}"
        except Exception as exc:  # torch o MPS: la API arranca igual, sin búsqueda semántica
            log.exception("No se pudo cargar el modelo de texto")
            missing["busqueda_semantica"] = f"no se pudo cargar el modelo: {exc}"
    else:
        missing["busqueda_semantica"] = "RAPPI_IA_LIGHT=1"
    try:
        composer = default_composer()
    except Exception as exc:  # el cliente de Claude: la API arranca igual y redacta con plantillas
        log.exception("No se pudo crear el redactor con Claude")
        missing["redaccion_llm"] = f"no se pudo crear el redactor con Claude: {type(exc).__name__}"
        composer = TemplateComposer()
    for code, detail in missing.items():  # /health solo dice el código; aquí queda el porqué
        if not light:  # RAPPI_IA_LIGHT=1 es una decisión, no un fallo
            log.warning("Falta %s: %s", code, detail)
    agent = RappiAgent(embedder, composer)
    log.info("Servicios listos: %s", {k: v for k, v in Services(agent, embedder).capabilities.items() if v})
    return Services(agent, embedder, missing)
