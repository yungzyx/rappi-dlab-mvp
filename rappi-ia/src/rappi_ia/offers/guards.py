"""Guardias de ofertas: lo que el agente nunca propone por su cuenta.

Una oferta es todo lo que el agente muestra sin que se lo hayan pedido: la sugerencia cruzada de /agent/ask y de
/recommendations (`suggest_complement`), los ganchos de servicios y los momentos de /agent/offer. Nunca es:
- alcohol (Licores y todo concepto +18), ni tabaco, vapeo o bienestar sexual;
- salud o farmacia: el grupo «Farmacia y cuidado personal» entero (medicamentos, vitaminas, higiene, dermocosmética);
- bebé (también un producto del catálogo cuyo nombre lo dice, aunque su concepto sea corriente);
- un concepto sensible;
- un producto de las verticales Farmacia y Licores, ni de una tienda que Rappi rotula Farmacia, Sex shop o Smoking
  shop (aunque esté en otra vertical).

Quien lo pide por su nombre (una búsqueda, una pregunta al agente) sí lo recibe: las guardias son de lo que se ofrece,
no de lo que se encuentra. La única excepción es el kit de una ocasión que la persona eligió (`plan` de /agent/offer):
puede traer el alcohol de esa ocasión, con su marca +18 (`is_plannable`), pero nunca lo sensible, farmacia, bebé
ni salud.
Esto reemplaza a docs/diseno-ia.md regla 6b, que permitía el alcohol como complemento con +18.
Las reglas viven solo aquí; las consultas de productos las aplican con `search_products(..., offer=True)`.
"""

from ..concepts.matcher import KeywordMatcher
from ..concepts.taxonomy import Concept, Occasion, load_taxonomy
from ..text import tokens

