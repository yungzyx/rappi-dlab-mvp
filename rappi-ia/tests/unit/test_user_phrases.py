"""Frases reales de usuarios (rondas de prueba actuando como usuario, 04-10). Cada caso falló alguna vez: el chat
buscaba la frase literal y traía cualquier cosa, o elegía una ocasión equivocada."""

import pytest

from rappi_ia.agent.understand import Understander

U = Understander()


@pytest.mark.parametrize(
    ("text", "concept"),
    [
        ("un completo", "sandwiches"),  # el hot dog chileno, no un «Aliño Completo»
        ("serbesa", "cerveza"),
        ("algo pa picar", "snacks-salados"),
        ("leche de formula", "alimentacion-bebe"),
        ("arena pal gato", "accesorios-mascota"),
    ],
)
def test_chilean_and_misspelled_words_name_the_right_concept(text, concept):
    assert U.understand(None, text, "supermercado").concepts[:1] == [concept]


@pytest.mark.parametrize(
    ("text", "occasion"),
    [
        ("copete barato", "carrete"),
        ("cumpleaños de mi hijo", "cumpleanos"),  # una fiesta infantil no va a Licores
        ("algo dulce", "antojo"),
        ("estoy aburrido", "panorama"),
    ],
)
def test_vague_requests_become_occasions(text, occasion):
    assert U.understand(None, text, "supermercado").occasion == occasion


def test_the_help_examples_the_app_shows_are_understood():
    """«Algo de sushi» va primero en la ayuda; «Arma un carrete» sigue más abajo y sigue siendo una ocasión."""
    assert U.understand(None, "sushi", "supermercado").concepts[:1] == ["sushi"]
    assert U.understand(None, "algo para el carrete", "supermercado").occasion == "carrete"


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("ayuda", "ayuda"),
        ("quien eres", "ayuda"),
        ("que puedes hacer", "ayuda"),
        ("hacen delivery?", "envio"),
        ("cuanto se demora", "envio"),
        ("tienen ofertas?", "ofertas"),
    ],
)
def test_questions_about_the_app_are_not_product_searches(text, kind):
    assert U.understand(None, text, "supermercado").kind == kind


def test_cheap_asks_for_the_cheapest_first():
    assert U.understand(None, "pizza barata", "restaurantes").cheapest
    assert U.understand(None, "cerveza mas barata", "licores").cheapest
    assert not U.understand(None, "cerveza", "licores").cheapest


# Ronda 2
@pytest.mark.parametrize(
    ("text", "concept"),
    [
        ("juguete pal gato", "accesorios-mascota"),  # «pal» = «para el»
        ("leche de almendras", "vegano"),  # «Alternativas vegetales»
    ],
)
def test_round_two_words(text, concept):
    assert U.understand(None, text, "supermercado").concepts[:1] == [concept]


def test_without_is_not_asking_for_it():
    """«algo sin azúcar» buscaba azúcar."""
    assert "azucar" not in U.understand(None, "algo sin azúcar", "supermercado").concepts


@pytest.mark.parametrize(
    ("text", "occasion"),
    [
        ("algo barato pa comer", "hambre"),  # «pa» = «para»
        ("estoy triste", "animo"),
        ("mi nieto viene el domingo y quiero comprarle algo", "regalo-nino"),
    ],
)
def test_round_two_occasions(text, occasion):
    assert U.understand(None, text, "supermercado").occasion == occasion


def test_asking_for_a_recommendation_is_not_a_search():
    for text in ("qué me recomiendas", "oye mochi me recomiendas algo?"):
        assert U.understand(None, text, "supermercado").kind == "recomendar", text


def test_asking_someone_to_buy_for_you_is_rappifavor():
    assert U.understand(None, "necesito que me compren algo en una ferretería", None).service == "rappifavor"


