"""Modelo local de texto: e5 (requiere el extra `ml`: `pip install -e ".[ml]"`).

Se cargan una sola vez por proceso. En un Mac con Apple Silicon usan la GPU (MPS) si está disponible.
"""

import logging
import threading
from functools import cache

import numpy as np

from .. import config

log = logging.getLogger(__name__)


def _device() -> str:
    import torch

    return "mps" if torch.backends.mps.is_available() else "cpu"


class E5Embedder:
    """`intfloat/multilingual-e5-*`: exige prefijos `passage:` (documentos) y `query:` (consultas)."""

    def __init__(
        self,
        model_name: str = config.TEXT_EMBEDDING_MODEL,
        batch_size: int = 64,
        revision: str | None = config.TEXT_EMBEDDING_REVISION,
    ):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.batch_size = batch_size
        device = _device()
        log.info("Cargando %s en %s", model_name, device)
        self._model = SentenceTransformer(model_name, device=device, revision=revision)
        self._model.max_seq_length = 512
        self._lock = threading.Lock()  # la API atiende en un pool de hilos: una inferencia a la vez por modelo
        dimension = (
            getattr(self._model, "get_embedding_dimension", None) or self._model.get_sentence_embedding_dimension
        )
        self.dim = dimension()

    def _encode(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            vectors = self._model.encode(
                texts,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        return vectors.astype(np.float32)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._encode([f"passage: {t}" for t in texts])

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._encode([f"query: {t}" for t in texts])


@cache
def text_embedder() -> E5Embedder:
    return E5Embedder()
