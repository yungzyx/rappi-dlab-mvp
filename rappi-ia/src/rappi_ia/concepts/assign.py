"""Asigna un concepto a cada producto del catálogo y a cada plato, con procedencia.

Prioridad (la primera que responda gana):
- Producto del catálogo: categoría de Rappi mapeada → reglas sobre el nombre.
- Plato: reglas sobre el nombre del plato → sección del menú mapeada → cocina del restaurante mapeada.

En los platos manda el nombre porque las secciones suelen ser genéricas ("Promociones", "Combos"), salvo que la
regla caiga fuera de lo que vende un restaurante ("Perro caliente" no es alimento para perros): ahí gana la sección
o la cocina mapeada. En los productos manda la categoría porque el nombre trae marcas y ruido ("Fanta Naranja 1,5 L"),
salvo que el nombre calce un concepto sensible o de bebé y la categoría no (un lubricante en "Agua saborizada", una
mamadera en "Frutos secos y semillas"), fuera de mascotas y juguetes (un analgésico veterinario sigue en mascotas), que
calce un concepto de especialidad que afina una categoría de comida («Kikkoman Salsa de Soya» en "Otras salsas" es
despensa asiática, en cualquier parte del nombre), o que diga alcohol en una categoría de bebidas sin alcohol
(«Mistral Ice Energy» en "Energizantes"). Una categoría dudosa de suplementos o de bebé no le cede el producto a una
regla de comida («Oregano Oil 60 Softgels» en "Productos naturales").
"""

import re
from dataclasses import dataclass, replace
from functools import cache

from ..offers.guards import alcohol_in_name, alcohol_section
from ..text import FILLER_WORDS, tokens
from .matcher import KeywordMatcher, Match
from .taxonomy import Concept, Taxonomy, guarded_concepts, keeps_sensitive, load_taxonomy