OFFER_BLOCKED_GROUPS = ("bebe", "salud")  # grupos de taxonomy.toml; el alcohol y el tabaco se bloquean por sus marcas
# Parecida a catalog.stores.NOT_PUSHED_VERTICALS (lo que la Home no empuja), pero con otro motivo y otra lista.
OFFER_BLOCKED_VERTICALS = ("farmacia", "licores")
ALCOHOL_VERTICALS = ("licores",)  # las bloqueadas de las que el alcohol de un kit elegido sí puede salir
DRINK_GROUP = "bebidas"  # el grupo de taxonomy.toml cuyos conceptos no dicen si un trago lleva alcohol
NOT_PLANNABLE_OCCASIONS = ("guagua", "enfermo")  # bebé y salud: ni siquiera como kit que la persona pide
# Palabras de un nombre que dicen alcohol aunque la tienda no lo marque: las marcas de la tienda (`is_alcoholic`,
# `age_restricted`) y la categoría pueden estar mal. En la base real del 14-10-2026, «Soju Uva Verde 13.0» venía en
# «Frutas» sin ninguna marca, y una cerveza, un ron y un vino tinto quedaban en frutas, decoración y útiles. Palabra
# entera, con su plural: «ron» no está en «ronda» ni «gin» en «ginger». Es la lista de los productos del catálogo; los
# platos tienen la suya (abajo). Bloquea también lo que solo nombra el alcohol (vinagre de vino, copas de vino,
# galletas Vino): de una oferta que nadie pidió, sobra; quien lo busca por su nombre lo sigue encontrando.
ALCOHOL_NAME_WORDS = frozenset(
    {
        *("soju", "makgeolli", "umeshu", "sake", "cerveza", "vino", "whisky", "pisco", "ron", "vodka", "gin"),
        *("tequila", "licor", "aperitivo", "espumante", "champagne", "sidra"),
    }
)
_ALCOHOL_NAMES = KeywordMatcher(("alcohol", word) for word in ALCOHOL_NAME_WORDS)
# Lo mismo en los platos de un menú, que no traen ninguna marca de alcohol: en la base real del 14-10-2026 cinco
# «Soju …» venían con concepto `asiatica` y dos «Sangría» con `gaseosas`. Lista propia porque en un menú «sake» es
# salmón («Sake Roll», más de 2.400 platos de sushi) y los tragos tienen otros nombres (schop, chela, piscola,
# terremoto, sour, las cervezas por su marca y los vinos por su cepa). También bloquea platos que solo nombran el
# alcohol («bife al vino», «pasas al ron», «Churrasco Kunstmann», un helado «Borgoña»): en una oferta, sobran; la
# búsqueda y la pregunta no cambian. «austral» no está: es sobre todo merluza austral (47 platos), y la cerveza sale
# por su sección. «mimosa» tampoco: en la base real del 14-10-2026 las dos que hay son sin alcohol (un jugo y una de
# «Sin Alcohol»). Desde «tom collins», los cócteles que en la base real del 22-10-2026 se llamaban así sin otra palabra
# de alcohol («Vaina», «Caipiroska» en «Bebidas», «Botella de Ramazzotti»): los vecinos del kNN pueden sacar un plato
# del alcohol y aquí lo sigue bloqueando el nombre. Desde «absolut», los de la base real del 24-10-2026: «ABSOLUTE
# PEAR» («Corto con pera y bebida con hielo») tenía concepto sandwiches, y «Jarra de Ramazzoti» venía mal escrita.
MENU_ALCOHOL_NAME_WORDS = frozenset(
    {
        *("soju", "sangria", "michelada", "cerveza", "schop", "shop", "chela", "chelada", "vino", "pisco", "piscola"),
        *("vodka", "whisky", "whiskey", "tequila", "ron", "gin", "mojito", "margarita", "terremoto", "spritz"),
        *("makgeolli", "makgeoli", "umeshu", "licor", "espumante", "champagne", "champana", "sidra", "negroni"),
        *("caipirinha", "caipirina", "daiquiri", "sour", "borgona", "pina colada"),
        *("corona", "escudo", "guinness", "kunstmann", "heineken", "cristal", "stella artois"),
        *("budweiser", "cusquena"),
        *("cabernet", "carmenere", "merlot", "chardonnay", "sauvignon", "syrah", "malbec", "pinot", "cono sur"),
        *("tom collins", "vaina", "algarrobina", "daikiri", "caipiroska", "bloody mary", "cuba libre", "kir royal"),
        *("ruso blanco", "ruso negro", "cosmopolitan", "clavo oxidado", "ramazzotti"),
        *("absolut", "absolute", "ramazzoti"),
    }
)
# Palabras de trago que también nombran comida: (lo que en el nombre dice que es comida, conceptos de plato que lo
# dicen). «Pizza Margarita» y la «Margarita Familiar» de una pizzería (concepto pizza) son pizzas; «Sour Cream», «Sweet
# and Sour Roll», la «Sopa Hot Sour» y un roll «Tako Sour» no son un pisco sour; «Hamburguesa la Corona» y las
# quesadillas «Corona Sacra» no son la cerveza; Negroni es también un salame y «cristal», un latte. Una piña colada es
# también un jugo, un batido, un té de burbujas o un helado (10 de las 27 de la base real). La vaina es también la de
# los porotos, la algarrobina un jarabe («Tres Leches Algarrobina») y «Combo Eros Ramazzotti», un combo de paninos: solo
# los libra la frase, no el concepto (un trago de algarrobina que el kNN pone en postres sigue siendo un trago).
_MENU_FOOD_SENSES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "margarita": (("pizza", "pizzeta"), ("pizza",)),
    "sour": (("cream", "sweet", "hot", "roll", "papas"), ("salsas", "sushi", "pescados-mariscos", "sopas")),
    "corona": (("la corona", "sacra"), ()),
    "negroni": (("salame",), ()),
    "cristal": (("latte", "fideo"), ()),
    "pina colada": (
        ("sin alcohol", "virgin", "jugo", "smoothie", "shake", "milkshake", "tea", "helado"),
        ("jugos", "helados"),
    ),
    "vaina": (("edamame", "en vaina", "con vaina", "sin vaina"), ()),
    "algarrobina": (("tres leches", "torta", "helado", "postre"), ()),
    "ramazzotti": (("eros",), ()),
    "ramazzoti": (("eros",), ()),
}
_MENU_ALCOHOL_NAMES = KeywordMatcher(
    ((word if word in _MENU_FOOD_SENSES else "alcohol", word) for word in MENU_ALCOHOL_NAME_WORDS),
    avoid=[(word, phrase) for word, (phrases, _) in _MENU_FOOD_SENSES.items() for phrase in phrases],
)
# Secciones de un menú que son de tragos («Cervezas», «Vinos y Piscos», «Coctelería», «Bebidas Alcohólicas»): ningún
# plato de ahí se ofrece, aunque su nombre no diga alcohol («Misiones de Rengo», «Sake Dry» en «Cervezas Japonesas y
# Sake»). Una sección mezclada («Bebidas y Cervezas») se salta entera. «Cóctel» en singular es también comida para
# picar en Chile («Cocktail», «Empanadas de Cóctel»): solo cuentan «cócteles», «cocktails» y «coctelería» (también
# «cockteleria»). Nada de «chop» (19 «Chop Suey»). «Sin alcohol», «no alcohólicas» o «mocktails» la libran.
MENU_ALCOHOL_SECTION_WORDS = frozenset(
    {
        *("alcohol", "alcoholica", "alcoholico", "licor", "vino", "cerveza", "trago", "cocteles", "cocktails"),
        *("cocteleria", "cockteleria", "pisco", "espumante", "sour"),
    }
)
_SOBER_SECTION = (
    *("sin alcohol", "no alcoholica", "no alcoholicas", "no alcoholico", "no alcoholicos", "not alcohol"),
    *("mocktail", "sour cream", "sweet and sour"),
)
_MENU_ALCOHOL_SECTIONS = KeywordMatcher(
    (("alcohol", word) for word in MENU_ALCOHOL_SECTION_WORDS), avoid=[("alcohol", p) for p in _SOBER_SECTION]
)
# La descripción de un plato sin concepto o con uno de bebida: en la base real del 24-10-2026, 22 tragos («Electric
# Lemonade Deli»: «Vodka ron gin blue curacao…», en «Barra Barbazul»; «HAVANA ESPECIAL»: «Corto + Bebida», en
# «Combinados» junto a platos peruanos) y 22 combos o packs con su cerveza, su vino o su botella de pisco o fernet no
# tenían concepto ni decían alcohol en el nombre ni en la sección, y 9 tragos tenían concepto de bebida («Gautama
# Jack», gaseosas: «Ron havana dorado…»; un café irlandés). Sin concepto, la descripción es lo único que dice qué es el
# plato, y un concepto de bebida no dice si lleva alcohol: la que nombra alcohol no se ofrece, aunque sea comida
# cocinada con vino o ron (risottos, canelés, cannoli al marsala) o algo sin alcohol (un café con jarabe de amaretto,
# una piña colada sin alcohol). Con un concepto de comida no cuenta: unos 1.100 platos ofrecibles así la nombran, casi
# todos comida. Las palabras: las de los nombres de platos sin la vaina ni la algarrobina (en una descripción son
# porotos y un jarabe), más tragos, destilados, licores y sus marcas, el cóctel y el corto. Una descripción es larga:
# solo se libra la palabra que queda dentro de una frase de comida («cóctel de camarones», «empanaditas cóctel», «sour
# cream», «pizza margarita», «espresso corto», «chop suey»), no las demás («Empanadas cóctel x12 + 2 cócteles») ni por
# una palabra de comida en otra parte («tabla de empanadas + 2 cócteles»). «Sin alcohol» tampoco la libra («Mojito con
# o sin alcohol»), y «alcohol» solo no cuenta: casi siempre es «sin alcohol». Sin apóstrofes («Gordon's»).
MENU_ALCOHOL_DESCRIPTION_WORDS = frozenset(
    {
        *(MENU_ALCOHOL_NAME_WORDS - {"vaina", "algarrobina"}),
        *("trago", "alcoholica", "alcoholico", "con alcohol", "contiene alcohol", "chilcano", "whiskies", "prosecco"),
        *("mezcal", "fernet", "jagermeister", "jager", "jagerbomb", "kahlua", "triple sec", "havana"),
        *("alto del carmen", "mistral", "capel", "control c", "ginebra", "aguardiente", "destilado"),
        *("captain morgan", "flor de cana"),
        *("aperol", "campari", "vermouth", "vermut", "cognac", "conac", "brandy", "bourbon", "baileys", "amaretto"),
        *("cachaca", "smirnoff", "bacardi", "jack daniel", "jack daniels", "johnnie walker", "johnny walker", "chivas"),
        *("jameson", "ballantines", "tanqueray", "beefeater", "hendricks", "gordons", "malibu", "stolichnaya"),
        *("royal guard", "kross", "torobayo", "becker", "lager", "pilsen", "ipa", "chop", "tinto", "navegado", "clery"),
        *("calimocho", "kalimotxo", "pichuncho", "gintonic", "roncola"),
        *("pinas coladas", "cubas libres", "rusos blancos", "rusos negros", "bloody marys", "clavos oxidados"),
        *("stellas artois", "havanna"),
        *("coctel", "cocktail", "corto"),
    }
)
_MENU_ALCOHOL_DESCRIPTIONS = KeywordMatcher(("alcohol", word) for word in MENU_ALCOHOL_DESCRIPTION_WORDS)
_DESCRIPTION_FOOD_PHRASES = sorted(
    (
        tuple(tokens(phrase))
        for phrase in (
            *("coctel de camaron", "coctel de camarones", "cocktail de camarones", "coctel de mariscos"),
            *("tipo coctel", "tamano coctel", "empanadas coctel", "empanaditas coctel", "empanadas de queso coctel"),
            *("empanaditas de queso coctel", "panes coctel", "sopaipillas coctel", "choclito coctel", "queso coctel"),
            *("sour cream", "crema sour", "sweet and sour", "sweet sour", "hot and sour", "hot sour"),
            *("pizza margarita", "pizzeta margarita", "pesto margarita", "salsa margarita"),
            *("espresso corto", "expreso corto", "cafe corto", "corto de cafe", "cafe tinto", "chop suey", "chop suei"),
            *("fideos de cristal", "fideo cristal", "fideos cristal", "salame negroni"),
            *("eros ramazzotti", "eros ramazzoti"),
        )
    ),
    key=len,
    reverse=True,  # la frase más larga primero
)


