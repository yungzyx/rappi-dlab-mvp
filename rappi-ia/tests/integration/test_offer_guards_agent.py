"""Las guardias de ofertas en el agente: `suggest_complement` (que usan /agent/ask y /recommendations) y los ganchos de
servicios nunca proponen alcohol, farmacia, bebé, salud, conceptos sensibles, sex shops ni tabaquerías."""

import pytest
from rappi_scraper.storage.search import build_search_documents
from test_query_budget import CountingConnection

from conftest import add_dish, add_price, add_product, add_store
from owner_client import OwnerClient
from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.rappi_agent import Context, RappiAgent
from rappi_ia.agent.tools import search_products, suggest_complement
from rappi_ia.agent.verticals import ranked_verticals
from rappi_ia.api import app as api
from rappi_ia.api.services import Services
from rappi_ia.catalog import cache
from rappi_ia.concepts.pipeline import build_concepts
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents
from rappi_ia.offers.guards import is_offerable, offerable_vertical


@pytest.fixture
def demo(db):
    """El catálogo de prueba (`seed_demo`): ahí están pizza y cerveza, y las aristas curadas de complements.toml."""
    seed_demo(db)
    embedder = HashEmbedder()
    embed_search_documents(db, embedder)
    return db, embedder


@pytest.fixture
def demo_client(demo):
    db, embedder = demo

    def conn_override():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    api.app.dependency_overrides[api.get_services] = lambda: Services(
        RappiAgent(embedder, TemplateComposer()), embedder
    )
    yield OwnerClient(api.app)
    api.app.dependency_overrides.clear()


def stock(db, embedder, products):
    """Agrega (id, nombre, tienda, categoría de Rappi) a precio fijo y recalcula documentos, conceptos y embeddings."""
    for pid, name, store, category in products:
        add_product(db, pid, name, store, category)
        add_price(db, store, pid, 1990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, embedder)


def test_complement_never_offers_alcohol(demo):
    db, embedder = demo
    # La semilla trae la arista curada pizza → cerveza (la más fuerte de la pizza) y cerveza a la venta.
    assert db.execute(
        "SELECT 1 FROM concept_edges WHERE from_concept = 'pizza' AND to_concept = 'cerveza' AND method = 'curado'"
    ).fetchone()

    suggestion = suggest_complement(db, ["pizza"], "restaurantes", embedder)

    assert suggestion is not None and suggestion.concept == "gaseosas"  # la siguiente arista de la pizza
    assert not any(p.age_restricted for p in suggestion.products)


def test_complement_never_offers_a_blocked_concept_or_vertical_from_any_source(demo):
    """Barrido: ninguna fuente de la taxonomía, desde ninguna pantalla, saca una oferta bloqueada."""
    db, embedder = demo
    taxonomy = load_taxonomy()
    suggested = 0
    for source in taxonomy.concepts:
        for current in (None, "restaurantes", "licores"):
            suggestion = suggest_complement(db, [source], current, embedder)
            if suggestion is None:
                continue
            suggested += 1
            assert is_offerable(taxonomy.concepts[suggestion.concept]), (source, suggestion.concept)
            assert offerable_vertical(suggestion.vertical), (source, suggestion.vertical)
            assert not any(p.age_restricted for p in suggestion.products), (source, suggestion.concept)
    assert suggested > 20  # el barrido no es vacío: el catálogo de prueba sí tiene complementos


