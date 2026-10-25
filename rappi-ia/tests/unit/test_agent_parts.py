"""Piezas del agente sin base de datos: verificador del texto del LLM y entendimiento de precios."""

from types import SimpleNamespace

import pytest

from rappi_ia.agent.compose import AGE_NOTICE, ClaudeComposer, Draft, TemplateComposer, facts, verify_llm_text
from rappi_ia.agent.rappi_agent import RappiAgent
from rappi_ia.agent.understand import Intent, Understander, _clean, _price


def test_llm_text_verifier():
    refs = {"p1": "Cerveza Escudo 470 cc"}
    assert verify_llm_text("¡Te recomiendo {p1}!", refs) == "¡Te recomiendo Cerveza Escudo 470 cc!"
    assert verify_llm_text("{p1} a solo $990", refs) is None  # cifras propias
    assert verify_llm_text("Prueba {p2}", refs) is None  # marcador desconocido


def test_claude_composer_gives_up_quickly():
    """Si Claude no responde, la plantilla contesta en segundos (por defecto el SDK espera 10 min × 3 intentos)."""
    pytest.importorskip("anthropic")
    composer = ClaudeComposer(api_key="sin-clave")

    assert composer._client.timeout == 6
    assert composer._client.max_retries == 1


def _text(text):
    return SimpleNamespace(type="text", text=text)


def _reply(*content, stop_reason="end_turn"):
    """Una respuesta de la API de mensajes con sus bloques de contenido."""
    return SimpleNamespace(content=list(content), stop_reason=stop_reason)


def _composer(create):
    composer = ClaudeComposer.__new__(ClaudeComposer)  # sin red ni clave
    composer.model, composer._fallback = "claude-sonnet-5", TemplateComposer()
    composer._client = SimpleNamespace(messages=SimpleNamespace(create=create))
    return composer


RESULTS = Draft(kind="resultados", concept_label="🍺 Cerveza", vertical_label="Licores", product_names=["Escudo"])


def test_claude_thinking_block_then_text_uses_text():
    """Un bloque de pensamiento antes del texto no tiene `.text`: antes eso caía siempre a la plantilla."""
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        thinking = SimpleNamespace(type="thinking", thinking="", signature="x")
        return _reply(thinking, _text('{"text": "Mira, te dejo {p1} bien helada."}'))

    assert _composer(create).compose(RESULTS) == "Mira, te dejo Escudo bien helada."
    assert sent["thinking"] == {"type": "disabled"}  # 200 tokens no alcanzan para pensar y redactar


@pytest.mark.parametrize(
    ("model", "options"),
    [
        ("claude-sonnet-5", {"max_tokens": 200, "thinking": {"type": "disabled"}}),
        ("claude-opus-5", {"max_tokens": 200, "thinking": {"type": "disabled"}}),
        # Rechaza "disabled": between_tools no piensa en una respuesta sin herramientas.
        ("claude-sonnet-5-5", {"max_tokens": 200, "thinking": {"type": "between_tools"}}),
        # No se puede apagar: esfuerzo bajo y espacio para pensar antes del texto.
        ("claude-opus-5-5", {"max_tokens": 2000, "output_config": {"effort": "low"}}),
        ("claude-fable-5", {"max_tokens": 2000}),  # "disabled" es un 400: desconocido, sin `thinking`
        ("otro-modelo", {"max_tokens": 2000}),
    ],
)
def test_thinking_options_follow_the_model(model, options):
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return _reply(_text('{"text": "Mira, te dejo {p1} bien helada."}'))

    composer = _composer(create)
    composer.model = model
    assert composer.compose(RESULTS) == "Mira, te dejo Escudo bien helada."
    assert {k: v for k, v in sent.items() if k in ("max_tokens", "thinking", "output_config")} == options


def test_claude_max_tokens_logs_reason(caplog):
    cut = _reply(_text('{"text": "Mira, te dejo'), stop_reason="max_tokens")
    with caplog.at_level("WARNING"):
        assert _composer(lambda **_: cut).compose(RESULTS) == TemplateComposer().compose(RESULTS)
    assert "max_tokens" in caplog.text

    for reply, reason in [
        (_reply(SimpleNamespace(type="thinking", thinking="", signature="x")), "sin_texto"),
        (_reply(_text('{"text": "Todo a $100"}')), "verificador"),
    ]:
        caplog.clear()
        with caplog.at_level("WARNING"):
            _composer(lambda r=reply, **_: r).compose(RESULTS)
        assert reason in caplog.text, reason

    def boom(**_):
        raise ConnectionError("sin red")

    caplog.clear()
    with caplog.at_level("WARNING"):
        _composer(boom).compose(RESULTS)
    assert "error:ConnectionError" in caplog.text


