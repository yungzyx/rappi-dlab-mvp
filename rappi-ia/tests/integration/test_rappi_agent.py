"""Conducta del agente (docs/diseno-ia.md §4) contra `rappi_ia_test`, con el modelo falso de embeddings."""

from dataclasses import replace

import pytest
from rappi_scraper.storage.search import build_search_documents

from conftest import add_dish, add_price, add_product, add_store
from rappi_ia.agent import verticals
from rappi_ia.agent.rappi_agent import Context, RappiAgent
from rappi_ia.agent.tools import search_products
from rappi_ia.agent.verticals import ranked_verticals
from rappi_ia.concepts.pipeline import build_concepts
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents
from rappi_ia.retrieval import hybrid


@pytest.fixture
def rappi_agent(db):
    add_store(db, 1, "supermercado", "Súper")
    add_store(db, 2, "licores", "Botillería")
    add_store(db, 3, "restaurantes", "Pizzería")
    products = [
        (100, "Papas fritas Lays Clásicas 180 g", 1, "Snacks salados", 1990),
        (101, "Pizza congelada pepperoni", 1, "Pizas y tartas saladas", 3990),
        (200, "Cerveza Escudo Lata 470 cc", 2, "Cervezas", 1290),
        (201, "Cerveza Kunstmann Torobayo 330 cc", 2, "Cervezas", 2990),
        (202, "Cigarrillos Marlboro Rojo 20 u", 2, "Cigarrillos", 5500),
    ]
    for pid, name, store, category, price in products:
        add_product(db, pid, name, store, category)
        add_price(db, store, pid, price)
    add_dish(db, 500, "Pizza pepperoni familiar", 3, "Pizzas", ["Pizzas"])
    db.execute("INSERT INTO scrape_runs (run_id, kind, status) VALUES (999, 'restaurants', 'done')")
    db.execute("INSERT INTO menu_price_snapshots (run_id, item_id, price) VALUES (999, 500, 8990)")
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embedder = HashEmbedder()
    embed_search_documents(db, embedder)
    return RappiAgent(embedder), db


def test_greeting_does_not_hide_the_request_and_suggests_cross_vertical(rappi_agent):
    agent, db = rappi_agent
    r = agent.reply(db, "hola, quiero cerveza", Context(vertical="licores"))

    assert r["intent"]["kind"] == "buscar" and r["vertical"] == "licores"
    assert {p["concept"] for p in r["products"]} == {"cerveza"}
    assert all(p["price"].startswith("$") for p in r["products"])  # precios vigentes por SQL
    assert r["age_notice"] and "mayores de 18" in r["text"]
    assert r["suggestion"]["vertical"] == "supermercado"  # de otra tienda
    assert r["suggestion"]["concept"] == "snacks-salados"
    assert r["reason"] == r["suggestion"]["reason"] == "Porque llevas 🍺 cerveza"


def test_no_cross_suggestion_in_rappi_hoy_mode_or_when_topic_already_shown(rappi_agent):
    agent, db = rappi_agent
    assert "suggestion" not in agent.reply(db, "cerveza", Context(vertical="licores", mode="actual"))
    shown = Context(vertical="licores", shown_topics=["snacks-salados"])
    assert "suggestion" not in agent.reply(db, "cerveza", shown)


def test_tobacco_only_when_asked_by_name(rappi_agent):
    agent, db = rappi_agent
    carrete = agent.reply(db, "algo para el carrete", Context(vertical="licores"))
    assert "cigarrillos" not in {p["concept"] for p in carrete["products"]}
    asked = agent.reply(db, "cigarrillos marlboro", Context(vertical="licores"))
    assert [p["concept"] for p in asked["products"]] == ["cigarrillos"]
    assert "suggestion" not in asked  # un concepto sensible nunca es origen de una sugerencia


def test_price_filter_and_cheapest_alternative(rappi_agent):
    agent, db = rappi_agent
    cheap = agent.reply(db, "cerveza bajo 2 mil", Context(vertical="licores"))
    assert [p["entity_id"] for p in cheap["products"]] == ["200"]
    none = agent.reply(db, "cerveza bajo 500", Context(vertical="licores"))
    assert none["products"] == [] and "$1.290" in none["text"] and not none["unmet"]


def test_price_cap_never_shows_another_concept(rappi_agent):
    """Con tope, lo que cabe bajo el tope era otra cosa (vasos, chocolates) y se mostraba con «Porque llevas
    cerveza»; el «no hay bajo $X, el más barato cuesta $Y» nunca se alcanzaba."""
    agent, db = rappi_agent
    for pid, name, category, price in [
        (210, "Vasos Plásticos Desechables 10 u", "Vajilla desechable", 250),
        (211, "Chocolate Trencito 25 g", "Chocolates", 300),
    ]:
        add_product(db, pid, name, 2, category)
        add_price(db, 2, pid, price)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)

    r = agent.reply(db, "cerveza bajo 500", Context(vertical="licores"))

    assert r["products"] == [] and "suggestion" not in r
    assert "No encontré" in r["text"] and "$1.290" in r["text"] and not r["unmet"]


def test_cheapest_without_the_cap_is_also_of_the_requested_concept(rappi_agent):
    """Sin tope, el súper no trae cervezas entre sus resultados (un vaso calza la palabra y no es «sin resultado»):
    «el más barato» no puede ser otra cosa, como las papas fritas a $1.990."""
    agent, db = rappi_agent
    add_product(db, 220, "Vaso Schop Vidrio 500 ml", 1, "Vajilla")
    add_price(db, 1, 220, 2500)
    db.execute("UPDATE catalog_items SET description = 'Ideal para servir cerveza' WHERE master_product_id = 220")
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)

    r = agent.reply(db, "cerveza bajo 500", Context(vertical="supermercado"))

    assert r["vertical"] == "supermercado" and r["intent"]["concepts"] == ["cerveza"]
    assert r["products"] == [] and not r["unmet"]
    assert "más barato" not in r["text"] and "$1.990" not in r["text"]


def test_unmet_by_cosine_shows_nothing_and_is_recorded(rappi_agent, monkeypatch):
    """Sin concepto nombrado, «sin resultado» lo decide el coseno bajo τ: antes se mostraban sus vecinos igual
    (arena para gato a quien pedía un pasaje de avión, que hoy va a RappiTravel) y la demanda no se anotaba."""
    agent, db = rappi_agent
    monkeypatch.setattr(hybrid, "UNNAMED_TAU", 0.99)  # sin concepto ni ocasión decide UNNAMED_TAU

    r = agent.reply(db, "kombucha de jengibre artesanal", Context(vertical="supermercado"))

    assert r["intent"]["concepts"] == []
    assert r["products"] == [] and r["unmet"] and "τ" in r["unmet_reason"]
    assert "Lo anoté" in r["text"]


def test_a_query_without_words_to_search_is_not_recorded_as_unmet(rappi_agent, monkeypatch):
    """«té» es stopword: la regla léxica estricta nunca puede confirmarlo y, sin concepto nombrado, solo quedaba el
    coseno bajo τ. Express y Licores respondían «No encontré «té»… Lo anoté» teniendo decenas de tés."""
    agent, db = rappi_agent
    add_product(db, 820, "Té Supremo Canela 20 bolsitas", 1, "Té e infusiones")
    add_price(db, 1, 820, 1990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)
    monkeypatch.setattr(hybrid, "UNNAMED_TAU", 0.99)  # sin concepto ni ocasión decide UNNAMED_TAU

    # «porfa» queda al final de la consulta limpia (solo se limpia el inicio) y no es algo que buscar.
    for text in ["té", "quiero té porfa"]:
        r = agent.reply(db, text, Context(vertical="supermercado"))

        assert r["intent"]["concepts"] == [], text
        assert not r["unmet"] and r["products"] and "Lo anoté" not in r["text"], text


def test_symptoms_are_not_recorded_as_unmet_demand(rappi_agent, monkeypatch):
    """Sin remedios para el síntoma se muestra lo de cuidarse: no mostrar lo pedido no es falta de surtido. «tengo
    tos» quedaba anotado como demanda no satisfecha por el coseno bajo τ."""
    agent, db = rappi_agent
    monkeypatch.setattr(hybrid, "UNNAMED_TAU", 0.99)  # sin concepto ni ocasión decide UNNAMED_TAU

    r = agent.reply(db, "tengo tos", Context(vertical="supermercado"))

    assert not r["unmet"] and "Lo anoté" not in r["text"]


def test_conditioner_finds_conditioners_and_soap_finds_soap(rappi_agent):
    """El concepto de la consulta sale de las keywords y el del producto de su categoría: si no coinciden
    («acondicionador» era keyword de higiene-personal y los acondicionadores están en cuidado-cabello), el foco se
    quedaba con el jabón. Se arregla en la taxonomía, no cediendo el foco ante las palabras."""
    agent, db = rappi_agent
    for pid, name, category in [
        (800, "Acondicionador Sedal Ceramidas 340 ml", "Acondicionador"),
        (801, "Acondicionador Pantene Rizos Definidos 400 ml", "Acondicionador"),
        (802, "Jabón Líquido Dove Original 250 ml", "Jabones y exfoliantes corporales"),
    ]:
        add_product(db, pid, name, 1, category)
        add_price(db, 1, pid, 2990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)

    outcome = search_products(db, "supermercado", "acondicionador", None, agent.embedder)

    assert outcome.result.query_concepts == ["cuidado-cabello"]
    assert {p.entity_id for p in outcome.products} == {"800", "801"}
    soap = search_products(db, "supermercado", "jabón", None, agent.embedder)
    assert [p.entity_id for p in soap.products] == ["802"]