def test_complement_never_lands_in_pharmacy(db):
    embedder = HashEmbedder()
    add_store(db, 2, "licores", "Botillería")
    add_store(db, 11, "farmacia", "Farmacia")
    stock(
        db,
        embedder,
        [
            (200, "Cerveza Escudo Lata 470 cc", 2, "Cervezas"),
            (300, "Papas fritas Lays Clásicas 180 g", 11, "Snacks salados"),
            (301, "Ramitas Evercrisp Queso 250 g", 11, "Snacks salados"),
        ],
    )
    # Los snacks (un concepto cualquiera) solo están en la farmacia: Mochi no los lleva ahí.
    assert ranked_verticals(db, ["snacks-salados"]) == ["farmacia"]
    assert suggest_complement(db, ["cerveza"], "licores", embedder) is None

    # Con snacks también en el súper, la farmacia sigue siendo la vertical típica, pero la oferta sale del súper.
    add_store(db, 1, "supermercado", "Súper")
    stock(db, embedder, [(302, "Papas Kryzpo Original 130 g", 1, "Snacks salados")])
    assert ranked_verticals(db, ["snacks-salados"])[0] == "farmacia"
    suggestion = suggest_complement(db, ["cerveza"], "licores", embedder)
    assert suggestion.concept == "snacks-salados" and suggestion.vertical == "supermercado"
    assert [p.entity_id for p in suggestion.products] == ["302"]


def test_complement_never_comes_from_a_sex_shop_or_a_smoking_shop_in_another_vertical(demo):
    """En el mall de prueba el smoking shop vende «Chicles de menta» (golosinas, un concepto corriente) y Express vende
    gomitas: la oferta de golosinas sale de Express aunque el mall sea donde más calza."""
    db, embedder = demo
    assert db.execute(
        "SELECT 1 FROM concept_edges WHERE from_concept = 'juguetes-infantiles' AND to_concept = 'golosinas'"
    ).fetchone()
    assert ranked_verticals(db, ["golosinas"])  # hay golosinas en el catálogo de prueba

    suggestion = suggest_complement(db, ["juguetes-infantiles"], "conveniencia", embedder)

    assert suggestion is not None and suggestion.concept == "golosinas"
    assert suggestion.vertical == "conveniencia"
    assert [p.name for p in suggestion.products] == ["Gomitas ácidas 150 g (prueba)"]
    # Sin la guardia, esa misma búsqueda en el mall trae las golosinas del smoking shop.
    unguarded = search_products(db, "mall", "Golosinas", ["golosinas"], embedder, k=4)
    assert [p.store for p in unguarded.products] == ["Smoking shop (prueba)"]
    guarded = search_products(db, "mall", "Golosinas", ["golosinas"], embedder, k=4, offer=True)
    assert guarded.products == []


def test_offer_searches_skip_a_pharmacy_listed_among_the_supermarkets(demo):
    db, embedder = demo
    args = (db, "supermercado", "cepillo dental", ["cuidado-oral"], embedder)

    assert [p.store for p in search_products(*args, k=4).products] == ["Farmacia de prueba en súper"]
    assert search_products(*args, k=4, offer=True).products == []


def test_a_product_flagged_for_adults_is_never_offered_whatever_its_concept(demo):
    """El catálogo de Rappi marca +18 a un producto aunque su concepto sea corriente (una gaseosa con alcohol)."""
    db, embedder = demo
    db.execute("UPDATE catalog_items SET age_restricted = true WHERE master_product_id IN (91003, 92001)")
    db.commit()

    suggestion = suggest_complement(db, ["pizza"], "restaurantes", embedder)

    assert suggestion is not None and suggestion.concept != "gaseosas"
    assert not any(p.age_restricted for p in suggestion.products)


def test_ask_cross_sell_respects_the_guards(demo_client):
    body = demo_client.post(
        "/agent/ask", json={"message": "pizza", "vertical": "restaurants", "user_id": "u1", "session_id": "s1"}
    ).json()

    assert body["products"]  # la respuesta sí trae pizzas
    assert body["suggestion"]["concept"] == "gaseosas"  # no cerveza
    assert not body["age_notice"]
    assert not any(p["age_restricted"] for p in body["suggestion"]["products"])


def test_recommendations_respect_the_guards(demo_client):
    event = {"type": "search", "session_id": "s1", "vertical": "restaurants", "concept_id": "pizza", "query": "pizza"}
    assert demo_client.post("/events", json={"user_id": "u1", "events": [event]}).json() == {"guardados": 1}

    rows = demo_client.get("/recommendations", params={"user_id": "u1", "vertical": "restaurants"}).json()["rows"]

    assert [row["concept"] for row in rows] == ["gaseosas"]
    assert not any(p["age_restricted"] for row in rows for p in row["products"])


