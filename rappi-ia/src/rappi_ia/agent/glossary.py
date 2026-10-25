"""Fichas de platos para «¿qué es un poke?» (glosario.toml, escritas a mano). Se validan al cargar: una ficha sin
texto o con un id repetido es un error de datos, no una respuesta vacía."""

import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

GLOSSARY_FILE = Path(__file__).with_name("glosario.toml")


@dataclass(frozen=True)
class Dish:
    id: str
    name: str
    keywords: tuple[str, ...]
    text: str
    query: str  # lo que se busca después de la ficha


@cache
def load_glossary() -> dict[str, Dish]:
    raw = tomllib.loads(GLOSSARY_FILE.read_text(encoding="utf-8"))
    dishes: dict[str, Dish] = {}
    for d in raw.get("dish", ()):
        if d["id"] in dishes or not d["text"].strip() or not d["keywords"]:
            raise ValueError(f"glosario.toml: ficha inválida o repetida: {d['id']}")
        dishes[d["id"]] = Dish(d["id"], d["name"], tuple(d["keywords"]), d["text"], d.get("query", d["name"].lower()))
    return dishes