def test_chance_word_matches_do_not_replace_the_concept_of_the_query(rappi_agent):
    """La coincidencia estricta mira todo el texto (descripción y categoría incluidas) y el stemming junta palabras
    (flores/flor, perfume/perfuma): si el foco cedía ante esa mayoría, «flores» mostraba azúcar flor y ron Flor de
    Caña, y «perfume» un suavizante y un limpiapisos que «perfuman»."""
    agent, db = rappi_agent
    for pid, name, category, description in [
        (810, "Ramo de Rosas Rojas 12 u", "Regalos", None),
        (811, "Azúcar Flor Iansa 1 kg", "Azúcar y endulzantes", None),
        (812, "Ron Flor de Caña 4 Años 750 ml", "Ron", None),
        (813, "Body Mist Bfresh Vainilla 250 ml", "Fragancias", None),
        (814, "Suavizante Downy Brisa 1 L", "Suavizantes", "Perfuma tu ropa por semanas"),
        (815, "Limpiapisos Excell Lavanda 900 ml", "Limpiapisos", "Perfuma tu hogar"),
    ]:
        add_product(db, pid, name, 1, category)
        add_price(db, 1, pid, 2990)
        if description:
            db.execute("UPDATE catalog_items SET description = %s WHERE master_product_id = %s", (description, pid))
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)

    flowers = search_products(db, "supermercado", "flores", None, agent.embedder)
    perfume = search_products(db, "supermercado", "perfume", None, agent.embedder)

    assert flowers.result.query_concepts == ["flores-regalos"]
    assert [p.entity_id for p in flowers.products] == ["810"]
    assert perfume.result.query_concepts == ["fragancias"]
    assert [p.entity_id for p in perfume.products] == ["813"]


def test_filler_prices_are_never_shown(rappi_agent):
    """$0 y $1 son precios de relleno de platos que dependen de sus opciones: pasaban cualquier tope y se ofrecían
    a «$0»."""
    agent, db = rappi_agent
    for item_id, name, price in [
        (530, "Completo Dinámico", 0),
        (531, "Completo Elige Tu Salsa", 1),
        (532, "Completo Italiano", 900),
    ]:
        add_dish(db, item_id, name, 3, "Completos")
        db.execute("INSERT INTO menu_price_snapshots (run_id, item_id, price) VALUES (999, %s, %s)", (item_id, price))
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)

    capped = search_products(db, "restaurantes", "completo", None, agent.embedder, price_max=1000)
    assert [p.entity_id for p in capped.products] == ["532"]
    shown = [p.entity_id for p in search_products(db, "restaurantes", "completo", None, agent.embedder).products]
    assert "532" in shown and not {"530", "531"} & set(shown)


def test_the_price_shown_is_from_the_current_branch_not_an_old_one(rappi_agent):
    """608121 en Licores: una sucursal que solo salió en la corrida 1 lo tenía a $39.950 y la vigente del mismo formato
    lo vende a $77.940. La búsqueda ya filtraba por $77.940, pero el agente mostraba $39.950 de la sucursal vieja."""
    agent, db = rappi_agent
    for store_id, name in [(4, "Mi Market Vieja"), (5, "Mi Market Licores")]:
        add_store(db, store_id, "licores", name)
    db.execute("UPDATE stores SET store_type = 'mi_market_licores' WHERE store_id IN (4, 5)")
    add_product(db, 230, "Whisky Johnnie Walker Black Label 750 cc", 4, "Whiskys")
    db.execute("INSERT INTO store_products (store_id, sku, master_product_id) VALUES (5, 'sku-230', 230)")
    old_run, new_run = (
        db.execute("INSERT INTO scrape_runs (kind, status) VALUES ('stores', 'done') RETURNING run_id").fetchone()[0]
        for _ in range(2)
    )
    db.execute(
        """INSERT INTO price_snapshots (run_id, store_id, sku, price, in_stock, scraped_at)
           VALUES (%s, 4, 'sku-230', 39950, true, now() - interval '1 week'), (%s, 5, 'sku-230', 77940, true, now())""",
        (old_run, new_run),
    )
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)

    for price_max in (None, 80000):
        products = search_products(db, "licores", "whisky", None, agent.embedder, price_max=price_max).products
        assert [(p.entity_id, p.price_value, p.store) for p in products] == [("230", 77940, "Mi Market Licores")]


def test_a_price_saved_twice_with_the_same_date_is_still_shown(rappi_agent):
    """Importar dos veces el mismo CSV legacy guarda el precio con la misma fecha en dos corridas. El último precio se
    elegía sin desempate y, si no era el de la corrida que la vigencia toma por última (desempata por run_id), Mochi
    ocultaba el producto aunque estuviera en la búsqueda."""
    agent, db = rappi_agent
    add_store(db, 6, "licores", "Botillería Centro")
    add_product(db, 240, "Pisco Mistral 35° 750 cc", 6, "Pisco")
    new_run = "INSERT INTO scrape_runs (kind, status) VALUES ('legacy_csv', 'done') RETURNING run_id"
    runs = [db.execute(new_run).fetchone()[0] for _ in range(2)]
    db.execute(
        """INSERT INTO price_snapshots (run_id, store_id, sku, price, in_stock, scraped_at)
           VALUES (%s, 6, 'sku-240', 6990, true, '2026-09-24'), (%s, 6, 'sku-240', 6990, true, '2026-09-24')""",
        runs,
    )
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)

    products = search_products(db, "licores", "pisco mistral", None, agent.embedder).products
    assert [p.entity_id for p in products] == ["240"]


def test_ambiguous_between_restaurant_and_store_asks(rappi_agent):
    agent, db = rappi_agent
    r = agent.reply(db, "quiero pizza")
    assert r["intent"]["kind"] == "aclarar"
    assert {a["vertical"] for a in r["actions"]} == {"restaurantes", "supermercado"}
    assert r["text"].startswith("¿🍕 Pizza")


def test_unmet_demand_is_flagged_and_said(rappi_agent):
    agent, db = rappi_agent
    r = agent.reply(db, "kebab mixto", Context(vertical="restaurantes"))
    assert r["unmet"] and r["products"] == []
    assert "No encontré" in r["text"] and "Lo anoté" in r["text"]


def test_greeting_mentions_only_offerable_interests(rappi_agent):
    """Mochi no saluda con «Veo tu interés en…» de algo sensible, alcohol, salud ni bebé: pasa al siguiente interés."""
    agent, db = rappi_agent
    blocked = {"cigarrillos": 9.0, "cerveza": 3.0, "panales": 2.5, "vitaminas": 2.0, "medicamentos": 1.5}
    for profile in (blocked, {"cerveza": 1.0}, {"panales": 1.0}, {"vitaminas": 1.0}):
        assert "Veo tu interés" not in agent.reply(db, "hola", Context(profile=profile))["text"], profile
    hello = agent.reply(db, "hola", Context(profile={**blocked, "snacks-salados": 0.5}))
    assert "snacks salados" in hello["text"].lower() and "cerveza" not in hello["text"].lower()


def test_explicit_request_wins_over_occasion(rappi_agent):
    agent, db = rappi_agent
    r = agent.reply(db, "cervezas y papas fritas para el carrete", Context(vertical="licores"))
    assert r["intent"]["kind"] == "ocasion" and r["intent"]["occasion"] == "carrete"
    assert set(r["intent"]["concepts"]) == {"cerveza", "snacks-salados"}
    assert {p["concept"] for p in r["products"]} <= {"cerveza", "snacks-salados"}


def test_symptoms_without_pharmacy_remedies_never_bring_medicines(rappi_agent):
    agent, db = rappi_agent
    r = agent.reply(db, "tengo fiebre", Context(vertical="supermercado"))
    assert "medicamentos" not in {p["concept"] for p in r["products"]}


def test_symptoms_starting_with_me_are_symptoms_and_bring_no_unlabeled_painkillers(rappi_agent):
    """«me duele la cabeza» se limpiaba a «duele la cabeza» antes de buscar el síntoma, y mostraba un analgésico sin
    concepto que calzaba la palabra «cabeza»."""
    agent, db = rappi_agent
    add_product(db, 710, "Anacin Max Dolor de Cabeza X 8 Comprimidos", 1, "Analgésicos sistémicos")
    add_price(db, 1, 710, 2600)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)

    r = agent.reply(db, "me duele la cabeza", Context(vertical="supermercado"))

    assert r["intent"]["occasion"] == "enfermo"
    assert "710" not in [p["entity_id"] for p in r["products"]]


