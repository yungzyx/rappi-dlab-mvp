"""Reglas por palabra clave. Incluye los errores que tenía el cerebro por reglas del prototipo (substrings)."""

import pytest

from rappi_ia.concepts.assign import concept_matcher
from rappi_ia.concepts.matcher import KeywordMatcher
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.text import normalize, tokens


def test_normalize_removes_accents_and_enie():
    assert normalize("Pañales Talla G, 40 u.") == "panales talla g 40 u"
    assert tokens("¿Café  con LECHE?") == ["cafe", "con", "leche"]


@pytest.fixture(scope="module")
def matcher():
    return concept_matcher(load_taxonomy())


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Galletas Tritón Chocolate", "galletas"),  # plural
        ("Combo hamburguesa + bebida", "hamburguesa"),  # a igual especificidad gana la primera
        ("Fanta Naranja 1,5 L", "gaseosas"),  # la marca gana a "naranja"
        ("Papas fritas corte americano", "snacks-salados"),  # frase más específica que "papa"
        ("comida para mi perro", "alimento-perro"),
        ("quiero whisky", "whisky"),
        ("hola, quiero sushi", "sushi"),
        ("Pizza pepperoni familiar", "pizza"),
        ("Pañal Huggies etapa 3", "panales"),
        ("panales talla g", "panales"),  # sin ñ
    ],
)
def test_best_concept(matcher, text, expected):
    assert matcher.best(text).target == expected


@pytest.mark.parametrize("text", ["bebestibles", "comercial", "escena", "equivale"])
def test_no_substring_false_positives(matcher, text):
    """El prototipo confundía 'bebestibles' con bebé y 'equivale' con 'vale'."""
    match = matcher.best(text)
    assert match is None or match.target not in {"articulos-bebe", "panales", "alimentacion-bebe"}


def test_multiword_needs_whole_phrase():
    m = KeywordMatcher([("a", "papas fritas"), ("b", "papa")])
    assert m.best("papas fritas").target == "a"
    assert m.best("papas cocidas").target == "b"
    assert m.best("fritas") is None


def test_matches_are_ranked_by_specificity_then_position():
    m = KeywordMatcher([("x", "leche"), ("y", "leche condensada"), ("z", "manjar")])
    found = [match.target for match in m.matches("manjar y leche condensada")]
    assert found == ["y", "z"]  # "leche" queda dentro de "leche condensada"
    assert [x.target for x in m.matches("leche y manjar")] == ["x", "z"]


def test_overlapping_matches_keep_only_the_most_specific():
    m = KeywordMatcher([("snack", "papas fritas"), ("verdura", "papas"), ("cerveza", "cervezas")])
    assert [x.target for x in m.matches("cervezas y papas fritas")] == ["snack", "cerveza"]


def test_avoid_words_block_a_keyword_in_the_same_name_but_not_elsewhere():
    m = KeywordMatcher([("agua", "agua"), ("hogar", "bolsa")], avoid=[("agua", "bolsa"), ("agua", "gas natural")])
    assert m.best("Agua mineral 600 ml").target == "agua"
    assert [x.target for x in m.matches("Bolsa para agua caliente")] == ["hogar"]  # la bolsa sigue siendo bolsa
    assert [x.target for x in m.matches("Bolsas de agua")] == ["hogar"]  # el plural también cuenta
    assert m.best("Agua con gas natural") is None  # una frase de varias palabras bloquea si está completa y seguida
    assert m.best("Agua natural con gas").target == "agua"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Mood Aceite Esencial Roll-On Calma", None),
        ("Sticki Rolls Set Brazalete", None),
        ("California Roll 10 piezas", "sushi"),
        ("Almond Roll", "sushi"),
        ("Hand Roll Salmón", "sushi"),
        ("New york roll", "sushi"),  # «ny» bloquea por palabra entera: «york» no lo contiene
        ("Roll De Canela", None),  # un pastel, no sushi (el 14-10-2026 salía en el Súper y en Chocolaterías)
        ("Sumkha Granol Gluten Free Cinna Roll", None),
        ("Cinnamon Rolls (2 unds)", None),
        ("Sausage roll", None),
        ("Hilos Mulina Ariadna Café 1728", None),
        ("Botón Nacar Figuras Café Flor", None),
        ("Café Molido 250 g", "cafe"),
        ("Bolsa Para Agua Polar", None),
        ("Dispensador Para Agua", None),
        ("Agua Mineral Sin Gas 600 cc", "agua"),
        ("Té Polvo Leche Real", None),  # antes caía en lácteos por «leche»
        ("Nesquik Saborizante Para Leche", None),
        ("Leche Entera 1 L", "lacteos"),
        ("Vilay Bebida de Coco Natural", None),
        ("Bebida Isotónica 500 ml", "gaseosas"),
        ("Dispensador de Jabón Vidrio", None),
        ("Jabón Líquido Manos 500 ml", "higiene-personal"),
        ("Collar Gato Smart Id Retro", "accesorios-mascota"),
        ("Doco Arnes Perro Athletica Gris", "accesorios-mascota"),
        ("Doco Correa Perro Reflectante Large", "accesorios-mascota"),
        ("Collar Ajustable Para Gatos Casaideas", "accesorios-mascota"),
        ("Set De Arnés Y Correa Azul Marino Para Perros", "accesorios-mascota"),
        ("Alimento Seco Perro Adulto", "alimento-perro"),
        ("Equate Rasuradora Desechable Con Mango Ergonómico", None),  # juicio de precisión del 06-10-2026
        ("Twister Sandía 100 Gr Hilo", None),
        ("Jugo En Polvo Sabor Mango", "jugos"),
        ("Mango Tommy 1 kg", "frutas"),
        ("Crema de Maní Natural 1 kg", "frutos-secos"),
        ("Vilay Bebida de Almendras Sabor Original", "vegano"),
        ("Vilay Bebida Arroz Y Chocolate Fun 200 Cc", "vegano"),
        ("Caja De 6 Moai Sólidos Sin Azúcar", None),
        ("Arroz Grado 1 1 kg", "arroz-legumbres"),
        ("Crema de Zapallo Instantánea", "sopas"),
        ("Comida Para Gatos Adultos Salmón", "alimento-gato"),
    ],
)
def test_known_false_positives_of_name_rules(matcher, text, expected):
    match = matcher.best(text)
    assert (match.target if match else None) == expected