MIN_MAP_CONFIDENCE = 0.6  # bajo esto, el mapeo de categoría se considera dudoso y se prueban las reglas
RULE_CONFIDENCE = 0.7  # confianza de una regla por palabra clave sobre el nombre
# Lo que un nombre de plato impone sobre su sección. Sin «frescos»: un ingrediente en el nombre («Mechada palta mayo»,
# «Phad Kee Maoo Vacuno») no dice qué plato es; la sección sí (juicio de precisión del 06-10-2026).
MENU_GROUPS = frozenset({"alcohol", "bebidas", "snacks", "dulces", "despensa", "comida"})
# Procedencia de un concepto que dio el nombre de la sección del plato (`_from_section_name`).
SECTION_NAME = "seccion-nombre:"
# Palabras que llevan una sección a alcohol y que en un menú chileno también son comida: «Aperitivos» es la comida para
# picar o el trago de antes de comer, y «Cocktail» en singular, comida de fiesta («Emp. queso horno cocktail»). En
# plural, «cócteles» son tragos.
AMBIGUOUS_SECTION_WORDS = frozenset({"aperitivo", "aperitivos", "coctel", "cocktail"})
# Lo que dice que un plato de esas secciones es comida sólida. Sin frutas, lácteos ni huevos: también están en los
# tragos («Mango Sour», «Piña Colada», «Ruso Blanco», la yema de la «Vaina»).
SOLID_FOOD_CONCEPTS = frozenset({"quesos", "fiambres", "verduras"})
# Lo que dice que un plato es una bebida aunque no diga alcohol: un trago con nombre de verdura («Pepino Tonic», «Apio
# Frozen», «Jarra de Pepino») no es comida. Palabras sueltas y un volumen («300 cc», «1/2 Lt», «16 oz»). Que una comida
# quede como alcohol por una de ellas («Queso con galletas soda») es la dirección segura.
DRINK_WORDS = KeywordMatcher(
    ("bebida", word)
    for word in (
        *("bebida", "jugo", "limonada", "batido", "tonic", "tonica", "fizz", "mule", "punch", "ponche", "frozen"),
        *("ice", "fresh", "smash", "cooler", "highball", "soda", "ginger", "shot", "clerico", "jarra", "botella"),
        *("copa", "vaso", "bar", "rhum", "destilado"),
    )
)
LIQUID_VOLUME = re.compile(
    r"\d\s*(?:ml|cc|c\.c|c/c|cm3|oz|lts?|l|litros?)\b|\b(?:ml|cc|cm3|oz|lts?|litros?)\b", re.IGNORECASE
)
# La cocina del local es la pista más débil: solo cuenta con un mapeo muy confiable (Sushi → sushi). Con mapeos
# dudosos (Americana → pizza, Asiática → sushi) acertaba el 62 %.
CUISINE_MIN_CONFIDENCE = 0.85
# Un plato no es el ingrediente crudo que nombra («Macarrón Frutilla», «Papas Familiar», «Queso» en Empanadas): por el
# nombre acertaban 1 de cada 3. Los que nombran la proteína (pescados, pollo, carnes) sí se quedan.
INGREDIENT_CONCEPTS = frozenset({"frutas", "verduras", "lacteos", "quesos", "fiambres", "huevos"})
PROTEIN_CONCEPTS = frozenset({"pollo", "pescados-mariscos"})
# Grupos cuya categoría manda aunque el nombre calce un sensible: ahí la palabra tiene otro sentido (un analgésico
# veterinario, un insecto vibrador de juguete) y el concepto sensible los ocultaría.
CATEGORY_WINS_GROUPS = frozenset({"mascotas", "juguetes"})
# Conceptos cuya categoría, aunque sea dudosa, no le cede el producto a una regla de comida (`_category_keeps`): los
# suplementos y lo de bebé. No toda salud: en «Otros cuidado corporal» (higiene, 0,45) los colorantes de repostería sí
# son comida.
CATEGORY_KEEPS_FROM_FOOD = frozenset({"vitaminas", "panales", "alimentacion-bebe", "articulos-bebe"})
# Bebidas cuyo nombre trae sabores de trago («Café Amaretto Almond», «Dosha Caramel & Whisky»): ahí solo la graduación
# dice alcohol (`_alcohol_by_name`).
FLAVOURED_DRINKS = frozenset({"cafe", "te"})
# Conceptos de especialidad que el nombre reconoce mejor que la categoría: Rappi pone «Kikkoman Salsa de Soya» en
# «Otras salsas» y «Pepero» en «Galletas», y con la categoría mandando quedaban casi vacíos. Solo afinan una categoría
# de comida o bebida sin alcohol (`NAME_REFINES_GROUPS`): un shampoo de wasabi, un tazón para matcha o un licor siguen
# donde los pone su categoría. Son productos de tienda: en un menú no cuentan (un roll en panko sigue siendo sushi).
NAME_REFINES_CONCEPTS = frozenset({"despensa-asiatica", "snacks-asiaticos", "bebidas-asiaticas"})
NAME_REFINES_GROUPS = frozenset({"bebidas", "snacks", "dulces", "despensa", "frescos", "comida"})
# La categoría «Cigarrillos» de las tabaquerías de Rappi Mall trae también vapers, líquidos y papelillos. Dentro de
# ella (y solo ahí: «Cereal Puffs» no es un vaper) estas palabras del nombre deciden el concepto.
TOBACCONIST = KeywordMatcher(
    [
        *(("vapeo", kw) for kw in ("puff", "puffs", "e-liquid", "eliquid", "vape", "vaper", "vaporizador", "pod")),
        *(("vapeo", kw) for kw in ("sales de nicotina", "nic salt", "desechable")),
        *(("accesorios-fumador", kw) for kw in ("wrap", "blunt", "papelillo", "papel", "filtro", "boquilla")),
        *(("accesorios-fumador", kw) for kw in ("tabaquera", "grinder", "moledor", "cenicero", "encendedor", "pipa")),
    ]
)


@dataclass(frozen=True)
class MappedName:
    concept_id: str
    method: str
    confidence: float
    model_version: str | None = None


@dataclass(frozen=True)
class Assignment:
    entity_type: str
    entity_id: str
    concept_id: str
    method: str
    confidence: float
    model_version: str | None
    source: str
    # El concepto de la categoría que el nombre afinó (NAME_REFINES_CONCEPTS): el kNN lo respeta ante vecinas de comida.
    # Solo vive durante `rappi-ia concepts`; no se guarda en la base.
    refines: str | None = None