def test_unlabeled_medicines_are_never_shown_for_symptoms_or_in_pharmacy(rappi_agent, monkeypatch):
    """El filtro de sensibles miraba solo el concepto: un medicamento sin concepto (su categoría, «Analgésicos
    sistémicos», no está en category_map.csv) pasaba siempre. «tengo tos» mostraba antitusivos y «me siento mal»,
    laxantes, traídos por cercanía. Con síntomas, o en farmacia, lo que no tiene concepto no se muestra."""
    agent, db = rappi_agent
    add_store(db, 11, "farmacia", "Farmacia")
    for pid, name, store, category in [
        (710, "Anacin Max Dolor de Cabeza y Tos X 8 Comprimidos", 1, "Analgésicos sistémicos"),
        (711, "Anacin Clásico Nivea X 8 Comprimidos", 11, "Analgésicos sistémicos"),
        (712, "Crema de Manos Nivea 75 ml", 11, "Cremas de manos"),
    ]:
        add_product(db, pid, name, store, category)
        add_price(db, store, pid, 2600)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)
    monkeypatch.setattr(hybrid, "thresholds", lambda: {"supermercado": 0.0, "farmacia": 0.0})  # sin «sin resultado»
    monkeypatch.setattr(hybrid, "UNNAMED_TAU", 0.0)

    for text in ["tengo tos", "me duele la cabeza"]:
        r = agent.reply(db, text, Context(vertical="supermercado"))
        assert "710" not in [p["entity_id"] for p in r["products"]], text
    shown = [p["entity_id"] for p in agent.reply(db, "nivea", Context(vertical="farmacia"))["products"]]
    assert "712" in shown and "711" not in shown


def test_the_suggestion_reason_names_what_the_answer_shows_and_symptoms_get_none(rappi_agent):
    """En una ocasión, el origen de la sugerencia salía de todos sus conceptos: «regalo para mi polola» mostraba solo
    chocolates y decía «Porque llevas 🍷 vino». A quien tiene fiebre se le hacía venta cruzada («Porque llevas 🍎
    frutas», sin frutas en la respuesta), aunque con síntomas ni siquiera se muestra «También en»."""
    agent, db = rappi_agent
    add_store(db, 10, "chocolateria", "Chocolatería")
    for pid, name, store, category in [
        (600, "Chocolate Sahne-Nuss 250 g", 10, "Chocolates"),
        (620, "Queso Gouda Colún 250 g", 1, "Quesos"),
        (621, "Café Nescafé Tradición 170 g", 1, "Café"),
        (622, "Jugo Watts Naranja 1 L", 1, "Jugos"),
        (623, "Leche Colún Entera 1 L", 1, "Leches"),
    ]:
        add_product(db, pid, name, store, category)
        add_price(db, store, pid, 1990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)

    gift = agent.reply(db, "regalo para mi polola", Context(vertical="chocolateria"))
    assert {p["concept"] for p in gift["products"]} == {"chocolates"}
    assert gift["suggestion"]["reason"] == "Porque llevas 🍫 chocolates"

    sick = agent.reply(db, "tengo fiebre", Context(vertical="supermercado"))
    assert sick["products"] and "suggestion" not in sick and sick["reason"] is None
    # Con un concepto nombrado que sí tiene complemento (el mismo que sugiere en el regalo), tampoco.
    sick = agent.reply(db, "tengo fiebre, quiero chocolate", Context(vertical="chocolateria"))
    assert {p["concept"] for p in sick["products"]} == {"chocolates"}
    assert "suggestion" not in sick and sick["reason"] is None


def test_the_pizza_answer_has_no_cross_suggestion_of_alcohol_and_so_no_age_notice(rappi_agent):
    """Antes la pizza sugería cerveza y la nota +18 cubría esa sugerencia. El alcohol ya no es un complemento
    (offers/guards.py, que manda sobre docs/diseno-ia.md regla 6b): la pizza no trae cerveza ni nota +18."""
    agent, db = rappi_agent
    r = agent.reply(db, "pizza", Context(vertical="restaurantes"))
    assert r["products"] and "suggestion" not in r and not r["age_notice"]


def test_unmet_is_recorded_even_with_a_price_cap(rappi_agent):
    agent, db = rappi_agent
    r = agent.reply(db, "kebab bajo 10 mil", Context(vertical="restaurantes"))
    assert r["unmet"] and "Lo anoté" in r["text"]


def test_occasion_picks_its_vertical_without_asking_about_its_first_concept(rappi_agent):
    """Antes el vertical salía solo del primer concepto de la ocasión: 'tengo hambre' preguntaba por pizza (o iba
    al súper) y un carrete iba adonde estuviera la cerveza aunque el resto de la ocasión estuviera en otro lado."""
    agent, db = rappi_agent
    hungry = agent.reply(db, "tengo hambre", Context())
    assert hungry["intent"]["kind"] == "ocasion" and hungry["vertical"] == "restaurantes"  # vertical fijo
    # Carrete: cerveza (2 en licores) va primero, pero snacks (3 en el súper) pesa más en el total de la ocasión.
    for pid, name in [(102, "Ramitas Evercrisp Queso 250 g"), (103, "Papas Kryzpo Original 130 g")]:
        add_product(db, pid, name, 1, "Snacks salados")
        add_price(db, 1, pid, 1590)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    party = agent.reply(db, "arma un carrete", Context())
    assert party["intent"]["kind"] == "ocasion" and party["vertical"] == "supermercado"


@pytest.fixture
def pharmacy_rappi_agent(rappi_agent):
    """Farmacia con las categorías que esos productos tienen en la base (category_map.csv): «Antiácidos» y
    «Gotas, lubricantes y lágrimas» son medicamentos, «Lubricantes» es bienestar sexual."""
    agent, db = rappi_agent
    add_store(db, 11, "farmacia", "Farmacia")
    products = [
        (700, "Sal de Fruta Eno Limón 5 g", "Antiácidos"),
        (701, "Bentley Gel Lubricante Íntimo Ice 60 ml", "Lubricantes"),
        (702, "Systane Lubricante Ocular Ultra 10 ml", "Gotas, lubricantes y lágrimas"),
    ]
    for pid, name, category in products:
        add_product(db, pid, name, 11, category)
        add_price(db, 11, pid, 4990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)
    return agent, db


@pytest.fixture
def remedies_rappi_agent(rappi_agent):
    """Farmacia con remedios para la fiebre (uno con receta) y algo para el súper."""
    agent, db = rappi_agent
    add_store(db, 11, "farmacia", "Farmacia")
    for pid, name in [
        (800, "Paracetamol 500 mg para la fiebre y el dolor 16 comprimidos"),
        (801, "Tapsin Día fiebre y resfrío 18 comprimidos"),
        (802, "Amoxicilina 500 mg para la fiebre 21 cápsulas"),
        (803, "Crema de manos Nivea 75 ml"),
    ]:
        add_product(db, pid, name, 11, "Analgésicos tópicos" if pid != 803 else "Cremas de manos")
        add_price(db, 11, pid, 2990)
    db.execute(
        "UPDATE store_products SET raw = '{\"requires_medical_prescription\": true}' WHERE master_product_id = 802"
    )
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)
    return agent, db


def test_a_symptom_goes_to_pharmacy_with_remedies_and_no_notice(remedies_rappi_agent):
    """«tengo fiebre» iba a Express con sopas y jugos, escondía los remedios y agregaba «consulta a un químico
    farmacéutico»: cortaba la compra. Ahora va a Farmacia con lo que se vende para eso, nunca con receta."""
    agent, db = remedies_rappi_agent
    for ctx in (Context(), Context(vertical="conveniencia")):
        r = agent.reply(db, "tengo fiebre", ctx)
        ids = [p["entity_id"] for p in r["products"]]
        assert r["vertical"] == "farmacia" and {"800", "801"} <= set(ids)
        assert "802" not in ids  # con receta
        assert "químico farmacéutico" not in r["text"]
        assert not r.get("suggestion") and not r.get("also_in") and not r["unmet"]


def test_a_symptom_without_remedies_for_it_gets_no_medicine(remedies_rappi_agent):
    """Si nada en la farmacia nombra el síntoma («me siento mal», «tengo tos»), Mochi no elige un remedio (antes, los
    analgésicos; 24-10, docs/decisiones.md): lo dice, nombra al químico farmacéutico y no anota demanda."""
    agent, db = remedies_rappi_agent
    for text in ["me siento mal", "tengo tos"]:
        r = agent.reply(db, text, Context(vertical="supermercado"))
        assert not any(p["concept"] == "medicamentos" for p in r["products"]), text
        assert r["text"].startswith("No encontré en Farmacia un remedio") and "químico farmacéutico" in r["text"], text
        assert not r["unmet"] and not r.get("suggestion") and not r.get("also_in"), text
    assert not agent.reply(db, "tengo fiebre", Context())["text"].startswith("No encontré")


def test_a_trip_opens_rappitravel_and_suggests_something_for_it(rappi_agent):
    """RappiTravel no tiene catálogo: Mochi lleva a su pantalla y suma un gancho del catálogo para el viaje."""
    agent, db = rappi_agent
    add_store(db, 11, "farmacia", "Farmacia")
    add_store(db, 12, "mall", "Tienda")
    add_product(db, 900, "Protector solar Eucerin FPS 50 50 ml", 11, "Protectores solares faciales")
    add_price(db, 11, 900, 15990)
    add_product(db, 901, "Bikini triángulo dos piezas", 12, "Bikinis")
    add_price(db, 12, 901, 12990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)

    # El protector solar es de farmacia y del grupo salud: Mochi no lo propone, aunque «playa» lo enganche primero.
    r = agent.reply(db, "me voy de vacaciones a la playa", Context())
    assert r["intent"]["kind"] == "servicio" and r["service"] == "rappitravel"
    assert r["actions"] == [{"label": "Abrir RappiTravel", "route": ["travel"], "service": "rappitravel"}]
    assert "RappiTravel" in r["text"] and not r["products"]
    assert r["suggestion"]["concept"] == "ropa" and r["suggestion"]["reason"] == "Para tu viaje ✈️"
    assert [p["entity_id"] for p in r["suggestion"]["products"]] == ["901"]
    # Una sola sugerencia por tema en la sesión: si ya se mostró, se pasa al siguiente gancho (o a ninguno).
    again = agent.reply(db, "me voy de vacaciones a la playa", Context(shown_topics=["ropa"]))
    assert again.get("suggestion", {}).get("concept") != "ropa"
    # En «Rappi hoy» no hay ganchos.
    assert "suggestion" not in agent.reply(db, "me voy de vacaciones", Context(mode="actual"))


