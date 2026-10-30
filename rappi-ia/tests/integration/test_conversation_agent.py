"""Conversar con Mochi (25-10, docs/diseno/2026-10-25-mochi-conversacion-design.md) contra `rappi_ia_test`: cada
respuesta trae `conversation`, el estado que la app devuelve como `previous`, y el seguimiento hereda el tope, las
personas, el orden, la ocasión y lo que no va."""

from dataclasses import replace

import pytest
from rappi_scraper.storage.search import build_search_documents

from conftest import add_dish, add_price, add_product, add_store
from rappi_ia.agent.rappi_agent import Context, RappiAgent
from rappi_ia.concepts.pipeline import build_concepts
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents

GROCERIES = [  # (id, nombre, categoría, precio) del súper
    (100, "Asado de tira vacuno 1 kg", "Res", 12990),
    (101, "Asado carnicero vacuno 800 g", "Res", 8990),
    (102, "Plateada para asado 1 kg", "Res", 10990),
    (103, "Albóndigas de vacuno 500 g", "Res", 2990),
    (104, "Carbón de espino 2,5 kg", "Carbón, Leña y chispa", 3990),
    (110, "Quesillo sin lactosa 380 g", "Quesos frescos", 1990),
    (111, "Queso mantecoso laminado 250 g", "Quesos maduros", 2990),
    (112, "Pan amasado 6 unidades", "Pan salado fresco", 1890),
    (113, "Manjar sin lactosa 400 g", "Pasta dulce para untar", 2490),
    (114, "Café molido tradicional 250 g", "Café", 4990),
    (115, "Leche sin lactosa entera 1 L", "Leche natural", 1290),
    (116, "Torta de chocolate 12 porciones", "Tortas y ponques", 14990),
    (117, "Gomitas surtidas 500 g", "Gomitas y caramelos", 2490),
    (118, "Globos de colores 25 unidades", "Bombas y Globos", 1990),
    (119, "Rompecabezas infantil 48 piezas", "Rompecabezas", 6990),
    (120, "Bebida cola 3 L", "Gaseosas", 2290),
    (121, "Bebida naranja 1,5 L", "Gaseosas", 1490),
]
WINES = [
    (200, "Vino tinto reserva 750 cc", 4990),
    (201, "Vino tinto gran reserva 750 cc", 9490),
    (202, "Vino tinto icono 750 cc", 25990),
    (203, "Vino tinto clásico 750 cc", 3990),
]
EXPRESS = [
    (300, "Helado de leche chocolate 1 L", "Helados", 3990),
    (301, "Helado de leche vainilla 1 L", "Helados", 3490),
    (302, "Bebida cola 1,5 L", "Gaseosas", 1590),
    (303, "Bebida limón 1,5 L", "Gaseosas", 1490),
]
DISHES = [  # (id, nombre, tienda, sección, precio)
    (500, "Pizza pepperoni familiar", 3, "Pizzas", 12990),
    (501, "Pizza vegetariana familiar", 3, "Pizzas", 11990),
    (502, "Pizza Carnivori familiar", 3, "Pizzas", 14990),
    (503, "Pizza veggie mediana", 3, "Pizzas", 8990),
    (510, "Desayuno para dos", 5, "Desayunos", 15990),
    (511, "Desayuno americano", 5, "Desayunos", 9990),
]


@pytest.fixture
def talk(db):
    add_store(db, 1, "supermercado", "Súper")
    add_store(db, 2, "licores", "Botillería")
    add_store(db, 3, "restaurantes", "Pizzería")
    add_store(db, 4, "conveniencia", "Express")
    add_store(db, 5, "restaurantes", "Café del barrio")
    for pid, name, category, price in GROCERIES:
        add_product(db, pid, name, 1, category)
        add_price(db, 1, pid, price)
    for pid, name, price in WINES:
        add_product(db, pid, name, 2, "Vino tinto")
        add_price(db, 2, pid, price)
    for pid, name, category, price in EXPRESS:
        add_product(db, pid, name, 4, category)
        add_price(db, 4, pid, price)
    db.execute("INSERT INTO scrape_runs (run_id, kind, status) VALUES (999, 'restaurants', 'done')")
    for pid, name, store, section, price in DISHES:
        add_dish(db, pid, name, store, section, [section])
        db.execute("INSERT INTO menu_price_snapshots (run_id, item_id, price) VALUES (999, %s, %s)", (pid, price))
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, HashEmbedder())
    agent = RappiAgent(HashEmbedder())

    def say(*messages: str, vertical: str | None = None) -> list[dict]:
        """Una conversación: cada mensaje lleva el `conversation` de la respuesta anterior, como la app."""
        replies, previous = [], None
        for message in messages:
            reply = agent.reply(db, message, Context(vertical=vertical, previous=previous))
            replies.append(reply)
            previous = reply["conversation"]
        return replies

    return say


def _ids(reply: dict) -> list[str]:
    return [p["entity_id"] for p in reply["products"]]


def test_every_answer_says_how_to_follow_it(talk):
    (pizza,) = talk("pizza", vertical="restaurantes")
    state = pizza["conversation"]
    assert state["concepts"] == ["pizza"] and state["vertical"] == "restaurantes" and state["query"] == "pizza"
    assert state["product_ids"] == _ids(pizza) and state["price_max"] is None and state["order"] is None
    (hello,) = talk("hola")
    assert hello["conversation"] is None
    (advice,) = talk("mi hijo tiene fiebre, ¿qué le doy?")
    assert advice["conversation"] is None