def test_a_hand_cream_is_dermocosmetics_not_soup_or_fruit(matcher):
    assert matcher.best("Crema De Manos Cartera Limon").target == "dermocosmetica"
    assert matcher.best("Crema de Manos Nivea 75 ml").target == "dermocosmetica"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("roll de canela", None),
        ("cinna roll", None),
        ("almond roll", "sushi"),
        ("california roll", "sushi"),
        ("hand roll salmón", "sushi"),
    ],
)
def test_roll_in_a_query_is_sushi_only_when_it_is_sushi(query, expected):
    match = concept_matcher(load_taxonomy(), for_queries=True).best(query)

    assert (match.target if match else None) == expected


@pytest.mark.parametrize(
    "text",
    ["Maxi roll manjar", "NY Roll de Pistacho 9 cm", "Kathi Roll Chicken (1 Piece)", "Rolls de Pepperoni y Queso"],
)
def test_rolls_of_other_cuisines_and_pastry_are_not_sushi(matcher, text):
    """«Roll» solo es sushi si el plato no es un pastel, un wrap ni un pan de pizzería (otro concepto puede calzar)."""
    assert "sushi" not in [m.target for m in matcher.matches(text)]


ASIAN = {"despensa-asiatica", "snacks-asiaticos", "bebidas-asiaticas"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Nombres reales del catálogo (base real, 14-10-2026)
        ("Kikkoman Salsa de Soya", "despensa-asiatica"),
        ("Sakura Salsa Soya Premium Salsera", "despensa-asiatica"),
        ("Tucapel Arroz Sushi Bolsa", "despensa-asiatica"),
        ("Los Granos Arroz Para Sushi", "despensa-asiatica"),
        ("Alga Nori Yumart 10 Uds", "despensa-asiatica"),
        ("Aceite De Sesamo 227ml", "despensa-asiatica"),
        ("Palitos Para Sushi 100 Pares", "despensa-asiatica"),
        ("Gengibre Para Sushi", "despensa-asiatica"),
        ("Buldak Fideo Ramyeon Rosé Bowl", "snacks-asiaticos"),
        ("Chapagetti Fideo", "snacks-asiaticos"),
        ("Pepero Crunchy", "snacks-asiaticos"),
        ("Kai Mochi Helado Mochi Mango", "snacks-asiaticos"),
        ("Maruchan Sopa Instantánea Sabor a Pollo", "snacks-asiaticos"),  # el ramen instantáneo ya no es «sopas»
        ("Ramen Instantáneo Pollo Ajo Nissin 81 Gr", "snacks-asiaticos"),
        ("Brota té Matcha en Polvo", "bebidas-asiaticas"),
        ("Blendy té Verde Matcha Latte", "bebidas-asiaticas"),
        ("Bebida Bubble Tea, Taro", "bebidas-asiaticas"),
        ("Bebida Bubble Tea Milk Tea", "bebidas-asiaticas"),
        ("Té Leche Helado Verano Kirin 500 Ml", "bebidas-asiaticas"),
        ("OKF Bebida de Aloe Vera", "bebidas-asiaticas"),
        ("Bebida Okf Aloe Vera Granada 500 Ml", "bebidas-asiaticas"),
    ],
)
def test_asian_pantry_snacks_and_drinks_by_name(matcher, text, expected):
    assert matcher.best(text).target == expected