def test_recommendations_never_name_an_unofferable_interest(demo, demo_client):
    """«Por tu interés en 🍺 cerveza» es Mochi nombrando alcohol (o salud) por su cuenta: esos intereses no son
    fuente de una recomendación, como en `_top_interest`. Uno ofrecible, aunque pese menos, sí."""
    db, _ = demo
    db.execute(  # vitaminas → jugos (jugos se ofrece y el súper de prueba vende jugo): sin la regla, sería una fila
        """INSERT INTO concept_edges (from_concept, to_concept, method, weight, data_source)
           VALUES ('vitaminas', 'jugos', 'curado', 0.9, 'curado')"""
    )
    db.commit()

    def search(concept: str) -> dict:
        return {"type": "search", "session_id": "s1", "vertical": "grocery", "concept_id": concept, "query": concept}

    events = [search("cerveza")] * 3 + [search("vitaminas")] * 2 + [search("pizza")]
    assert demo_client.post("/events", json={"user_id": "u1", "events": events}).json() == {"guardados": 6}
    body = demo_client.get("/recommendations", params={"user_id": "u1", "limit": 6}).json()
    assert body["interests"][:2] == ["cerveza", "vitaminas"]  # el perfil los guarda: solo no se ofrecen

    reasons = [row["reason"] for row in body["rows"]]
    assert reasons == ["Por tu interés en 🍕 pizza"]
    assert not any(p["age_restricted"] for row in body["rows"] for p in row["products"])


def test_a_service_hook_never_suggests_health_or_pharmacy_products(demo):
    """RappiTravel engancha protector solar (dermocosmética, del grupo salud) con una farmacia: no se propone."""
    db, embedder = demo
    agent = RappiAgent(embedder, TemplateComposer())

    beach = agent.reply(db, "me voy de vacaciones a la playa", Context())

    assert beach["service"] == "rappitravel"
    assert beach.get("suggestion", {}).get("concept") != "dermocosmetica"
    assert beach.get("suggestion", {}).get("vertical") != "farmacia"


def test_a_service_hook_never_lands_in_pharmacy(db):
    """Un concepto corriente (una mochila de viaje) que solo vende una farmacia no se propone; si otra vertical lo
    vende, la oferta sale de ahí aunque la farmacia calce primero."""
    embedder = HashEmbedder()
    agent = RappiAgent(embedder, TemplateComposer())
    add_store(db, 11, "farmacia", "Farmacia")
    stock(db, embedder, [(902, "Mochila de viaje 40 litros", 11, "Maletas de viaje")])
    assert ranked_verticals(db, ["accesorios-moda"]) == ["farmacia"]

    assert "suggestion" not in agent.reply(db, "busco un hotel en puerto varas", Context())

    add_store(db, 12, "mall", "Tienda")
    stock(db, embedder, [(903, "Mochila de viaje 30 litros", 12, "Maletas de viaje")])
    assert ranked_verticals(db, ["accesorios-moda"])[0] == "farmacia"
    suggestion = agent.reply(db, "busco un hotel en puerto varas", Context())["suggestion"]
    assert suggestion["vertical"] == "mall" and [p["entity_id"] for p in suggestion["products"]] == ["903"]


def test_complement_never_lands_in_licores(db):
    """«Ni Licores»: una gaseosa que solo vende una botillería no se propone desde Licores; si otra vertical la
    vende, la oferta sale de ahí aunque Licores calce primero."""
    embedder = HashEmbedder()
    add_store(db, 3, "restaurantes", "Pizzería")
    add_store(db, 2, "licores", "Botillería (prueba)")
    stock(
        db,
        embedder,
        [(210, "Gaseosa cola 1,5 L (prueba)", 2, "Gaseosas"), (211, "Gaseosa lima 1,5 L (prueba)", 2, "Gaseosas")],
    )
    assert ranked_verticals(db, ["gaseosas"]) == ["licores"]
    assert suggest_complement(db, ["pizza"], "restaurantes", embedder) is None

    add_store(db, 1, "supermercado", "Súper (prueba)")
    stock(db, embedder, [(212, "Gaseosa naranja 1,5 L (prueba)", 1, "Gaseosas")])
    assert ranked_verticals(db, ["gaseosas"])[0] == "licores"
    suggestion = suggest_complement(db, ["pizza"], "restaurantes", embedder)
    assert suggestion.concept == "gaseosas" and suggestion.vertical == "supermercado"
    assert [p.entity_id for p in suggestion.products] == ["212"]


