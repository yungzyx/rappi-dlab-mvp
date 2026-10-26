"""Las preferencias explícitas con el agente sin base (offers/preferences.py): qué frases las fijan, qué sacan, qué
ordenan y qué dice el agente. También los atajos de la ayuda (sin salud) y las intenciones `resumen` y `pedido`."""

import re
from pathlib import Path

import pytest

from rappi_ia.agent import rappi_agent as agent
from rappi_ia.agent.compose import Draft, TemplateComposer
from rappi_ia.agent.rappi_agent import HELP_ACTIONS, HELP_EXAMPLES, Context, RappiAgent
from rappi_ia.agent.understand import Understander
from rappi_ia.offers import preferences as prefs

U = Understander()


@pytest.mark.parametrize(
    ("text", "action", "items"),
    [
        ("soy vegetariano", "agregar", [("dieta", "vegetariano")]),
        ("Soy vegetariana y alérgica al maní", "agregar", [("dieta", "vegetariano"), ("alergia", "mani")]),
        ("no como maní", "agregar", [("alergia", "mani")]),
        ("recuerda que soy celíaca", "agregar", [("alergia", "gluten")]),
        ("no tomo leche", "agregar", [("alergia", "lactosa")]),
        ("ya no soy vegano", "quitar", [("dieta", "vegano")]),
        ("ya no como carne", "agregar", [("dieta", "vegetariano")]),  # ahora no come: se agrega
        ("muéstrame mis preferencias", "mostrar", []),
        ("¿qué preferencias tengo?", "mostrar", []),
        ("olvida mis preferencias", "olvidar", []),
        ("mi comida favorita es el sushi", "agregar", [("cocina", "sushi")]),
        ("me encanta la comida mexicana", "agregar", [("cocina", "mexicana")]),
    ],
)
def test_what_is_said_sets_them(text, action, items):
    intent = U.understand(None, text, "supermercado")
    assert intent.kind == "preferencia"
    assert intent.preference.action == action
    assert list(intent.preference.items) == items


def test_a_favorite_store_is_read_without_its_article():
    assert prefs.read_command("mi tienda favorita es el Jumbo").store == "jumbo"
    assert prefs.read_command("prefiero pedir en Lider").store == "lider"


@pytest.mark.parametrize(
    "text",
    ["sushi sin maní", "galletas de maní", "leche sin lactosa", "yogurt", "olvida todo", "me gusta el sushi"],
)
def test_orders_and_other_questions_are_not_preferences(text):
    """Un pedido con «sin» no es una alergia, «olvida todo» es la memoria y «me gusta el sushi» se busca."""
    assert U.understand(None, text, "supermercado").kind != "preferencia"


def test_a_cuisine_that_is_not_food_is_not_a_favorite():
    assert U.understand(None, "mi comida favorita es la cerveza", "supermercado").kind != "preferencia"


def product(name, concept=None, entity_type="catalog_item", store=None):
    return {"name": name, "concept": concept, "entity_type": entity_type, "store": store}


def test_a_diet_drops_what_names_it_unless_the_name_says_it_fits():
    mine = prefs.build([("dieta", "vegetariano"), ("alergia", "mani")])
    assert not mine.keeps(product("Pizza pepperoni familiar", "pizza", "menu_item"))
    assert mine.keeps(product("Pizza margarita mediana", "pizza", "menu_item"))
    assert not mine.keeps(product("Hamburguesa doble queso", "hamburguesa", "menu_item"))  # su concepto es carne
    assert mine.keeps(product("Hamburguesa vegetal", "hamburguesa", "menu_item"))
    assert not mine.keeps(product("Pollo con vegetales", "pollo-preparado", "menu_item"))  # «vegetales» no basta
    assert not mine.keeps(product("Galletas de maní", "galletas"))
    assert mine.keeps(product("Galletas sin maní", "galletas"))


def test_only_food_is_filtered():
    """Lo que no es comida no se toca: un alimento de perro sabor carne no es la dieta de la persona."""
    mine = prefs.build([("dieta", "vegano")])
    assert mine.keeps(product("Alimento para perro sabor carne", "alimento-perro"))
    assert not mine.keeps(product("Queso gouda laminado", "quesos"))
    assert mine.keeps(product("Bebida de almendras", "lacteos"))