def test_claude_composer_falls_back_to_template_on_any_failure():
    composer = ClaudeComposer.__new__(ClaudeComposer)  # sin red ni clave
    composer.model = "test"
    composer._fallback = TemplateComposer()

    def boom(**_):
        raise ConnectionError("sin red")

    composer._client = SimpleNamespace(messages=SimpleNamespace(create=boom))
    draft = Draft(kind="resultados", concept_label="🍺 Cerveza", vertical_label="Licores", age_notice=True)
    assert composer.compose(draft) == TemplateComposer().compose(draft)

    def invents_prices(**_):
        return _reply(_text('{"text": "Todo a $100"}'))

    composer._client = SimpleNamespace(messages=SimpleNamespace(create=invents_prices))
    assert "$100" not in composer.compose(draft)


def test_price_parsing_ignores_units_and_small_numbers():
    assert _price("cerveza bajo 2 mil")[0] == 2000
    assert _price("vino hasta $12.990")[0] == 12990
    assert _price("snacks bajo 5k")[0] == 5000
    assert _price("pisco bajo 8000")[0] == 8000
    for text in [
        "arroz hasta 5 kilos",
        "pañales hasta 12 kg",
        "leche no mas de 2 litros",
        "cerveza bajo 5 grados",
        "pizza para hasta 4 personas",
        "algo bajo 5",
        "vino bajo $5,5",  # un decimal sin mil/lucas/k no es precio (se leía como $5)
        "vino bajo $2.5",
    ]:
        assert _price(text)[0] is None, text
    assert "3 mil" not in _price("cerveza bajo 3 mil")[1]  # la frase de precio sale de la consulta


@pytest.mark.parametrize(
    "text, value, rest",
    [
        ("vino bajo 1,5 lucas", 1500, ["vino"]),
        ("vino bajo 2.5 lucas", 2500, ["vino"]),
        ("snacks hasta 1,5k", 1500, ["snacks"]),
        ("completo por menos de 1000 pesos", 1000, ["completo"]),
        ("cerveza bajo 5 mil pesos", 5000, ["cerveza"]),
        ("pisco hasta $8.000 clp", 8000, ["pisco"]),
        # «u» es la «o» antes de otra o, no «unidades»: el tope se perdía.
        ("pisco bajo 5,5 lucas u otro trago", 5500, ["pisco", "u", "otro", "trago"]),
        ("vino bajo 2,5 lucas u otra cosa", 2500, ["vino", "u", "otra", "cosa"]),
        ("vino bajo $2.5 lucas u otra cosa", 2500, ["vino", "u", "otra", "cosa"]),
        ("vino bajo 10 mil u otra cosa", 10000, ["vino", "u", "otra", "cosa"]),
        # Coma de miles: «$10,000» se leía como un tope de $10 y dejaba «,000» en la consulta.
        ("vino hasta $10,000", 10000, ["vino"]),
        ("pisco bajo 12,990 pesos", 12990, ["pisco"]),
    ],
)
def test_price_parsing_accepts_decimal_thousands_and_drops_the_currency_word(text, value, rest):
    """«1,5 lucas» no se entendía (el tope se ignoraba sin aviso y la consulta quedaba con «1 5 lucas») y «pesos»
    quedaba en la consulta: «Mira estas opciones de «completo pesos»»."""
    price, without = _price(text)
    assert price == value and without.split() == rest


def test_price_parsing_still_ignores_decimal_units():
    assert _price("cerveza bajo 4.5 grados")[0] is None
    assert _price("bebida hasta 1,5 litros")[0] is None


@pytest.mark.parametrize(
    "text",
    [
        "bebida hasta 1,5 mil ml",
        "cerveza hasta 1,5 mil cc",
        "bajo 1,5 k kg",
        "pañales bajo $2.5 mil u",
    ],
)
def test_a_decimal_followed_by_a_unit_is_not_a_price_and_does_not_fail(text):
    """Si a «mil/lucas/k» le sigue una unidad, la regex soltaba esa palabra y se quedaba con «5,5» a secas:
    float('5,5') lanzaba ValueError (HTTP 400 en /agent/ask) y «$2.5» se leía como $25."""
    assert _price(text)[0] is None