def concept_matcher(taxonomy: Taxonomy, for_queries: bool = False) -> "KeywordMatcher | QueryMatcher":
    """`for_queries`: para entender consultas, no para asignar productos. Suma el nombre de los sensibles y sus
    `query_keywords`: «necesito medicamentos» pide medicamentos aunque «Dosificador de medicamentos» no sea uno. Sin
    `for_queries` suma las `product_keywords`: «panko» nombra un producto del súper; en una consulta pide un roll."""
    entries = [
        (c.id, kw)
        for c in taxonomy.concepts.values()
        for kw in (
            *_name_keyword(c, for_queries),
            *c.keywords,
            *(c.query_keywords if for_queries else c.product_keywords),
        )
    ]
    avoid = [(c.id, word) for c in taxonomy.concepts.values() for word in c.avoid]
    if not for_queries:
        return KeywordMatcher(entries, avoid)
    alone = [(c.id, kw) for c in taxonomy.concepts.values() for kw in _query_only_words(c)]
    return QueryMatcher(KeywordMatcher((e for e in entries if e not in alone), avoid), KeywordMatcher(alone))


# Acompañan un pedido sin nombrar otra cosa («venden los medicamentos», «algún lubricante barato»).
_NOT_CONTENT = FILLER_WORDS | {
    *("el", "la", "los", "las", "de", "del", "y", "o"),
    *("algo", "algun", "alguna", "algunos", "algunas"),
    *("vende", "venden"),
    *("barato", "barata", "baratos", "baratas"),
}


class QueryMatcher:
    """Las palabras sueltas que solo sirven para pedir un sensible («medicamentos», «lubricante») cuentan solo si son
    todo el pedido, sin contar saludo, cortesía, verbos de pedido ni artículos. Con otras palabras son un complemento
    («pastillero para medicamentos», «lubricante wd-40») y el foco en el sensible ocultaba lo pedido."""

    def __init__(self, matcher: KeywordMatcher, alone: KeywordMatcher):
        self._matcher = matcher
        self._alone = alone

    def matches(self, text: str) -> list[Match]:
        found = self._matcher.matches(text)
        words = tokens(text)
        content = [i for i, word in enumerate(words) if word not in _NOT_CONTENT]
        if found or len(content) != 1:
            return found
        match = self._alone.best(words[content[0]])
        return [replace(match, position=content[0])] if match else []

    def best(self, text: str) -> Match | None:
        found = self.matches(text)
        return found[0] if found else None


def _query_only_words(concept: Concept) -> list[str]:
    """Palabras sueltas que no asignan productos y sirven para pedirlo: el nombre de un sensible de una palabra y sus
    `query_keywords` de una palabra («lubricante»; «lubricante ocular» es una frase y calza en cualquier parte)."""
    name = [] if _name_keyword(concept, for_queries=False) else [concept.name]
    return [kw for kw in (*name, *concept.query_keywords) if len(tokens(kw)) == 1]


def _name_keyword(concept: Concept, for_queries: bool) -> tuple[str, ...]:
    """El nombre del concepto también es keyword, salvo al asignar el de un sensible de una sola palabra:
    «Dosificador de medicamentos» no es un medicamento."""
    if concept.sensitive and len(tokens(concept.name)) == 1 and not for_queries:
        return ()
    return (concept.name,)


def assign_catalog_item(
    item_id: str, name: str, category: str | None, category_map: dict[str, MappedName], matcher: KeywordMatcher
) -> Assignment | None:
    mapped = category_map.get(_key(category)) if category else None
    rule = _from_rule("catalog_item", item_id, name, matcher)
    if (
        mapped
        and mapped.concept_id in _drink_concepts()
        and (alcohol := _alcohol_by_name(item_id, name, mapped, matcher))
    ):
        return alcohol
    refine = _refining_rule(item_id, name, matcher, rule)
    if refine and mapped and mapped.concept_id in refinable_by_name():
        return replace(refine, refines=mapped.concept_id)
    # Guardia simétrica: un nombre sensible o de bebé manda sobre una categoría común (un lubricante en «Agua
    # saborizada», una mamadera en «Frutos secos y semillas»).
    guarded_name = (
        rule is not None
        and mapped is not None
        and (keeps_sensitive(rule.concept_id, mapped.concept_id) or _baby_over(rule.concept_id, mapped.concept_id))
        and mapped.concept_id not in _category_always_wins()
    )
    if mapped and mapped.confidence >= MIN_MAP_CONFIDENCE and not guarded_name:
        split = TOBACCONIST.best(name) if mapped.concept_id == "cigarrillos" else None
        if split:
            return Assignment(
                "catalog_item", item_id, split.target, "regla", RULE_CONFIDENCE, None, f"nombre:{split.keyword}"
            )
        return _from_map("catalog_item", item_id, mapped, f"categoria:{category}")
    if rule and not (mapped and _category_keeps(mapped.concept_id, rule.concept_id)):
        return rule
    return _from_map("catalog_item", item_id, mapped, f"categoria:{category}") if mapped else None