# Ronda 3
def test_misspelled_request_and_product():
    intent = U.understand(None, "nesecito shampu", "supermercado")
    assert intent.concepts[:1] == ["cuidado-cabello"] and intent.query == "shampu"


@pytest.mark.parametrize(
    ("text", "occasion"),
    [("voy a ver el partido", "carrete"), ("cena romántica", "cita")],
)
def test_round_three_occasions(text, occasion):
    assert U.understand(None, text, "supermercado").occasion == occasion


def test_fried_chicken_with_fries_is_a_dish():
    assert U.understand(None, "pollo con papas fritas", "supermercado").concepts[:1] == ["pollo-preparado"]


@pytest.mark.parametrize("text", ["mcdonalds", "quiero un mc donalds", "burger king"])
def test_restaurant_chains_go_to_restaurants(text):
    intent = U.understand(None, text, None)
    assert intent.vertical == "restaurantes" and intent.explicit_vertical, text


# Ronda 4: conversaciones. El segundo mensaje refina el primero.
def _then(first, then, vertical=None):
    previous_intent = U.understand(None, first, vertical or "supermercado")
    previous = {
        "query": previous_intent.query,
        "concepts": previous_intent.concepts,
        "vertical": previous_intent.vertical,
    }
    return U.understand(None, then, "supermercado", previous=previous)


@pytest.mark.parametrize(
    ("first", "then", "concept", "query"),
    [
        ("pañales", "talla g", "panales", "panales talla g"),
        ("shampoo", "para pelo graso", "cuidado-cabello", "shampoo para pelo graso"),
        ("leche", "sin lactosa", "lacteos", "leche sin lactosa"),
        ("chocolates", "más grande", "chocolates", "chocolates mas grande"),
        ("hamburguesa", "con papas", "hamburguesa", "hamburguesa con papas"),
    ],
)
def test_a_short_follow_up_refines_the_previous_request(first, then, concept, query):
    intent = _then(first, then)
    assert intent.concepts[:1] == [concept] and intent.query == query and intent.follow_up


def test_cheaper_keeps_the_previous_request():
    intent = _then("cerveza", "más barata", "licores")
    assert intent.concepts == ["cerveza"] and intent.cheapest and intent.vertical == "licores"


def test_naming_a_vertical_moves_the_previous_request_there():
    intent = _then("vino tinto", "y en el súper?", "licores")
    assert intent.concepts == ["vino"] and intent.vertical == "supermercado" and intent.explicit_vertical


@pytest.mark.parametrize(("first", "then"), [("quiero una pizza", "mejor sushi"), ("comida pal perro", "para gato")])
def test_naming_something_new_is_a_new_request(first, then):
    assert not _then(first, then).follow_up


def test_without_a_previous_message_nothing_changes():
    assert not U.understand(None, "talla g", "supermercado").follow_up


def test_healthier_after_hunger_is_a_salad():
    assert _then("tengo hambre", "algo más sano").concepts[:1] == ["ensaladas-bowls"]


# Ronda 5
@pytest.mark.parametrize(("text", "concept"), [("🍕", "pizza"), ("quiero un 🍔", "hamburguesa"), ("🍺🍺", "cerveza")])
def test_emojis_name_their_concept(text, concept):
    assert U.understand(None, text, "supermercado").concepts[:1] == [concept]


def test_voice_fillers_are_not_searched():
    intent = U.understand(None, "eh quiero este una coca po", "supermercado")
    assert intent.query == "coca" and intent.concepts[:1] == ["gaseosas"]


@pytest.mark.parametrize(("text", "concept"), [("beer", "cerveza"), ("pastillas para dormir", "vitaminas")])
def test_round_five_words(text, concept):
    assert U.understand(None, text, "supermercado").concepts[:1] == [concept]


@pytest.mark.parametrize(
    "text",
    ["como va a estar el clima", "cuéntame un chiste", "cuál es la capital de francia", "eres tonto", "te quiero"],
)
def test_off_topic_is_answered_not_logged_as_demand(text):
    assert U.understand(None, text, "supermercado").kind == "fuera"