def test_the_trip_hook_depends_on_where_you_go(rappi_agent):
    """«playa» engancha un traje de baño (no el protector solar: es de farmacia y salud); «nieve», una chaqueta; un
    viaje sin contexto, una mochila de viaje."""
    agent, db = rappi_agent
    add_store(db, 11, "farmacia", "Farmacia")
    add_store(db, 12, "mall", "Tienda")
    for pid, name, store, category in [
        (900, "Protector solar Eucerin FPS 50 50 ml", 11, "Protectores solares faciales"),
        (901, "Chaqueta acolchada impermeable hombre", 12, "Abrigos, Chamarras, Chalecos"),
        (902, "Mochila de viaje 40 litros", 12, "Maletas de viaje"),
        (903, "Bikini triángulo dos piezas", 12, "Bikinis"),
    ]:
        add_product(db, pid, name, store, category)
        add_price(db, store, pid, 19990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)

    def hook(text):
        suggestion = agent.reply(db, text, Context())["suggestion"]
        return suggestion["question"], [p["entity_id"] for p in suggestion["products"]]

    # Traje de baño y chaqueta son ropa: la búsqueda del gancho trae las dos; la pregunta dice cuál gancho fue.
    question, ids = hook("me voy de vacaciones a la playa")
    assert question == "¿Te falta traje de baño? 👙" and "903" in ids and "900" not in ids
    question, ids = hook("me voy de viaje a la nieve")
    assert question == "¿Te falta una chaqueta para el frío? 🧥" and "901" in ids
    assert hook("busco un hotel en puerto varas") == ("¿Te falta una mochila de viaje? 🎒", ["902"])


def test_a_gift_can_be_sent_with_rappifavor(rappi_agent):
    agent, db = rappi_agent
    r = agent.reply(db, "un regalo para mi mamá", Context())
    assert {"label": "Mandarlo con RappiFavor", "route": ["favor"], "service": "rappifavor"} in r["actions"]
    assert r["service"] == "rappifavor"
    assert not agent.reply(db, "un regalo para mi mamá", Context(mode="actual"))["actions"]


def test_an_errand_opens_rappifavor(rappi_agent):
    agent, db = rappi_agent
    r = agent.reply(db, "se me quedaron las llaves en la oficina", Context())
    assert r["service"] == "rappifavor"
    assert r["actions"] == [{"label": "Abrir RappiFavor", "route": ["favor"], "service": "rappifavor"}]
    assert "suggestion" not in r


def test_what_is_not_in_the_catalog_can_be_bought_with_rappifavor(rappi_agent, monkeypatch):
    """«No está en el catálogo» era el final: ahora RappiFavor lo compra en otra tienda (solo en «Propuesta»)."""
    agent, db = rappi_agent
    monkeypatch.setattr(hybrid, "UNNAMED_TAU", 0.99)  # sin concepto ni ocasión decide UNNAMED_TAU
    r = agent.reply(db, "kombucha de jengibre", Context(vertical="supermercado"))
    assert (
        r["unmet"] and {"label": "Pedirlo con RappiFavor", "route": ["favor"], "service": "rappifavor"} in r["actions"]
    )
    assert r["service"] == "rappifavor"  # el prototipo lo registra como ofrecido
    assert "RappiFavor" in r["text"]
    actual = agent.reply(db, "kombucha de jengibre", Context(vertical="supermercado", mode="actual"))
    assert actual["unmet"] and not actual["actions"]


def test_sensitive_concepts_are_found_when_asked_by_their_plain_name(pharmacy_rappi_agent):
    """«medicamentos» y «lubricante» no asignan productos, pero en la consulta nombran el concepto: sin él, los
    sensibles quedaban ocultos («necesito medicamentos» iba al súper y «lubricante» no encontraba nada)."""
    agent, db = pharmacy_rappi_agent
    medicines = agent.reply(db, "necesito medicamentos", Context())
    assert medicines["vertical"] == "farmacia"
    assert "700" in [p["entity_id"] for p in medicines["products"]]
    assert {p["concept"] for p in medicines["products"]} == {"medicamentos"}

    for text in ("venden medicamentos", "necesito los medicamentos"):  # daban «No encontré… Lo anoté»
        asked = agent.reply(db, text, Context(vertical="farmacia"))
        assert "700" in [p["entity_id"] for p in asked["products"]] and not asked["unmet"], text

    lube = agent.reply(db, "lubricante", Context(vertical="farmacia"))
    assert [p["entity_id"] for p in lube["products"]] == ["701"] and lube["age_notice"]
    eyes = agent.reply(db, "lubricante ocular", Context(vertical="farmacia"))
    assert eyes["products"][0]["entity_id"] == "702"
    assert "701" not in [p["entity_id"] for p in eyes["products"]]


def test_words_that_only_ask_for_a_sensitive_concept_do_not_hide_what_was_asked(rappi_agent, monkeypatch):
    """Con otras palabras, «lubricante» y «medicamentos» son un complemento: «lubricante wd-40» mostraba lubricantes
    íntimos con el aviso +18 y «pastillero para medicamentos», analgésicos en vez de pastilleros."""
    agent, db = rappi_agent
    add_store(db, 11, "farmacia", "Farmacia")
    add_store(db, 12, "mall", "Ferretería")
    for pid, name, store, category in [
        (900, "Lubricante Multiuso WD-40 311 g", 12, "Aerosoles y pinturas"),
        (901, "Bentley Gel Lubricante Íntimo Ice 60 ml", 12, "Lubricantes"),
        (910, "Pastillero Semanal 7 Días", 11, "Otros Equipo y material médico"),
        (911, "Paracetamol 500 mg 16 Comprimidos", 11, "Analgésicos sistémicos"),
    ]:
        add_product(db, pid, name, store, category)
        add_price(db, store, pid, 3990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)
    monkeypatch.setattr(hybrid, "thresholds", lambda: {"mall": 0.0, "farmacia": 0.0})  # sin «sin resultado»
    monkeypatch.setattr(hybrid, "UNNAMED_TAU", 0.0)

    oil = agent.reply(db, "lubricante wd-40", Context(vertical="mall"))
    assert [p["entity_id"] for p in oil["products"]] == ["900"] and not oil["age_notice"]
    assert "bienestar-sexual" not in oil["intent"]["concepts"]
    pills = agent.reply(db, "pastillero para medicamentos", Context(vertical="farmacia"))
    assert [p["entity_id"] for p in pills["products"]] == ["910"]


def test_hunger_includes_roast_and_fried_chicken(rappi_agent):
    """Los conceptos de la ocasión son el foco de la búsqueda: desde que el pollo asado o frito es `pollo-preparado`
    (y no `pollo`), «tengo hambre» lo descartaba."""
    agent, db = rappi_agent
    add_dish(db, 520, "Pollo Asado Entero", 3, "Pollos")
    db.execute("INSERT INTO menu_price_snapshots (run_id, item_id, price) VALUES (999, 520, 9990)")
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)
    r = agent.reply(db, "tengo hambre", Context())
    assert r["vertical"] == "restaurantes"
    assert "520" in [p["entity_id"] for p in r["products"]]


def test_concept_without_assortment_goes_to_its_group_vertical(rappi_agent):
    agent, db = rappi_agent
    r = agent.reply(db, "quiero sushi", Context())  # no hay sushi en ningún vertical
    assert r["vertical"] == "restaurantes" and r["unmet"]


@pytest.fixture
def volume_rappi_agent(rappi_agent):
    """Como en la base real: restaurantes tiene muchos más ítems de casi todo que las tiendas (cada local lista sus
    papas fritas y su schop), aunque en su catálogo esos conceptos pesen poco."""
    agent, db = rappi_agent
    add_store(db, 4, "restaurantes", "Sanguchería")
    dishes = [
        (501, "Papas fritas medianas"),
        (502, "Papas fritas grandes"),
        (503, "Papas fritas con queso"),
        (504, "Schop cerveza Escudo"),
        (505, "Cerveza Kunstmann lager"),
        (506, "Cerveza Austral calafate"),
        (507, "Hamburguesa clásica"),
        (508, "Hamburguesa doble queso"),
        (509, "Hamburguesa italiana"),
        (510, "Hamburguesa vegana"),
        (511, "Hamburguesa BBQ"),
        (512, "Hamburguesa con palta"),
        (513, "Hamburguesa con huevo"),
        (514, "Hamburguesa de pollo"),
        (515, "Hamburguesa de queso"),
        (516, "Hamburguesa americana"),
        (517, "Hamburguesa chilena"),
        (518, "Hamburguesa mexicana"),
        (519, "Hamburguesa ranchera"),
        (520, "Hamburguesa XL"),
    ]
    for item_id, name in dishes:
        add_dish(db, item_id, name, 4, "Carta", ["Hamburguesas"])
        db.execute("INSERT INTO menu_price_snapshots (run_id, item_id, price) VALUES (999, %s, 4990)", (item_id,))
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)
    return agent, db


