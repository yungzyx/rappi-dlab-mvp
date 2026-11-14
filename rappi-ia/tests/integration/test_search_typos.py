"""Errores de tipeo: una búsqueda que queda "sin resultado" se corrige con el vocabulario del catálogo y se vuelve a
buscar con las reglas de siempre (retrieval/spelling.py). Sobre el catálogo de prueba (`seed_demo`) más los casos
que #129 dejó sin resultado en la base real: "nutela", "cuchuflis", "cervezaaaa" y "eh quiero este una coca"."""

import pytest
from rappi_scraper.storage.search import build_search_documents

from conftest import add_dish, add_product, add_store
from rappi_ia.agent.grouped_search import search_grouped
from rappi_ia.agent.tools import search_products
from rappi_ia.concepts.pipeline import build_concepts
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents
from rappi_ia.retrieval import spelling

SUPER, TURBO, MALL = 9101, 9301, 9601  # tiendas de `seed_demo`


def _price(db, store_id: int, product_id: int, price: int) -> None:
    db.execute(
        """INSERT INTO price_snapshots (run_id, store_id, sku, price, in_stock)
           SELECT max(run_id), %s, %s, %s, true FROM scrape_runs WHERE kind = 'stores'""",
        (store_id, f"sku-{product_id}", price),
    )


