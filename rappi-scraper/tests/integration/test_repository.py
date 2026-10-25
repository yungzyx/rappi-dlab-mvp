import csv

import pytest
from psycopg import errors

from conftest import FakeClient, restaurant_block, with_top_section
from rappi_scraper.pipeline.restaurants import process_restaurant_jobs
from rappi_scraper.scraping.restaurant_parser import parse_restaurant
from rappi_scraper.storage import repository
from rappi_scraper.storage.db import connect, database_url
from rappi_scraper.storage.export import export_catalog_csv
from rappi_scraper.storage.search import SEARCH_DOCUMENTS_LOCK, build_search_documents, search


def _product(sku, master_id, name, price, **extra):
    return {
        "product_id": sku,
        "master_product_id": master_id,
        "name": name,
        "price": price,
        "real_price": price,
        "category_id": 76,
        "category_name": "Pañales",
        "trademark": "Babysec",
        "presentation": "1 x 40 Und",
        "in_stock": True,
        **extra,
    }


def _store(conn, store_id, store_type, vertical, brand=("Lider", 12216)):
    repository.upsert_store(
        conn,
        {
            "store_id": store_id,
            "name": brand[0],
            "brand_id": brand[1],
            "brand_name": brand[0],
            "store_type": store_type,
            "city": "Santiago",
        },
    )
    repository.upsert_store_vertical(conn, store_id, vertical)


def _count(conn, sql):
    return conn.execute(sql).fetchone()[0]


def test_save_products_is_idempotent_and_keeps_price_history(db):
    _store(db, 1, "lider", "supermercado")
    run1 = repository.start_run(db, "stores", {})
    repository.save_products(db, run1, 1, [_product("a", 100, "Pañal Babysec G", 9990)])
    repository.save_products(db, run1, 1, [_product("a", 100, "Pañal Babysec G", 9990)])  # reintento
    run2 = repository.start_run(db, "stores", {})
    repository.save_products(db, run2, 1, [_product("a", 100, "Pañal Babysec G", 8990)])
    db.commit()

    assert _count(db, "SELECT count(*) FROM catalog_items") == 1
    assert _count(db, "SELECT count(*) FROM store_products") == 1
    assert _count(db, "SELECT count(*) FROM price_snapshots") == 2
    assert _count(db, "SELECT diferencia FROM v_price_changes") == -1000


def test_same_master_product_in_two_chains_is_one_catalog_item(db):
    _store(db, 1, "lider", "supermercado")
    _store(db, 2, "turbo", "turbo", brand=("Turbo", 999))
    run = repository.start_run(db, "stores", {})
    repository.save_products(db, run, 1, [_product("a", 100, "Coca-Cola 1,5 L", 1990)])
    repository.save_products(db, run, 2, [_product("zz", 100, "Coca-Cola 1,5 L", 2290)])
    db.commit()

    assert _count(db, "SELECT count(*) FROM catalog_items") == 1
    assert _count(db, "SELECT n_verticales FROM v_cross_vertical_items") == 2
    assert _count(db, "SELECT count(*) FROM v_price_compare") == 2


def test_vertical_membership_is_shared_by_store_type(db):
    _store(db, 1, "lider", "supermercado")
    _store(db, 2, "lider", "conveniencia")  # otra sucursal del mismo formato, en otro listado
    run = repository.start_run(db, "stores", {})
    repository.save_products(db, run, 1, [_product("a", 100, "Arroz", 1500)])
    db.commit()

    verticals = {r[0] for r in db.execute("SELECT vertical FROM v_item_verticals")}
    assert verticals == {"supermercado", "conveniencia"}


def test_store_vertical_upsert_twice_without_filters(db):
    _store(db, 1, "lider", "mall")
    repository.upsert_store_vertical(db, 1, "mall", "Hogar")  # segunda vez, sin filtros
    repository.upsert_store_vertical(db, 1, "mall", "", "", ["Moda"])
    db.commit()

    assert db.execute("SELECT subvertical, filters FROM store_verticals").fetchone() == ("Hogar", ["Moda"])