def test_cross_suggestion_goes_where_the_concept_is_typical_not_where_there_are_more_items(volume_rappi_agent):
    """Restaurantes tiene 3 papas fritas y el súper 1, pero en el súper los snacks son su catálogo y en el
    restaurante un acompañamiento: la sugerencia para la cerveza viene del súper."""
    agent, db = volume_rappi_agent
    r = agent.reply(db, "cerveza", Context(vertical="licores"))
    assert r["suggestion"]["concept"] == "snacks-salados"
    assert r["suggestion"]["vertical"] == "supermercado"


def test_store_products_asked_from_home_go_to_a_store_without_asking(volume_rappi_agent):
    """Hay más cervezas en restaurantes (3) que en Licores (2): antes preguntaba "¿restaurante o Licores?"."""
    agent, db = volume_rappi_agent
    r = agent.reply(db, "quiero cerveza", Context())
    assert r["intent"]["kind"] == "buscar"
    assert r["vertical"] == "licores"


def test_prepared_food_still_goes_to_restaurants(volume_rappi_agent):
    agent, db = volume_rappi_agent
    r = agent.reply(db, "una hamburguesa", Context())
    assert r["vertical"] == "restaurantes"
    assert {p["concept"] for p in r["products"]} == {"hamburguesa"}


def test_answer_shows_other_verticals_with_offer_and_real_stores(volume_rappi_agent, monkeypatch):
    """Multiverticalidad visible: la cerveza también está en el súper (y no se ofrece el restaurante, donde es
    un acompañamiento). Cada vertical trae sus tiendas: nombre y logo si el scraper lo guardó."""
    agent, db = volume_rappi_agent
    monkeypatch.setattr(verticals, "MIN_ITEMS_ELSEWHERE", 1)  # el catálogo de prueba es chico
    add_product(db, 300, "Cerveza Cristal Lata 470 cc", 1, "Cervezas")
    add_price(db, 1, 300, 990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)

    r = agent.reply(db, "cerveza", Context(vertical="licores"))
    also = r["also_in"]
    assert also["concept"] == "cerveza"
    assert [v["vertical"] for v in also["verticals"]] == ["supermercado"]
    [super_] = also["verticals"]
    assert super_["prototype_vertical"] == "grocery" and super_["items"] == 1
    assert super_["stores"] == [{"name": "Súper", "logo": None}]


def test_other_verticals_also_when_the_current_one_has_nothing(rappi_agent, monkeypatch):
    """«También en» tomaba el concepto de los productos mostrados: justo cuando la vertical actual no tiene lo pedido
    («vodka» en farmacia) no decía dónde sí está."""
    agent, db = rappi_agent
    monkeypatch.setattr(verticals, "MIN_ITEMS_ELSEWHERE", 1)  # el catálogo de prueba es chico
    add_store(db, 11, "farmacia", "Farmacia")
    for pid, name, store, category in [
        (230, "Vodka Absolut Blue 750 ml", 2, "Vodka"),
        (720, "Sal de Fruta Eno Limón 5 g", 11, "Antiácidos"),
    ]:
        add_product(db, pid, name, store, category)
        add_price(db, store, pid, 9990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)

    r = agent.reply(db, "vodka", Context(vertical="farmacia"))

    assert r["products"] == [] and r["intent"]["concepts"] == ["vodka"]
    assert r["also_in"]["concept"] == "vodka"
    assert [v["vertical"] for v in r["also_in"]["verticals"]] == ["licores"]


def test_no_other_verticals_for_sensitive_or_in_rappi_hoy(volume_rappi_agent):
    agent, db = volume_rappi_agent
    assert "also_in" not in agent.reply(db, "cigarrillos marlboro", Context(vertical="licores"))
    assert "also_in" not in agent.reply(db, "una hamburguesa", Context(mode="actual"))


def test_other_verticals_do_not_repeat_a_chain(volume_rappi_agent, monkeypatch):
    agent, db = volume_rappi_agent
    monkeypatch.setattr(verticals, "MIN_ITEMS_ELSEWHERE", 1)
    add_store(db, 5, "conveniencia", "Súper")  # la misma cadena también en Express
    add_store(db, 6, "conveniencia", "Minimarket")
    add_store(db, 7, "supermercado", "Almacén")
    for pid, store in [(300, 1), (301, 5), (302, 5), (303, 6), (304, 7)]:
        add_product(db, pid, f"Cerveza Cristal Lata {pid}", store, "Cervezas")
        add_price(db, store, pid, 990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)

    also = {
        v["vertical"]: [s["name"] for s in v["stores"]]
        for v in agent.reply(db, "cerveza", Context(vertical="licores"))["also_in"]["verticals"]
    }
    assert also["conveniencia"] == ["Súper", "Minimarket"]
    assert also["supermercado"] == ["Almacén"]  # "Súper" ya salió en Express


def test_other_verticals_are_ordered_by_how_much_offer_they_have(volume_rappi_agent, monkeypatch):
    """Para "¿dónde más lo encuentro?" pesa la cantidad: una chocolatería con 1 cerveza (el 100% de su catálogo
    chico) no va antes que un súper con 2."""
    agent, db = volume_rappi_agent
    monkeypatch.setattr(verticals, "MIN_ITEMS_ELSEWHERE", 1)
    add_store(db, 8, "chocolateria", "Chocolatería")
    for pid, store in [(300, 1), (301, 1), (305, 8)]:
        add_product(db, pid, f"Cerveza Cristal Lata {pid}", store, "Cervezas")
        add_price(db, store, pid, 990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)

    r = agent.reply(db, "cerveza", Context(vertical="licores"))
    assert [v["vertical"] for v in r["also_in"]["verticals"]] == ["supermercado", "chocolateria"]


def test_no_other_verticals_when_talking_about_symptoms(volume_rappi_agent, monkeypatch):
    """«malestar» y «cuidarme» son de la ocasión «Me siento mal» pero no de SYMPTOMS: sacaban Licores de la vertical,
    y aun así mostraban «También en» (con Licores)."""
    agent, db = volume_rappi_agent
    monkeypatch.setattr(verticals, "MIN_ITEMS_ELSEWHERE", 1)
    add_store(db, 9, "conveniencia", "Express")
    for pid, store in [(400, 1), (401, 9)]:
        add_product(db, pid, f"Jugo Watts Naranja {pid}", store, "Jugos")
        add_price(db, store, pid, 1290)
    db.commit()
    build_search_documents(db)
    build_concepts(db)

    assert "also_in" in agent.reply(db, "jugo de naranja", Context(vertical="supermercado"))
    for text in ["tengo fiebre, quiero jugo", "malestar", "algo para cuidarme"]:
        sick = agent.reply(db, text, Context(vertical="supermercado"))
        assert sick["products"] and "also_in" not in sick, text
        assert "me siento mal" not in sick["text"].lower(), text
    # Con otra ocasión antes en el texto («tecito» es once), «malestar» y «cuidarme» siguen siendo síntoma.
    for text in [
        "un tecito para el malestar",
        "despues del carrete tengo malestar",
        "despues del carrete quiero cuidarme",
    ]:
        sick = agent.reply(db, text, Context())
        assert sick["vertical"] != "licores" and "also_in" not in sick and "suggestion" not in sick, text


# Ítems con concepto por vertical en la base real (03-10): restaurantes es unas 5 veces el súper.
REAL_TOTALS = {
    "chocolateria": 1145,
    "turbo": 2562,
    "licores": 5734,
    "farmacia": 6141,
    "conveniencia": 9220,
    "supermercado": 32441,
    "mall": 35398,
    "restaurantes": 168668,
}


def _assortment(db, rows, totals=REAL_TOTALS):
    """Cambia el surtido materializado por cifras dadas (las de la base real no caben en un fixture). El resto de
    cada vertical va a un concepto de relleno, que cuenta en el total pero no existe en la taxonomía."""
    db.execute("DROP MATERIALIZED VIEW concept_assortment")
    db.execute("CREATE TABLE concept_assortment (concept_id text, vertical text, items integer)")
    used = {v: sum(n for _, vertical, n in rows if vertical == v) for v in totals}
    with db.cursor() as cur:
        cur.executemany(
            "INSERT INTO concept_assortment VALUES (%s, %s, %s)",
            [*rows, *(("relleno", v, totals[v] - used[v]) for v in totals)],
        )


def test_a_small_vertical_needs_enough_offer_to_be_chosen(rappi_agent):
    """Por participación, una vertical chica ganaba con un puñado de productos: «pan» iba a chocolaterías (46 de sus
    1.145 ítems) con 431 en el súper, y «quiero pastas» mostraba lasañas de una pastelería."""
    agent, db = rappi_agent
    _assortment(
        db,
        [("panaderia", "chocolateria", 10), ("panaderia", "supermercado", 150)],
        {"chocolateria": 200, "supermercado": 10_000},
    )
    assert ranked_verticals(db, ["panaderia"]) == ["supermercado", "chocolateria"]

    db.rollback()
    _assortment(
        db,
        [
            ("panaderia", "chocolateria", 46),
            ("panaderia", "conveniencia", 180),
            ("panaderia", "turbo", 36),
            ("panaderia", "supermercado", 431),
        ],
    )
    assert agent.reply(db, "pan", Context())["vertical"] == "conveniencia"
    assert verticals.typical_verticals(db)["panaderia"] == "conveniencia"
    # La lista sigue completa (la sugerencia y «También en» buscan también en las demás).
    assert set(ranked_verticals(db, ["panaderia"])) == {"chocolateria", "conveniencia", "turbo", "supermercado"}


