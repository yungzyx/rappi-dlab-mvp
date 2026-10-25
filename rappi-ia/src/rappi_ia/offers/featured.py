"""Lo destacado: lo que la app muestra sin que la persona lo pida («Lo más pedido», los kits, «lo que más piden» en
restaurantes) se ve bien y calza con su título.

Las reglas viven en datos (`destacado.toml`, junto a este módulo) y se validan al cargar:
- `featured`: con foto, sin nombres repetidos y, en los platos, ni acompañamientos ni relleno (`side_dish`) y de un
  local de la ciudad de la persona (`profiles.city_places`); con `main`, además, platos principales (`main_dish`).
- `one_per_concept`: un producto por concepto mientras alcancen («Lo más pedido» no son tres pizzas).
"""

import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from psycopg import Connection

from ..concepts.taxonomy import load_taxonomy
from ..text import normalize, tokens
from .profiles import city_places

DATA_PATH = Path(__file__).resolve().parent / "destacado.toml"


@dataclass(frozen=True)
class Rules:
    min_main_price: float
    not_main: frozenset[str]  # conceptos que no son plato principal
    side_sections: tuple[tuple[str, ...], ...]  # palabras con que empieza una sección de relleno
    side_names: frozenset[str]  # primera palabra del nombre de un plato de relleno


@cache
def load_rules(path: Path = DATA_PATH) -> Rules:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    main, side = raw.get("plato_principal", {}), raw.get("relleno", {})
    price = main.get("precio_minimo")
    if not isinstance(price, int | float) or price <= 0:
        raise ValueError("destacado.toml: «precio_minimo» va como un número mayor que cero")
    concepts = load_taxonomy().concepts
    for concept in main.get("conceptos_fuera", ()):
        if concept not in concepts:
            raise ValueError(f"destacado.toml: concepto desconocido «{concept}»")
    for key in ("secciones", "nombres"):
        words = side.get(key)
        if not words or not all(isinstance(w, str) and normalize(w) for w in words):
            raise ValueError(f"destacado.toml: «{key}» va como una lista de textos no vacíos")
    if any(len(tokens(n)) > 1 for n in side["nombres"]):
        raise ValueError("destacado.toml: cada uno de «nombres» es una sola palabra (se compara la primera del plato)")
    return Rules(
        float(price),
        frozenset(main.get("conceptos_fuera", ())),
        tuple(tuple(tokens(s)) for s in side["secciones"]),
        frozenset(normalize(n) for n in side["nombres"]),
    )


def side_dish(name: str, section: str | None, price: float | None) -> bool:
    """Un acompañamiento o relleno: la sección del menú empieza con una de relleno («Agregados», «Bebidas y jugos») o el
    nombre empieza con una palabra de relleno y cuesta menos que un plato principal («Salsa de ajo» de $600; sin precio
    también: no se sabe)."""
    rules = load_rules()
    words = tokens(name)
    if words and words[0] in rules.side_names and (price is None or price < rules.min_main_price):
        return True
    heading = tokens(section or "")
    return any(heading[: len(start)] == list(start) for start in rules.side_sections)


def main_dish(price: float | None, concept: str | None) -> bool:
    """Un plato principal: con precio desde el mínimo y de un concepto que es plato (sin concepto, decide el precio)."""
    rules = load_rules()
    return price is not None and price >= rules.min_main_price and concept not in rules.not_main


def featured(conn: Connection, products: list[dict], city: str, main: bool = False) -> list[dict]:
    """Los productos (`Product.to_dict()`) que se pueden destacar, en su orden: con foto y sin repetir un nombre; los
    platos, sin acompañamientos ni relleno (`side_dish`) y de un local de `city` (`city_places`; un local sin comuna no
    se sabe dónde está y queda fuera). Con `main`, los platos además son principales (`main_dish`)."""
    dishes = [int(p["entity_id"]) for p in products if p.get("entity_type") == "menu_item"]
    facts = (
        {
            item_id: (section, normalize(comuna or ""))
            for item_id, section, comuna in conn.execute(
                """SELECT mi.item_id::text, ms.name, s.city FROM menu_items mi
                   JOIN stores s ON s.store_id = mi.store_id
                   LEFT JOIN menu_sections ms ON ms.store_id = mi.store_id AND ms.section_id = mi.section_id
                   WHERE mi.item_id = ANY(%s)""",
                (dishes,),
            )
        }
        if dishes
        else {}
    )
    places = city_places(city)
    names: set[str] = set()
    kept = []
    for product in products:
        name = normalize(product["name"])
        if not product.get("img") or name in names:
            continue
        if product.get("entity_type") == "menu_item":
            section, comuna = facts.get(product["entity_id"], (None, ""))
            if side_dish(product["name"], section, product.get("price_value")) or comuna not in places:
                continue
            if main and not main_dish(product.get("price_value"), product.get("concept")):
                continue
        names.add(name)
        kept.append(product)
    return kept


def one_per_concept(products: list[dict], limit: int) -> list[dict]:
    """Hasta `limit` productos: primero uno por concepto, en su orden (cada uno sin concepto cuenta como distinto), y
    si no alcanzan, los que quedan, también en su orden."""
    seen: set[str] = set()
    first, rest = [], []
    for product in products:
        concept = product.get("concept")
        if concept is None or concept not in seen:
            first.append(product)
            if concept is not None:
                seen.add(concept)
        else:
            rest.append(product)
    return (first + rest)[:limit]