def test_stores_without_store_type_do_not_share_verticals(db):
    for store_id, vertical in ((1, "mall"), (2, "licores")):
        repository.upsert_store(db, {"store_id": store_id, "name": f"T{store_id}", "store_type": ""})
        repository.upsert_store_vertical(db, store_id, vertical)
    db.commit()

    rows = db.execute("SELECT store_id, vertical FROM v_store_verticals ORDER BY store_id").fetchall()
    assert rows == [(1, "mall"), (2, "licores")]


def test_restaurants_do_not_share_verticals_through_their_store_type(db):
    """Rappi manda storeType 'restaurant' para todos los restaurantes (tests/fixtures/restaurant.html): no es un
    formato. El cruce armaba 13 millones de filas con 3.604 restaurantes y le pasaría a todos el vertical de uno."""
    for store_id in (1, 2):
        repository.upsert_store(db, {"store_id": store_id, "name": f"R{store_id}", "store_type": "restaurant"})
        repository.upsert_store_vertical(db, store_id, "restaurantes")
    repository.upsert_store_vertical(db, 1, "chocolateria")
    db.commit()

    rows = db.execute("SELECT store_id, vertical FROM v_store_verticals ORDER BY 1, 2").fetchall()
    assert rows == [(1, "chocolateria"), (1, "restaurantes"), (2, "restaurantes")]


def test_search_is_isolated_per_vertical(db, page):
    _store(db, 1, "lider", "supermercado")
    run = repository.start_run(db, "stores", {})
    repository.save_products(db, run, 1, [_product("a", 100, "Pañales Babysec Premium G", 9990)])
    restaurant = parse_restaurant(page("restaurant"))
    repository.save_restaurant(db, run, restaurant)
    db.commit()

    counts = build_search_documents(db)
    db.commit()

    assert counts["catalog_item"] == 1 and counts["menu_item"] == 61
    assert search(db, "supermercado", "pañales")
    assert search(db, "restaurantes", "pañales") == []
    assert search(db, "restaurantes", "arepa")
    assert search(db, "supermercado", "arepa") == []
    assert _count(db, "SELECT count(*) FROM search_documents WHERE vertical IS NULL") == 0


def test_search_documents_mark_products_that_need_a_prescription(db):
    """Rappi marca `requires_medical_prescription`: Mochi no los muestra cuando se habla de síntomas."""
    _store(db, 1, "cruzverde", "farmacia")
    run = repository.start_run(db, "stores", {})
    repository.save_products(
        db,
        run,
        1,
        [
            _product("a", 100, "Amoxicilina 500 mg", 3990, requires_medical_prescription=True),
            _product("b", 101, "Paracetamol 500 mg", 990, requires_medical_prescription=False),
        ],
    )
    build_search_documents(db)
    rows = db.execute(
        "SELECT entity_id, metadata->'receta' FROM search_documents WHERE entity_type = 'catalog_item' ORDER BY 1"
    ).fetchall()
    assert rows == [("100", True), ("101", None)]