def test_a_sick_person_is_never_sent_to_a_liquor_store(rappi_agent):
    """En Licores el jugo pesa más que en el súper (es para mezclar): «tengo fiebre, quiero jugo» iba a una
    botillería."""
    agent, db = rappi_agent
    _assortment(
        db,
        [
            ("jugos", "licores", 182),
            ("jugos", "turbo", 69),
            ("jugos", "conveniencia", 187),
            ("jugos", "supermercado", 421),
            ("jugos", "farmacia", 28),
        ],
    )
    intent = agent.understander.understand(db, "tengo fiebre, quiero jugo")
    assert intent.symptom and intent.concepts == ["jugos"]
    assert intent.vertical != "licores"


def test_a_gift_is_not_sent_to_a_liquor_store(rappi_agent):
    """En una ocasión se suman conceptos muy distintos y el piso de masa lo fija la tienda con más oferta de
    cualquiera: en «regalo», los juguetes y joyas del Mall dejaban fuera a las chocolaterías (419 chocolates) y un
    regalo pedido desde el inicio iba a Licores, con vinos y espumantes y el aviso +18."""
    agent, db = rappi_agent
    _assortment(
        db,
        [
            ("chocolates", "chocolateria", 419),
            ("vino", "licores", 801),
            ("espumante", "licores", 178),
            ("chocolates", "licores", 147),
            ("juguetes-infantiles", "mall", 1822),
            ("joyeria", "mall", 1423),
            ("fragancias", "mall", 514),
            ("chocolates", "mall", 153),
            ("flores-regalos", "mall", 153),
            ("chocolates", "supermercado", 936),
            ("juguetes-infantiles", "supermercado", 330),
            ("fragancias", "supermercado", 303),
            ("vino", "supermercado", 267),
        ],
    )
    intent = agent.understander.understand(db, "regalo para mi polola")
    assert intent.occasion == "regalo"
    assert intent.vertical == "chocolateria"


def test_ambiguity_is_measured_with_the_same_share_that_ranks(rappi_agent):
    """La vertical se elige por participación, pero la ambigüedad se medía con conteos: con restaurantes 5 veces más
    grande, ningún concepto llegaba al umbral (0 de 112) y «aclarar» no salía nunca. Cifras de la base real."""
    agent, db = rappi_agent
    _assortment(
        db,
        [
            ("platos-listos", "restaurantes", 3024),
            ("platos-listos", "supermercado", 463),
            ("platos-listos", "conveniencia", 89),
            ("platos-listos", "turbo", 23),
            ("platos-listos", "chocolateria", 14),
            ("pizza", "restaurantes", 11361),
            ("pizza", "supermercado", 167),
            ("pizza", "conveniencia", 35),
            ("pizza", "chocolateria", 10),
            ("latina", "restaurantes", 900),
            ("latina", "chocolateria", 10),
        ],
    )
    ready = agent.understander.understand(db, "platos listos")
    assert ready.concepts == ["platos-listos"]
    assert ready.kind == "aclarar" and set(ready.options) == {"restaurantes", "supermercado"}
    assert agent.understander.understand(db, "quiero pizza").vertical == "restaurantes"  # 6,7 % frente a 0,5 %
    # 10 platos latinos en chocolaterías pesan casi lo mismo que en restaurantes, pero no compiten: no se pregunta.
    assert agent.understander.understand(db, "comida latina").kind == "buscar"


def test_packaged_sweets_are_not_offered_from_restaurants(rappi_agent):
    agent, db = rappi_agent
    add_store(db, 10, "chocolateria", "Chocolatería")
    for pid, store in [(600, 10), (601, 10)]:
        add_product(db, pid, f"Chocolate Sahne-Nuss {pid} g", store, "Chocolates")
        add_price(db, store, pid, 1990)
    for item_id in (610, 611, 612):
        add_dish(db, item_id, f"Chocolate caliente con barra {item_id}", 3, "Postres", ["Café"])
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    assert ranked_verticals(db, ["chocolates"]) == ["chocolateria"]


@pytest.fixture
def trip(rappi_agent):
    agent, db = rappi_agent
    add_store(db, 11, "farmacia", "Farmacia")
    add_store(db, 12, "mall", "Tienda")
    add_product(db, 900, "Protector solar Eucerin FPS 50 50 ml", 11, "Protectores solares faciales")
    add_price(db, 11, 900, 15990)
    add_product(db, 901, "Bikini triángulo dos piezas", 12, "Bikinis")
    add_price(db, 12, 901, 12990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)
    return agent, db


def test_the_beach_hook_respects_rappi_hoy_and_topics_already_shown(trip):
    """Con «playa» el gancho del traje de baño SÍ aplica (el del protector solar no: es de farmacia y salud): así
    «Rappi hoy» y shown_topics se prueban de verdad."""
    agent, db = trip
    beach = "me voy de vacaciones a la playa"
    r = agent.reply(db, beach, Context())
    assert r["suggestion"]["question"] == "¿Te falta traje de baño? 👙"
    assert r["reason"] == r["suggestion"]["reason"] == "Para tu viaje ✈️"
    assert "suggestion" not in agent.reply(db, beach, Context(mode="actual"))
    again = agent.reply(db, beach, Context(shown_topics=["ropa"]))
    assert again.get("suggestion", {}).get("concept") != "ropa"


@pytest.fixture
def pharmacy(rappi_agent):
    agent, db = rappi_agent
    add_store(db, 11, "farmacia", "Farmacia")
    for pid, name, category, price in [
        (800, "Paracetamol 500 mg para la fiebre y el dolor 16 comprimidos", "Analgésicos tópicos", 1490),
        (801, "Tapsin Día fiebre y resfrío 18 comprimidos", "Analgésicos tópicos", 2990),
        (804, "Jarabe Bisolvon para la tos 120 ml", "Analgésicos tópicos", 4990),
        (805, "Termómetro digital para la fiebre", "Termómetros", 3990),
    ]:
        add_product(db, pid, name, 11, category)
        add_price(db, 11, pid, price)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)
    return agent, db


def test_one_remedy_is_not_enough_and_only_medicines_are_remedies(pharmacy):
    agent, db = pharmacy
    cough = agent.reply(db, "tengo tos", Context())
    # un solo jarabe no alcanza: Mochi no elige otro remedio (ni los analgésicos)
    assert cough["text"].startswith("No encontré en Farmacia un remedio")
    assert not any(p["concept"] == "medicamentos" for p in cough["products"])
    fever = agent.reply(db, "tengo fiebre", Context())
    assert fever["intent"]["vertical"] == "farmacia" and fever["tags"] == ["medicamentos"]
    assert "805" not in [p["entity_id"] for p in fever["products"]]  # un termómetro no es un remedio


def test_remedies_respect_the_price_cap(pharmacy):
    agent, db = pharmacy
    r = agent.reply(db, "tengo fiebre, algo de menos de 2000", Context())
    assert r["intent"]["price_max"] == 2000
    assert all(p["price_value"] <= 2000 for p in r["products"])


def test_a_symptom_with_a_named_vertical_stays_there(pharmacy):
    agent, db = pharmacy
    r = agent.reply(db, "tengo fiebre, algo del supermercado", Context())
    assert r["intent"]["vertical"] == "supermercado" and r["vertical"] == "supermercado"


def test_questions_about_the_app_get_an_answer_not_products(rappi_agent):
    agent, db = rappi_agent
    help_ = agent.reply(db, "quien eres", Context())
    assert not help_["products"] and "Mochi" in help_["text"]
    assert [a["label"] for a in help_["actions"]] == [
        "🍣 Algo de sushi",
        "🍽️ ¿Qué almuerzo hoy?",
        "🤒 Tengo fiebre",
        "🎉 Arma un carrete",  # sigue, pero ya no es lo primero que se ofrece
    ]
    assert [a["query"] for a in help_["actions"]] == ["sushi", "tengo hambre", "tengo fiebre", "algo para el carrete"]
    assert "envío" in agent.reply(db, "hacen delivery?", Context())["text"]
    assert "Ofertas" in agent.reply(db, "tienen ofertas?", Context())["text"]
    off_topic = agent.reply(db, "cuéntame un chiste", Context(mode="propuesta"))
    assert not off_topic["products"] and not off_topic.get("unmet") and not off_topic["actions"]
    assert "pedir" in off_topic["text"]
    memory = agent.reply(db, "olvida lo que te dije", Context(mode="propuesta"))
    assert not memory["products"] and "Olvidar" in memory["text"]
    order = agent.reply(db, "mi pedido no llega", Context(mode="propuesta"))
    assert not order["products"] and not order.get("unmet") and "Mis pedidos" in order["text"]


def test_cheap_shows_the_cheapest_first(rappi_agent):
    """Reordenar solo los 6 más relevantes no daba lo más barato: hay que mirar más candidatos."""
    agent, db = rappi_agent
    for pid in range(210, 225):  # 15 cervezas caras más relevantes por nombre, y la barata al final
        add_product(db, pid, f"Cerveza Cerveza Cerveza premium {pid}", 2, "Cervezas")
        add_price(db, 2, pid, 9990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)
    prices = [p["price_value"] for p in agent.reply(db, "cerveza barata", Context(vertical="licores"))["products"]]
    assert prices == sorted(prices) and prices[0] == 1290
    pricey = [p["price_value"] for p in agent.reply(db, "cerveza cara", Context(vertical="licores"))["products"]]
    assert pricey == sorted(pricey, reverse=True) and pricey[0] == 9990