def test_clean_query_drops_greeting_and_request_words():
    assert _clean("hola mochi quiero sushi") == "sushi"
    assert _clean("buenas tardes tienen kombucha") == "kombucha"


def test_clean_query_drops_courtesy_at_the_end():
    """«quiero té porfa» buscaba «te porfa»: sin concepto, la búsqueda vectorial traía pasteles y porotos."""
    assert _clean("quiero te porfa") == "te"
    assert _clean("te por favor") == "te"
    assert _clean("una pizza gracias mochi") == "pizza"
    assert _clean("pan para una") == "pan para una"  # solo cortesía: un artículo al final no se toca


def test_greeting_and_thanks_combos_are_not_searches():
    u = Understander()
    for text in ["hola buenas", "hola, buenas tardes", "hola mochi"]:
        assert u.understand(None, text, "licores").kind == "saludo", text
    for text in ["ok gracias", "gracias mochi", "muchas gracias!"]:
        assert u.understand(None, text, "licores").kind == "gracias", text


def test_brand_words_do_not_switch_vertical():
    u = Understander()
    assert u.understand(None, "cigarros pall mall", "conveniencia").vertical == "conveniencia"
    assert u.understand(None, "chocolate super 8", "conveniencia").vertical == "conveniencia"
    mention = u.understand(None, "leche del super", "conveniencia")
    assert (mention.vertical, mention.explicit_vertical) == ("supermercado", True)


def test_symptoms_alone_do_not_name_medicines():
    intent = Understander().understand(None, "tengo fiebre y dolor de cabeza", "supermercado")
    assert intent.symptom and "medicamentos" not in intent.concepts
    assert "medicamentos" not in Understander().understand(None, "me siento enfermo", "supermercado").concepts


def test_symptoms_starting_with_me_are_detected():
    """«me» es palabra de pedido y se quitaba al inicio antes de buscar síntomas y ocasiones: «me siento mal» y
    «me duele la cabeza» no contaban como síntoma y buscaban «duele la cabeza»."""
    u = Understander()
    for text in ["me siento mal", "me duele la cabeza", "Me duele la guata"]:
        intent = u.understand(None, text, "supermercado")
        assert intent.symptom and intent.occasion == "enfermo", text
    assert u.understand(None, "me duele la cabeza", "supermercado").query == "duele la cabeza"  # la consulta, limpia


def test_feeling_unwell_is_a_symptom_even_after_another_occasion():
    """«malestar» y «cuidarme» son de la ocasión «Me siento mal», pero solo contaban como síntoma si esa ocasión era la
    mejor, y a igual largo gana la que va primero: «un tecito para el malestar» (once) o «después del carrete tengo
    malestar» permitían Licores, venta cruzada y «También en»."""
    u = Understander()
    for text in [
        "un tecito para el malestar",
        "despues del carrete tengo malestar",
        "después del carrete quiero cuidarme",
    ]:
        assert u.understand(None, text, "supermercado").symptom, text
    assert not u.understand(None, "un tecito para la once", "supermercado").symptom


def test_llm_verifier_blocks_claims_invented_names_and_spelled_numbers():
    refs = {"p1": "Cerveza Escudo 470 cc"}
    allowed = "Cerveza Escudo 470 cc 🍺 cerveza Licores"
    assert (
        verify_llm_text("Te recomiendo {p1}, bien heladita.", refs, allowed)
        == "Te recomiendo Cerveza Escudo 470 cc, bien heladita."
    )
    for bad in [
        "{p1} es sin alcohol y el más barato",
        "Llévate {p1} y una Kunstmann Torobayo",
        "cuesta mil novecientos pesos {p1}",
        "{p1} con envío gratis",
    ]:
        assert verify_llm_text(bad, refs, allowed) is None, bad


def test_llm_never_sees_the_user_query_and_notices_are_added_in_code():
    draft = Draft(
        kind="sin_resultado",
        query="kebab, mi rut 12.345.678-5 y fono +56 9 1234 5678",
        vertical_label="restaurantes",
        age_notice=True,
    )
    payload = facts(draft, {})
    assert "query" not in payload and "12.345" not in str(payload)

    composer = ClaudeComposer.__new__(ClaudeComposer)
    composer.model, composer._fallback = "test", TemplateComposer()
    composer._client = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **_: _reply(_text('{"text": "Uy, eso no lo tengo por ahora."}')))
    )
    text = composer.compose(draft)
    assert text.startswith("Uy, eso no lo tengo") and text.endswith(AGE_NOTICE)