@pytest.fixture
def catalog(db):
    seed_demo(db)
    for pid, name, store, category in [
        (99060, "Nutella crema de avellanas 350 g (prueba)", SUPER, "Untables"),
        (99061, "Nutella crema de avellanas 750 g (prueba)", SUPER, "Untables"),
        (99062, "Cuchuflíes rellenos de manjar 6 unidades (prueba)", TURBO, None),
        (99063, "Coca-Cola original 1,5 L (prueba)", TURBO, "Gaseosas"),
        (99064, "Tres Erres Pisco Especial 35° 1 L (prueba)", TURBO, "Piscos"),
        (99065, "Aceite de masajes relajante (prueba)", TURBO, None),
        *[(99070 + i, f"Libro de pasajes bíblicos tomo {i} (prueba)", MALL, "Libros") for i in range(20)],
    ]:
        add_product(db, pid, name, store, category)
        _price(db, store, pid, 3990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embedder = HashEmbedder()
    embed_search_documents(db, embedder)
    return db, embedder


@pytest.mark.parametrize(
    ("vertical", "query", "corrected", "found"),
    [
        ("supermercado", "nutela", "nutella", "Nutella"),
        ("turbo", "cuchuflis", "cuchuflíes", "Cuchuflíes"),  # como lo escribe el catálogo
        ("licores", "cervezaaaa", "cerveza", "Cerveza"),
        ("turbo", "eh quiero este una coca", "coca", "Coca-Cola"),
    ],
)
def test_a_typo_without_results_is_corrected_and_searched_again(catalog, vertical, query, corrected, found):
    db, embedder = catalog

    assert search_products(db, vertical, query, None, embedder).result.unmet  # como lo dejó #129

    outcome = search_products(db, vertical, query, None, embedder, correct=True)

    assert outcome.corrected_query == corrected and not outcome.result.unmet
    assert outcome.products and all(found in p.name for p in outcome.products[:1])


def test_a_concept_found_after_correcting_follows_the_usual_rules(catalog):
    """ "cervezaaaa" → "cerveza" nombra el concepto: en Licores se muestran solo cervezas, y en farmacia (que no las
    vende) sigue "sin resultado"."""
    db, embedder = catalog

    liquor = search_products(db, "licores", "cervezaaaa", None, embedder, correct=True)
    assert liquor.result.query_concepts == ["cerveza"]
    assert {p.concept for p in liquor.products} == {"cerveza"}

    pharmacy = search_products(db, "farmacia", "cervezaaaa", None, embedder, correct=True)
    assert pharmacy.result.unmet and pharmacy.products == [] and pharmacy.corrected_query is None


def test_queries_without_typos_keep_their_result(catalog):
    """Lo que no queda "sin resultado" no se corrige, y una negativa con palabras que el catálogo tiene sigue igual."""
    db, embedder = catalog

    found = search_products(db, "turbo", "cuchuflíes", None, embedder, correct=True)
    assert found.corrected_query is None and found.products

    negative = search_products(db, "turbo", "sofá de tres cuerpos", None, embedder, correct=True)
    assert negative.result.unmet and negative.products == [] and negative.corrected_query is None


def test_the_grouped_search_corrects_once_when_nothing_was_found(catalog):
    db, embedder = catalog

    grouped = search_grouped(db, "cervezaaaa", embedder, None, 6)
    assert grouped.corrected_query == "cerveza" and not grouped.unmet
    assert grouped.groups and grouped.groups[0].vertical == "licores"
    assert grouped.to_dict()["corrected_query"] == "cerveza"

    exact = search_grouped(db, "cervezaaaa", embedder, None, 6, correct=False)
    assert exact.unmet and exact.corrected_query is None

    negative = search_grouped(db, "sofá de tres cuerpos", embedder, None, 6)
    assert negative.unmet and negative.corrected_query is None


def test_the_correction_keeps_what_the_person_wrote_where_it_was_right(catalog):
    db, _ = catalog
    assert spelling.correct_query(db, "Nutela de 350 g", "supermercado") == "nutella de 350 g"
    assert spelling.correct_query(db, "pañales talla m", "supermercado") is None  # nada que corregir
    assert spelling.correct_query(db, "nutella bajo 3000", "supermercado") is None  # un número no se corrige
    assert spelling.correct_query(db, "xyzzy", None) is None
    # Quien le habla al asistente conversa: "recomiendas" no se corrige ni "mochi" se salta como un saludo.
    assert spelling.correct_query(db, "oye mochi me recomiendas algo", "turbo") is None
    assert spelling.correct_query(db, "ok gracias", None) is None  # solo cortesía: nada que buscar
    # "pasajes" está en 20 documentos del catálogo (en el mall): es una palabra real, y en Turbo no pasa a "masajes".
    assert spelling.correct_query(db, "pasajes", "turbo") is None
    # Una ocasión pide lo que su nombre no dice: "polola" no se cambia por la palabra más parecida del catálogo.
    assert spelling.correct_query(db, "regalo para mi polola", "mall") is None


@pytest.fixture
def names(db, monkeypatch):
    """Un local de otra ciudad que se llama "Suchi Tacna" (un plato), entre 300 platos de sushi: "suchi" calza su plato
    y es un nombre que suena igual a "sushi". "Zushi Bar" trae su nombre también en un plato ("Zushi especial"): es una
    palabra del menú, no solo un nombre. NAME_RATIO baja a 100 para no sembrar miles de platos."""
    monkeypatch.setattr(spelling, "NAME_RATIO", 100)
    seed_demo(db)
    add_store(db, 9901, "restaurantes", "Suchi Tacna - Antofagasta", city="Antofagasta")
    add_store(db, 9902, "restaurantes", "Mil Rolls - Providencia")
    add_store(db, 9903, "restaurantes", "Zushi Bar - Ñuñoa")
    dishes = [(99100, "Hand roll de salmón", 9901, "Rolls"), (99101, "Zushi especial", 9903, "Rolls")]
    dishes += [(99200 + i, f"Sushi roll de la casa {i}", 9902, "Sushi") for i in range(300)]
    for item_id, name, store_id, section in dishes:
        add_dish(db, item_id, name, store_id, section)
        db.execute(
            """INSERT INTO menu_price_snapshots (run_id, item_id, price)
               SELECT max(run_id), %s, 4990 FROM scrape_runs WHERE kind = 'restaurants'""",
            (item_id,),
        )
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embedder = HashEmbedder()
    embed_search_documents(db, embedder)
    return db, embedder


def test_a_name_that_sounds_like_a_common_word_is_corrected_even_if_it_matches(names):
    db, embedder = names

    plain = search_products(db, "restaurantes", "suchi", None, embedder)
    assert plain.result.strict_lexical_matches  # el plato de "Suchi Tacna"

    outcome = search_products(db, "restaurantes", "suchi", None, embedder, correct=True)
    assert outcome.corrected_query == "sushi" and outcome.products
    assert all("Sushi" in p.name for p in outcome.products[:3])

    grouped = search_grouped(db, "suchi", embedder, None, 6)
    assert grouped.corrected_query == "sushi" and not grouped.unmet
    assert search_grouped(db, "suchi", embedder, None, 6, correct=False).corrected_query is None  # "tal cual"


def test_a_name_searched_by_name_is_not_corrected(names):
    """Con otra palabra del nombre ("suchi tacna") se busca el local, y una palabra que también está en un plato
    ("zushi") no es solo un nombre."""
    db, embedder = names

    for query in ("suchi tacna", "zushi"):
        assert search_products(db, "restaurantes", query, None, embedder, correct=True).corrected_query is None
        assert search_grouped(db, query, embedder, None, 6).corrected_query is None
    assert spelling.name_words(db, "zushi") is None
    assert spelling.name_words(db, "suchi") >= {"suchi", "tacna"}


def test_the_common_word_needs_name_ratio_times_more_documents(names, monkeypatch):
    """Con 300 documentos de sushi contra 2 de "Suchi Tacna" (su plato y el local), bajo NAME_RATIO (1000) el nombre se
    queda, como "cakao" (la chocolatería) frente a "cacao" en la base real. Turbo no tiene "suchi": nada que corregir
    ahí."""
    db, _ = names
    assert spelling.correct_query(db, "suchi", "restaurantes", matched=True) == "sushi"
    monkeypatch.setattr(spelling, "NAME_RATIO", 1000)
    assert spelling.correct_query(db, "suchi", None, matched=True) is None
    assert spelling.correct_query(db, "suchi", "turbo", matched=True) is None
