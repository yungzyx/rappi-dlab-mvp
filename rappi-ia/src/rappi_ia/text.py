"""Normalización de texto en español para reglas y comparación: minúsculas, sin tildes ni ñ, solo letras y números."""

import re
import unicodedata

from . import config

_NON_WORD = re.compile(r"[^a-z0-9]+")

# Palabras de un mensaje que no dicen qué se busca (normalizadas): saludo, cortesía, nombre del asistente y pedido.
# El nombre actual del asistente no está aquí: lo da `assistant_words()`, y solo se quita como vocativo (el mochi
# también es un postre).
GREETING_WORDS = {"hola", "holi", "buenas", "buenos", "dias", "tardes", "noches", "hey", "wena", "alo", "ola"}
THANKS_WORDS = {"gracias", "muchas", "vale", "listo", "ok", "okay", "perfecto", "genial", "bacan", "buenisimo"}
REQUEST_WORDS = {
    "quiero",
    "queria",
    "busco",
    "necesito",
    "nesecito",
    "nececito",
    "nesesito",
    "tienen",
    "tienes",
    "hay",
    "dame",
    "me",
    "podrias",
    "puedes",
    "porfa",
    "por",
    "favor",
    "un",
    "una",
    "unos",
    "unas",
}
# Muletillas de quien escribe como habla («eh quiero este una coca»): solo las salta la corrección de errores de tipeo
# (retrieval/spelling.py), que corre cuando la búsqueda queda «sin resultado». «este» y «pues» también son palabras.
MUTTER_WORDS = {"eh", "ehh", "ehm", "em", "emm", "mm", "mmm", "este", "oye", "po", "pos", "pues", "osea"}
FILLER_WORDS = frozenset(GREETING_WORDS | THANKS_WORDS | REQUEST_WORDS)


def normalize(text: str) -> str:
    """'Pañales Talla G, 40 u.' → 'panales talla g 40 u'."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    without_marks = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return _NON_WORD.sub(" ", without_marks).strip()


def tokens(text: str) -> list[str]:
    return normalize(text).split()


# Solo el artículo en minúscula y entero: «de El Bodegón» (un nombre propio) y «de elote» se quedan como están.
_CONTRACTION = re.compile(r"\b(de|a) el\b")


def contract_articles(text: str) -> str:
    """«de el súper» → «del súper» y «a el súper» → «al súper»: las plantillas interpolan etiquetas como «el súper»
    después de «de» o «a»."""
    return _CONTRACTION.sub(lambda m: "del" if m.group(1) == "de" else "al", text)


def assistant_words() -> frozenset[str]:
    """Los nombres con que la persona llama al agente: `config.AGENT_NAME` (leído al usarlo, no al importar),
    normalizado."""
    return frozenset({normalize(config.AGENT_NAME)})


# Desde aquí el prospecto de un medicamento ya no dice para qué sirve: «consulte si presenta fiebre» no vuelve
# antipirético a un laxante, ni «puede contener trazas de maní» a un producto «sin maní».
LEAFLET_WARNINGS = re.compile(
    r"\b(?:advertencias?|contraindicaciones|precauciones|efectos (?:adversos|secundarios)|reacciones adversas"
    r"|sobredosis|interacciones|como debo usar|posologia)\b"
)
