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


def test_with_con_the_whole_phrase_is_searched():
    """ "café con leche" y "pan con palta" son platos que se llaman así: con "con" se busca la frase entera, aunque la
    leche y la palta solo digan con qué va (no son conceptos pedidos). Con "para", solo lo pedido."""
    assert read_query("café con leche") == ("café con leche", ["cafe"], None, False)
    assert read_query("pan con palta")[:2] == ("pan con palta", ["panaderia"])
    assert read_query("leche para el café")[:2] == ("leche leche", ["lacteos"])  # más el texto de la arista
    # con alcohol en el para qué se corta igual: la cerveza no se muestra y solo llenaría los candidatos
    assert read_query("algo para picar con la cerveza")[0] == "algo para picar"


def test_alcohol_only_as_context_means_nothing_adult():
    assert read_query("bebida para mezclar con pisco") == ("bebida", ["gaseosas"], None, True)
    _, concepts, _, sober = read_query("pisco con bebida")
    assert concepts == ["pisco"] and not sober  # pidió el pisco
    _, concepts, occasion, sober = read_query("algo para tomar con el pisco")
    assert occasion.id == "bebestibles" and concepts == ["gaseosas"] and sober
    assert read_query("café para llevar") == ("café para llevar", None, None, False)  # tal cual


@pytest.mark.parametrize(
    ("text", "asked", "query"),
    [
        ("jugo para el ron", ["jugos"], "jugo"),  # sin arista ron–jugos
        ("bebida para el whisky", ["gaseosas"], "bebida"),  # sin arista whisky–gaseosas
        ("limón para el pisco sour", ["frutas"], "limon"),  # sin arista pisco–frutas
        ("chicle para el cigarro", ["golosinas"], "chicle"),  # cualquier +18, no solo el alcohol
    ],
)
def test_alcohol_after_the_connector_is_only_what_it_goes_with(text, asked, query):
    """Algo sin alcohol para acompañar un trago: se busca eso, sin nada +18, aunque no haya arista curada."""
    assert read_query(text) == (query, asked, None, True)


@pytest.mark.parametrize(
    ("text", "asked"),
    [
        ("ron con coca cola", ["ron"]),  # lo pedido es el trago
        ("cerveza para el asado", ["cerveza"]),
        ("vino para la pasta", ["vino"]),
    ],
)
def test_a_drink_named_first_is_still_what_is_asked(text, asked):
    _, concepts, _, sober = read_query(text)
    assert concepts == asked and not sober


def test_an_occasion_with_drinks_does_not_hide_them():
    """Una ocasión sin tragos ("algo para tomar") antes del pisco: lo que va con él por su arista, sin +18. Una con
    tragos en sus conceptos ("carrete") no hace del alcohol un para qué sin arista: "carrete con tequila" pide el
    tequila."""
    _, concepts, occasion, sober = read_query("algo para tomar con el pisco")
    assert occasion.id == "bebestibles" and concepts == ["gaseosas"] and sober
    assert query_need("algo para el carrete con tequila").context == ()
    need = query_need("vaso para whisky")  # "vaso" no nombra un concepto: como siempre
    assert need.context == () and need.end is None


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
