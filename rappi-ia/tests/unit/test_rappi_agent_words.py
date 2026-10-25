"""Reglas de palabras de Mochi que no necesitan la base (revisión de las rondas 5 a 10)."""

import pytest

from rappi_ia.agent.rappi_agent import _moved, _names, _stem


@pytest.mark.parametrize(
    ("name", "word", "says"),
    [
        ("Pizza Champiñón", "champinones", True),  # plural pedido, singular en el nombre
        ("Roll Salmón Queso", "sal", False),  # «sin sal» no saca el salmón
        ("Salsa de tomate", "sal", False),
        ("Papas con sal de mar", "sal", True),
        ("Pasta con tomates", "tomate", True),
    ],
)
def test_words_match_whole_with_their_plural(name, word, says):
    assert _names(name, _stem(word)) is says


def test_free_from_is_said_only_with_sin_libre_or_zero():
    assert _names("Pan sin gluten", "gluten", free_from=True)
    assert _names("Pan pita libre de gluten", "gluten", free_from=True)
    assert not _names("Pan con gluten", "gluten", free_from=True)


def test_a_vertical_with_a_few_is_not_said_to_have_none():
    assert _moved("farmacia", "conveniencia", "helados", 18).startswith("En farmacia casi no hay «helados»")
    assert _moved("farmacia", "licores", "vino", 0).startswith("En farmacia no hay «vino»")


@pytest.fixture(scope="module")
def agent():
    from rappi_ia.agent.rappi_agent import RappiAgent

    return RappiAgent()


@pytest.mark.parametrize(
    ("text", "vertical", "avoided"),
    [
        ("sandwich sin palta", "restaurantes", ["palta"]),  # «palta» es palabra de los sándwiches y aun así se excluye
        ("empanadas sin queso", "restaurantes", ["queso"]),
        ("pizza sin las aceitunas", "restaurantes", ["aceituna"]),
        ("algo sin carne", "supermercado", []),  # «sin carne» nombra lo vegano
    ],
)
def test_what_is_asked_without(agent, text, vertical, avoided):
    assert agent._avoided(agent.understander.understand(None, text, vertical)) == avoided


def test_without_x_is_a_free_from_detail(agent):
    intent = agent.understander.understand(None, "vino sin alcohol", "licores")
    assert agent._detail(intent) == ("alcohol", "sin alcohol", True)


# El nombre del agente sale de config.AGENT_NAME. Se quita solo como vocativo: al lado
# de un saludo o un «gracias», o antes de un pedido; si es todo el pedido («quiero mochi»), se busca el postre.
@pytest.fixture(scope="module")
def understander():
    from rappi_ia.agent.understand import Understander

    return Understander()


def _name():
    from rappi_ia import config

    return config.AGENT_NAME


def test_greeting_with_agent_name(understander):
    for text in [f"hola {_name()}", f"Hola, {_name()}!", f"buenas tardes {_name().lower()}"]:
        assert understander.understand(None, text, "restaurantes").kind == "saludo", text


def test_thanks_with_agent_name(understander):
    for text in [f"gracias {_name()}", f"ok, muchas gracias {_name()}!"]:
        assert understander.understand(None, text, "restaurantes").kind == "gracias", text


def test_vocative_is_stripped_before_query(understander):
    for text in [
        f"hola {_name()} quiero sushi",
        f"{_name()}, quiero sushi",
        f"oye {_name()} necesito sushi porfa",
        f"sushi porfa {_name()}",
    ]:
        assert understander.understand(None, text, "restaurantes").query == "sushi", text


def test_the_name_before_courtesy_or_an_article_is_the_dessert(understander):
    """Solo antes de un saludo o de un verbo de pedido el nombre es vocativo: «porfa», «por» o un artículo después
    no lo vuelven un llamado."""
    name = _name().lower()
    for text in [f"quiero un {name} porfa", f"quiero {name} por favor", f"dame {name} un poco"]:
        intent = understander.understand(None, text, "restaurantes")
        assert intent.query.split()[0] == name, (text, intent.query)
    assert understander.understand(None, f"quiero un {name} porfa", "restaurantes").query == name


def test_dessert_alone_stays_a_query(understander):
    """El mochi también es un postre: si el nombre es todo el pedido, se busca."""
    name = _name().lower()
    for text, query in [(f"quiero {name}", name), (name, name), (f"{name} de matcha", f"{name} de matcha")]:
        intent = understander.understand(None, text, "restaurantes")
        assert intent.kind == "buscar" and intent.query == query, text


def test_follows_agent_name_env(understander, monkeypatch):
    from rappi_ia import config

    monkeypatch.setattr(config, "AGENT_NAME", "Pelusa")
    assert understander.understand(None, "hola pelusa", "restaurantes").kind == "saludo"
    assert understander.understand(None, "gracias Pelusa", "restaurantes").kind == "gracias"
    assert understander.understand(None, "hola pelusa quiero sushi", "restaurantes").query == "sushi"


@pytest.mark.parametrize(
    ("text", "kind", "occasion", "concepts"),
    [
        ("Mochi, ¿qué me recomiendas?", "recomendar", None, []),
        ("Mochi, ¿qué hay de rico para cenar?", "ocasion", "hambre", None),
        ("Mochi se me antoja algo dulce", "ocasion", "antojo", None),
        ("te quiero mochi", "fuera", None, []),
        ("Mochi, ¿cuál es el mejor sushi?", "buscar", None, ["sushi"]),
        ("quiero mochi", "buscar", None, []),
    ],
)
def test_the_agent_name_is_not_read_as_a_product(understander, monkeypatch, text, kind, occasion, concepts):
    """Con «mochi» como palabra de los snacks asiáticos, estos mensajes al agente pedían snacks asiáticos (revisión
    del 14-10-2026). Dicen lo mismo que antes de los conceptos asiáticos."""
    from rappi_ia import config

    monkeypatch.setattr(config, "AGENT_NAME", "Mochi")
    intent = understander.understand(None, text, "restaurantes")
    assert (intent.kind, intent.occasion) == (kind, occasion), text
    assert "snacks-asiaticos" not in intent.concepts
    if concepts is not None:
        assert intent.concepts == concepts, text