@pytest.mark.parametrize(
    "text",
    [
        "Shampoo Líquido Wasabi Shan Kui",
        "Wasabi Shan Kui Shampoo",
        "Acuarela Noris 12 Colores",
        "Staedtler Noris Lápiz Grafito HB",
        "Relx Creator Silkmesh Pod Lychee Burst",
        "Vozol Vapeador Gear Shisha 25000 Passion Fruit Lychee Orange",
        "Vape Matcha Ice 5000 Puffs",
        "Mochila de viaje 40 litros",
        "Margarina Sin Sal 250 g",
        "Lindor Matcha",  # «matcha» a secas sigue siendo té (los matcha latte de las cafeterías)
        "Smart Snack Bolitas Pistacho Matcha",
        "Manare Vinagre de Manzana Con Matcha y Limón Orgánico",
        "Leche de Soya Sin Azúcar 1 L",
        "Crema Corporal Aloe Vera Super Hidratante 240 g",
        "Golden Bebida Aloe Vera Sabor Original",  # sin «okf» ni «bebida de aloe»: queda en su categoría
        "Hubba Bubba Goma de Mascar Bubble Tape",
    ],
)
def test_lookalikes_are_not_asian(matcher, text):
    assert not ASIAN & {m.target for m in matcher.matches(text)}


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("salsa de soya", "despensa-asiatica"),
        ("arroz para sushi", "despensa-asiatica"),
        ("alga nori", "despensa-asiatica"),
        ("buldak", "snacks-asiaticos"),
        ("pepero", "snacks-asiaticos"),
        ("ramen instantáneo", "snacks-asiaticos"),
        ("té matcha", "bebidas-asiaticas"),
        ("milkis", "bebidas-asiaticas"),
        ("sushi", "sushi"),  # lo de siempre no cambia
        ("ramen", "asiatica"),
        ("salsa de tomate", "salsas"),
    ],
)
def test_asian_concepts_in_a_query(query, expected):
    assert concept_matcher(load_taxonomy(), for_queries=True).best(query).target == expected


@pytest.mark.parametrize("query", ["shampoo wasabi", "mochila", "lápices noris", "vape lychee"])
def test_lookalike_queries_are_not_asian(query):
    found = concept_matcher(load_taxonomy(), for_queries=True).matches(query)
    assert not ASIAN & {m.target for m in found}


# Lo que el catálogo llamaba antes de los conceptos asiáticos (taxonomía 2026-10-04): son platos y bebidas de
# restaurante, y los conceptos asiáticos no se piden hechos (`prepared`), así que no compiten en restaurantes.
DISH_QUERIES = [
    ("miso ramen", ["asiatica"]),
    ("shoyu ramen", ["asiatica"]),
    ("kimchi ramen", ["asiatica"]),
    ("panko roll", ["sushi"]),
    ("wasabi roll", ["sushi"]),
    ("bubble tea", []),
    ("boba", []),
    ("milk tea", []),
    ("tteokbokki", []),
    ("dorayaki", []),
    ("tempura panko", []),
    ("ramyeon", []),
    ("hoisin", []),
    ("matcha latte", ["te", "cafe"]),
    ("fideos de arroz", ["pastas", "arroz-legumbres"]),
    ("pollo en salsa teriyaki", ["pollo", "salsas", "asiatica"]),
    ("sopa miso", ["sopas"]),
    ("mochi helado", ["helados"]),
    ("bowl base arroz de sushi", ["ensaladas-bowls", "arroz-legumbres", "sushi"]),  # «arroz de sushi»: un plato
    ("arroz sushi con cerdo", ["arroz-legumbres", "sushi", "carnes"]),
]


@pytest.mark.parametrize(("query", "concepts"), DISH_QUERIES)
def test_dish_words_label_products_but_do_not_read_queries(query, concepts):
    """«panko», «miso» o «bubble tea» en una consulta piden un plato o una bebida de restaurante: siguen con el concepto
    de antes. En un producto del catálogo sí lo nombran (`product_keywords`)."""
    found = concept_matcher(load_taxonomy(), for_queries=True).matches(query)
    assert [m.target for m in found] == concepts


@pytest.mark.parametrize(
    ("name", "concept"),
    [
        ("Panko Blanco 1kg", "despensa-asiatica"),
        ("Kimchi 200g", "despensa-asiatica"),
        ("Wasabi En Polvo 20 Gr", "despensa-asiatica"),
        ("Real Thai Fideos de Arroz", "despensa-asiatica"),
        ("Arroz Sushi Tanaka 1 kg", "despensa-asiatica"),
        ("Arroz de Sushi Kokuho Rose 1 kg", "despensa-asiatica"),
        ("Dorayaki Sabor Chocolate", "snacks-asiaticos"),
        ("Plato Vaso Yopokki Tteokbokki Tradicional", "snacks-asiaticos"),
        ("Coco Matcha Latte", "bebidas-asiaticas"),
        ("Gunys Popping Boba Uva 350ml", "bebidas-asiaticas"),
    ],
)
def test_product_only_words_still_label_catalog_products(matcher, name, concept):
    assert matcher.best(name).target == concept