def test_a_soda_sold_only_by_a_licores_store_in_the_seed_is_not_suggested(demo):
    db, embedder = demo
    sodas = "SELECT master_product_id FROM catalog_items WHERE name ILIKE 'Gaseosa%'"
    skus = f"SELECT sku FROM store_products WHERE master_product_id IN ({sodas})"
    db.execute(f"DELETE FROM price_snapshots WHERE sku IN ({skus})")  # noqa: S608 (consultas fijas)
    db.execute(f"DELETE FROM store_products WHERE master_product_id IN ({sodas})")  # noqa: S608
    db.commit()
    stock(db, embedder, [(94901, "Gaseosa cola 1,5 L botillería (prueba)", 9401, "Gaseosas")])
    assert ranked_verticals(db, ["gaseosas"]) == ["licores"]

    suggestion = suggest_complement(db, ["pizza"], "restaurantes", embedder)  # pasa a la arista siguiente, si hay
    assert suggestion is None or (suggestion.concept != "gaseosas" and suggestion.vertical != "licores")


def test_an_offer_never_brings_a_catalog_item_whose_name_says_alcohol(db):
    """«Soju Uva Verde 13.0» está en «Frutas» en la base real, sin marca de alcohol ni +18: quien lo busca lo encuentra,
    pero el agente no lo ofrece. Un plato «Sake Roll» (salmón) sí se ofrece: los platos tienen su propia lista."""
    embedder = HashEmbedder()
    add_store(db, 21, "supermercado", "Súper")
    add_store(db, 22, "restaurantes", "Sushi")
    db.execute("INSERT INTO scrape_runs (run_id, kind, status) VALUES (999, 'restaurants', 'done')")
    add_dish(db, 941, "Sake Roll", 22, "Rolls")
    db.execute("INSERT INTO menu_price_snapshots (run_id, item_id, price) VALUES (999, 941, 6990)")
    stock(db, embedder, [(931, "Soju Uva Verde 13.0", 21, "Frutas"), (932, "Uva Verde 1 kg", 21, "Frutas")])

    searched = search_products(db, "supermercado", "uva verde", [], embedder)
    offered = search_products(db, "supermercado", "uva verde", [], embedder, offer=True)
    kit = search_products(db, "supermercado", "uva verde", [], embedder, offer=True, adult_ok=True)
    dish = search_products(db, "restaurantes", "sake roll", [], embedder, offer=True)

    assert {p.entity_id for p in searched.products} == {"931", "932"}
    assert [p.entity_id for p in offered.products] == ["932"]
    soju = next(p for p in kit.products if p.entity_id == "931")  # en un kit elegido, con su marca +18
    assert soju.age_restricted
    assert [p.entity_id for p in dish.products] == ["941"]


def test_an_offer_never_brings_a_catalog_item_whose_name_says_baby(db):
    """En la base real los juguetes y la ropa de bebé vienen con conceptos corrientes: quien los busca los encuentra,
    pero el agente no los ofrece, ni en el kit de una ocasión."""
    embedder = HashEmbedder()
    add_store(db, 21, "mall", "Juguetería")
    stock(
        db,
        embedder,
        [
            (951, "Fisher-price Juguete Para Bebés Set De Cocina De Madera", 21, "Juguetes"),
            (952, "Set De Cocina De Madera", 21, "Juguetes"),
        ],
    )

    def found(**offer):
        outcome = search_products(db, "mall", "set de cocina de madera", [], embedder, **offer)
        return {p.entity_id for p in outcome.products}

    assert found() == {"951", "952"}
    assert found(offer=True) == {"952"}
    assert found(offer=True, adult_ok=True) == {"952"}