def test_search_documents_rebuild_the_vocabulary_by_vertical(db):
    """Las palabras del catálogo, sin tildes ni ñ, por vertical y con en cuántos documentos están: rappi-ia corrige con
    ellas los errores de tipeo (migración 041). Se rearma con los documentos: lo que ya no existe sale."""
    _store(db, 1, "lider", "supermercado")
    _store(db, 2, "cruzverde", "farmacia")
    run = repository.start_run(db, "stores", {})
    repository.save_products(
        db, run, 1, [_product("a", 100, "Nutella 350 g", 3990), _product("b", 101, "Nutella Pañales", 990)]
    )
    repository.save_products(db, run, 2, [_product("c", 102, "Paracetamol", 990)])
    build_search_documents(db)
    vocabulary = dict(
        ((v, w), n) for v, w, n in db.execute("SELECT vertical, word, docs FROM search_vocabulary").fetchall()
    )
    assert vocabulary[("supermercado", "nutella")] == 2
    assert vocabulary[("supermercado", "panales")] == 2  # «Pañales» en la categoría de los dos
    shown = db.execute("SELECT display FROM search_vocabulary WHERE vertical = 'supermercado' AND word = 'panales'")
    assert shown.fetchone()[0] == "pañales"  # la corrección la muestra como la escribe el catálogo
    assert ("farmacia", "nutella") not in vocabulary and vocabulary[("farmacia", "paracetamol")] == 1

    db.execute("DELETE FROM store_products WHERE master_product_id IN (100, 101)")
    db.execute("DELETE FROM catalog_items WHERE master_product_id IN (100, 101)")
    repository.save_products(db, run, 1, [_product("d", 103, "Arroz", 1500)])
    build_search_documents(db)
    words = {w for (w,) in db.execute("SELECT word FROM search_vocabulary WHERE vertical = 'supermercado'")}
    assert "arroz" in words and "nutella" not in words


EMBEDDED_ITEMS = "SELECT count(*) FROM search_documents WHERE embedding IS NOT NULL AND entity_type = 'catalog_item'"


def test_rebuilding_search_keeps_embedding_only_if_text_unchanged(db):
    _store(db, 1, "lider", "supermercado")
    run = repository.start_run(db, "stores", {})
    repository.save_products(db, run, 1, [_product("a", 100, "Arroz Tucapel", 1500)])
    db.commit()
    build_search_documents(db)
    db.execute("UPDATE search_documents SET embedding = '[1,2,3]', embedding_model = 'test'")

    repository.save_products(db, run, 1, [_product("a", 100, "Arroz Tucapel", 1700)])  # solo precio
    build_search_documents(db)
    assert _count(db, EMBEDDED_ITEMS) == 1

    repository.save_products(db, run, 1, [_product("a", 100, "Arroz Tucapel Grado 1", 1700)])  # texto
    build_search_documents(db)
    assert _count(db, EMBEDDED_ITEMS) == 0


def test_rebuilding_search_writes_only_changes_and_drops_missing_entities(db):
    _store(db, 1, "lider", "supermercado")
    run = repository.start_run(db, "stores", {})
    repository.save_products(
        db, run, 1, [_product("a", 100, "Arroz Tucapel", 1500), _product("b", 101, "Té Club", 900)]
    )
    db.commit()
    assert build_search_documents(db)["escritos"] == 3  # 2 productos + la tienda
    db.commit()

    unchanged = build_search_documents(db)  # sin cambios: no reescribe filas (ni sus entradas en los índices)
    assert (unchanged["catalog_item"], unchanged["escritos"], unchanged["eliminados"]) == (2, 0, 0)

    db.execute("DELETE FROM store_products WHERE master_product_id = 101")
    db.execute("DELETE FROM catalog_items WHERE master_product_id = 101")
    assert build_search_documents(db)["eliminados"] == 1
    assert _count(db, "SELECT count(*) FROM search_documents WHERE entity_type = 'catalog_item'") == 1


DOCUMENTS = (
    "SELECT entity_type, entity_id, (metadata->>'precio_min')::int, (metadata->>'tiendas')::int "
    "FROM search_documents ORDER BY 1, 2"
)


def test_search_keeps_only_the_offers_seen_in_the_last_run_of_their_store_type(db):
    """Cada corrida baja una sucursal por formato, y no siempre la misma: la sucursal vieja no pone el precio mínimo,
    no suma tiendas y lo que solo ella vendía ya no se busca."""
    _store(db, 1, "lider", "supermercado")  # sucursal A
    _store(db, 2, "lider", "supermercado")  # sucursal B, mismo formato
    run1 = repository.start_run(db, "stores", {})
    repository.save_products(
        db, run1, 1, [_product("s1", 100, "Arroz Tucapel", 100), _product("s2", 101, "Té Club", 900)]
    )
    run2 = repository.start_run(db, "stores", {})
    repository.save_products(db, run2, 2, [_product("s1", 100, "Arroz Tucapel", 200)])
    db.commit()

    build_search_documents(db)

    assert db.execute(DOCUMENTS).fetchall() == [("catalog_item", "100", 200, 1), ("store", "2", None, None)]


