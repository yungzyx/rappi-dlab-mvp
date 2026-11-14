"""Lo pedido y su para qué (concepts/need.py): en "X para Y" o "X con Y" se busca X si los complementos curados dicen
que X e Y van juntos. Sin base: la taxonomía, los complementos y las reglas del entendimiento."""

import pytest

from rappi_ia.agent.tools import read_query
from rappi_ia.agent.understand import Understander
from rappi_ia.concepts.need import goes_with
from rappi_ia.concepts.taxonomy import complement_queries
from rappi_ia.retrieval.hybrid import asked_text, detect_concepts, occasion_search, query_need

U = Understander()


def _asked(text: str) -> list[str]:
    return [m.target for m in query_need(text).asked]


@pytest.mark.parametrize(
    ("text", "asked", "context"),
    [
        ("bebida para mezclar con pisco", ["gaseosas"], ("pisco",)),
        ("hielo para el pisco", ["hielo"], ("pisco",)),
        ("tónica para el gin", ["gaseosas"], ("gin",)),
        ("algo para picar con la cerveza", ["snacks-salados"], ("cerveza",)),  # el "para" de lo pedido no corta
        ("queso para el vino", ["quesos"], ("vino",)),
        ("carbón para el asado", ["carbon"], ("carnes",)),
        ("pisco con bebida", ["pisco"], ("gaseosas",)),  # pide el pisco: lo nombrado primero es lo pedido
    ],
)
def test_what_goes_after_para_or_con_is_context_when_it_goes_with_what_is_asked(text, asked, context):
    need = query_need(text)
    assert _asked(text) == asked and need.context == context
    assert all(goes_with(a, c) > 0 for a in asked for c in context)


def test_an_occasion_can_be_what_is_asked_and_keeps_what_goes_with_the_context():
    """ "algo dulce" es antojo; del antojo, lo que va con el café, del que más al que menos (las aristas)."""
    need = query_need("algo dulce para el café de la tarde")
    assert need.asked == () and need.context == ("cafe",) and need.occasion == "antojo"
    assert need.occasion_concepts == ("pasteleria", "galletas", "chocolates")
    query, concepts, occasion = occasion_search("algo dulce para el café de la tarde")
    assert occasion.id == "antojo" and concepts == ["pasteleria", "galletas", "chocolates"]


@pytest.mark.parametrize(
    "text",
    [
        "café para llevar",  # "llevar" no nombra un concepto
        "comida para gato",  # un solo concepto
        "pilas para control",
        "shampoo para perro",  # el perro dice de qué tipo es el shampoo: no hay arista
        "arroz con leche",  # un postre
        "pizza con piña",  # sin arista: se busca como siempre
        "galletas de chocolate",  # "de" no es un conector: dice cómo son
        "detergente para ropa",
        "café para la once",  # la once es una ocasión, no un concepto: manda el café
        "chocolate",
    ],
)
def test_without_an_edge_or_a_connector_nothing_changes(text):
    need = query_need(text)
    assert need.context == () and need.end is None
    assert _asked(text) == detect_concepts(text)


def test_only_the_asked_words_are_searched_plus_how_the_edge_names_them():
    assert asked_text("bebida para mezclar con pisco", query_need("bebida para mezclar con pisco")) == "bebida"
    edge = complement_queries().get(("pastas", "salsas"))
    text = asked_text("salsa para la pasta", query_need("salsa para la pasta"))
    assert text == f"salsa {edge}".strip() and "pasta " not in f"{text} "
    assert asked_text("café para llevar", query_need("café para llevar")) == "café para llevar"  # tal cual


def test_alcohol_only_as_context_means_nothing_adult():
    assert read_query("bebida para mezclar con pisco") == ("bebida", ["gaseosas"], None, True)
    _, concepts, _, sober = read_query("pisco con bebida")
    assert concepts == ["pisco"] and not sober  # pidió el pisco
    _, concepts, occasion, sober = read_query("algo para tomar con el pisco")
    assert occasion.id == "bebestibles" and concepts == ["gaseosas"] and sober
    assert read_query("café para llevar") == ("café para llevar", None, None, False)  # tal cual


def test_mochi_understands_the_same_need():
    intent = U.understand(None, "bebida para mezclar con pisco", "licores")
    assert intent.concepts == ["gaseosas"] and intent.context == ["pisco"] and intent.query == "bebida"
    intent = U.understand(None, "algo dulce para el café de la tarde", "supermercado")
    assert intent.kind == "ocasion" and intent.occasion == "antojo" and not intent.explicit_concepts
    assert intent.concepts == ["pasteleria", "galletas", "chocolates"] and intent.context == ["cafe"]


@pytest.mark.parametrize(
    ("text", "concepts"),
    [
        ("café para llevar", ["cafe"]),
        ("comida para gato", ["alimento-gato"]),
        ("pilas para control", ["ferreteria"]),
        ("arroz con leche", ["postres"]),
    ],
)
def test_mochi_keeps_what_has_no_context(text, concepts):
    intent = U.understand(None, text, "supermercado")
    assert intent.concepts == concepts and intent.context == []