def test_an_offer_never_brings_a_dish_whose_name_says_alcohol(db):
    """En la base real, cinco platos «Soju …» tienen concepto `asiatica`: la búsqueda los encuentra, una oferta no.
    En un menú «sake» es salmón y la «Margarita Familiar» de una pizzería es una pizza: los dos se ofrecen."""
    embedder = HashEmbedder()
    add_store(db, 22, "restaurantes", "Sushi")
    add_store(db, 23, "restaurantes", "Pizzería")
    db.execute("INSERT INTO scrape_runs (run_id, kind, status) VALUES (999, 'restaurants', 'done')")
    for item_id, name, store, section in (
        (941, "Sake Roll", 22, "Rolls"),
        (942, "Soju Durazno", 22, "Rolls"),
        (943, "Margarita Familiar", 23, "Pizzas"),
        (944, "Michelada clásica", 23, "Pizzas"),
    ):
        add_dish(db, item_id, name, store, section)
        db.execute("INSERT INTO menu_price_snapshots (run_id, item_id, price) VALUES (999, %s, 6990)", (item_id,))
    stock(db, embedder, [])
    # Aquí el nombre la lleva a `cocteles`; en la base real 24 pizzas así quedaron con concepto pizza.
    db.execute("UPDATE item_concepts SET concept_id = 'pizza' WHERE entity_type = 'menu_item' AND entity_id = '943'")
    # «soju» ya es palabra de licores (taxonomy.toml); aquí vuelve a sushi, como estaba en la base real, para probar la
    # guardia por el nombre.
    assert db.execute("SELECT concept_id FROM item_concepts WHERE entity_id = '942'").fetchone()[0] == "licores"
    db.execute("UPDATE item_concepts SET concept_id = 'sushi' WHERE entity_type = 'menu_item' AND entity_id = '942'")
    concepts = dict(db.execute("SELECT entity_id, concept_id FROM item_concepts WHERE entity_type = 'menu_item'"))
    assert (concepts["942"], concepts["944"]) == ("sushi", "pizza")  # conceptos que se ofrecen

    def offered(query, offer):
        return {p.name for p in search_products(db, "restaurantes", query, [], embedder, offer=offer).products}

    for query, name in (("soju", "Soju Durazno"), ("michelada", "Michelada clásica")):
        assert name in offered(query, False)  # la búsqueda no cambia
        assert name not in offered(query, True)
    assert "Sake Roll" in offered("sake roll", True)
    assert "Margarita Familiar" in offered("margarita", True)


def test_vertical_to_try_never_offers_a_popular_dish_whose_name_says_alcohol(demo):
    """«Vertical por probar» muestra en restaurantes sus platos populares, que no pasan por la búsqueda de ofertas."""
    from rappi_ia.offers.engine import _popular_dishes

    db, _ = demo
    assert "Tiramisú individual (prueba)" in {d["name"] for d in _popular_dishes(db)}
    db.execute("UPDATE menu_items SET name = 'Mojito de la casa (prueba)' WHERE item_id = 98004")  # sigue en postres
    cache.clear()  # sin corrida nueva: como si la caché del catálogo hubiera vencido

    assert "Mojito de la casa (prueba)" not in {d["name"] for d in _popular_dishes(db)}