def _refining_rule(item_id: str, name: str, matcher: KeywordMatcher, rule: Assignment | None) -> Assignment | None:
    """El concepto de especialidad que nombra el producto, aunque otra regla calce antes en el nombre: en «Ramen Muy
    Picante Buldak Original» (categoría «Otras salsas») «ramen» es comida asiática y «buldak», el ramen instantáneo.
    Con la mejor regla a secas ganaba «ramen», que no afina, y el producto quedaba en salsas. Un nombre que dice algo
    sensible, alcohol o bebé en cualquier parte no se afina («Soju Salsa Gochujang», «Salsa Wasabi Sabor Whisky»): no
    pasa a un concepto que el agente ofrece."""
    if rule is None or matcher.best(name, exclude=_not_guarded()) is not None:
        return None
    if rule.concept_id in NAME_REFINES_CONCEPTS:
        return rule
    return _from_rule("catalog_item", item_id, name, matcher, exclude=_not_refining())


# Graduación alcohólica en el nombre («Bauza 35º 750cc + Bebida», «Coc Vin Export Selecto Tropical 8°», «Mistral Ice
# 2.5°», «7°G»). No una temperatura («4°C», «4 ° Celsius»), los grados Brix de un jugo («12° Brix»), un ordinal («2°
# Edición», «1° Básico») ni un número de pieza («N°5»).
ALCOHOL_STRENGTH = re.compile(
    r"(?<![\w.,-])[1-9]\d?(?:[.,]\d+)?\s*[°º]"
    r"(?!\s*(?:c\b|celsius|f\b|fahrenheit|brix|edici|b[aá]sico|medio|semestre|piso|lugar))",
    re.IGNORECASE,
)
# Lo que dice «sin alcohol» en el nombre: ahí una graduación no cuenta («Cerveza 0.0°», «Espumante Sin Alcohol 5°»).
_NO_ALCOHOL = re.compile(r"sin\s+alcohol|(?<![\d.,])0[.,]0(?![\d])", re.IGNORECASE)


def alcohol_strength(name: str) -> str | None:
    """La graduación alcohólica que trae el nombre (`ALCOHOL_STRENGTH`), salvo que diga sin alcohol o 0,0."""
    if _NO_ALCOHOL.search(name):
        return None
    found = ALCOHOL_STRENGTH.search(name)
    return found[0] if found else None


def _alcohol_by_name(item_id: str, name: str, mapped: MappedName, matcher: KeywordMatcher) -> Assignment | None:
    """Un trago en una categoría de bebidas sin alcohol: el nombre manda. En la base real del 14-10-2026 «Mistral Ice
    Energy» estaba en Energizantes, «Johnnie Red 700 Cc Con Bebida» y «Campanario Mango Sour» en Jugos y «Coc Vin 8°»
    en Té listo, sin marca de alcohol de la tienda: el agente los ofrecía como bebida. Por una regla de alcohol en
    cualquier parte del nombre o, sin ella, por su graduación (va a `licores`). En café y té, solo por la graduación."""
    match = None if mapped.concept_id in FLAVOURED_DRINKS else matcher.best(name, exclude=_not_alcohol())
    if match:
        return Assignment(
            "catalog_item", item_id, match.target, "regla", RULE_CONFIDENCE, None, f"nombre:{match.keyword}"
        )
    strength = alcohol_strength(name)
    if strength:
        return Assignment("catalog_item", item_id, "licores", "regla", RULE_CONFIDENCE, None, f"nombre:{strength}")
    return None


def _baby_over(name_concept: str, category_concept: str) -> bool:
    """Si el nombre dice bebé y la categoría, algo que el agente ofrece."""
    concepts = load_taxonomy().concepts
    return concepts[name_concept].parent == "bebe" and category_concept not in guarded_concepts()


def _category_keeps(category_concept: str, name_concept: str) -> bool:
    """Si una categoría dudosa conserva su concepto ante la regla del nombre: la de un sensible ante algo común y la de
    suplementos o bebé ante comida. Un suplemento nombra lo que trae («Oregano Oil 60 Softgels», «Cola De Pavo 500mg 120
    Caps», «Propóleo Miel Spray»): en «Productos naturales» (vitaminas, 0,5) pasaban a condimentos, pollo o untables."""
    return keeps_sensitive(category_concept, name_concept) or (
        category_concept in CATEGORY_KEEPS_FROM_FOOD and name_concept in _food_concepts()
    )