def test_a_recommendation_uses_what_the_user_likes(rappi_agent):
    agent, db = rappi_agent
    liked = agent.reply(db, "qué me recomiendas", Context(profile={"snacks-salados": 3.0}))
    assert liked["text"].startswith("Por tu interés en 🥨 snacks salados 😉") and liked["products"]
    unknown = agent.reply(db, "qué me recomiendas", Context())
    assert unknown["intent"]["kind"] == "ayuda" and unknown["actions"]


def test_a_recommendation_never_pushes_alcohol_baby_or_health_interests(rappi_agent):
    """«Qué me recomiendas» responde con el interés más alto: si es de los que Mochi no propone solo, pasa al
    siguiente ofrecible y, si no hay, a los ejemplos de siempre."""
    agent, db = rappi_agent
    for profile in ({"cerveza": 3.0}, {"panales": 3.0}, {"vitaminas": 3.0}, {"cerveza": 3.0, "cigarrillos": 9.0}):
        r = agent.reply(db, "qué me recomiendas", Context(profile=profile))
        assert r["intent"]["kind"] == "ayuda" and r["actions"] and not r["products"], profile
        assert "Por tu interés en" not in r["text"]
    r = agent.reply(db, "qué me recomiendas", Context(profile={"cerveza": 3.0, "panales": 2.0, "snacks-salados": 0.5}))
    assert r["text"].startswith("Por tu interés en 🥨 snacks salados") and "cerveza" not in r["text"].lower()


def test_a_recommendation_is_an_offer_so_it_skips_blocked_stores_and_adult_products(rappi_agent):
    """«Por tu gusto por…» lo propone Mochi sin que se lo pidan: no trae un producto que solo vende una tienda que Rappi
    rotula Smoking shop, ni uno +18 bajo un concepto corriente (a quien lo pide por su nombre sí se le muestra)."""
    agent, db = rappi_agent
    add_store(db, 4, "mall", "Smoking shop del mall")
    db.execute("UPDATE store_verticals SET subvertical = 'Smoking shop' WHERE store_id = 4")
    add_store(db, 5, "supermercado", "Súper nocturno")
    add_product(db, 110, "Papas fritas Pringles Original 124 g", 4, "Snacks salados")
    add_price(db, 4, 110, 990)
    add_product(db, 111, "Papas fritas Doritos Queso 150 g", 5, "Snacks salados")
    add_price(db, 5, 111, 1190)
    db.execute("UPDATE catalog_items SET age_restricted = true WHERE master_product_id = 111")
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)

    asked = {p["entity_id"] for p in agent.reply(db, "snacks salados", Context())["products"]}
    liked = agent.reply(db, "qué me recomiendas", Context(profile={"snacks-salados": 3.0}))

    assert {"110", "111"} & asked  # pedidos por su nombre, se encuentran
    assert liked["text"].startswith("Por tu interés en 🥨 snacks salados") and liked["products"]
    assert not {"110", "111"} & {p["entity_id"] for p in liked["products"]}


def test_an_unasked_recommendation_does_not_list_licores_pharmacy_or_their_stores_in_also_in(rappi_agent, monkeypatch):
    """El «También en» de «Por tu gusto por…» (Mochi lo dice sola) no nombra Licores ni Farmacia ni una tienda que Rappi
    rotula Farmacia; en una respuesta pedida sí aparecen, como siempre."""
    agent, db = rappi_agent
    monkeypatch.setattr(verticals, "MIN_ITEMS_ELSEWHERE", 1)  # el catálogo de prueba es chico
    add_store(db, 7, "conveniencia", "Farmacia Express")
    db.execute("UPDATE store_verticals SET subvertical = 'Farmacia' WHERE store_id = 7")
    add_store(db, 8, "chocolateria", "Chocolatería")
    add_product(db, 120, "Papas fritas Licorera 100 g", 2, "Snacks salados")
    add_price(db, 2, 120, 1100)
    add_product(db, 121, "Papas fritas Botica 100 g", 7, "Snacks salados")
    add_price(db, 7, 121, 1200)
    add_product(db, 122, "Papas fritas Bombonera 100 g", 8, "Snacks salados")
    add_price(db, 8, 122, 1300)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)

    asked = agent.reply(db, "snacks salados", Context(vertical="supermercado"))
    liked = agent.reply(db, "qué me recomiendas", Context(profile={"snacks-salados": 3.0}))

    assert {v["vertical"] for v in asked["also_in"]["verticals"]} >= {"licores", "conveniencia", "chocolateria"}
    assert liked["text"].startswith("Por tu interés en 🥨 snacks salados")
    elsewhere = {v["vertical"] for v in liked["also_in"]["verticals"]}
    assert elsewhere and not elsewhere & {"licores", "farmacia", "conveniencia"}  # esta última: solo una «Farmacia»
    stores = {s["name"] for v in liked["also_in"]["verticals"] for s in v["stores"]}
    assert stores and not stores & {"Botillería", "Farmacia Express"}


def test_a_conversation_follows_the_previous_request(rappi_agent):
    """Ronda 4: «más barata» o «de otra marca» después de «cerveza» olvidaban la cerveza y traían cualquier cosa."""
    agent, db = rappi_agent
    first = agent.reply(db, "cerveza", Context(vertical="licores"))
    shown = [p["entity_id"] for p in first["products"]]
    previous = {"query": first["intent"]["query"], "concepts": first["intent"]["concepts"],
                "vertical": first["vertical"], "product_ids": shown[:1]}  # fmt: skip
    cheaper = agent.reply(db, "más barata", Context(previous=previous))
    assert cheaper["intent"]["follow_up"] and {p["concept"] for p in cheaper["products"]} == {"cerveza"}
    prices = [p["price_value"] for p in cheaper["products"]]
    assert prices == sorted(prices)
    other = agent.reply(db, "de otra marca", Context(previous=previous))
    assert other["products"] and shown[0] not in [p["entity_id"] for p in other["products"]]


def test_a_concept_named_with_generic_words_is_searched_by_its_name(rappi_agent, monkeypatch):
    """«algo más sano» se entiende como ensaladas, pero esas palabras no están en ningún producto: la búsqueda traía
    pizza y pescado. Si nada es del concepto pedido, se busca por el nombre del concepto."""
    agent, db = rappi_agent
    add_dish(db, 520, "Ensalada César con pollo", 3, "Ensaladas", ["Ensaladas"])
    db.execute("INSERT INTO menu_price_snapshots (run_id, item_id, price) VALUES (999, 520, 6990)")
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)
    from rappi_ia.agent import rappi_agent as module

    real = module.search_products

    def like_the_real_catalog(conn, vertical, query, *args, **kwargs):  # con «algo mas sano» no sale la ensalada
        outcome = real(conn, vertical, query, *args, **kwargs)
        if query != "Ensaladas y bowls":
            outcome = replace(outcome, products=[p for p in outcome.products if p.concept != "ensaladas-bowls"])
        return outcome

    monkeypatch.setattr(module, "search_products", like_the_real_catalog)
    r = agent.reply(db, "algo más sano", Context(vertical="restaurantes"))
    assert r["intent"]["concepts"][:1] == ["ensaladas-bowls"]
    assert [p["entity_id"] for p in r["products"]] == ["520"]


@pytest.fixture
def ice_creams(rappi_agent):
    agent, db = rappi_agent
    add_store(db, 4, "turbo", "Turbo")
    for pid, name, store in [
        (300, "Helado de chocolate 1 L", 1),
        (301, "Helado de frutilla 1 L", 1),
        (302, "Helado Lúcuma Manjar 1 L", 4),
        (305, "Helado lúcuma nuez 1 L", 4),
    ]:
        add_product(db, pid, name, store, "Helados")
        add_price(db, store, pid, 3990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)
    return agent, db


def test_a_flavor_missing_here_is_shown_where_it_is(ice_creams):
    """«helado de lúcuma» en el súper mostraba helados de chocolate: en Turbo sí hay de lúcuma."""
    agent, db = ice_creams
    r = agent.reply(db, "helado de lúcuma", Context(vertical="supermercado"))
    assert r["vertical"] == "turbo"
    assert sorted(p["name"] for p in r["products"]) == ["Helado Lúcuma Manjar 1 L", "Helado lúcuma nuez 1 L"]
    assert "Turbo" in r["text"] and "lúcuma" in r["text"]


def test_a_detail_said_in_plural_or_english_finds_its_vertical(ice_creams):
    """«helado kids»: el singular a mano es «kid», pero el índice guarda «kids» (no es español). La búsqueda de la
    vertical que lo tiene mira el singular y sus plurales, como la expresión regular del nombre."""
    agent, db = ice_creams
    for pid, name in ((308, "Helado Kids frutilla 1 L"), (309, "Helado Kids chocolate 1 L")):
        add_product(db, pid, name, 4, "Helados")
        add_price(db, 4, pid, 3990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)

    r = agent.reply(db, "helado kids", Context(vertical="supermercado"))

    assert r["vertical"] == "turbo"
    assert sorted(p["name"] for p in r["products"]) == ["Helado Kids chocolate 1 L", "Helado Kids frutilla 1 L"]