@pytest.mark.parametrize("text", ["farmacia de turno", "algo abierto ahora", "cerca de mí"])
def test_opening_hours_and_location_are_app_questions(text):
    assert U.understand(None, text, "supermercado").kind == "envio"


def test_a_price_said_as_de_n_lucas_is_a_cap():
    assert U.understand(None, "cerveza de 2 lucas", "licores").price_max == 2000
    assert U.understand(None, "pack de 6 cervezas", "licores").price_max is None


def test_an_alternative_replaces_the_previous_refinement():
    """helado → de chocolate → «y de vainilla?» buscaba «helado de chocolate y de vainilla»."""
    previous = {"query": "helado de chocolate", "concepts": ["helados"], "vertical": "conveniencia"}
    intent = U.understand(None, "y de vainilla?", "conveniencia", previous=previous)
    assert intent.follow_up and "chocolate" not in intent.query and "vainilla" in intent.query


# Ronda 6
@pytest.mark.parametrize(
    "text", ["mi pedido no llega", "quiero cancelar mi pedido", "me llegó mal el pedido", "donde viene el rappi"]
)
def test_order_complaints_are_answered_not_searched(text):
    assert U.understand(None, text, "supermercado").kind == "pedido"


def test_a_refused_concept_is_neither_shown_nor_searched():
    intent = U.understand(None, "no quiero pizza, algo más sano", "restaurantes")
    assert "pizza" not in intent.concepts and "pizza" not in intent.query
    assert intent.concepts[:1] == ["ensaladas-bowls"]


def test_anything_but_x_offers_the_rest_of_the_occasion():
    intent = U.understand(None, "cualquier cosa menos sushi", None)
    assert intent.occasion == "hambre" and "sushi" not in intent.concepts and intent.concepts
    assert "sushi" not in intent.query


def test_without_meat_is_vegetarian():
    assert U.understand(None, "algo sin carne", "supermercado").concepts == ["vegano"]


def test_my_dad_is_not_potatoes():
    assert "verduras" not in U.understand(None, "regalo de navidad para mi papá", "mall").concepts


@pytest.mark.parametrize(
    ("text", "concept"),
    [
        ("juguete para mi perro", "accesorios-mascota"),
        ("amburgesa", "hamburguesa"),
        ("pisa familiar", "pizza"),
    ],
)
def test_round_six_words(text, concept):
    assert U.understand(None, text, "supermercado").concepts[:1] == [concept]


def test_national_holidays_are_an_occasion():
    intent = U.understand(None, "algo para las fiestas patrias", None)
    assert intent.occasion == "fiestas-patrias" and "empanadas" in intent.concepts


def test_a_longer_follow_up_with_fillers_still_follows():
    """sushi → «mejor no, algo más barato»: cinco palabras, pero solo «barato» dice algo."""
    intent = _then("sushi", "mejor no, algo más barato")
    assert intent.follow_up and intent.concepts == ["sushi"] and intent.cheapest


def test_more_expensive_sorts_the_priciest_first():
    intent = _then("vino tinto", "uno más caro")
    assert intent.follow_up and intent.priciest and not intent.cheapest


# Ronda 7
@pytest.mark.parametrize(
    ("text", "concept"),
    [
        ("venden cigarros electrónicos?", "vapeo"),
        ("almuerzo saludable", "ensaladas-bowls"),
    ],
)
def test_round_seven_words(text, concept):
    assert U.understand(None, text, "supermercado").concepts[:1] == [concept]


def test_people_are_not_searched():
    """«para la presión de mi mamá» traía mamaderas; «para mi señora», lo que calzara con «señora»."""
    assert "senora" not in U.understand(None, "vino y flores para mi señora", "licores").query
    assert "mama" not in U.understand(None, "algo para mi mamá", "supermercado").query