def test_an_offer_never_brings_a_dish_from_a_drinks_section(db):
    """En la base real, «Sake Dry» y «Sake Nigori» (sección «Cervezas Japonesas y Sake») tienen concepto `asiatica` y un
    nombre que no dice alcohol: la sección lo dice. Una sección «sin alcohol» sí se ofrece."""
    embedder = HashEmbedder()
    add_store(db, 22, "restaurantes", "Sushi")
    db.execute("INSERT INTO scrape_runs (run_id, kind, status) VALUES (999, 'restaurants', 'done')")
    for item_id, name, section in (
        (951, "Sake Dry", "Cervezas Japonesas y Sake"),
        (952, "Misiones de Rengo 3/4 Lt", "Licores"),
        (953, "Limonada menta", "Bebidas sin Alcohol"),
        (954, "Gyozas de cerdo", "Cocktail De Aperitivo"),  # «cóctel» en singular: comida para picar
    ):
        add_dish(db, item_id, name, 22, section)
        db.execute("INSERT INTO menu_price_snapshots (run_id, item_id, price) VALUES (999, %s, 4990)", (item_id,))
    stock(db, embedder, [])
    db.execute(
        """INSERT INTO item_concepts (entity_type, entity_id, concept_id, method, confidence)
           SELECT 'menu_item', id, 'asiatica', 'regla', 1 FROM unnest(%s::text[]) AS id
           ON CONFLICT (entity_type, entity_id) DO UPDATE SET concept_id = 'asiatica'""",
        (["951", "952", "953", "954"],),
    )

    def offered(query, offer):
        found = search_products(db, "restaurantes", query, ["asiatica"], embedder, offer=offer).products
        return {p.name for p in found}

    for query, name in (("sake dry", "Sake Dry"), ("misiones de rengo", "Misiones de Rengo 3/4 Lt")):
        assert name in offered(query, False)  # la búsqueda no cambia
        assert name not in offered(query, True)
    assert "Limonada menta" in offered("limonada", True)
    assert "Gyozas de cerdo" in offered("gyozas", True)


def test_an_offer_never_brings_a_dish_without_concept_whose_description_names_alcohol(db):
    """En la base real, los cócteles de «Barra Barbazul» no tienen concepto ni dicen alcohol en el nombre ni en la
    sección: solo la descripción. Un concepto de bebida tampoco lo dice («Gautama Jack», gaseosas); uno de comida sí
    (un risotto al vino blanco se ofrece)."""
    embedder = HashEmbedder()
    add_store(db, 22, "restaurantes", "Barbazul")
    db.execute("INSERT INTO scrape_runs (run_id, kind, status) VALUES (999, 'restaurants', 'done')")
    for item_id, name, section, description in (
        (961, "Electric Lemonade Deli", "Barra Barbazul", "Vodka ron gin blue curacao jugo de limón y sprite. 475cc"),
        (962, "Limonada Deli", "Barra Barbazul", "Jugo de limón, menta y jarabe de azúcar. 475cc"),
        (963, "Risotto Deli", "Fondos", "Risotto de hongos al vino blanco"),
        (964, "Gautama Jack", "Bebidas", "Ron havana dorado, leche de coco, maracuya y naranja"),
    ):
        add_dish(db, item_id, name, 22, section)
        db.execute("UPDATE menu_items SET description = %s WHERE item_id = %s", (description, item_id))
        db.execute("INSERT INTO menu_price_snapshots (run_id, item_id, price) VALUES (999, %s, 5990)", (item_id,))
    stock(db, embedder, [])
    db.execute("DELETE FROM item_concepts WHERE entity_type = 'menu_item' AND entity_id IN ('961', '962')")
    db.execute(
        """INSERT INTO item_concepts (entity_type, entity_id, concept_id, method, confidence)
           VALUES ('menu_item', '963', 'pastas', 'regla', 1), ('menu_item', '964', 'gaseosas', 'regla', 1)
           ON CONFLICT (entity_type, entity_id) DO UPDATE SET concept_id = EXCLUDED.concept_id"""
    )
    build_search_documents(db)
    embed_search_documents(db, embedder)

    def offered(query, offer):
        return {p.name for p in search_products(db, "restaurantes", query, [], embedder, offer=offer).products}

    assert "Electric Lemonade Deli" in offered("electric lemonade deli", False)  # la búsqueda no cambia
    assert "Electric Lemonade Deli" not in offered("electric lemonade deli", True)
    assert "Limonada Deli" in offered("limonada deli", True)
    assert "Risotto Deli" in offered("risotto deli", True)
    assert "Gautama Jack" in offered("gautama jack", False)
    assert "Gautama Jack" not in offered("gautama jack", True)


