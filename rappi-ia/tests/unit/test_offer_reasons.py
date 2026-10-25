"""Por qué se ofrece algo: el `reason` de cada oferta trae las claves de siempre más `text` y `basis`."""

from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.offers import engine
from rappi_ia.offers.engine import complement_reason


def concept(concept_id: str):
    return load_taxonomy().concepts[concept_id]


def test_cart_reason_names_the_origin():
    reason = complement_reason("carrito", concept("pizza"), concept("gaseosas"))

    assert reason["text"] == "Porque llevas 🍕 pizza."
    assert reason["basis"] == [{"kind": "carrito", "id": "pizza", "source": "contexto"}]
    assert complement_reason("checkout", concept("pizza"), concept("gaseosas"))["text"] == "Porque llevas 🍕 pizza."


def test_next_order_reason_says_what_was_ordered():
    reason = complement_reason("proximo_pedido", concept("pizza"), concept("gaseosas"))

    assert reason["text"] == "Porque pediste 🍕 pizza."
    assert reason["basis"] == [{"kind": "pedido", "id": "pizza", "source": "contexto"}]


def test_cart_reason_is_anonymous_for_a_non_offerable_origin():
    """El agente no nombra alcohol por su cuenta: ni el texto ni la base repiten la cerveza."""
    for moment in ("carrito", "checkout", "proximo_pedido"):
        reason = complement_reason(moment, concept("cerveza"), concept("snacks-salados"))

        assert reason["text"] in (engine.REASON_CART_ANONYMOUS, engine.REASON_NEXT_ANONYMOUS), moment
        assert "cerveza" not in reason["text"].lower() and "🍺" not in reason["text"]
        assert reason["basis"] == [], moment


def test_reason_keeps_the_ids_the_app_reads():
    reason = complement_reason("carrito", concept("pizza"), concept("gaseosas"))

    assert reason["concept"] == "gaseosas" and reason["from_concept"] == "pizza"
    assert engine.REASON_PLAN == "Porque elegiste «{occasion}»."
    assert engine.REASON_NO_RESULT == "Porque buscaste «{query}» y aquí sí hay."
    assert engine.REASON_TO_TRY == "Porque aún no pides en {vertical}."


def test_next_order_text_says_its_purpose_once():
    """«Para tu próximo pedido: …, para acompañar lo que pediste» repetía el «para»."""
    text = engine.NEXT_ORDER_TEXT.format(destino="bebidas gaseosas", vertical="Express")
    assert text == "Para tu próximo pedido: bebidas gaseosas, en Express."