def assign_menu_item(
    item_id: str,
    name: str,
    section: str | None,
    cuisines: list[str],
    section_map: dict[str, MappedName],
    cuisine_map: dict[str, MappedName],
    matcher: KeywordMatcher,
    description: str | None = None,
) -> Assignment | None:
    by_name = _from_rule("menu_item", item_id, name, matcher, exclude=NAME_REFINES_CONCEPTS)
    if by_name and by_name.concept_id in INGREDIENT_CONCEPTS:
        by_name = None
    if by_name and by_name.concept_id in name_wins_in_menus():
        return by_name
    mapped = _from_menu_maps(item_id, section, cuisines, section_map, cuisine_map, CUISINE_MIN_CONFIDENCE)
    if mapped:
        return mapped
    if by_name and by_name.concept_id in _food_concepts():
        return by_name
    by_section = _from_section_name(item_id, section, matcher, name, description or "")
    if by_section or by_name is None:
        return by_section
    # Un nombre que no es comida («Aros de Calamar» → joyería) en un local de cocina conocida: la cocina, aunque sea
    # una pista dudosa, acierta más que la palabra suelta.
    return _from_menu_maps(item_id, None, cuisines, {}, cuisine_map, MIN_MAP_CONFIDENCE) or by_name


def _from_section_name(
    item_id: str, section: str | None, matcher: KeywordMatcher, name: str = "", description: str = ""
) -> Assignment | None:
    """Una sección sin mapeo que nombra un plato («Empanadas de Horno», «Pizzas Familiares») dice qué son sus platos.
    Salvo en una sección que dice alcohol con una palabra que también es comida (`_ambiguous_alcohol`), para un plato
    que es comida sólida y no dice alcohol (`_solid_food`): «Queso Brie» en «Aperitivo» no es un licor. Lo demás de esas
    secciones sigue con su alcohol: traen cócteles que no dicen serlo («Primavera», «Bitter Batido») y que solo el
    concepto protege de las ofertas, porque la guardia de secciones no ve «Aperitivos»."""
    match = matcher.best(section, NAME_REFINES_CONCEPTS) if section else None
    if match is None or match.target not in _food_concepts() or match.target in INGREDIENT_CONCEPTS:
        return None
    if _ambiguous_alcohol(section, match, matcher) and _solid_food(name, description, matcher):
        return None
    return Assignment("menu_item", item_id, match.target, "regla", RULE_CONFIDENCE, None, f"{SECTION_NAME}{section}")


def _ambiguous_alcohol(section: str, match: Match, matcher: KeywordMatcher) -> bool:
    """Si la sección dice alcohol solo por una palabra que también es comida (`AMBIGUOUS_SECTION_WORDS`): nada más en
    ella dice bebida (`_says_drink`). «Aperitivos & Tragos», «Aperitivos y Whisky» y «Aperitivo Spritz» son de
    tragos."""
    return load_taxonomy().concepts[match.target].parent == "alcohol" and not _says_drink(section, matcher)


def _solid_food(name: str, description: str, matcher: KeywordMatcher) -> bool:
    """Si el nombre del plato dice comida sólida (`SOLID_FOOD_CONCEPTS`: «Queso», «Chorizo», «Papas») y ni el nombre ni
    la descripción dicen que es una bebida (`_says_drink`). «Pepino Tonic» es un trago."""
    found = matcher.best(name)
    return (
        found is not None
        and found.target in SOLID_FOOD_CONCEPTS
        and not any(_says_drink(text, matcher) for text in (name, description))
    )


def _says_drink(text: str, matcher: KeywordMatcher) -> bool:
    """Una keyword de alcohol de la taxonomía, una palabra de alcohol de los nombres o de las secciones de las guardias
    de menús («sour», «michelada», «trago», «alcohólica»), una graduación, una palabra de bebida (`DRINK_WORDS`) o un
    volumen (`LIQUID_VOLUME`). Sin las palabras ambiguas (`AMBIGUOUS_SECTION_WORDS`): «Emp. queso horno cocktail» es
    una empanada de fiesta e «ideal como aperitivo» describe también comida."""
    words = " ".join(word for word in tokens(text) if word not in AMBIGUOUS_SECTION_WORDS)
    return bool(
        matcher.best(words, exclude=_not_alcohol())
        or DRINK_WORDS.best(words)
        or LIQUID_VOLUME.search(text)
        or alcohol_strength(text)
        or alcohol_in_name("menu_item", text)
        or alcohol_section(text)
    )