# Sin concepto, también la sección del menú: en la base real del 24-10-2026, cervezas («Erdinger Dunkel», «Gulden
# Draak») en «Botellas» y «Botellas 300 cc», y vinos con el nombre abreviado o mal escrito («Cab.Sauvig CASAS
# PATRONALES», «Chardonay AROMO») en «Tinto» y «Blanco», sin nada más que diga alcohol. Con concepto estas secciones
# no deciden: ahí también hay gaseosas («Botellas 1.5 Lts») y platos peruanos («Combinados»).
UNKNOWN_DISH_SECTION_WORDS = frozenset(
    {"botella", "tinto", "blanco", "gin", "destilados", "spritz", "combinados", "cock ta ils"}
)
_UNKNOWN_DISH_SECTIONS = KeywordMatcher(
    (("alcohol", word) for word in UNKNOWN_DISH_SECTION_WORDS),
    avoid=[("alcohol", phrase) for phrase in ("te blanco", "chocolate blanco", "arroz blanco")],
)


def _without_food_phrases(description: str) -> str:
    """La descripción en palabras normalizadas y sin apóstrofes, sin las frases de comida (`_DESCRIPTION_FOOD_PHRASES`):
    lo que queda es lo que puede nombrar un trago."""
    words, kept, i = tokens(description.replace("'", "").replace("’", "")), [], 0
    while i < len(words):
        phrase = next((p for p in _DESCRIPTION_FOOD_PHRASES if tuple(words[i : i + len(p)]) == p), None)
        if phrase:
            i += len(phrase)
        else:
            kept.append(words[i])
            i += 1
    return " ".join(kept)


