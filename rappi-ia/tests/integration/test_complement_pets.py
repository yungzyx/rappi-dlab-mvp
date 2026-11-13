"""Mascotas: con la comida de gato no sale nada de perro, sobre el catálogo de prueba con productos de mascotas.

- Comida de gato → accesorios: el "Educador Sanitario Perro" de la marca que la persona compra no encabeza la oferta
  ni sale (caso de la reunión del 12-11-2026, con un spray de Drag Pharma); los accesorios que dicen gato, sí.
- Comida de perro → accesorios: el mismo educador sí vale (dice perro).
- Arena (accesorios, sin especie en su concepto) → comida: con su nombre, la persona lleva algo de gato, y la mitad de
  la alternancia ya no le ofrece comida de perro."""

import pytest
from rappi_scraper.storage.search import build_search_documents

from rappi_ia.agent import tools
from rappi_ia.agent.tools import suggest_complement
from rappi_ia.concepts.pipeline import build_concepts
from rappi_ia.demo import seed
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents

CATEGORY = "Mascotas (prueba)"  # sin mapeo: el concepto sale del nombre
TRAINER = "Educador Sanitario Perro (prueba)"
CAT_THINGS = ["Arena Sanitaria para Gatos (prueba)", "Rascador para Gatos con Pelota (prueba)"]
DOG_THINGS = ["Juguete Cuerda para Perro (prueba)", "Cama para Perro Mediana (prueba)"]
CAT_FOOD = ["Alimento Húmedo para Gatos Adulto (prueba)", "Alimento Seco para Gato Salmón (prueba)"]
DOG_FOOD = ["Alimento Húmedo para Perros Adulto (prueba)", "Alimento Seco para Perro Carne (prueba)"]
LITTER = "Arena Sanitaria Aglutinante Café Moka (prueba)"


@pytest.fixture
def demo(db, monkeypatch):
    seed.seed_demo(db)
    monkeypatch.setitem(seed._AISLE_OF_CATEGORY, CATEGORY, seed._AISLE_OF_CATEGORY["Arroz"])
    run_id = db.execute("SELECT max(run_id) FROM scrape_runs").fetchone()[0]
    categories = dict(db.execute("SELECT name, category_id FROM categories").fetchall())
    names = [TRAINER, *CAT_THINGS, *DOG_THINGS, *CAT_FOOD, *DOG_FOOD, LITTER]
    for product_id, name in enumerate(names, start=99101):
        seed._insert_catalog_item(db, categories, product_id, name, CATEGORY)
        seed._insert_offer(db, run_id, 9101, product_id, CATEGORY, 2990)
    db.execute("INSERT INTO product_brands (brand_key, name) VALUES ('marca-querida', 'Marca Querida')")
    trainer = db.execute("SELECT master_product_id::text FROM catalog_items WHERE name = %s", (TRAINER,)).fetchone()[0]
    db.execute(
        """INSERT INTO item_brands (entity_type, entity_id, brand_key, source)
           VALUES ('catalog_item', %s, 'marca-querida', 'regla')""",
        (trainer,),
    )
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embedder = HashEmbedder()
    embed_search_documents(db, embedder)
    db.commit()
    concepts = dict(
        db.execute(
            """SELECT ci.name, ic.concept_id FROM catalog_items ci
               JOIN item_concepts ic ON ic.entity_type = 'catalog_item' AND ic.entity_id = ci.master_product_id::text
               WHERE ci.name = ANY(%s)""",
            (names,),
        ).fetchall()
    )
    assert concepts[TRAINER] == concepts[LITTER] == "accesorios-mascota"
    assert {concepts[n] for n in CAT_FOOD} == {"alimento-gato"}
    assert {concepts[n] for n in DOG_FOOD} == {"alimento-perro"}
    return db, embedder


def names(suggestion):
    return [p.name for p in suggestion.products]


def test_cat_food_never_brings_their_dog_trainer(demo):
    db, embedder = demo

    chosen = suggest_complement(db, ["alimento-gato"], None, embedder, {"alimento-gato"}, {"marca-querida": 3})

    assert (chosen.concept, chosen.brand) == ("accesorios-mascota", None)
    assert TRAINER not in names(chosen)
    assert names(chosen) and all(tools.says_species(name, "gato") for name in names(chosen))


def test_dog_food_still_brings_their_dog_trainer(demo):
    db, embedder = demo

    chosen = suggest_complement(db, ["alimento-perro"], None, embedder, {"alimento-perro"}, {"marca-querida": 3})

    assert (chosen.concept, chosen.brand) == ("accesorios-mascota", "marca-querida")
    assert names(chosen)[0] == TRAINER


def test_cat_litter_never_gets_dog_food_even_in_the_other_half(demo, monkeypatch):
    db, embedder = demo
    # La otra mitad de la alternancia, siempre que haya dos candidatos.
    monkeypatch.setattr(tools, "_takes_second", lambda candidates, user_id: len(candidates) >= 2)
    source = ["accesorios-mascota"]

    unnamed = suggest_complement(db, source, None, embedder, set(source), user_id="proto-mascotas")
    named = suggest_complement(db, source, None, embedder, set(source), user_id="proto-mascotas", source_names=[LITTER])

    assert {unnamed.concept, named.concept} == {"alimento-perro", "alimento-gato"}  # sin el nombre, como antes
    assert named.concept == "alimento-gato"
