"""Preguntas en texto libre a Mochi (24-10, eval/frases_usuarios/preguntas-libres.txt) contra `rappi_ia_test`: cantidad
de personas, presupuesto con «con», consejo médico, fichas de platos y «con qué acompaño», con las guardias de
siempre."""

import pytest
from rappi_scraper.storage.search import build_search_documents

from conftest import add_dish, add_price, add_product, add_store
from rappi_ia.agent.rappi_agent import Context, RappiAgent
from rappi_ia.concepts.pipeline import build_concepts
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents


@pytest.fixture
def agent(db):
    add_store(db, 1, "supermercado", "Súper")
    add_store(db, 2, "licores", "Botillería")
    add_store(db, 3, "restaurantes", "Poke Bar")
    add_store(db, 4, "farmacia", "Farmacia")
    products = [
        (100, "Salmón fresco filete 500 g", 1, "Pescados", 8990),
        (101, "Lechuga costina", 1, "Verduras", 990),
        (102, "Tomate larga vida kilo", 1, "Verduras", 1990),
        (103, "Asado de tira vacuno 1 kg", 1, "Carnes", 12990),
        (104, "Carbón de espino 2,5 kg", 1, "Carbón", 3990),
        (105, "Sopa instantánea de pollo", 1, "Sopas", 690),
        (200, "Vino tinto Cabernet 750 cc", 2, "Vinos", 4990),
        (201, "Mojito listo para tomar 350 cc", 2, "Cócteles", 1990),
        (202, "Ramitas saladas 200 g", 2, "Snacks salados", 1290),
        (203, "Papas fritas corrugadas 150 g", 2, "Snacks salados", 1490),
        (106, "Papas fritas lisas 180 g", 1, "Snacks salados", 1590),
        (300, "Paracetamol 500 mg para la fiebre 16 comprimidos", 4, "Analgésicos tópicos", 1990),
        (301, "Tapsin Día fiebre y resfrío 18 comprimidos", 4, "Analgésicos tópicos", 2990),
    ]
    for pid, name, store, category, price in products:
        add_product(db, pid, name, store, category)
        add_price(db, store, pid, price)
    add_dish(db, 500, "Poke de salmón", 3, "Pokes", ["Pokes"])
    db.execute("INSERT INTO scrape_runs (run_id, kind, status) VALUES (999, 'restaurants', 'done')")
    db.execute("INSERT INTO menu_price_snapshots (run_id, item_id, price) VALUES (999, 500, 7990)")
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, HashEmbedder())
    return RappiAgent(HashEmbedder()), db


def test_medical_advice_is_not_given_and_no_remedies_are_shown(agent):
    """«¿qué le doy?» pide que Mochi elija un remedio: no lo hace, dice a quién preguntarle y deja ir a Farmacia."""
    rappi, db = agent
    r = rappi.reply(db, "mi hijo tiene fiebre, ¿qué le doy?", Context())
    assert r["intent"]["kind"] == "consejo" and r["products"] == [] and not r["unmet"]
    assert "químico farmacéutico" in r["text"] and "pediatra" in r["text"]
    assert r["actions"] == [{"label": "Ir a Farmacia", "vertical": "farmacia"}]
    assert "pediatra" not in rappi.reply(db, "qué me tomo para la fiebre", Context())["text"]


def test_a_symptom_shows_only_remedies_that_name_it(agent):
    """«tengo fiebre» muestra lo que se vende para la fiebre; «tengo tos», sin nada que la nombre, ya no trae
    analgésicos: lo dice y, si hay, algo para cuidarse que no es salud."""
    rappi, db = agent
    fever = rappi.reply(db, "tengo fiebre", Context())
    assert {p["entity_id"] for p in fever["products"]} == {"300", "301"}
    cough = rappi.reply(db, "tengo tos", Context())
    assert all(p["concept"] != "medicamentos" for p in cough["products"])
    assert cough["text"].startswith("No encontré en Farmacia un remedio") and not cough["unmet"]
    assert not cough.get("suggestion") and not cough.get("also_in")


