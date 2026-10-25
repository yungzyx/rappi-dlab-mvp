"""Preguntas en texto libre a Mochi (eval/frases_usuarios/preguntas-libres.txt, 24-10): lo que entender.py tiene que
sacar de una pregunta de una persona común, sin base de datos (con la vertical de la pantalla, no se consulta el
surtido)."""

import pytest

from rappi_ia.agent.understand import Understander

U = Understander()


def understand(text: str):
    return U.understand(None, text, "supermercado")


@pytest.mark.parametrize(
    ("text", "people"),
    [
        ("¿qué llevo para un asado de 6?", 6),
        ("algo para una once para 4", 4),
        ("cumpleaños de mi hijo, somos 10", 10),
        ("desayuno para dos", 2),
        ("almuerzo para la oficina, somos 5", 5),
        ("sushi para 2 personas", 2),
        ("asado para seis", 6),
    ],
)
def test_how_many_people(text, people):
    assert understand(text).people == people


@pytest.mark.parametrize(
    "text",
    ["cerveza pack de 6", "pañales talla 3", "leche 1 litro", "huevos de 12", "asado de tira", "6 cervezas"],
)
def test_a_number_that_is_not_people(text):
    assert understand(text).people is None


def test_people_stay_in_the_query():
    """Los combos dicen para cuántos («Desayuno Para Dos»): la cantidad se busca igual."""
    assert understand("desayuno para dos").query == "desayuno para dos"


@pytest.mark.parametrize(
    ("text", "price"),
    [("qué puedo cenar con 8 mil pesos", 8000), ("algo rico con 5 lucas", 5000), ("con $7.000 qué almuerzo", 7000)],
)
def test_a_budget_said_with_con(text, price):
    assert understand(text).price_max == price


def test_con_and_a_quantity_is_not_a_budget():
    assert understand("pan con 2 kilos de harina").price_max is None


@pytest.mark.parametrize(
    ("text", "query"),
    [
        ("qué compro para un picnic", "picnic"),
        ("se me antoja algo salado", "algo salado"),
        ("necesito cosas para limpiar la casa", "limpiar la casa"),
    ],
)
def test_question_leads_are_not_searched(text, query):
    assert understand(text).query == query


@pytest.mark.parametrize(
    ("text", "occasion"),
    [
        ("qué compro para un picnic", "picnic"),
        ("algo calentito que hace frío", "frio"),
        ("algo para regalarle a mi mamá", "regalo"),
    ],
)
def test_new_occasions_and_words(text, occasion):
    assert understand(text).occasion == occasion


@pytest.mark.parametrize(
    ("text", "concept"),
    [
        ("se me antoja algo salado", "snacks-salados"),
        ("necesito cosas para limpiar la casa", "limpieza"),
        ("qué trago me recomiendas", "cocteles"),
    ],
)
def test_words_people_use_for_a_concept(text, concept):
    assert understand(text).concepts[:1] == [concept]


def test_asking_for_a_drink_recommendation_is_a_search_not_help():
    """«qué trago me recomiendas» nombra lo que quiere: se busca, como «¿me recomiendas un vino?»."""
    assert understand("qué trago me recomiendas").kind == "buscar"


@pytest.mark.parametrize(
    "text",
    [
        "mi hijo tiene fiebre, ¿qué le doy?",
        "que me tomo para el dolor de cabeza",
        "qué puedo tomar para la tos",
        "cuánto paracetamol le doy a mi hija",
        "dosis de ibuprofeno para niños",
    ],
)
def test_asking_for_medical_advice(text):
    assert understand(text).kind == "consejo"


@pytest.mark.parametrize("text", ["tengo fiebre", "algo para la tos", "paracetamol", "qué le doy de comer"])
def test_not_medical_advice(text):
    assert understand(text).kind != "consejo"


@pytest.mark.parametrize(
    ("text", "dish"),
    [
        ("¿qué es un poke?", "poke"),
        ("que es el ceviche", "ceviche"),
        ("¿qué lleva una paella?", "paella"),
        ("hola mochi, ¿qué es un ramen?", "ramen"),
    ],
)
def test_what_is_a_dish(text, dish):
    intent = understand(text)
    assert intent.kind == "que_es" and intent.dish == dish


def test_what_is_something_without_a_card_is_a_normal_question():
    assert understand("¿qué es rappi?").kind != "que_es"


@pytest.mark.parametrize(
    ("text", "concept"),
    [
        ("¿con qué acompaño un salmón?", "pescados-mariscos"),
        ("con que acompaño el asado", "carnes"),
        ("qué le pongo a la pasta", "pastas"),
    ],
)
def test_what_goes_with(text, concept):
    intent = understand(text)
    assert intent.kind == "acompanar" and intent.concepts[:1] == [concept]


def test_a_named_drink_for_a_dish_is_a_search_for_the_drink():
    """«¿qué vino va con pasta?» pide vino (alcohol pedido): se busca, no es «con qué acompaño»."""
    intent = understand("¿qué vino va con pasta?")
    assert intent.kind == "buscar" and intent.concepts[:1] == ["vino"]


# Revisión de código del 24-10
@pytest.mark.parametrize(
    "text",
    [
        "pañales para 2 años",
        "comida para 2 perros",
        "leche para 6 meses",
        "cargador para 2 celulares",
        "cumpleaños de mi hijo de 6",
    ],
)
def test_ages_and_amounts_are_not_people(text):
    assert understand(text).people is None


CHILD_SYMPTOMS = [
    "mi guagua tiene fiebre",
    "algo para la fiebre de mi hijo",
    "algo para la tos de mi hija",
    "remedio para la tos de mi hija",
]


@pytest.mark.parametrize("text", CHILD_SYMPTOMS)
def test_a_child_with_a_symptom_gets_no_remedies_chosen_by_mochi(text):
    assert understand(text).kind == "consejo"


def test_a_named_remedy_for_a_child_is_searched():
    assert understand("paracetamol infantil para mi hijo").kind != "consejo"


@pytest.mark.parametrize(
    "text",
    [
        "qué sopa le doy a mi hijo resfriado",
        "qué jugo me tomo si estoy resfriado",
        "mi mamá está enferma, le doy un regalo",
        "qué pastilla de menta me recomiendas",
    ],
)
def test_advice_words_with_something_mochi_can_offer_are_not_medical_advice(text):
    assert understand(text).kind != "consejo"


@pytest.mark.parametrize("text", ["qué es lo más barato en sushi", "qué tiene de bueno el ramen"])
def test_a_dish_inside_another_question_is_not_its_card(text):
    assert understand(text).kind != "que_es"


@pytest.mark.parametrize("text", ["qué pido hoy", "que como hoy"])
def test_what_should_i_order_today_is_hunger_not_a_search_for_today(text):
    assert understand(text).occasion == "hambre"


def test_what_goes_with_an_occasion_starts_from_what_mochi_can_offer():
    intent = understand("con que acompaño el carrete")
    assert intent.kind == "acompanar" and intent.concepts[0] not in {"cerveza", "pisco", "ron", "vodka"}


def test_picnic_alone_is_not_the_occasion():
    """El buscador sigue buscando «picnic» (chocolates Costa Picnic); la ocasión es «para un picnic»."""
    assert understand("picnic").occasion is None