def test_a_product_the_store_no_longer_sells_leaves_the_search(db):
    _store(db, 1, "lider", "supermercado")
    run1 = repository.start_run(db, "stores", {})
    repository.save_products(
        db, run1, 1, [_product("s1", 100, "Arroz Tucapel", 100), _product("s2", 101, "Té Club", 900)]
    )
    run2 = repository.start_run(db, "stores", {})
    repository.save_products(db, run2, 1, [_product("s1", 100, "Arroz Tucapel", 120)])
    db.commit()

    build_search_documents(db)

    assert db.execute(DOCUMENTS).fetchall() == [("catalog_item", "100", 120, 1), ("store", "1", None, None)]


def test_a_store_type_missing_from_the_last_run_keeps_its_last_known_offers(db):
    """Un formato que la última corrida no pudo bajar (falló, o no salió en los listados) conserva su último dato."""
    _store(db, 1, "lider", "supermercado")
    _store(db, 2, "jumbo", "supermercado", brand=("Jumbo", 1))
    run1 = repository.start_run(db, "stores", {})
    repository.save_products(db, run1, 2, [_product("j1", 200, "Fideos Carozzi", 900)])
    run2 = repository.start_run(db, "stores", {})
    repository.save_products(db, run2, 1, [_product("s1", 100, "Arroz Tucapel", 100)])
    db.commit()

    build_search_documents(db)

    assert [r[:2] for r in db.execute(DOCUMENTS)] == [
        ("catalog_item", "100"), ("catalog_item", "200"), ("store", "1"), ("store", "2")
    ]  # fmt: skip


def test_a_dish_the_restaurant_no_longer_offers_leaves_the_search(db, page):
    parsed = parse_restaurant(page("restaurant"))
    run1 = repository.start_run(db, "restaurants", {})
    repository.save_restaurant(db, run1, parsed)
    run2 = repository.start_run(db, "restaurants", {})
    repository.save_restaurant(db, run2, {**parsed, "items": parsed["items"][1:]})
    db.commit()

    build_search_documents(db)

    dishes = {r[0] for r in db.execute("SELECT entity_id FROM search_documents WHERE entity_type = 'menu_item'")}
    assert len(dishes) == 60 and str(parsed["items"][0]["item_id"]) not in dishes


# Los platos de una sección, también los que están en otra (como lo leería «lo más pedido», #106).
SECTION_DISHES = """
SELECT mi.rappi_item_id FROM menu_items mi
JOIN menu_sections ms ON ms.store_id = mi.store_id
     AND (ms.section_id = mi.section_id OR ms.section_id = ANY(mi.extra_section_ids))
WHERE ms.name = %s ORDER BY 1"""


def test_a_dish_in_mas_vendidos_and_in_its_own_section_is_saved_in_both(db, page):
    """Antes el plato quedaba solo en la última sección y «Más vendidos» quedaba vacía (24 de 66 en `rappi`, 21-10)."""
    data = page("restaurant")
    products = next(c for c in restaurant_block(data)["corridors"] if c["name"] == "Hamburguesas")["products"]
    burgers = [p["id"] for p in products]
    run = repository.start_run(db, "restaurants", {})

    repository.save_restaurant(db, run, parse_restaurant(with_top_section(data, products[:2])))

    assert _count(db, "SELECT count(*) FROM menu_items") == 61
    assert [r[0] for r in db.execute(SECTION_DISHES, ("Más vendidos",))] == sorted(burgers[:2])
    assert [r[0] for r in db.execute(SECTION_DISHES, ("Hamburguesas",))] == sorted(burgers)

    # La descarga siguiente ya no trae «Más vendidos»: el plato vuelve a estar solo en su sección.
    repository.save_restaurant(db, repository.start_run(db, "restaurants", {}), parse_restaurant(page("restaurant")))
    assert _count(db, "SELECT count(*) FROM menu_items WHERE extra_section_ids <> '{}'") == 0
    assert [r[0] for r in db.execute(SECTION_DISHES, ("Hamburguesas",))] == sorted(burgers)