def test_how_many_people_is_said_and_the_asado_gets_its_amount(agent):
    rappi, db = agent
    r = rappi.reply(db, "¿qué llevo para un asado de 6?", Context())
    assert r["products"] and r["intent"]["occasion"] == "asado"
    assert "Para 6 personas, calcula unos 2,1 kg de carne." in r["text"]


def test_a_budget_said_with_con_is_a_price_cap(agent):
    rappi, db = agent
    r = rappi.reply(db, "qué puedo comprar con 2 mil pesos de verduras", Context(vertical="supermercado"))
    assert r["intent"]["price_max"] == 2000
    assert all(p["price_value"] <= 2000 for p in r["products"])


def test_what_is_a_dish_says_its_card_and_shows_it(agent):
    rappi, db = agent
    r = rappi.reply(db, "¿qué es un poke?", Context())
    assert r["text"].startswith("Un poke es un bowl hawaiano")
    assert r["intent"]["kind"] == "que_es" and r["intent"]["dish"] == "poke"
    assert [p["name"] for p in r["products"]] == ["Poke de salmón"]


def test_what_goes_with_a_dish_shows_its_complement_never_alcohol(agent):
    """El complemento curado más fuerte del pescado es el vino (alcohol): Mochi no lo propone y sale la verdura."""
    rappi, db = agent
    r = rappi.reply(db, "¿con qué acompaño un salmón?", Context())
    assert r["intent"]["kind"] == "acompanar"
    assert {p["concept"] for p in r["products"]} == {"verduras"}
    assert not r["age_notice"] and "verduras" in r["text"]


def test_a_named_drink_is_searched_like_the_search_does(agent):
    """Alcohol pedido por su nombre: se busca, con el aviso +18 (no es una oferta de Mochi)."""
    rappi, db = agent
    r = rappi.reply(db, "qué trago me recomiendas", Context())
    assert [p["entity_id"] for p in r["products"]] == ["201"] and r["age_notice"]


def test_mochi_does_not_take_you_to_licores_unless_you_ask_for_alcohol(agent):
    """Los snacks pesan más en Licores (es para el carrete): sin pedir alcohol ni estar en Licores, Mochi responde desde
    otra vertical que los tenga; desde la pantalla de Licores o nombrándola, ahí."""
    rappi, db = agent
    assert rappi.reply(db, "se me antoja algo salado", Context())["vertical"] == "supermercado"
    assert rappi.reply(db, "algo salado", Context(vertical="licores"))["vertical"] == "licores"
    assert rappi.reply(db, "algo salado en la botillería", Context())["vertical"] == "licores"


def test_what_is_does_not_carry_the_previous_request(agent):
    """«pañales» y después «¿qué es un poke?» mostraba pañales: la ficha no sigue el pedido anterior."""
    rappi, db = agent
    previous = {"query": "salmon", "concepts": ["pescados-mariscos"], "vertical": "supermercado", "product_ids": []}
    r = rappi.reply(db, "¿qué es un poke?", Context(previous=previous))
    assert [p["name"] for p in r["products"]] == ["Poke de salmón"] and not r["intent"]["follow_up"]


def test_an_occasion_said_without_naming_alcohol_brings_none(agent):
    rappi, db = agent
    for text in ["algo para el carrete", "una cena romántica para dos"]:
        r = rappi.reply(db, text, Context())
        assert r["vertical"] != "licores" and not r["age_notice"], text
        assert not any(p["concept"] in {"cerveza", "vino", "espumante", "cocteles"} for p in r["products"]), text


def test_health_answers_say_so_for_the_app(agent):
    """La app oculta sus ideas («Arma un carrete») bajo una respuesta de salud: el intent dice si habló de síntomas."""
    rappi, db = agent
    assert rappi.reply(db, "tengo tos", Context())["intent"]["symptom"]
    assert rappi.reply(db, "mi hijo tiene fiebre, ¿qué le doy?", Context())["intent"]["symptom"]
    assert not rappi.reply(db, "salmón", Context())["intent"]["symptom"]


def test_what_goes_with_in_rappi_hoy_is_a_plain_search(agent):
    rappi, db = agent
    r = rappi.reply(db, "¿con qué acompaño un salmón?", Context(mode="actual"))
    assert not r["text"].startswith("No se me ocurre")