@cache
def refinable_by_name() -> frozenset[str]:
    """Lo que un concepto de especialidad puede afinar por el nombre: comida y bebida, nunca alcohol ni un sensible."""
    return frozenset(
        c.id
        for c in load_taxonomy().concepts.values()
        if c.parent in NAME_REFINES_GROUPS and not (c.sensitive or c.age_restricted)
    )


@cache
def _category_always_wins() -> frozenset[str]:
    return frozenset(c.id for c in load_taxonomy().concepts.values() if c.parent in CATEGORY_WINS_GROUPS)


@cache
def _drink_concepts() -> frozenset[str]:
    return frozenset(c.id for c in load_taxonomy().concepts.values() if c.parent == "bebidas")


@cache
def _not_refining() -> frozenset[str]:
    return frozenset(load_taxonomy().concepts) - NAME_REFINES_CONCEPTS


@cache
def _not_guarded() -> frozenset[str]:
    return frozenset(load_taxonomy().concepts) - guarded_concepts()


@cache
def _not_alcohol() -> frozenset[str]:
    return frozenset(c.id for c in load_taxonomy().concepts.values() if c.parent != "alcohol")


@cache
def _food_concepts() -> frozenset[str]:
    return frozenset(c.id for c in load_taxonomy().concepts.values() if c.parent in MENU_GROUPS | {"frescos"})


@cache
def dish_name_concepts() -> frozenset[str]:
    """Conceptos que el nombre de un plato fija aunque los vecinos digan otra cosa: un plato preparado («Pollo asado
    + Bebida») o su proteína («Pescado frito»). Un sabor («Pistacho» en una heladería) no: ahí los vecinos corrigen."""
    return frozenset(c.id for c in load_taxonomy().concepts.values() if c.parent == "comida") | PROTEIN_CONCEPTS


@cache
def name_wins_in_menus() -> frozenset[str]:
    """Conceptos que el nombre de un plato impone sobre la sección: lo que vende un restaurante, la proteína del plato
    («Combo pollo para 1» no es sushi aunque la sección «Combos» lo diga) y los sensibles."""
    return (
        frozenset(c.id for c in load_taxonomy().concepts.values() if c.parent in MENU_GROUPS or c.sensitive)
        | PROTEIN_CONCEPTS
    )


def _from_menu_maps(
    item_id: str,
    section: str | None,
    cuisines: list[str],
    section_map: dict[str, MappedName],
    cuisine_map: dict[str, MappedName],
    cuisine_min: float,
) -> Assignment | None:
    mapped = section_map.get(_key(section)) if section else None
    if mapped and mapped.confidence >= MIN_MAP_CONFIDENCE:
        return _from_map("menu_item", item_id, mapped, f"seccion:{section}")
    # La más confiable de las cocinas del local (llegan por orden alfabético: en un local «Asiática, Sushi» ganaba
    # Asiática y sus rolls quedaban como comida asiática); a igual confianza, la primera.
    found = [(m, c) for c in cuisines if (m := cuisine_map.get(_key(c))) and m.confidence >= cuisine_min]
    if found:
        mapped, cuisine = max(found, key=lambda pair: pair[0].confidence)
        # La cocina solo dice qué tipo de local es: menos confianza que la sección o el nombre.
        return _from_map("menu_item", item_id, mapped, f"cocina:{cuisine}", factor=0.8)
    return None


def _key(name: str | None) -> str:
    return (name or "").strip().lower()


def _from_map(entity_type: str, entity_id: str, mapped: MappedName, source: str, factor: float = 1.0) -> Assignment:
    return Assignment(
        entity_type,
        entity_id,
        mapped.concept_id,
        mapped.method,
        round(mapped.confidence * factor, 3),
        mapped.model_version,
        source,
    )


def _from_rule(
    entity_type: str, entity_id: str, name: str, matcher: KeywordMatcher, exclude: frozenset[str] = frozenset()
) -> Assignment | None:
    match = matcher.best(name, exclude)
    if match is None:
        return None
    return Assignment(entity_type, entity_id, match.target, "regla", RULE_CONFIDENCE, None, f"nombre:{match.keyword}")