def test_two_restaurants_sharing_a_rappi_dish_id_keep_their_own_dish_and_price(db, page):
    """Rappi repite el id de un plato entre restaurantes distintos: con item_id como clave global, el segundo se lo
    quitaba al primero (11 locales quedaron sin platos y se pisaron 1.717 precios, 30-09)."""
    parsed = parse_restaurant(page("restaurant"))
    first = parsed["store"]["store_id"]
    other = {**parsed, "store": {**parsed["store"], "store_id": first + 1, "brand_id": None, "name": "Otro local"}}
    other["items"] = [{**item, "price": item["price"] + 1000} for item in parsed["items"]]
    run = repository.start_run(db, "restaurants", {})
    repository.save_restaurant(db, run, parsed)
    repository.save_restaurant(db, run, other)
    db.commit()

    counts = dict(db.execute("SELECT store_id, count(*) FROM menu_items GROUP BY 1").fetchall())
    assert counts == {first: 61, first + 1: 61}
    rappi_id = parsed["items"][0]["item_id"]
    prices = dict(
        db.execute(
            """SELECT mi.store_id, mps.price FROM menu_items mi JOIN menu_price_snapshots mps USING (item_id)
               WHERE mi.rappi_item_id = %s""",
            (rappi_id,),
        ).fetchall()
    )
    assert prices == {first: parsed["items"][0]["price"], first + 1: parsed["items"][0]["price"] + 1000}

    # Volver a guardarlo no duplica: cada local conserva su plato.
    repository.save_restaurant(db, run, other)
    assert _count(db, "SELECT count(*) FROM menu_items") == 122
    build_search_documents(db)
    assert _count(db, "SELECT count(*) FROM search_documents WHERE entity_type = 'menu_item'") == 122


def test_a_restaurant_that_no_longer_exists_leaves_the_search(db):
    """chain:7386 («Kazoku Nh») quedó «ya no existe en Rappi» en la corrida 6 y sus 94 platos seguían buscables."""
    candidate = {"store_id": 384, "path": "/restaurantes/384-rincon-venezolano"}
    job = {
        "job_key": "chain:3607",
        "job_type": "restaurant",
        "payload": {"verticals": ["restaurantes"], "brand_id": 3607, "candidates": [candidate]},
    }
    for client in (FakeClient({candidate["path"]: "restaurant"}), FakeClient(gone={candidate["path"]})):
        run = repository.start_run(db, "restaurants", {})
        repository.add_jobs(db, run, [job])
        process_restaurant_jobs(db, client, run)
        repository.finish_run(db, run)
    assert [r[0] for r in db.execute("SELECT status FROM scrape_jobs ORDER BY run_id")] == ["done", "skipped"]

    build_search_documents(db)

    assert _count(db, "SELECT count(*) FROM search_documents WHERE vertical = 'restaurantes'") == 0


def test_job_queue_resume_and_done_store_types(db):
    run = repository.start_run(db, "stores", {})
    jobs = [
        {
            "job_key": "type:lider",
            "job_type": "store_group",
            "payload": {"verticals": ["supermercado"], "candidates": []},
        },
        {"job_key": "id:9", "job_type": "store_group", "payload": {"verticals": ["mall"], "candidates": []}},
    ]
    repository.add_jobs(db, run, jobs)
    repository.add_jobs(db, run, jobs)  # descubrir de nuevo no duplica
    repository.mark_job(db, run, "type:lider", "done", {"store_type": "lider"})

    assert [j["job_key"] for j in repository.pending_jobs(db, run, "store_group")] == ["id:9"]
    assert repository.pending_jobs(db, run, "store_group", "supermercado") == []
    assert repository.store_types_done(db, run) == {"lider"}
    assert set(repository.pending_payloads(db, run, "store_group")) == {"id:9"}
    assert repository.open_run(db, "stores") == run


