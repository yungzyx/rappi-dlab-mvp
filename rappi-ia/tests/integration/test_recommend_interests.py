"""«Qué me recomiendas» sin «No encontré» propio: si el interés más alto no trae nada, Mochi lo busca como se llaman sus
productos, pasa al siguiente interés y, si nada sirve, muestra los ejemplos de siempre. Nunca recomienda desde Farmacia
ni Licores (offers/guards.py). Contra `rappi_ia_test`."""

import pytest
from rappi_scraper.storage.search import build_search_documents

from conftest import add_price, add_product, add_store
from rappi_ia.agent import rappi_agent
from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.rappi_agent import Context, RappiAgent
from rappi_ia.concepts.pipeline import build_concepts
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents


@pytest.fixture
def catalog(db):
    add_store(db, 1, "supermercado", "Súper")
    add_store(db, 2, "licores", "Botillería")
    add_store(db, 3, "farmacia", "Botica")
    add_store(db, 4, "mall", "Mercería")
    products = [
        (100, "Papas fritas Lays Clásicas 180 g", 1, "Snacks salados", 1990),
        (101, "Papas fritas Marco Polo 150 g", 2, "Snacks salados", 1890),
        (102, "Papas fritas Kryzpo 130 g", 3, "Snacks salados", 2190),
        # Como en el Mall real: el nombre no dice «manualidades» ni «mercería».
        (300, "Lana Supersoft Gris Perla 100 Gr", 4, "Hilos", 2490),
        # Dice «guitarra» (la primera keyword de música) y es de cocina, como en el súper real.
        (400, "Set Parrillero Con Forma De Guitarra", 1, "Otros Cocina", 15990),
    ]
    for pid, name, store, category, price in products:
        add_product(db, pid, name, store, category)
        add_price(db, store, pid, price)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embedder = HashEmbedder()
    embed_search_documents(db, embedder)
    return db, embedder


class CountingComposer(TemplateComposer):
    """Como Claude (`remote`): anota qué redacta."""

    remote = True

    def __init__(self):
        self.kinds = []

    def compose(self, d):
        self.kinds.append(d.kind)
        return super().compose(d)


def ask(agent, db, vertical, profile):
    return agent.reply(db, "qué me recomiendas", Context(vertical=vertical, profile=profile))


def test_an_interest_whose_name_finds_nothing_is_searched_as_its_products_are_named(catalog):
    """Sin vectores, «Manualidades y mercería» no calza ningún nombre; su primera keyword («lana») sí."""
    db, _ = catalog
    agent = RappiAgent(None, TemplateComposer())

    r = ask(agent, db, "mall", {"manualidades": 3.0})

    assert r["text"].startswith("Por tu interés en 🧶 manualidades y mercería 😉")
    assert [p["entity_id"] for p in r["products"]] == ["300"]


def test_what_only_says_the_keyword_is_not_a_recommendation_of_the_interest(catalog):
    """«Por tu interés en 🎸 música…» con un set parrillero con forma de guitarra: el nombre dice la keyword, pero no
    es del interés. Una recomendación muestra productos del interés o pasa al siguiente."""
    db, _ = catalog
    agent = RappiAgent(None, TemplateComposer())

    r = ask(agent, db, "supermercado", {"musica": 3.0, "snacks-salados": 1.0})

    assert r["text"].startswith("Por tu interés en 🥨 snacks salados 😉")
    assert [p["entity_id"] for p in r["products"]] == ["100"]


def test_an_interest_with_nothing_here_gives_way_to_the_next_one(catalog):
    db, embedder = catalog
    agent = RappiAgent(embedder, TemplateComposer())

    r = ask(agent, db, "supermercado", {"manualidades": 3.0, "snacks-salados": 1.0})

    assert r["text"].startswith("Por tu interés en 🥨 snacks salados 😉")
    assert [p["entity_id"] for p in r["products"]] == ["100"]
    assert not r["unmet"] and "No encontré" not in r["text"]


def test_when_no_interest_finds_anything_the_examples_answer_and_nothing_is_noted(catalog):
    db, embedder = catalog
    agent = RappiAgent(embedder, TemplateComposer())

    r = ask(agent, db, "supermercado", {"manualidades": 3.0})

    assert r["intent"]["kind"] == "ayuda" and r["actions"] and not r["products"]
    assert not r["unmet"] and "No encontré" not in r["text"] and "Por tu interés" not in r["text"]


@pytest.mark.parametrize("screen", ["licores", "farmacia", None])
def test_from_licores_pharmacy_or_home_the_recommendation_comes_from_a_vertical_mochi_offers(catalog, screen):
    """Sin pantalla (la Home), la vertical más típica de las papas fritas en este catálogo sería Farmacia (empatan en
    cantidad y gana por nombre)."""
    db, embedder = catalog
    agent = RappiAgent(embedder, TemplateComposer())

    r = ask(agent, db, screen, {"snacks-salados": 3.0})

    assert r["text"].startswith("Por tu interés en 🥨 snacks salados 😉")
    assert r["vertical"] == "supermercado"
    assert [p["entity_id"] for p in r["products"]] == ["100"]


def test_a_recommendation_never_moves_to_licores_or_pharmacy_where_the_screen_has_little(catalog, monkeypatch):
    """«En chocolaterías casi no hay «bebidas gaseosas»; en Licores hay más»: en la base real (21-10-2026) 13 de 784
    recomendaciones se iban así a Licores o Farmacia. En una oferta, la vertical con más del interés es una que Mochi
    propone."""
    db, embedder = catalog
    monkeypatch.setattr(rappi_agent, "MIN_HOME_ITEMS", 1)  # el catálogo de prueba es chico
    agent = RappiAgent(embedder, TemplateComposer())

    r = ask(agent, db, "chocolateria", {"snacks-salados": 3.0})

    assert r["vertical"] == "supermercado"
    assert [p["entity_id"] for p in r["products"]] == ["100"]


def test_only_the_recommendation_that_answers_is_written_by_claude(catalog):
    """Los intentos que no encuentran nada no le piden un texto a Claude: con tres intereses serían segundos de más."""
    db, embedder = catalog
    composer = CountingComposer()
    agent = RappiAgent(embedder, composer)

    r = ask(agent, db, "supermercado", {"manualidades": 3.0, "snacks-salados": 1.0})

    assert r["products"] and composer.kinds == ["resultados"]