def test_off_topic_results_are_not_labelled_as_the_requested_concept():
    """'un lomo saltado' (peruana) que solo calza por palabras con pastas del súper: se cita la consulta."""
    intent = Intent("buscar", "un lomo saltado", concepts=["peruana"], explicit_concepts=True, query="lomo saltado")
    pasta = SimpleNamespace(name="Vivaldi Chef Pasta Fetuccini", concept="pastas", age_restricted=False)
    no_cheapest = SimpleNamespace(cheapest_without_filter=None)
    draft = RappiAgent()._draft(intent, "supermercado", [pasta], no_cheapest, None, False)
    assert draft.concept_label is None
    assert "«lomo saltado»" in TemplateComposer().compose(draft) and "peruana" not in TemplateComposer().compose(draft)


def test_services_are_recognized_when_no_product_is_named():
    u = Understander()
    for text, service in [
        ("me voy de vacaciones a la playa", "rappitravel"),
        ("busco un vuelo a buenos aires", "rappitravel"),
        ("necesito un hotel en viña", "rappitravel"),
        ("se me quedaron las llaves en la oficina", "rappifavor"),
        ("necesito enviar un paquete a providencia", "rappifavor"),
        ("quiero hacer un tramite en correos de chile", "rappifavor"),
    ]:
        intent = u.understand(None, text, None)
        assert (intent.kind, intent.service) == ("servicio", service), text
    # Si nombra un producto, manda el producto: «paquete de pañales» no es un envío.
    assert u.understand(None, "un paquete de pañales", "supermercado").service is None
    assert u.understand(None, "bloqueador para el viaje", "farmacia").concepts[:1] == ["dermocosmetica"]


def test_la_mascota_se_presenta_como_mochi():
    """La mascota del prototipo es Mochi (una mochila, no un gato): así se presenta en el saludo y en la ayuda."""
    for kind in ("saludo", "ayuda"):
        text = TemplateComposer().compose(Draft(kind=kind))
        assert "Soy Mochi" in text and "😺" not in text, text
    for kind in ("gracias", "fuera"):  # tampoco habla como gato en el resto de las respuestas
        text = TemplateComposer().compose(Draft(kind=kind))
        assert "😺" not in text and "😸" not in text, text


def test_help_and_empty_texts_give_sushi_as_the_example_not_the_party():
    """La demo parte con algo simple: el sushi. El carrete sigue existiendo como ocasión, pero no es el ejemplo."""
    for kind in ("ayuda", "vacio"):
        text = TemplateComposer().compose(Draft(kind=kind))
        assert "sushi" in text and "carrete" not in text, text


def test_claude_puede_nombrar_a_mochi():
    """«Mochi» es el nombre de la mascota, no un producto inventado: la verificación no descarta el texto por él."""
    refs = {"p1": "Cerveza Escudo 470 cc"}
    text = verify_llm_text("¡Hola! Aquí Mochi: te recomiendo {p1}.", refs)
    assert text == "¡Hola! Aquí Mochi: te recomiendo Cerveza Escudo 470 cc."


def test_agent_name_comes_from_config(monkeypatch):
    """El nombre visible del agente sale de `config.AGENT_NAME`: cambiarlo cambia el saludo y la ayuda."""
    from rappi_ia import config

    monkeypatch.setattr(config, "AGENT_NAME", "Lupe")
    for kind in ("saludo", "ayuda"):
        text = TemplateComposer().compose(Draft(kind=kind))
        assert "Soy Lupe" in text and "Mochi" not in text, text
    refs = {"p1": "Cerveza Escudo 470 cc"}
    assert verify_llm_text("¡Hola! Aquí Lupe: te recomiendo {p1}.", refs)  # el nombre de la config no es un invento


def test_unmet_note_has_no_pronoun_that_must_agree_with_the_query():
    """«sepa que lo buscas» no concuerda con «empanadas» ni «la leche»: la nota no lleva pronombre."""
    for query in ("empanadas", "la leche", "kebab"):
        text = TemplateComposer().compose(
            Draft(kind="sin_resultado", query=query, vertical_label="restaurantes", unmet=True)
        )
        assert "Lo anoté" in text and " lo buscas" not in text and "sepa que buscas eso" in text