@pytest.mark.parametrize("text", ["remedio para la diabetes", "colesterol", "algo para la hipertensión"])
def test_chronic_conditions_need_a_prescription(text):
    assert U.understand(None, text, "supermercado").kind == "receta"


def test_blood_pressure_is_a_monitor_not_baby_bottles():
    """«algo para la presión de mi mamá» traía mamaderas: hay tensiómetros (y los remedios son con receta)."""
    assert U.understand(None, "necesito algo para la presión de mi mamá", "farmacia").concepts == ["primeros-auxilios"]


def test_not_wanting_to_cook_is_hunger():
    assert U.understand(None, "llegué tarde del trabajo y no quiero cocinar", None).occasion == "hambre"


def test_a_coffee_chain_is_a_restaurant():
    intent = U.understand(None, "algo de starbucks", None)
    assert intent.vertical == "restaurantes" and intent.explicit_vertical


# Ronda 8
@pytest.mark.parametrize(
    ("text", "concept"),
    [("útiles escolares", "utiles"), ("bebida isotónica", "energizantes")],
)
def test_round_eight_words(text, concept):
    assert U.understand(None, text, "supermercado").concepts[:1] == [concept]


@pytest.mark.parametrize("text", ["olvida lo que te dije", "qué sabes de mí", "no guardes lo que busco"])
def test_memory_questions_are_answered_first(text):
    """«olvida lo que te dije» traía joyas: «dije» es un colgante."""
    assert U.understand(None, text, "supermercado").kind == "memoria"


def test_kids_in_slang_are_an_occasion():
    assert U.understand(None, "algo pa los cabros chicos", None).occasion == "regalo-nino"


def test_none_of_them_asks_for_others():
    intent = _then("completo", "no me gustó ninguno")
    assert intent.follow_up and intent.exclude_previous


# Ronda 9
def test_stretched_letters_are_read_as_one():
    assert U.understand(None, "holaaaa", "supermercado").kind == "saludo"
    assert U.understand(None, "cervezaaaa", "licores").concepts[:1] == ["cerveza"]


@pytest.mark.parametrize("text", ["jajaja", "jajajaja xd", "123", "https://www.rappi.cl"])
def test_laughter_numbers_and_links_are_not_searched(text):
    assert U.understand(None, text, "supermercado").kind == "vacio"


def test_a_misspelled_vertical_is_still_a_vertical():
    intent = U.understand(None, "algo de la farmasia", None)
    assert intent.vertical == "farmacia" and intent.explicit_vertical


def test_the_vertical_named_is_not_searched():
    """«en el super algo para el desayuno» buscaba «super» y traía comida para gatos Super."""
    intent = U.understand(None, "en el super algo para el desayuno", None)
    assert intent.vertical == "supermercado" and "super" not in intent.query.split()
    assert "farmacia" not in U.understand(None, "en la farmacia algo bajo 5 lucas", None).query
    assert "lider" in U.understand(None, "leche del lider", None).query  # la cadena es también la marca


def test_a_price_range_caps_at_its_top_and_mil_alone_is_a_thousand():
    assert U.understand(None, "vino tinto entre 5 y 10 mil", "licores").price_max == 10000
    assert U.understand(None, "cerveza a menos de mil", "licores").price_max == 1000


def test_something_to_drink_is_drinks():
    assert U.understand(None, "algo para tomar", "supermercado").concepts[:1] == ["gaseosas"]


# Ronda 10
@pytest.mark.parametrize(
    ("text", "concept"),
    [
        ("un energético", "energizantes"),
        ("toallas húmedas", "panales"),
    ],
)
def test_round_ten_words(text, concept):
    assert U.understand(None, text, "supermercado").concepts[:1] == [concept]


def test_studying_all_night_is_an_occasion_that_never_beats_what_is_named():
    assert U.understand(None, "algo para estudiar toda la noche", None).occasion == "estudiar"
    assert U.understand(None, "café pa estudiar toda la noche", "supermercado").concepts[:1] == ["cafe"]


