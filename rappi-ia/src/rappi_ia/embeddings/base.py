"""Interfaz de los modelos de embeddings y un modelo falso determinista para tests (sin descargar nada)."""

import hashlib
import threading
from typing import Protocol

import numpy as np

from ..text import tokens


class TextEmbedder(Protocol):
    model_name: str
    dim: int

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    def embed_queries(self, texts: list[str]) -> np.ndarray: ...


class HashEmbedder:
    """Bolsa de palabras con hashing, normalizada. Parecido léxico = parecido vectorial: suficiente para tests."""

    def __init__(self, dim: int = 64, model_name: str = "hash-test"):
        self.dim = dim
        self.model_name = model_name

    def _embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in tokens(text):
                digest = hashlib.md5(token.encode()).digest()
                out[row, int.from_bytes(digest[:4], "little") % self.dim] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms == 0, 1, norms)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts)

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts)


def to_pgvector(vector: np.ndarray) -> str:
    """Literal de pgvector ('[0.1,0.2,…]'); evita depender de un adaptador extra."""
    return "[" + ",".join(f"{x:.6f}" for x in vector.tolist()) + "]"


class MemoizedQueryEmbedder:
    """Recuerda los vectores de las consultas: el mismo texto se embebe una sola vez aunque se busque en varias
    verticales (cada `retrieve` embebe la consulta por su cuenta). Vale para la vida de una petición. Las verticales se
    buscan en hilos a la vez: el candado hace que el primero embeba y los demás esperen su vector."""

    def __init__(self, inner: TextEmbedder):
        self.inner = inner
        self.model_name = inner.model_name
        self.dim = inner.dim
        self._queries: dict[str, np.ndarray] = {}
        self._lock = threading.Lock()

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self.inner.embed_documents(texts)

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            missing = [t for t in dict.fromkeys(texts) if t not in self._queries]
            if missing:
                self._queries.update(zip(missing, self.inner.embed_queries(missing), strict=True))
            return np.stack([self._queries[t] for t in texts])