def test_favorites_only_order():
    mine = prefs.build([("cocina", "sushi"), ("tienda", "Jumbo")])
    shown = [product("Pizza", "pizza"), product("Roll", "sushi"), product("Arroz", None, store="Jumbo Bilbao")]
    ranked = mine.rank(shown)
    assert [p["name"] for p in ranked] == ["Roll", "Arroz", "Pizza"]
    assert mine.keep(shown) == shown  # ordenar no saca nada


def test_the_notice_names_what_is_left_out_and_only_with_food():
    mine = prefs.build([("dieta", "vegetariano"), ("alergia", "mani")])
    notice = mine.notice([product("Pizza", "pizza", "menu_item")])
    assert notice == "Por tus preferencias, saqué lo que dice tener carne o maní; revisa los ingredientes en la tienda."
    assert mine.notice([product("Shampoo", "cuidado-cabello")]) is None
    assert prefs.build([("cocina", "sushi")]).notice([product("Roll", "sushi")]) is None


def test_the_search_keeps_only_the_filters_and_says_when_it_emptied():
    """El buscador (`/search`) filtra con la dieta y las alergias pero no ordena; si sacó todo, igual lo dice."""
    mine = prefs.build([("dieta", "vegetariano"), ("cocina", "sushi"), ("tienda", "Jumbo")]).only_filters()
    shown = [product("Pizza", "pizza"), product("Roll", "sushi")]
    assert mine.rank(shown) == shown and mine.filters and not (mine.cuisines or mine.stores)
    assert prefs.build([("cocina", "sushi")]).only_filters().notice([product("Roll", "sushi")], dropped=1) is None
    assert "carne" in mine.notice([], dropped=2)
    assert mine.notice([]) is None


def test_applied_sets_them_only_for_the_turn():
    mine = prefs.build([("dieta", "vegano")])
    assert prefs.active() is None
    with prefs.applied(mine):
        assert prefs.active() is mine
    assert prefs.active() is None


def test_options_and_rules_are_data():
    found = prefs.load_options()
    assert {"vegetariano", "vegano", "mani", "mariscos", "gluten", "lactosa"} <= set(found.rules)
    assert "cerveza" not in found.cuisines and "sushi" in found.cuisines
    assert all(o["tipo"] in prefs.KINDS for o in prefs.options())
    assert prefs.valid("cocina", "sushi") and not prefs.valid("cocina", "vino")
    assert not prefs.valid("dieta", "mani")  # el maní es una alergia


def test_in_rappi_hoy_nothing_is_saved():
    reply = RappiAgent().reply(None, "soy vegetariano", Context(mode="actual", user_id="u-1"))
    assert reply["intent"]["kind"] == "preferencia" and "Rappi hoy" in reply["text"]
    assert "preferences" not in reply


# Mochi no tiene chat: ninguna respuesta pide que la persona le escriba (las acciones se tocan, el buscador busca).
ASKS_TO_WRITE = (
    *("dime", "dímel", "cuéntame", "escríbe", "pídeme", "me dices", "pregúntame", "por chat"),
    *("dile", "escríbele", "pídele que"),
)


@pytest.mark.parametrize(
    "kind",
    ["saludo", "gracias", "ayuda", "envio", "memoria", "receta", "pedido", "resumen", "fuera", "ofertas", "vacio"],
)
def test_no_fixed_text_asks_to_write_to_mochi(kind):
    for learns in (True, False):
        text = TemplateComposer().compose(Draft(kind=kind, learns=learns)).lower()
        assert not any(phrase in text for phrase in ASKS_TO_WRITE), (kind, text)


def test_the_agent_texts_do_not_ask_to_write_either():
    texts = [
        agent.ADVICE_NAME,
        agent.PREFERENCES_NO_USER,
        agent.PREFERENCES_NONE,
        agent.USUAL_NOT_FOUND,
        agent._listed_text([("dieta", "vegetariano")]),
    ]
    for text in texts:
        assert not any(phrase in text.lower() for phrase in ASKS_TO_WRITE), text