def test_the_most_ordered_dishes_skip_one_without_concept_whose_description_names_alcohol(db):
    """«Lo más pedido» en restaurantes (`most_ordered`) no pasa por la búsqueda de ofertas."""
    from rappi_ia.offers.engine import _priced_in_vertical

    add_store(db, 22, "restaurantes", "Barbazul")
    db.execute("INSERT INTO scrape_runs (run_id, kind, status) VALUES (999, 'restaurants', 'done')")
    for item_id, name, description in (
        (971, "Mal paso", "Whiskey con coca-cola"),
        (972, "Papas Deli", "Papas fritas"),
        (973, "Café irlandés", "Café, whiskey y crema chantilly"),  # concepto cafe: uno de bebida no lo dice
        (974, "Risotto Deli", "Risotto de hongos al vino blanco"),  # concepto pastas: uno de comida, sí
        (975, "Combinado", "C&oacute;ctel de la casa"),  # la descripción llega con entidades HTML
    ):
        add_dish(db, item_id, name, 22, "Combos")
        db.execute("UPDATE menu_items SET description = %s WHERE item_id = %s", (description, item_id))
        db.execute("INSERT INTO menu_price_snapshots (run_id, item_id, price) VALUES (999, %s, 5990)", (item_id,))
    stock(db, HashEmbedder(), [])  # la taxonomía en la base
    db.execute("DELETE FROM item_concepts WHERE entity_type = 'menu_item' AND entity_id IN ('971', '972', '975')")
    db.execute(
        """INSERT INTO item_concepts (entity_type, entity_id, concept_id, method, confidence)
           VALUES ('menu_item', '973', 'cafe', 'regla', 1), ('menu_item', '974', 'pastas', 'regla', 1)
           ON CONFLICT (entity_type, entity_id) DO UPDATE SET concept_id = EXCLUDED.concept_id"""
    )

    found = _priced_in_vertical(db, "restaurantes", ["971", "972", "973", "974", "975"])
    assert set(found) == {"972", "974"}


def test_vertical_to_try_never_offers_a_popular_drink_whose_description_names_alcohol(demo):
    """Los platos populares (`_popular_dishes`) tampoco pasan por la búsqueda de ofertas: un café con concepto `cafe`
    cuya descripción dice whiskey no se muestra."""
    from rappi_ia.offers.engine import _popular_dishes

    db, _ = demo
    db.execute(
        """UPDATE item_concepts SET concept_id = 'cafe'
           WHERE entity_type = 'menu_item' AND entity_id = '98004'"""
    )
    db.execute("REFRESH MATERIALIZED VIEW concept_assortment")
    cache.clear()
    assert "Tiramisú individual (prueba)" in {d["name"] for d in _popular_dishes(db)}

    db.execute("UPDATE menu_items SET description = 'Café, whiskey y crema' WHERE item_id = 98004")
    cache.clear()

    assert "Tiramisú individual (prueba)" not in {d["name"] for d in _popular_dishes(db)}


def test_vertical_to_try_never_offers_a_popular_dish_from_a_drinks_section(demo):
    from rappi_ia.offers.engine import _popular_dishes

    db, _ = demo
    assert "Tiramisú individual (prueba)" in {d["name"] for d in _popular_dishes(db)}
    db.execute(
        """UPDATE menu_sections SET name = 'Tragos de autor'
           WHERE (store_id, section_id) = (SELECT store_id, section_id FROM menu_items WHERE item_id = 98004)"""
    )
    cache.clear()

    assert "Tiramisú individual (prueba)" not in {d["name"] for d in _popular_dishes(db)}


def test_popular_dishes_come_from_the_catalog_cache(demo):
    """Buscar los platos populares recorre todos los platos: se guardan hasta una corrida nueva (o su TTL)."""
    from rappi_ia.offers.engine import _popular_dishes

    db, _ = demo
    first = _popular_dishes(db)
    assert first
    counting = CountingConnection(db)

    assert _popular_dishes(counting) == first
    assert not any("menu_items" in s for s in counting.statements)
    cache.clear()  # vence (corrida nueva o TTL): se buscan de nuevo
    assert _popular_dishes(counting) == first
    assert any("is_popular" in s for s in counting.statements)