def test_watching_a_movie_is_a_night_in():
    assert U.understand(None, "algo para ver una película", None).occasion == "panorama"


def test_to_go_is_a_restaurant():
    intent = U.understand(None, "un café con leche para llevar", None)
    assert intent.vertical == "restaurantes" and intent.kind == "buscar"


# Revisión de las rondas 5 a 10 (casos que las reglas nuevas resolvían mal)
def test_a_no_answer_before_the_request_is_not_a_refusal():
    assert U.understand(None, "no, quiero pizza", "restaurantes").concepts[:1] == ["pizza"]


def test_less_of_something_is_not_refusing_it():
    intent = U.understand(None, "yogurt con menos azúcar", "supermercado")
    assert intent.concepts[:1] == ["lacteos"] and "azucar" in intent.query


def test_a_refused_concept_never_comes_back_in_the_query():
    assert "sushi" not in U.understand(None, "cualquier cosa menos sushi", None).query
    assert U.understand(None, "no quiero cerveza", "licores").kind == "vacio"


@pytest.mark.parametrize("text", ["algo menos caro", "vino no tan caro", "crema para la cara", "cara de cerdo"])
def test_pricey_only_when_asked_for(text):
    assert not U.understand(None, text, "supermercado").priciest


def test_less_expensive_is_cheapest():
    assert U.understand(None, "vino menos caro", "licores").cheapest


def test_and_cheaper_keeps_the_previous_refinement():
    previous = {"query": "panales huggies talla g", "concepts": ["panales"], "vertical": "farmacia"}
    intent = U.understand(None, "y más barato?", "farmacia", previous=previous)
    assert "huggies" in intent.query and "talla g" in intent.query and intent.cheapest


def test_not_spicy_keeps_the_no():
    previous = {"query": "salsa", "concepts": ["salsas"], "vertical": "supermercado"}
    assert "no picante" in U.understand(None, "no picante", "supermercado", previous=previous).query


@pytest.mark.parametrize(
    ("text", "price", "kept"),
    [
        ("pizza grande 10 lucas", 10000, "grande"),
        ("televisor de 4k", None, "4k"),
        ("rompecabezas de 2 mil piezas", None, "piezas"),
        ("entre 2 y 3 kilos de carne", None, "entre 2 y 3 kilos"),
    ],
)
def test_prices_do_not_eat_sizes_or_quantities(text, price, kept):
    intent = U.understand(None, text, "supermercado")
    assert intent.price_max == price and kept in intent.query


def test_stretching_does_not_break_links_sizes_or_fillers():
    assert U.understand(None, "www.rappi.cl", "supermercado").kind == "vacio"
    assert "xxxl" in U.understand(None, "polera talla xxxl", "mall").query
    assert U.understand(None, "mmm quiero pizza", "restaurantes").query == "pizza"


@pytest.mark.parametrize(
    "text", ["lamina de privacidad para celular", "olvidate de la pizza, mejor sushi", "recargar mis datos"]
)
def test_memory_questions_are_phrases_not_words(text):
    assert U.understand(None, text, "mall").kind != "memoria"


def test_diabetes_supplies_are_products():
    assert U.understand(None, "tiras reactivas para diabetes", "farmacia").kind == "buscar"


def test_without_the_x_is_still_without():
    assert "frutas" not in U.understand(None, "helado sin la frutilla", "supermercado").concepts


def test_and_another_kind_replaces_the_previous_refinement():
    """vino tinto → «uno más caro» → «y blanco?» volvía a mostrar tintos."""
    previous = {"query": "vino tinto uno mas caro", "concepts": ["vino"], "vertical": "licores"}
    intent = U.understand(None, "y blanco?", "licores", previous=previous)
    assert "tinto" not in intent.query and "blanco" in intent.query