def test_zero_stock_is_kept_but_zero_ids_are_not(db):
    _store(db, 1, "lider", "supermercado")
    run = repository.start_run(db, "stores", {})
    repository.save_products(db, run, 1, [_product("a", 100, "Arroz", 1500, stock=0, category_id=0)])
    db.commit()

    assert _count(db, "SELECT stock FROM price_snapshots") == 0
    assert _count(db, "SELECT category_id FROM catalog_items") is None


def test_export_catalog_csv(db, tmp_path):
    _store(db, 1, "lider", "supermercado")
    run = repository.start_run(db, "stores", {})
    repository.save_products(db, run, 1, [_product("a", 100, "Pañales Babysec", 9990)])
    db.commit()

    target = export_catalog_csv(db, tmp_path / "catalogo.csv")

    with target.open(encoding="utf-8-sig") as f:  # con BOM, para Excel
        rows = list(csv.DictReader(f))
    assert [(r["vertical"], r["nombre"], r["categoria"]) for r in rows] == [
        ("supermercado", "Pañales Babysec", "Pañales")
    ]


def test_search_ignores_accents_both_ways(db):
    _store(db, 1, "lider", "supermercado")
    run = repository.start_run(db, "stores", {})
    repository.save_products(
        db,
        run,
        1,
        [_product("a", 100, "Café Molido Colombiano", 4990), _product("b", 101, "Jamon Serrano", 5990)],
    )
    db.commit()
    build_search_documents(db)

    assert [h["entity_id"] for h in search(db, "supermercado", "cafe") if h["entity_type"] == "catalog_item"] == ["100"]
    assert [h["entity_id"] for h in search(db, "supermercado", "jamón") if h["entity_type"] == "catalog_item"] == [
        "101"
    ]


def test_rebuilding_search_takes_the_documents_lock(db):
    """rappi-ia no copia vectores mientras se reescriben los documentos (la corrida ya figura 'done'): si alguien
    tiene el candado, la reescritura espera."""
    _store(db, 1, "lider", "supermercado")
    run = repository.start_run(db, "stores", {})
    repository.save_products(db, run, 1, [_product("a", 100, "Arroz Tucapel", 1500)])
    db.commit()
    with connect(database_url("DATABASE_URL_TEST")) as other:
        other.execute("SELECT pg_advisory_xact_lock(%s)", (SEARCH_DOCUMENTS_LOCK,))
        db.execute("SET lock_timeout = '200ms'")
        with pytest.raises(errors.LockNotAvailable):
            build_search_documents(db)
        db.rollback()
        other.rollback()
    assert build_search_documents(db)["catalog_item"] == 1


def test_search_documents_carry_no_html_from_descriptions(db):
    """~430 descripciones traen <p> y entidades (&iacute;, &nbsp;): entraban al índice, al vector y a Mochi."""
    _store(db, 1, "lider", "supermercado")
    run = repository.start_run(db, "stores", {})
    html = "<p>Prote&iacute;na neutra&nbsp;Nutri &amp; Co &#8211; 1&nbsp;kg</p><br/>"
    repository.save_products(db, run, 1, [_product("a", 100, "Proteína Nutri", 9990, description=html)])
    db.commit()
    build_search_documents(db)

    content = db.execute("SELECT content FROM search_documents WHERE entity_id = '100'").fetchone()[0]
    assert content.endswith("Proteína neutra Nutri & Co – 1 kg")
    assert "<" not in content and "&iacute;" not in content and "&nbsp;" not in content
    assert search(db, "supermercado", "neutra")