# Los textos de la app (prototipo-app y el panel): las cadenas y el texto de JSX, sin comentarios ni tests. Una frase
# cuenta si empieza una palabra («dile» sí, «dimensiones» no).
APPS = [Path(__file__).resolve().parents[3] / name / "src" for name in ("prototipo-app", "dashboard-empresa")]
_STRINGS = re.compile(r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"|`(?:[^`\\]|\\.)*`")
_JSX_TEXT = re.compile(r"[>}]([^<>{}]*)[<{]")
_COMMENTS = re.compile(r"/\*.*?\*/|(?<![:\\])//[^\n]*", re.S)


def _app_texts():
    for root in APPS:
        for path in sorted(root.rglob("*.js*")):
            if path.suffix not in (".js", ".jsx") or ".test." in path.name:
                continue
            code = _COMMENTS.sub(" ", path.read_text(encoding="utf-8"))
            yield from ((path, m.group(0)) for m in _STRINGS.finditer(code))
            if path.suffix == ".jsx":
                yield from ((path, m.group(1)) for m in _JSX_TEXT.finditer(code))


def test_the_app_texts_do_not_ask_to_write_either():
    """Lo que ve la persona en la app tampoco pide que le escriba a Mochi («Dile a Mochi…»)."""
    phrases = [re.compile(rf"(?<![\wáéíóúüñ]){re.escape(p)}") for p in ASKS_TO_WRITE]
    found = [(path.name, text) for path, text in _app_texts() if any(p.search(text.lower()) for p in phrases)]
    assert all(root.is_dir() for root in APPS)
    assert found == []


@pytest.mark.parametrize(("text", "kind"), [("hola", "saludo"), ("jajaja", "vacio")])
def test_a_greeting_or_an_empty_message_leaves_ideas_to_tap(text, kind):
    reply = RappiAgent().reply(None, text, Context())
    assert reply["intent"]["kind"] == kind and reply["actions"] == HELP_ACTIONS
    assert RappiAgent().reply(None, text, Context(mode="actual"))["actions"] == HELP_EXAMPLES


def test_no_preferences_yet_leads_to_the_sheet():
    assert "Mis preferencias" in agent.PREFERENCES_NONE and "soy vegetariano" not in agent.PREFERENCES_NONE


def test_help_shows_capabilities_and_no_health_example():
    """«¿Qué puedes hacer?» muestra lo que sabe hacer (repetir, armar un kit, algo para ti): ningún ejemplo de salud."""
    for actions in (HELP_ACTIONS, HELP_EXAMPLES):
        labels = " ".join(a["label"] + a.get("query", "") for a in actions).lower()
        assert "fiebre" not in labels and "remedio" not in labels
    assert {a.get("capability") for a in HELP_ACTIONS} >= {"recompra", "plan", "perfil"}
    reply = RappiAgent().reply(None, "¿qué puedes hacer?", Context())
    assert reply["actions"] == HELP_ACTIONS
    assert RappiAgent().reply(None, "¿qué puedes hacer?", Context(mode="actual"))["actions"] == HELP_EXAMPLES
    for learns in (True, False):
        assert "fiebre" not in TemplateComposer().compose(Draft(kind="ayuda", learns=learns))


@pytest.mark.parametrize("text", ["quiero pagar", "resumen de mi pedido", "¿qué llevo en el carro?", "cuánto llevo"])
def test_the_summary_is_a_review_before_paying(text):
    reply = RappiAgent().reply(None, text, Context())
    assert reply["intent"]["kind"] == "resumen"
    assert reply["actions"] == [{"label": "Revisar y pagar", "route": ["checkout"]}]
    assert "nunca hago el pedido por ti" in reply["text"]


def test_order_status_leads_to_my_orders():
    reply = RappiAgent().reply(None, "¿dónde viene mi pedido?", Context())
    assert reply["intent"]["kind"] == "pedido"
    assert reply["actions"] == [{"label": "Ver mis pedidos", "route": ["orders"]}]
