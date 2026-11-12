"""La marca que la persona compra con la consulta de una arista, sobre el catálogo de prueba con más arroces y salsas.

- Conservas → arroz y legumbres ("arroz"): entre 17 arroces que dicen "arroz" lo mismo, el de su marca va primero aunque
  la búsqueda lo deje fuera de los primeros 12 (antes se buscaba solo ahí: `BRAND_CANDIDATES`).
- Pastas → salsas ("salsa de tomate pomodoro pomarola…"): el kétchup de su marca dice "salsa", pero menos que las salsas
  de tomate que se ofrecen, y no encabeza la oferta.
- Unas lentejas de su marca no dicen "arroz" y no cuentan."""

import pytest
from rappi_scraper.storage.search import build_search_documents

from rappi_ia.agent import tools
from rappi_ia.agent.tools import suggest_complement
from rappi_ia.concepts.pipeline import build_concepts
from rappi_ia.concepts.taxonomy import complement_queries
from rappi_ia.demo import seed
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents

RICE = [f"Arroz grano largo número {i} (prueba)" for i in range(15)]
SAUCES = [
    "Pomarola Salsa de Tomate (prueba)",
    "Salsa de Tomate Pomodoro (prueba)",
    "Salsa de Tomate Bolognesa (prueba)",
    "Salsa Pesto Pomodoro (prueba)",
    "Salsa de Tomate Italiana Pomarola (prueba)",
]
KETCHUP = "Salsa Ketchup Clásica (prueba)"


@pytest.fixture
def demo(db):
    seed.seed_demo(db)
    run_id = db.execute("SELECT max(run_id) FROM scrape_runs").fetchone()[0]
    categories = dict(db.execute("SELECT name, category_id FROM categories").fetchall())
    extra = [(name, "Arroz") for name in RICE] + [(name, "Otras salsas") for name in [*SAUCES, KETCHUP]]
    for product_id, (name, category) in enumerate(extra, start=99001):
        seed._insert_catalog_item(db, categories, product_id, name, category)
        seed._insert_offer(db, run_id, 9101, product_id, category, 1490)
    db.execute("INSERT INTO product_brands (brand_key, name) VALUES ('marca-querida', 'Marca Querida')")
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embedder = HashEmbedder()
    embed_search_documents(db, embedder)
    db.commit()
    return db, embedder


def of_brand(db, name):
    entity = db.execute("SELECT master_product_id::text FROM catalog_items WHERE name = %s", (name,)).fetchone()[0]
    db.execute(
        """INSERT INTO item_brands (entity_type, entity_id, brand_key, source)
           VALUES ('catalog_item', %s, 'marca-querida', 'regla')""",
        (entity,),
    )
    db.commit()


def test_the_edges_have_their_query():
    assert complement_queries()[("conservas", "arroz-legumbres")] == "arroz"
    assert "pomarola" in complement_queries()[("pastas", "salsas")]


def test_their_rice_goes_first_even_out_of_the_first_twelve_of_the_search(demo):
    db, embedder = demo
    pool = tools.search_products(
        db, "supermercado", "arroz", ["arroz-legumbres"], embedder, k=tools.BRAND_CANDIDATES, offer=True
    )
    seen = {p.name for p in pool.products}
    rice = next(name for name in reversed(RICE) if name not in seen)  # fuera del pozo de antes
    of_brand(db, rice)

    chosen = suggest_complement(db, ["conservas"], None, embedder, {"conservas"}, {"marca-querida": 2})

    assert (chosen.concept, chosen.brand) == ("arroz-legumbres", "marca-querida")
    assert chosen.products[0].name == rice


def test_their_ketchup_does_not_head_the_offer_for_noodles(demo):
    db, embedder = demo
    of_brand(db, KETCHUP)

    chosen = suggest_complement(db, ["pastas"], None, embedder, {"pastas"}, {"marca-querida": 3})

    assert (chosen.concept, chosen.brand) == ("salsas", None)
    assert chosen.products[0].name in SAUCES
    assert KETCHUP not in [p.name for p in chosen.products]


def test_their_lentils_do_not_say_rice(demo):
    db, embedder = demo
    of_brand(db, "Lentejas 400 g (prueba)")

    chosen = suggest_complement(db, ["conservas"], None, embedder, {"conservas"}, {"marca-querida": 2})

    assert chosen.brand is None
    assert all("Arroz" in p.name for p in chosen.products)


def test_a_name_scores_by_the_words_of_the_query_it_says_with_their_root_and_without_accents(demo):
    """`_name_scores`: la suma del IDF de las palabras de la consulta que dice el nombre ("Lavalozas" dice "lavaloza",
    "Plátano" dice "platano"); el que no dice ninguna no está."""
    db, _ = demo
    names = ["Toddo Lavalozas Verde", "Plátano y lavaloza", "Sahumerio 5 Elementos - Armonía", "Pan de molde"]

    scores = tools._name_scores(db, "supermercado", names, "lavaloza platano pala")

    assert set(scores) == {"Toddo Lavalozas Verde", "Plátano y lavaloza"}
    assert scores["Plátano y lavaloza"] > scores["Toddo Lavalozas Verde"] > 0