def test_clean_html_leaves_plain_text_untouched(db):
    """Solo cambian las descripciones con HTML: si normalizara todo, miles de documentos cambiarían de hash y se
    volverían a embeber sin motivo."""
    plain = "Arroz grado 1.\nIdeal  para  guisos"
    assert db.execute("SELECT clean_html(%s)", (plain,)).fetchone()[0] == plain
    assert db.execute("SELECT clean_html('Salsa &amp;lt; picante')").fetchone()[0] == "Salsa &lt; picante"
    assert db.execute("SELECT clean_html(%s)", ("un sueño <b>profundo</b>, sin ruido",)).fetchone()[0] == (
        "un sueño profundo, sin ruido"
    )


def test_clean_html_knows_the_entities_found_after_the_first_run(db):
    """Tras la primera limpieza (30-09) quedaban &ccedil; («Açaí») y &ordm; en el catálogo real."""
    assert db.execute("SELECT clean_html('A&ccedil;aí 1&ordm; calidad')").fetchone()[0] == "Açaí 1º calidad"


def test_product_names_are_cleaned_too(db):
    """Un nombre real: «Basurero de Metal Con Pedal <ul> <li>tie» (el HTML también llega al nombre)."""
    _store(db, 1, "lider", "supermercado")
    run = repository.start_run(db, "stores", {})
    repository.save_products(db, run, 1, [_product("a", 100, "Basurero de Metal Con Pedal <ul> <li>tie", 9990)])
    db.commit()
    build_search_documents(db)

    content = db.execute("SELECT content FROM search_documents WHERE entity_id = '100'").fetchone()[0]
    assert content.startswith("Basurero de Metal Con Pedal tie. Marca:")


def test_filler_menu_prices_are_unknown_in_search(db):
    """Un plato cuyo precio depende de sus opciones viene a $0 o $1 («Completo Dinamico»): como precio pasaba
    cualquier tope. En la búsqueda queda sin precio; uno real se conserva."""
    _store(db, 3, "restaurant", "restaurantes", brand=("Lo de Anita", 900))
    run = repository.start_run(db, "restaurants", {})
    for item_id, name, price in [
        (1, "Completo Dinamico", 0),
        (2, "Elige Tu Bebida Favorita", 1),
        (3, "Completo", 2500),
    ]:
        db.execute(
            "INSERT INTO menu_items (item_id, rappi_item_id, store_id, name) VALUES (%s, %s, 3, %s)",
            (item_id, item_id, name),
        )
        db.execute(
            "INSERT INTO menu_price_snapshots (run_id, item_id, price, real_price) VALUES (%s, %s, %s, %s)",
            (run, item_id, price, price),
        )
    db.commit()
    build_search_documents(db)

    rows = db.execute(
        "SELECT entity_id, metadata ? 'precio', price_min FROM search_documents WHERE entity_type = 'menu_item'"
    ).fetchall()
    assert sorted(rows) == [("1", False, None), ("2", False, None), ("3", True, 2500)]


def test_building_search_refreshes_the_table_statistics(db, page):
    """/health de la API estima los documentos con las estadísticas de Postgres: tras rearmar la búsqueda decía
    292.690 con 253.749 reales, hasta el siguiente autovacuum."""
    _store(db, 1, "lider", "supermercado")
    run = repository.start_run(db, "stores", {})
    repository.save_products(db, run, 1, [_product("a", 100, "Pañales Babysec Premium G", 9990)])
    repository.save_restaurant(db, run, parse_restaurant(page("restaurant")))
    db.commit()
    counts = build_search_documents(db)
    db.commit()
    total = db.execute("SELECT count(*) FROM search_documents").fetchone()[0]
    estimate = db.execute(
        """SELECT coalesce(sum(greatest(c.reltuples, 0)), 0)::bigint FROM pg_inherits i
           JOIN pg_class c ON c.oid = i.inhrelid WHERE i.inhparent = 'search_documents'::regclass"""
    ).fetchone()[0]
    assert total == sum(counts[k] for k in ("catalog_item", "menu_item", "store")) and estimate == total