# Palabras de un nombre del catálogo que dicen bebé aunque el concepto no lo diga: en la base real del 14-10-2026 la
# ropa, los juguetes, las colonias y el detergente de bebé venían como ropa, juguetes-infantiles, fragancias o limpieza,
# y «vertical por probar» partía en Mall con un «Fisher-price Juguete Para Bebés». Palabra entera, con su plural.
# «infantil» no está: es de niños (cascos, libros, medias de fútbol), no de bebé.
BABY_NAME_WORDS = frozenset({"bebe", "guagua"})
_BABY_NAMES = KeywordMatcher(("bebe", word) for word in BABY_NAME_WORDS)


def is_plannable(concept: Concept) -> bool:
    """Si el concepto puede ir en el kit de una ocasión que la persona eligió: todo menos lo sensible, bebé y salud (el
    alcohol sí, con su marca +18)."""
    group = concept.parent or concept.id
    return not (concept.sensitive or group in OFFER_BLOCKED_GROUPS)


def is_offerable(concept: Concept) -> bool:
    """Si el agente puede proponer este concepto por su cuenta."""
    return is_plannable(concept) and not concept.age_restricted


def plannable_vertical(vertical: str, concept: Concept) -> bool:
    """Si el concepto de un kit puede salir de esta vertical: de las que el agente propone y, el alcohol, también de
    Licores. Farmacia nunca."""
    return offerable_vertical(vertical) or (concept.age_restricted and vertical in ALCOHOL_VERTICALS)


