"""La marca que la persona compra con la consulta de una arista (conservas → arroz y legumbres: "arroz"), sobre el
catálogo de prueba: el producto de su marca que calza la consulta va primero aunque la búsqueda lo deje fuera de los
primeros (`_brand_products` lo busca aparte), y uno de su marca que no la calza (las lentejas) no cuenta."""

import pytest

from rappi_ia.agent import tools
from rappi_ia.agent.tools import suggest_complement
from rappi_ia.concepts.taxonomy import complement_queries
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents


@pytest.fixture
def demo(db, monkeypatch):
    seed_demo(db)
    embedder = HashEmbedder()
    embed_search_documents(db, embedder)
    db.execute("INSERT INTO product_brands (brand_key, name) VALUES ('marca-arroz', 'Arrocera del Sur')")
    db.commit()
    monkeypatch.setattr(tools, "NAMED_CANDIDATES", 1)  # la búsqueda deja un solo producto: la marca queda fuera
    return db, embedder


def of_brand(db, name):
    entity = db.execute("SELECT master_product_id::text FROM catalog_items WHERE name = %s", (name,)).fetchone()[0]
    db.execute(
        """INSERT INTO item_brands (entity_type, entity_id, brand_key, source)
           VALUES ('catalog_item', %s, 'marca-arroz', 'regla')""",
        (entity,),
    )
    db.commit()


def test_the_edge_has_its_query():
    assert complement_queries()[("conservas", "arroz-legumbres")] == "arroz"


def test_their_brand_goes_first_when_it_says_the_query(demo):
    db, embedder = demo
    usual = suggest_complement(db, ["conservas"], None, embedder, {"conservas"})
    assert usual.concept == "arroz-legumbres" and len(usual.products) == 1
    other = "Arroz integral 1 kg (prueba)" if "grado 1" in usual.products[0].name else "Arroz grado 1 de 1 kg (prueba)"
    of_brand(db, other)

    chosen = suggest_complement(db, ["conservas"], None, embedder, {"conservas"}, {"marca-arroz": 2})

    assert chosen.brand == "marca-arroz"
    assert [p.name for p in chosen.products] == [other, usual.products[0].name]


def test_a_product_of_their_brand_that_does_not_say_the_query_does_not_count(demo):
    db, embedder = demo
    of_brand(db, "Lentejas 400 g (prueba)")

    chosen = suggest_complement(db, ["conservas"], None, embedder, {"conservas"}, {"marca-arroz": 2})

    assert chosen.brand is None
    assert all("Arroz" in p.name for p in chosen.products)


def test_the_name_has_to_say_a_word_of_the_query_with_its_root_and_without_accents(db):
    """`_saying`: la raíz y sin tildes, como la búsqueda por palabras ("Lavalozas" dice "lavaloza", "Plátano" dice
    "platano"), pero solo el nombre."""

    def product(name):
        return tools.Product(name, "catalog_item", name, name, "supermercado", None, 990.0, None, None, None)

    names = ["Toddo Lavalozas Verde", "Plátano de exportación", "Sahumerio 5 Elementos - Armonía", "Pan de molde"]

    said = tools._saying(db, [product(n) for n in names], "lavaloza platano pala")

    assert [p.name for p in said] == ["Toddo Lavalozas Verde", "Plátano de exportación"]
