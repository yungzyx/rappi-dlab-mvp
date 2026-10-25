"""Conversar con Mochi (25-10, docs/diseno/2026-10-25-mochi-conversacion-design.md): un seguimiento hereda el estado
del turno anterior (`previous`, el `conversation` que devolvió la API) y cambia solo lo que dice; un tema nuevo parte
de cero. Conversaciones de eval/frases_usuarios/conversaciones.txt."""

from rappi_ia.agent.understand import Understander

U = Understander()


def _then(previous: dict, text: str, vertical: str = "supermercado"):  # con pantalla: sin base
    return U.understand(None, text, vertical, previous=previous)


WINE = {"query": "vino bueno", "concepts": ["vino"], "vertical": "licores", "price_max": 10000.0}


def test_another_option_keeps_the_price_cap():
    """«un vino bueno hasta 10 mil» → «otra opción» volvía a mostrar vinos de $23.590."""
    intent = _then(WINE, "otra opción")
    assert intent.follow_up and intent.exclude_previous and intent.price_max == 10000
    assert intent.concepts == ["vino"] and intent.query == "vino bueno"


def test_a_new_cap_replaces_the_previous_one():
    assert _then(WINE, "menos de 5 lucas").price_max == 5000


def test_the_order_by_price_is_kept_until_it_changes():
    cheap = {"query": "pizza", "concepts": ["pizza"], "vertical": "restaurantes", "order": "barato"}
    assert _then(cheap, "sin carne").cheapest
    pricey = _then(cheap, "uno más caro")
    assert pricey.priciest and not pricey.cheapest


def test_order_words_do_not_pile_up_in_the_query():
    """pañales talla G → «más baratos» perdía la talla entre «panales talla g mas baratos»."""
    previous = {"query": "panales talla g", "concepts": ["panales"], "vertical": "farmacia"}
    intent = _then(previous, "más baratos")
    assert intent.query == "panales talla g" and intent.cheapest
    assert _then(previous, "¿y algo más barato?").query == "panales talla g"


def test_people_are_kept_and_replaced():
    once = {"query": "algo para una once para 4", "concepts": [], "occasion": "once", "vertical": "supermercado",
            "people": 4}  # fmt: skip
    without = _then(once, "sin lactosa")
    assert without.follow_up and without.people == 4 and "sin lactosa" in without.query
    more = _then(once, "para 10 personas")
    assert more.follow_up and more.people == 10
    assert "para 4" not in more.query and "para 10 personas" in more.query
    assert _then(once, "somos 8").people == 8


def test_an_occasion_follow_up_is_still_the_occasion():
    """Un asado «más barato» traía albóndigas y seitán: el seguimiento era una búsqueda de «carnes»."""
    once = {"query": "algo para una once para 4", "concepts": [], "occasion": "once", "vertical": "supermercado"}
    intent = _then(once, "sin lactosa")
    assert intent.kind == "ocasion" and intent.occasion == "once" and not intent.explicit_concepts
    assert "panaderia" in intent.concepts and intent.vertical == "supermercado"
    asado = {"query": "asado de 6", "concepts": ["carnes"], "occasion": "asado", "vertical": "supermercado",
             "people": 6}  # fmt: skip
    cheaper = _then(asado, "¿y algo más barato?")
    assert cheaper.kind == "ocasion" and cheaper.occasion == "asado" and cheaper.explicit_concepts
    assert cheaper.concepts == ["carnes"] and cheaper.query == "asado de 6" and cheaper.cheapest and cheaper.people == 6


def test_a_symptom_follow_up_still_looks_for_the_symptom():
    """«algo para el resfrío» → «más barato» traía sal de fruta: el síntoma se perdía."""
    cold = {"query": "algo para el resfrio", "concepts": [], "vertical": "farmacia", "symptom": True}
    intent = _then(cold, "más barato")
    assert intent.follow_up and intent.symptom and intent.cheapest and intent.query == "algo para el resfrio"


def test_without_meat_refines_the_previous_request():
    """«algo sin carne» después de «tengo hambre» buscaba proteína de soya en Express: «sin carne» nombra lo vegano,
    pero tras un pedido es lo que no va."""
    hungry = {"query": "tengo hambre", "concepts": [], "occasion": "hambre", "vertical": "restaurantes"}
    intent = _then(hungry, "algo sin carne")
    assert intent.follow_up and intent.occasion == "hambre" and "sin carne" in intent.query
    assert U.understand(None, "algo sin carne", "supermercado").concepts[:1] == ["vegano"]  # sin pedido anterior, igual


def test_a_new_topic_starts_from_scratch():
    asado = {"query": "asado de 6", "concepts": ["carnes"], "occasion": "asado", "vertical": "supermercado",
             "people": 6, "price_max": 20000.0, "order": "barato"}  # fmt: skip
    diapers = _then(asado, "pañales talla G")
    assert not diapers.follow_up and diapers.people is None and diapers.price_max is None and not diapers.cheapest
    headache = _then({"query": "pizza", "concepts": ["pizza"], "vertical": "restaurantes"}, "tengo dolor de cabeza")
    assert not headache.follow_up and headache.symptom and headache.concepts != ["pizza"]


def test_and_something_new_is_the_same_gathering():
    """«¿y para tomar?» después de un asado de 6: otra cosa, para las mismas 6 personas."""
    asado = {"query": "asado de 6", "concepts": ["carnes"], "occasion": "asado", "vertical": "supermercado",
             "people": 6, "price_max": 20000.0}  # fmt: skip
    drinks = _then(asado, "¿y para tomar?")
    assert not drinks.follow_up and drinks.concepts[:1] == ["gaseosas"]
    assert drinks.people == 6 and drinks.price_max is None


def test_unknown_previous_values_are_ignored():
    """El estado lo manda la app: una ocasión o un concepto que no existe no rompe nada."""
    weird = {"query": "x", "concepts": ["no-existe"], "occasion": "tampoco", "vertical": "supermercado"}
    assert not _then(weird, "más barato").follow_up


def test_the_state_never_exceeds_what_the_api_accepts():
    """El estado vuelve como `previous` (api/app.py: PreviousTurnIn, consulta de hasta 200): una conversación larga
    no lo rompe."""
    from rappi_ia.agent.rappi_agent import Context, RappiAgent
    from rappi_ia.api.app import PreviousTurnIn

    intent = U.understand(None, "pizza", "restaurantes")
    intent.query = " ".join(["pizza"] + ["con extra queso"] * 30)
    state = RappiAgent()._conversation(intent, "restaurantes", [], Context())
    assert len(state["query"]) <= 200 and state["query"].endswith("con extra queso")
    PreviousTurnIn(**state)  # no lanza