def plannable_occasion(occasion: Occasion) -> bool:
    """Si el agente arma el kit de esta ocasión (y la lista en la Home): no las de bebé ni salud, ni una sin concepto
    que pueda ir en el kit, ni una que solo sirve para entender preguntas (`plan = false`)."""
    concepts = load_taxonomy().concepts
    return (
        occasion.plan
        and occasion.id not in NOT_PLANNABLE_OCCASIONS
        and any(is_plannable(concepts[c]) for c in occasion.concepts)
    )


def alcohol_in_name(entity_type: str, name: str, concept_id: str | None = None) -> bool:
    """Si el nombre de un producto del catálogo (`ALCOHOL_NAME_WORDS`) o de un plato (`MENU_ALCOHOL_NAME_WORDS`) dice
    alcohol. `concept_id`: el del plato, si se sabe (una «Margarita» con concepto pizza es una pizza)."""
    if entity_type == "catalog_item":
        return _ALCOHOL_NAMES.best(name) is not None
    if entity_type != "menu_item":
        return False
    return any(
        m.target == "alcohol" or concept_id not in _MENU_FOOD_SENSES[m.target][1]
        for m in _MENU_ALCOHOL_NAMES.matches(name)
    )


def baby_in_name(entity_type: str, name: str) -> bool:
    """Si el nombre de un producto del catálogo dice bebé (`BABY_NAME_WORDS`). Los platos, no."""
    return entity_type == "catalog_item" and _BABY_NAMES.best(name) is not None


def alcohol_section(section: str | None) -> bool:
    """Si la sección del menú donde está un plato es de tragos (`MENU_ALCOHOL_SECTION_WORDS`)."""
    return bool(section) and _MENU_ALCOHOL_SECTIONS.best(section) is not None


def alcohol_in_description(description: str | None, concept_id: str | None, section: str | None = None) -> bool:
    """Si la descripción de un plato sin concepto o con uno de bebida nombra alcohol (`MENU_ALCOHOL_DESCRIPTION_WORDS`)
    o, sin concepto, su sección es de botellas, vinos o destilados (`UNKNOWN_DISH_SECTION_WORDS`). Con un concepto de
    comida, nunca: lo que es el plato lo dice su concepto."""
    concept = load_taxonomy().concepts.get(concept_id) if concept_id else None
    if concept is not None and concept.parent != DRINK_GROUP:  # un concepto que ya no existe, como sin concepto
        return False
    if concept is None and section and _UNKNOWN_DISH_SECTIONS.best(section) is not None:
        return True
    return bool(description) and _MENU_ALCOHOL_DESCRIPTIONS.best(_without_food_phrases(description)) is not None


def offerable_vertical(vertical: str) -> bool:
    """Si el agente puede proponer productos de esta vertical por su cuenta."""
    return vertical not in OFFER_BLOCKED_VERTICALS


def unofferable_subverticals() -> list[str]:
    """Los subverticales de tienda (store_verticals.subvertical) de los que el agente no propone, sea cual sea su
    vertical: los mismos que la Home no empuja (`catalog.stores.NOT_PUSHED_SUBVERTICALS`)."""
    # Import diferido: catalog.stores importa agent.tools, y agent.tools importa este módulo.
    from ..catalog.stores import NOT_PUSHED_SUBVERTICALS

    return list(NOT_PUSHED_SUBVERTICALS)