def test_a_missing_without_x_is_said_as_such(ice_creams):
    agent, db = ice_creams
    for pid in (303, 306):
        add_product(db, pid, f"Helado sin azúcar vainilla {pid}", 4, "Helados")
        add_price(db, 4, pid, 4990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)
    assert "no hay «sin azúcar»" in agent.reply(db, "helado sin azúcar", Context(vertical="supermercado"))["text"]


def test_one_product_elsewhere_is_not_enough_to_leave(ice_creams):
    """«protector solar factor 50» se iba al súper por un solo producto que decía «factor»."""
    agent, db = ice_creams
    add_product(db, 307, "Helado lavanda 1 L", 4, "Helados")
    add_price(db, 4, 307, 3990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)
    assert agent.reply(db, "helado de lavanda", Context(vertical="supermercado"))["vertical"] == "supermercado"


def test_few_results_are_completed_with_the_concept(rappi_agent, monkeypatch):
    """«unos puchos» mostraba un solo producto: se completa con la búsqueda por el nombre del concepto."""
    agent, db = rappi_agent
    for pid in range(203, 207):
        add_product(db, pid, f"Cigarrillos Lucky {pid} 20 u", 2, "Cigarrillos")
        add_price(db, 2, pid, 5000)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)
    from rappi_ia.agent import rappi_agent as module

    real = module.search_products

    def like_the_real_catalog(conn, vertical, query, *args, **kwargs):  # con «puchos» salía un solo producto
        outcome = real(conn, vertical, query, *args, **kwargs)
        return outcome if query == "Cigarrillos" else replace(outcome, products=outcome.products[:1])

    monkeypatch.setattr(module, "search_products", like_the_real_catalog)
    assert len(agent.reply(db, "unos puchos", Context(vertical="licores"))["products"]) >= 3
    # «puchos en la botillería»: se nombró dónde, y lo demás no es lo pedido
    assert len(agent.reply(db, "unos puchos en la botillería", Context(vertical="licores"))["products"]) == 1


def test_a_pill_form_is_not_a_detail(ice_creams):
    """«pastillas para dormir» saltaba a Licores por unas «pastillas» para la resaca."""
    agent, db = ice_creams
    add_product(db, 304, "Pastillas de menta", 4, "Helados")
    add_price(db, 4, 304, 990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)
    assert agent.reply(db, "helado en pastillas", Context(vertical="supermercado"))["vertical"] == "supermercado"


def test_a_flavor_missing_everywhere_keeps_the_vertical(ice_creams):
    agent, db = ice_creams
    r = agent.reply(db, "helado de lavanda", Context(vertical="supermercado"))
    assert r["vertical"] == "supermercado" and r["products"]


def test_a_named_vertical_is_never_left(ice_creams):
    agent, db = ice_creams
    assert agent.reply(db, "helado de lúcuma en el súper", Context())["vertical"] == "supermercado"


def test_a_concept_this_vertical_barely_has_goes_where_it_is(rappi_agent, monkeypatch):
    """«vino» desde Farmacia mostraba mascarillas: Farmacia casi no tiene vino y Licores sí."""
    agent, db = rappi_agent
    from rappi_ia.agent import rappi_agent as module

    monkeypatch.setattr(module, "MIN_HOME_ITEMS", 2)  # la base de prueba es chica: Licores tiene 2 cervezas
    r = agent.reply(db, "cerveza", Context(vertical="supermercado"))
    assert r["vertical"] == "licores" and {p["concept"] for p in r["products"]} == {"cerveza"}
    assert "no hay «cerveza», pero en Licores sí" in r["text"]
    assert agent.reply(db, "cerveza en el súper", Context(vertical="supermercado"))["vertical"] == "supermercado"


def test_a_remedy_for_a_symptom_searches_the_symptom_not_the_word_remedy(remedies_rappi_agent):
    """«remedio para la tos» traía remedios para el estómago: calzaban con la palabra «remedio»."""
    agent, db = remedies_rappi_agent
    add_product(db, 806, "Remedio natural para el estómago 20 comprimidos", 11, "Antiácidos")
    add_price(db, 11, 806, 2990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)
    r = agent.reply(db, "remedio para la fiebre", Context(vertical="supermercado"))
    assert r["vertical"] == "farmacia" and sorted(p["entity_id"] for p in r["products"]) == ["800", "801"]


def test_without_x_leaves_out_what_names_x(rappi_agent):
    """sushi → «sin palta» mostraba rolls con palta: el nombre que dice «palta» (y no «sin palta») queda fuera."""
    agent, db = rappi_agent
    for pid, name in [(530, "Roll palta salmón"), (531, "Roll sin palta queso"), (532, "Roll tempura queso")]:
        add_dish(db, pid, name, 3, "Sushi", ["Sushi"])
        db.execute("INSERT INTO menu_price_snapshots (run_id, item_id, price) VALUES (999, %s, 5990)", (pid,))
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)
    names = [p["name"] for p in agent.reply(db, "sushi sin palta", Context(vertical="restaurantes"))["products"]]
    assert names and "Roll palta salmón" not in names and "Roll sin palta queso" in names


def test_without_a_flavor_never_brings_that_flavor(ice_creams):
    """«galletas sin frutilla» se iba a otra vertical a buscar galletas de frutilla, y si todo nombraba lo excluido
    lo mostraba igual."""
    agent, db = ice_creams
    here = agent.reply(db, "helado sin lúcuma", Context(vertical="supermercado"))
    assert here["vertical"] == "supermercado" and here["products"]
    assert not any("cuma" in p["name"].lower() for p in here["products"])
    only_that = agent.reply(db, "helado sin lúcuma", Context(vertical="turbo"))
    assert not any("cuma" in p["name"].lower() for p in only_that["products"])
    # «chocolate» es palabra de los helados («helado de chocolate»), pero tras «sin» igual se excluye
    no_chocolate = agent.reply(db, "helado sin chocolate", Context(vertical="supermercado"))
    assert not any("chocolate" in p["name"].lower() for p in no_chocolate["products"])
    with_article = agent.reply(db, "helado sin la frutilla", Context(vertical="supermercado"))
    assert not any("frutilla" in p["name"].lower() for p in with_article["products"])


def test_a_detail_elsewhere_must_be_of_the_concept(ice_creams):
    """«café de menta» desde Farmacia mostraba Mentos: lo que dice «menta» y no es café no cuenta."""
    agent, db = ice_creams
    for pid in (308, 309):
        add_product(db, pid, f"Caramelos de menta {pid}", 4, "Caramelos")
        add_price(db, 4, pid, 990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)
    r = agent.reply(db, "helado de menta", Context(vertical="supermercado"))
    assert r["vertical"] == "supermercado" and all(p["concept"] == "helados" for p in r["products"])


def test_the_memory_answer_is_true_in_rappi_hoy(rappi_agent):
    agent, db = rappi_agent
    assert "Recuerdo" not in agent.reply(db, "qué sabes de mí", Context(mode="actual"))["text"]


def test_free_from_shows_only_what_says_so_even_when_cheap(ice_creams):
    """«vino barato sin alcohol» encontraba los sin alcohol, pero el orden por precio ponía primero los comunes."""
    agent, db = ice_creams
    for pid in (310, 311):
        add_product(db, pid, f"Helado sin azúcar frambuesa {pid}", 1, "Helados")
        add_price(db, 1, pid, 9990)  # más caros que los comunes (3.990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)
    r = agent.reply(db, "helado barato sin azúcar", Context(vertical="supermercado"))
    assert r["products"] and all("sin azúcar" in p["name"] for p in r["products"])


def test_a_remedy_treats_the_symptom_not_just_mentions_it(remedies_rappi_agent):
    """Con el catálogo del 04-10, «tengo fiebre» mostraba laxantes y antiácidos: su prospecto nombra la fiebre en las
    advertencias. Y el paracetamol, que no la nombra, no aparecía."""
    agent, db = remedies_rappi_agent
    add_product(
        db, 807, "Ciruelax laxante 75 mg. Advertencias: consulte a su médico si presenta fiebre", 11, "Laxantes"
    )
    add_product(db, 808, "Kitadol 500 mg 24 comprimidos", 11, "Analgésicos sistémicos")
    for pid in (807, 808):
        add_price(db, 11, pid, 2990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embed_search_documents(db, agent.embedder)
    shown = {p["entity_id"] for p in agent.reply(db, "tengo fiebre", Context())["products"]}
    assert "807" not in shown and {"800", "801", "808"} <= shown


class TextCountingEmbedder(HashEmbedder):
    """Anota cada texto que se embebe como consulta."""

    def __init__(self):
        super().__init__()
        self.texts: list[str] = []

    def embed_queries(self, texts: list[str]):
        self.texts.extend(texts)
        return super().embed_queries(texts)


def test_ask_embeds_each_text_once(ice_creams):
    """«helado de lúcuma bajo 5000»: la búsqueda con tope, la del más barato sin tope, el reintento por el concepto y la
    del detalle repiten consultas; cada texto se embebe una vez por turno (el modelo tiene un solo candado)."""
    agent, db = ice_creams
    counting = TextCountingEmbedder()
    agent.embedder = counting

    r = agent.reply(db, "helado de lúcuma bajo 5000", Context(vertical="supermercado"))

    assert r["products"]
    assert counting.texts and len(counting.texts) == len(set(counting.texts)), counting.texts
    counting.texts.clear()
    agent.reply(db, "helado de lúcuma bajo 5000", Context(vertical="supermercado"))
    assert counting.texts  # la memoria es del turno: el siguiente vuelve a embeber