def test_another_option_keeps_the_cap_and_never_repeats(talk):
    """ "un vino hasta 10 mil" → "otra opción" volvía a mostrar vinos de $25.990; "otra" dos veces repetía la
    primera."""
    first, other = talk("un vino hasta 10 mil", "otra opción", vertical="licores")
    assert first["products"] and all(p["price_value"] <= 10000 for p in other["products"])
    assert not set(_ids(first)) & set(_ids(other))
    assert other["conversation"]["price_max"] == 10000
    assert set(other["conversation"]["product_ids"]) == set(_ids(first)) | set(_ids(other))


def test_without_meat_shows_only_what_says_it_has_none(talk):
    """pizza → "sin carne" mostraba una "Pizza Carnivori" y una de pepperoni: no dicen "carne"."""
    pizza, veggie = talk("pizza", "sin carne", vertical="restaurantes")
    assert {p["name"] for p in veggie["products"]} == {"Pizza vegetariana familiar", "Pizza veggie mediana"}
    assert "sin carne" in veggie["text"] and veggie["conversation"]["query"] == "pizza sin carne"


def test_a_diet_nothing_says_is_said_not_faked(talk):
    """helado → "sin lactosa" mostraba helados de leche: si ningún nombre lo dice, Mochi lo dice."""
    ice_cream, lactose_free = talk("helado", "sin lactosa", vertical="conveniencia")
    assert ice_cream["products"] and lactose_free["products"] == []
    assert lactose_free["text"].startswith("No encontré") and "sin lactosa" in lactose_free["text"]


def test_without_alcohol_on_soft_drinks_changes_nothing(talk):
    """ "¿y para tomar?" → "sin alcohol" llevaba a Licores: las bebidas ya no tienen alcohol."""
    drinks, still = talk("algo para tomar", "sin alcohol", vertical="conveniencia")
    assert still["vertical"] == "conveniencia" and set(_ids(still)) == set(_ids(drinks))


def test_an_occasion_follow_up_is_still_the_occasion(talk):
    """ "once para 4" → "sin lactosa": lo de la once que dice "sin lactosa", para las mismas 4 personas."""
    once, without = talk("algo para una once para 4", "sin lactosa", vertical="supermercado")
    assert once["intent"]["occasion"] == "once" and once["conversation"]["occasion"] == "once"
    assert once["conversation"]["concepts"] == []  # una ocasión sin nombrar productos
    assert without["products"] and all("sin lactosa" in p["name"].lower() for p in without["products"])
    assert without["intent"]["occasion"] == "once" and "Para 4 personas" in without["text"]


def test_a_cheaper_asado_is_still_an_asado(talk):
    """ "asado de 6" → "¿y algo más barato?" traía albóndigas: eran las carnes más baratas, no cortes para el asado."""
    asado, cheaper = talk("¿qué llevo para un asado de 6?", "¿y algo más barato?")
    prices = [p["price_value"] for p in cheaper["products"]]
    assert cheaper["products"] and prices == sorted(prices) and "103" not in _ids(cheaper)
    assert "Para 6 personas, calcula unos 2,1 kg de carne." in cheaper["text"]
    assert cheaper["conversation"]["order"] == "barato" and cheaper["conversation"]["people"] == 6


def test_more_people_replaces_the_count(talk):
    once, more = talk("algo para una once para 4", "para 10 personas", vertical="supermercado")
    assert "Para 10 personas" in more["text"] and more["conversation"]["people"] == 10


def test_a_vertical_without_it_is_said_and_not_noted_as_missing(talk):
    """desayuno para dos → "en el súper mejor": "No encontré… Lo anoté" y RappiFavor, aunque hay en restaurantes."""
    breakfast, grocery = talk("desayuno para dos", "en el súper mejor")
    assert breakfast["vertical"] == "restaurantes" and grocery["vertical"] == "supermercado"
    assert grocery["products"] == [] and not grocery["unmet"] and "restaurantes" in grocery["text"]
    assert "Lo anoté" not in grocery["text"]


def test_an_occasion_shows_a_bit_of_each_thing(talk, monkeypatch):
    """ "cumpleaños de mi hijo, somos 10" mostraba solo decoración: la búsqueda con todos los nombres de la ocasión
    ("Pastelería Decoración Golosinas…") traía eso en el catálogo real. Ahora el súper, repartido entre sus
    conceptos."""
    from rappi_ia.agent import rappi_agent as module

    real = module.search_products

    def like_the_real_catalog(conn, vertical, query, *args, **kwargs):  # la búsqueda conjunta: solo decoración
        outcome = real(conn, vertical, query, *args, **kwargs)
        if len(query.split()) > 2:
            return replace(outcome, products=[p for p in outcome.products if p.concept == "decoracion"])
        return outcome

    monkeypatch.setattr(module, "search_products", like_the_real_catalog)
    (birthday,) = talk("cumpleaños de mi hijo, somos 10")
    assert birthday["vertical"] == "supermercado"
    assert len({p["concept"] for p in birthday["products"]}) >= 4


def test_a_new_topic_does_not_drag_the_previous_one(talk):
    pizza, wine = talk("pizza sin carne", "vino tinto", vertical="restaurantes")
    assert not wine["intent"]["follow_up"] and wine["conversation"]["query"] == "vino tinto"
