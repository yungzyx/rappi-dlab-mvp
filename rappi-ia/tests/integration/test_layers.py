"""Capa de perfiles (docs/diseno/2026-10-06-capa-perfiles-design.md) contra `rappi_ia_test`."""

from dataclasses import replace

from rappi_scraper.storage.search import build_search_documents

from conftest import add_dish, add_price, add_product, add_store
from rappi_ia.concepts.pipeline import build_concepts
from rappi_ia.concepts.store import seed_taxonomy
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.layers import attributes as attributes_layer
from rappi_ia.layers.attributes import build_attributes
from rappi_ia.layers.brands import build_brands
from rappi_ia.layers.graph import build_relations
from rappi_ia.layers.measures import build_measures
from rappi_ia.layers.report import layer_report
from rappi_ia.layers.runs import finish_layer_run, start_layer_run


def test_layer_run_is_recorded(db):
    run = start_layer_run(db, "measures", "2026-10-06")
    finish_layer_run(db, run, {"items": 3})

    status, counts, finished = db.execute(
        "SELECT status, counts, finished_at FROM layer_runs WHERE run_id = %s", (run,)
    ).fetchone()
    assert status == "done" and counts == {"items": 3} and finished is not None


def test_a_failed_layer_run_keeps_its_status(db):
    run = start_layer_run(db, "attributes", "2026-10-06")
    finish_layer_run(db, run, {}, status="failed")
    assert db.execute("SELECT status FROM layer_runs WHERE run_id = %s", (run,)).fetchone()[0] == "failed"


def test_capa_schema_exists(db):
    assert db.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'capa'").fetchone()


def _measure_catalog(db):
    add_store(db, 1, "supermercado")
    add_store(db, 2, "restaurantes")
    add_product(db, 10, "Coca-Cola 3 L", 1, "Gaseosas")
    add_product(db, 11, "Cerveza Cristal 6 x 350 ml", 1, "Cervezas")
    db.execute(
        "UPDATE catalog_items SET quantity = 1, unit_type = 'und', presentation = '1Und' WHERE master_product_id = 10"
    )
    db.execute(
        "UPDATE catalog_items SET quantity = 350, unit_type = 'ml', presentation = '6 X 350 mL'"
        " WHERE master_product_id = 11"
    )
    add_dish(db, 500, "Pizza Familiar", 2, "Pizzas")
    db.commit()


def test_build_measures_fills_products_and_dishes_and_is_idempotent(db):
    _measure_catalog(db)

    first = build_measures(db)
    rows = db.execute(
        "SELECT entity_type, entity_id, unit, pack, total, size_label FROM item_measures ORDER BY 1, 2"
    ).fetchall()
    second = build_measures(db)

    assert first == {"productos": 2, "platos": 1, "corregidos": 1, "sospechosas": 0}
    assert rows == [
        ("catalog_item", "10", "ml", 1, 3000.0, None),
        ("catalog_item", "11", "ml", 6, 2100.0, None),
        ("menu_item", "500", None, 1, None, "familiar"),
    ]
    assert second == first
    assert db.execute("SELECT count(*) FROM item_measures").fetchone()[0] == 3
    assert db.execute("SELECT count(*) FROM layer_runs WHERE layer = 'measures'").fetchone()[0] == 2


def _attribute_catalog(db):
    add_store(db, 1, "supermercado")
    items = [
        (20, "Pan de molde", "Panes", 3000, '{"gluten_free": true}'),
        (21, "Leche sin lactosa 1 L", "Leches", 1000, "{}"),
        (22, "Leche entera 1 L", "Leches", 2000, "{}"),
        (23, "Leche descremada 1 L", "Leches", 3000, "{}"),
        (24, "Leche semidescremada 1 L", "Leches", 9000, "{}"),
    ]
    for pid, name, category, price, attrs in items:
        add_product(db, pid, name, 1, category)
        add_price(db, 1, pid, price)
        db.execute("UPDATE catalog_items SET attributes = %s::jsonb WHERE master_product_id = %s", (attrs, pid))
    db.execute("UPDATE price_snapshots SET real_price = 3600, discount_pct = 17 WHERE sku = 'sku-20'")
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    build_measures(db)


def _attrs(db):
    rows = db.execute("SELECT entity_id, attribute_id, source FROM item_attributes ORDER BY 1, 2").fetchall()
    return {(i, a): s for i, a, s in rows}


def test_build_attributes_from_rappi_text_and_prices(db, monkeypatch):
    monkeypatch.setattr(attributes_layer, "MIN_CONCEPT_ITEMS_FOR_PRICE", 4)  # la base de prueba es chica
    _attribute_catalog(db)

    build_attributes(db)
    found = _attrs(db)

    assert found[("20", "sin-gluten")] == "rappi"
    assert found[("21", "sin-lactosa")] == "regla"
    assert found[("20", "con-descuento")] == "derivado"
    assert {i for (i, a) in found if a == "economico"} == {"21"}  # el 25 % más barato de «leche»
    assert db.execute("SELECT count(*) FROM attribute_defs").fetchone()[0] > 70


def test_build_attributes_is_idempotent_and_keeps_curated_rows(db):
    _attribute_catalog(db)
    build_attributes(db)
    db.execute(
        """INSERT INTO item_attributes (entity_type, entity_id, attribute_id, source, confidence, rules_version)
           VALUES ('catalog_item', '22', 'organico', 'curado', 1, 'a mano')"""
    )

    build_attributes(db)
    first = _attrs(db)
    build_attributes(db)

    assert _attrs(db) == first
    assert first[("22", "organico")] == "curado"
    assert db.execute("SELECT count(*) FROM layer_runs WHERE layer = 'attributes'").fetchone()[0] == 3


def test_dish_size_comes_from_the_measures(db):
    add_store(db, 2, "restaurantes")
    add_dish(db, 500, "Pizza Familiar", 2, "Pizzas")
    db.commit()
    build_search_documents(db)
    build_measures(db)

    build_attributes(db)

    assert _attrs(db)[("500", "familiar")] == "regla"


def test_capa_views_expose_attributes_and_unit_prices(db):
    _attribute_catalog(db)
    build_attributes(db)

    attrs = db.execute(
        "SELECT attribute_name, family FROM capa.item_attributes"
        " WHERE entity_id = '21' AND attribute_id = 'sin-lactosa'"
    ).fetchone()
    per_l = db.execute(
        "SELECT price, price_per_l FROM capa.item_unit_prices WHERE entity_id = '21' AND vertical = 'supermercado'"
    ).fetchone()

    assert attrs == ("Sin lactosa", "dieta")
    assert per_l == (1000, 1000.0)  # $1.000 por 1 L


def test_layer_report_lists_coverage_sources_and_a_sample(db):
    _attribute_catalog(db)
    build_attributes(db)

    report = layer_report(db, sample=2)

    assert "# Capas de perfiles" in report
    assert "sin-gluten" in report and "rappi" in report  # cobertura por atributo y fuente
    assert "Leche sin lactosa 1 L" in report  # muestra revisable con el nombre del ítem
    assert "Marcas y producto canónico por vertical" in report and "Productos canónicos con ids distintos" in report
    assert layer_report(db, sample=2) == report  # muestra con semilla fija: mismo reporte


def test_layer_report_shows_the_last_motor_run_of_each_source(db):
    """`rappi-ia motor` corre una vez por fuente: el reporte muestra las dos, no solo la última."""
    for source, transitions in (("synthetic", 64), ("prototype", 9), ("synthetic", 65)):
        run = start_layer_run(db, "motor", "2026-10-16")
        finish_layer_run(db, run, {"fuente": source, "transiciones": transitions})
    run = start_layer_run(db, "measures", "2026-10-06")
    finish_layer_run(db, run, {"items": 3})

    runs = layer_report(db).split("## Cobertura")[0]

    assert "motor (synthetic)" in runs and '"transiciones": 65' in runs and '"transiciones": 64' not in runs
    assert "motor (prototype)" in runs and '"transiciones": 9' in runs
    assert "| measures |" in runs


def test_pet_attributes_come_from_the_concept_group(db):
    add_store(db, 1, "supermercado")
    add_product(db, 30, "Gato Vino Cabernet Sauvignon 1 L", 1, "Vinos")
    add_product(db, 31, "Alimento para gato adulto 1 kg", 1, "Alimento para gatos")
    db.commit()
    build_search_documents(db)
    build_concepts(db)

    build_attributes(db)

    assert ("30", "gato") not in _attrs(db) and _attrs(db)[("31", "gato")] == "regla"


def test_unit_price_ratios_flag_a_mispriced_item(db):
    add_store(db, 1, "supermercado")
    for pid, price in [(40, 1000), (41, 1100), (42, 1200), (43, 1300), (44, 250000)]:
        add_product(db, pid, "Coca-Cola 2 L", 1, "Gaseosas")
        add_price(db, 1, pid, price)
        db.execute("UPDATE catalog_items SET quantity = 2, unit_type = 'l' WHERE master_product_id = %s", (pid,))
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    build_measures(db)

    rows = db.execute(
        "SELECT entity_id, round(ratio::numeric, 1) FROM capa.unit_price_ratios WHERE ratio > 5 ORDER BY 1"
    ).fetchall()

    assert [r[0] for r in rows] == ["44"] and rows[0][1] > 100


def test_economico_compares_the_price_per_unit_not_the_shelf_price(db, monkeypatch):
    """Un sobre de 15 g es barato en la góndola y caro por gramo: «económico» es lo segundo."""
    monkeypatch.setattr(attributes_layer, "MIN_CONCEPT_ITEMS_FOR_PRICE", 4)
    add_store(db, 1, "supermercado")
    items = [(50, "Alimento perro 15 g", 500, 15), (51, "Alimento perro 1000 g", 4000, 1000),
             (52, "Alimento perro 2000 g", 9000, 2000), (53, "Alimento perro 3000 g", 14000, 3000),
             (54, "Alimento perro 5000 g", 30000, 5000)]  # fmt: skip
    for pid, name, price, grams in items:
        add_product(db, pid, name, 1, "Alimento para perros")
        add_price(db, 1, pid, price)
        db.execute(
            "UPDATE catalog_items SET quantity = %s, unit_type = 'gr' WHERE master_product_id = %s", (grams, pid)
        )
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    build_measures(db)

    build_attributes(db)

    cheap = {i for (i, a) in _attrs(db) if a == "economico"}
    assert "50" not in cheap and "51" in cheap  # $4,0/g contra $33,3/g del sobre


def test_curated_rows_survive_even_when_a_rule_detects_the_same_attribute(db):
    _attribute_catalog(db)
    build_attributes(db)
    db.execute(
        "UPDATE item_attributes SET source = 'curado', rules_version = 'a mano' "
        "WHERE entity_id = '21' AND attribute_id = 'sin-lactosa'"
    )

    build_attributes(db)

    assert _attrs(db)[("21", "sin-lactosa")] == "curado"


def test_unit_price_ratios_ignore_items_without_a_comparable_unit(db):
    add_store(db, 1, "supermercado")
    add_product(db, 60, "Cable 2 mt", 1, "Cables")
    add_price(db, 1, 60, 3000)
    db.execute("UPDATE catalog_items SET quantity = 2, unit_type = 'mt' WHERE master_product_id = 60")
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    build_measures(db)

    assert db.execute("SELECT count(*) FROM capa.unit_price_ratios").fetchone()[0] == 0


def test_rules_version_changes_when_the_rules_change(tmp_path):
    from rappi_ia.layers.runs import rules_version

    a, b = tmp_path / "a.toml", tmp_path / "b.toml"
    a.write_text('version = "x"\nA = 1\n')
    b.write_text('version = "x"\nA = 2\n')
    assert rules_version("2026-10-06", a) != rules_version("2026-10-06", b)
    assert rules_version("2026-10-06", a) == rules_version("2026-10-06", a)
    assert rules_version("2026-10-06", a).startswith("2026-10-06+")


def _brand_catalog(db):
    add_store(db, 1, "supermercado")
    add_store(db, 2, "restaurantes")
    items = [
        (70, "Coca-Cola Original 1.5 L", "Coca-Cola"), (71, "Coca Cola Zero 1.5 L", "COCA COLA"),
        (72, "Coca-Cola Sin Azúcar 1.5 L", "Coca-Cola Sin Azúcar"), (73, "Papas Fritas Lays 150 g", "Lays"),
        (74, "Leche Entera 1 L", "Líder"), (75, "Leche Descremada 1 L", "Lider"),
        (76, "Lays Papas Onduladas", ""), (77, "Cargador USB", "Nan"),
    ]  # fmt: skip
    for pid, name, trademark in items:
        add_product(db, pid, name, 1, "Varios")
        db.execute("UPDATE catalog_items SET trademark = %s WHERE master_product_id = %s", (trademark, pid))
    add_dish(db, 500, "Combo Whopper", 2, "Combos")
    db.execute("INSERT INTO brands (brand_id, name, kind) VALUES (9, 'Burger King', 'restaurant')")
    db.execute("UPDATE stores SET brand_id = 9 WHERE store_id = 2")
    db.commit()


def test_build_brands_joins_writings_infers_from_the_name_and_flags_store_brands(db, monkeypatch):
    from rappi_ia.layers import brands as brands_layer

    monkeypatch.setattr(brands_layer, "MIN_PARENT_ITEMS", 2)  # la base de prueba es chica
    monkeypatch.setattr(brands_layer, "MIN_INDEX_ITEMS", 1)
    _brand_catalog(db)

    counts = build_brands(db)
    by_item = dict(db.execute("SELECT entity_id, brand_key FROM item_brands").fetchall())
    sources = dict(db.execute("SELECT entity_id, source FROM item_brands").fetchall())

    assert by_item["70"] == by_item["71"] == by_item["72"]  # tres escrituras y una línea: una marca
    assert (
        db.execute("SELECT name FROM product_brands WHERE brand_key = %s", (by_item["70"],)).fetchone()[0]
        == "Coca-Cola"
    )
    assert by_item["74"] == by_item["75"]  # Líder = Lider
    assert by_item["76"] == by_item["73"] and sources["76"] == "regla"  # «Lays Papas…» sin marca declarada
    assert "77" not in by_item  # «Nan» no es una marca
    assert by_item["500"] and sources["500"] == "cadena"
    assert counts["marcas"] >= 4 and counts["deducidas_del_nombre"] == 1
    assert db.execute("SELECT is_store_brand FROM product_brands WHERE brand_key = %s", (by_item["74"],)).fetchone()[0]
    assert build_brands(db) == counts  # idempotente


def test_store_brand_items_get_the_marca_propia_attribute(db):
    _brand_catalog(db)
    build_search_documents(db)
    build_concepts(db)
    build_measures(db)
    build_brands(db)

    build_attributes(db)

    found = _attrs(db)
    assert found[("74", "marca-propia")] == "derivado" and ("70", "marca-propia") not in found


def test_canonical_products_join_the_same_product_across_ids_and_never_across_sizes(db, monkeypatch):
    from rappi_ia.layers import brands as brands_layer
    from rappi_ia.layers.canonical import build_canonical

    monkeypatch.setattr(brands_layer, "MIN_INDEX_ITEMS", 1)
    add_store(db, 1, "supermercado")
    add_store(db, 2, "licores")
    items = [
        (80, "Coca-Cola Original 1.5 L", "Coca-Cola", 1, 1.5),
        (81, "Coca Cola Original 1,5 L", "COCA COLA", 2, 1.5),
        (82, "Coca-Cola Original 3 L", "Coca-Cola", 1, 3),
        (83, "Coca-Cola Zero 1.5 L", "Coca-Cola", 1, 1.5),
        (84, "Cargador USB", "", 1, None),
    ]
    for pid, name, trademark, store, liters in items:
        add_product(db, pid, name, store, "Gaseosas")
        db.execute(
            "UPDATE catalog_items SET trademark = %s, quantity = %s, unit_type = %s WHERE master_product_id = %s",
            (trademark, liters, "l" if liters else None, pid),
        )
    db.commit()
    build_measures(db)
    build_brands(db)

    counts = build_canonical(db)
    canon = dict(db.execute("SELECT master_product_id::text, canonical_id FROM item_canonical").fetchall())

    assert canon["80"] == canon["81"]  # mismo producto, dos ids, dos verticales
    assert len({canon["80"], canon["82"], canon["83"]}) == 3  # otro tamaño u otra variante: otro producto
    assert "84" not in canon  # sin marca ni medida no se puede unir: no se inventa
    assert counts == {"canonicos": 3, "items": 4, "compartidos": 1}
    assert build_canonical(db) == counts


def test_canonical_ids_are_stable_and_curated_rows_survive_the_rebuild(db, monkeypatch):
    from rappi_ia.layers import brands as brands_layer
    from rappi_ia.layers.canonical import build_canonical

    monkeypatch.setattr(brands_layer, "MIN_INDEX_ITEMS", 1)
    add_store(db, 1, "supermercado")
    for pid in (90, 91):
        add_product(db, pid, "Coca-Cola Original 1.5 L", 1, "Gaseosas")
        db.execute(
            "UPDATE catalog_items SET trademark = 'Coca-Cola', quantity = 1.5, unit_type = 'l'"
            " WHERE master_product_id = %s",
            (pid,),
        )
    db.commit()
    build_measures(db)
    build_brands(db)
    build_canonical(db)
    before = db.execute("SELECT canonical_id FROM item_canonical WHERE master_product_id = 90").fetchone()[0]
    db.execute("UPDATE item_brands SET source = 'curado' WHERE entity_id = '91'")
    db.execute("UPDATE item_canonical SET method = 'curado' WHERE master_product_id = 91")

    build_brands(db)
    build_canonical(db)

    assert db.execute("SELECT canonical_id FROM item_canonical WHERE master_product_id = 90").fetchone()[0] == before
    assert db.execute("SELECT source FROM item_brands WHERE entity_id = '91'").fetchone()[0] == "curado"
    assert db.execute("SELECT method FROM item_canonical WHERE master_product_id = 91").fetchone()[0] == "curado"


def test_concept_edges_is_a_compatible_view_over_the_knowledge_graph(db):
    """`concept_edges` pasó a ser una vista de `knowledge_edges` (relación `complementa`): quien lee o escribe con la
    tabla vieja sigue funcionando."""
    build_concepts(db)

    curated = db.execute("SELECT count(*) FROM concept_edges WHERE method = 'curado'").fetchone()[0]
    graph = db.execute(
        """SELECT count(*) FROM knowledge_edges WHERE relation = 'complementa' AND method = 'curado'
           AND from_kind = 'concept' AND to_kind = 'concept'"""
    ).fetchone()[0]
    db.execute(
        """INSERT INTO concept_edges (from_concept, to_concept, method, weight, support, data_source)
           VALUES ('cerveza', 'pizza', 'coocurrencia', 0.7, 12, 'synthetic')"""
    )
    learned = db.execute(
        "SELECT relation, from_kind, to_kind, weight FROM knowledge_edges WHERE method = 'coocurrencia'"
    ).fetchone()

    assert curated == graph and curated > 50
    assert learned == ("complementa", "concept", "concept", 0.7)


def test_removing_a_concept_removes_its_edges_from_the_graph(db):
    build_concepts(db)
    full = load_taxonomy()  # cacheada: no se muta, se arma una copia sin «cerveza»
    taxonomy = replace(full, concepts={k: v for k, v in full.concepts.items() if k != "cerveza"})
    db.execute(
        "INSERT INTO knowledge_edges (from_id, to_id, method, weight, data_source)"
        " VALUES ('cerveza', 'vino', 'curado', 0.5, 'curado') ON CONFLICT DO NOTHING"
    )

    seed_taxonomy(db, taxonomy)

    assert db.execute("SELECT count(*) FROM knowledge_edges WHERE 'cerveza' IN (from_id, to_id)").fetchone()[0] == 0


def _edges(db, relation, **where):
    sql = (
        "SELECT from_kind, from_id, to_kind, to_id, weight, support, data_source"
        " FROM knowledge_edges WHERE relation = %s"
    )
    for column in where:
        sql += f" AND {column} = %s"
    rows = db.execute(sql + " ORDER BY 1, 2, 3, 4", (relation, *where.values())).fetchall()
    return {(fk, fi, tk, ti): (w, sup, src) for fk, fi, tk, ti, w, sup, src in rows}


def test_build_relations_writes_taxonomy_curated_and_synonym_edges_and_is_idempotent(db):
    build_concepts(db)
    complements = db.execute("SELECT count(*) FROM concept_edges WHERE method = 'curado'").fetchone()[0]

    counts = build_relations(db)
    total = db.execute("SELECT count(*) FROM knowledge_edges").fetchone()[0]
    again = build_relations(db)

    types = _edges(db, "es_tipo_de")
    assert len(types) == len(load_taxonomy().concepts)
    assert types[("concept", "cerveza", "group", "alcohol")][0] == 1.0
    sustituye = _edges(db, "sustituye")  # simétrica: se guarda en las dos direcciones
    assert ("concept", "cafe", "concept", "te") in sustituye and ("concept", "te", "concept", "cafe") in sustituye
    assert ("group", "alcohol", "concept", "panales") in _edges(db, "conflicto")
    assert ("concept", "panales", "group", "alcohol") in _edges(db, "conflicto")
    assert ("term", "pizza", "concept", "pizza") in _edges(db, "sinonimo")
    assert _edges(db, "de_ocasion")  # cada ocasión de la taxonomía arma sus conceptos
    assert db.execute("SELECT count(*) FROM concept_edges WHERE method = 'curado'").fetchone()[0] == complements
    assert counts["curadas"] > 40 and again == counts
    assert db.execute("SELECT count(*) FROM knowledge_edges").fetchone()[0] == total
    assert db.execute("SELECT count(*) FROM layer_runs WHERE layer = 'relations'").fetchone()[0] == 2


def test_build_relations_keeps_complementa_and_what_other_layers_learned(db):
    build_concepts(db)
    db.execute(
        """INSERT INTO concept_edges (from_concept, to_concept, method, weight, support, data_source)
           VALUES ('cerveza', 'pizza', 'coocurrencia', 0.7, 40, 'prototype')"""
    )

    build_relations(db)

    assert db.execute("SELECT count(*) FROM concept_edges WHERE method = 'coocurrencia'").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM concept_edges WHERE method = 'curado'").fetchone()[0] > 50


def _graph_catalog(db):
    add_store(db, 1, "supermercado")
    add_store(db, 2, "licores")
    items = [  # (id, nombre, marca, concepto, tienda)
        (100, "Galletas sin gluten Mantequilla", "Gloria", "galletas", 1),
        (101, "Galletas sin gluten Chips", "Gloria", "galletas", 1),
        (102, "Galletas sin gluten Avena", "Gloria", "galletas", 1),
        (103, "Galletas Soda", "Gloria", "galletas", 1),
        (104, "Galletas Dulces", "Gloria", "galletas", 1),
        (105, "Galletas Crema", "Gloria", "galletas", 1),
        (106, "Cerveza Cristal 350 ml", "Cristal", "cerveza", 2),
        (107, "Cerveza Escudo 350 ml", "Cristal", "cerveza", 2),
        (108, "Cerveza Royal 350 ml", "Cristal", "cerveza", 1),
        (109, "Cerveza Austral 350 ml", "Cristal", "cerveza", 2),
    ]
    for pid, name, trademark, _concept, store in items:
        add_product(db, pid, name, store, "Varios")
        db.execute("UPDATE catalog_items SET trademark = %s WHERE master_product_id = %s", (trademark, pid))
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    for pid, _name, _brand, concept, _store in items:
        db.execute(
            """INSERT INTO item_concepts (entity_type, entity_id, concept_id, method, confidence)
               VALUES ('catalog_item', %s, %s, 'curado', 1)
               ON CONFLICT (entity_type, entity_id) DO UPDATE SET concept_id = EXCLUDED.concept_id""",
            (str(pid), concept),
        )
    db.execute("REFRESH MATERIALIZED VIEW concept_assortment")
    build_measures(db)
    build_brands(db)
    build_attributes(db)
    db.commit()


def test_catalog_relations_respect_their_thresholds(db, monkeypatch):
    from rappi_ia.layers import brands as brands_layer
    from rappi_ia.layers import graph as graph_layer

    monkeypatch.setattr(brands_layer, "MIN_INDEX_ITEMS", 1)
    monkeypatch.setattr(graph_layer, "MIN_BRAND_ITEMS", 3)
    monkeypatch.setattr(graph_layer, "MIN_VERTICAL_ITEMS", 1)
    _graph_catalog(db)

    build_relations(db)

    gluten = _edges(db, "tiene_atributo", to_id="sin-gluten")
    assert gluten == {("concept", "galletas", "attribute", "sin-gluten"): (0.5, 3, "catalogo")}  # 3 de 6, no cerveza
    sells = _edges(db, "se_vende_en")
    assert sells[("concept", "cerveza", "vertical", "licores")][0] == 1.0  # donde más tiene
    assert round(sells[("concept", "cerveza", "vertical", "supermercado")][0], 3) == 0.333  # 1 de 3: relativo
    brands = {k[1]: (k[3], v[0]) for k, v in _edges(db, "marca_de").items()}
    assert brands == {"gloria": ("galletas", 1.0), "cristal": ("cerveza", 1.0)}


def test_catalog_relations_drop_small_samples(db, monkeypatch):
    from rappi_ia.layers import brands as brands_layer

    monkeypatch.setattr(brands_layer, "MIN_INDEX_ITEMS", 1)
    _graph_catalog(db)

    build_relations(db)  # umbrales de producción: Cristal vende 4 ítems (< 5) y Gloria 6; 3 sin gluten alcanzan

    assert ("concept", "cerveza", "vertical", "supermercado") not in _edges(db, "se_vende_en")  # 1 ítem < 3
    assert ("concept", "cerveza", "vertical", "licores") in _edges(db, "se_vende_en")
    assert {k[1] for k in _edges(db, "marca_de")} == {"gloria"}  # Cristal vende 4 < 5
    assert ("concept", "galletas", "attribute", "sin-gluten") in _edges(db, "tiene_atributo")


def test_equivale_links_a_canonical_product_to_every_vertical_that_sells_it(db, monkeypatch):
    from rappi_ia.layers import brands as brands_layer
    from rappi_ia.layers.canonical import build_canonical

    monkeypatch.setattr(brands_layer, "MIN_INDEX_ITEMS", 1)
    add_store(db, 1, "supermercado")
    add_store(db, 2, "licores")
    colas = [(80, "Coca-Cola Original 1.5 L", 1), (81, "Coca Cola Original 1,5 L", 2), (82, "Coca-Cola Zero 1.5 L", 1)]
    for pid, name, store in colas:
        add_product(db, pid, name, store, "Gaseosas")
        db.execute(
            "UPDATE catalog_items SET trademark = 'Coca-Cola', quantity = 1.5, unit_type = 'l'"
            " WHERE master_product_id = %s",
            (pid,),
        )
    db.commit()
    build_measures(db)
    build_brands(db)
    build_canonical(db)

    build_relations(db)

    shared = db.execute("SELECT canonical_id FROM item_canonical WHERE master_product_id = 80").fetchone()[0]
    assert _edges(db, "equivale") == {
        ("canonical", str(shared), "vertical", "licores"): (1.0, 1, "catalogo"),
        ("canonical", str(shared), "vertical", "supermercado"): (1.0, 1, "catalogo"),
    }  # el producto que solo vende una vertical no tiene aristas


def _co_search_events(db, events, source="synthetic"):
    """`events`: (usuario, sesión, tipo, concepto)."""
    for user in {e[0] for e in events}:
        db.execute("INSERT INTO app_users (user_id, source) VALUES (%s, %s) ON CONFLICT DO NOTHING", (user, source))
    for user, session, kind, concept in events:
        db.execute(
            "INSERT INTO app_events (user_id, session_id, type, concept_id, source) VALUES (%s, %s, %s, %s, %s)",
            (user, session, kind, concept, source),
        )


def test_co_search_is_learned_per_source_from_what_people_search_not_from_the_cart(db, monkeypatch):
    from rappi_ia.layers import graph as graph_layer

    monkeypatch.setattr(graph_layer, "MIN_SESSIONS", 2)
    monkeypatch.setattr(graph_layer, "MIN_USERS", 2)
    build_concepts(db)
    sensitive = min(c.id for c in load_taxonomy().concepts.values() if c.sensitive)
    _co_search_events(
        db,
        [
            ("a", "s1", "search", "cerveza"), ("a", "s1", "chat", "pizza"), ("a", "s1", "search", sensitive),
            ("b", "s2", "search", "cerveza"), ("b", "s2", "view_item", "pizza"), ("b", "s2", "search", sensitive),
            ("c", "s3", "search", "vino"), ("c", "s3", "cart_add", "cerveza"),
            ("d", "s4", "search", "vino"), ("d", "s4", "search", "pizza"),
        ],
    )  # fmt: skip

    build_relations(db)

    edges = _edges(db, "co_busqueda")
    assert edges[("concept", "cerveza", "concept", "pizza")] == (1.0, 2, "synthetic")
    pizza_to_beer = edges[("concept", "pizza", "concept", "cerveza")][0]
    assert round(pizza_to_beer, 3) == 0.667  # dirigida: 2 de 3 sesiones con pizza
    assert not any("vino" in (k[1], k[3]) and "cerveza" in (k[1], k[3]) for k in edges)  # el carro no cuenta
    assert not any(sensitive in (k[1], k[3]) for k in edges)  # los sensibles no se aprenden
    assert db.execute("SELECT DISTINCT method FROM knowledge_edges WHERE relation = 'co_busqueda'").fetchall() == [
        ("coocurrencia",)
    ]


def test_one_person_cannot_make_two_concepts_look_related(db, monkeypatch):
    from rappi_ia.layers import graph as graph_layer

    monkeypatch.setattr(graph_layer, "MIN_SESSIONS", 2)  # MIN_USERS queda en su valor real (5)
    build_concepts(db)
    _co_search_events(
        db,
        [
            ("solo", f"s{i}", kind, concept)
            for i in range(4)
            for kind, concept in (("search", "cerveza"), ("chat", "pizza"))
        ]
        + [("otro", "s9", "search", "vino")],
    )

    build_relations(db)

    assert _edges(db, "co_busqueda") == {}


def test_two_users_sharing_a_session_id_are_not_one_session(db, monkeypatch):
    from rappi_ia.layers import graph as graph_layer

    monkeypatch.setattr(graph_layer, "MIN_SESSIONS", 1)
    monkeypatch.setattr(graph_layer, "MIN_USERS", 1)
    build_concepts(db)
    _co_search_events(db, [("a", "s1", "search", "cerveza"), ("b", "s1", "search", "pizza")])  # mismo id, otra persona

    build_relations(db)

    assert _edges(db, "co_busqueda") == {}


def test_se_vende_en_does_not_let_restaurant_dishes_drown_the_catalog_verticals(db, monkeypatch):
    from rappi_ia.layers import graph as graph_layer

    monkeypatch.setattr(graph_layer, "MIN_VERTICAL_ITEMS", 3)
    add_store(db, 1, "supermercado")
    add_store(db, 2, "licores")
    add_store(db, 3, "restaurantes")
    for pid, store in [(300, 1), (301, 1), (302, 1), (303, 1), (304, 2), (305, 2), (306, 2)]:
        add_product(db, pid, f"Gaseosa {pid}", store, "Varios")
    for item in range(400, 440):
        add_dish(db, item, f"Bebida {item}", 3, "Bebidas")
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    db.execute("DELETE FROM item_concepts")
    db.execute(
        """INSERT INTO item_concepts (entity_type, entity_id, concept_id, method, confidence)
           SELECT 'catalog_item', master_product_id::text, 'gaseosas', 'curado', 1 FROM catalog_items
           UNION ALL SELECT 'menu_item', item_id::text, 'gaseosas', 'curado', 1 FROM menu_items"""
    )
    db.execute("REFRESH MATERIALIZED VIEW concept_assortment")

    build_relations(db)

    sells = _edges(db, "se_vende_en", from_id="gaseosas")
    assert {k[3] for k in sells} == {"supermercado", "licores", "restaurantes"}  # 40 platos no tapan al catálogo
    assert sells[("concept", "gaseosas", "vertical", "supermercado")][0] == 1.0  # relativo al catálogo
    assert round(sells[("concept", "gaseosas", "vertical", "licores")][0], 2) == 0.75


def test_tiene_atributo_only_counts_the_kind_of_item_the_attribute_applies_to(db):
    build_concepts(db)
    build_attributes(db)  # siembra attribute_defs
    applies = dict(db.execute("SELECT attribute_id, applies_to FROM attribute_defs").fetchall())
    assert applies["economico"] == "catalog_item"
    db.execute("DELETE FROM item_concepts")
    rows = [("catalog_item", str(i)) for i in range(4)] + [("menu_item", str(100 + i)) for i in range(40)]
    for entity_type, entity_id in rows:
        db.execute(
            "INSERT INTO item_concepts (entity_type, entity_id, concept_id, method, confidence)"
            " VALUES (%s, %s, 'pizza', 'curado', 1)",
            (entity_type, entity_id),
        )
    for i in range(3):
        db.execute(
            """INSERT INTO item_attributes (entity_type, entity_id, attribute_id, source, confidence, rules_version)
               VALUES ('catalog_item', %s, 'economico', 'derivado', 0.9, 'test')""",
            (str(i),),
        )

    build_relations(db)

    edge = _edges(db, "tiene_atributo", to_id="economico")[("concept", "pizza", "attribute", "economico")]
    assert edge[0] == 0.75 and edge[1] == 3  # 3 de los 4 productos; los 40 platos no cuentan


# ── segmentos de usuario ──
from datetime import UTC, datetime, timedelta  # noqa: E402

from rappi_ia.events import store as events_store  # noqa: E402
from rappi_ia.layers.segments import build_segments, load_signals, user_metrics  # noqa: E402

SEG_NOW = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)  # miércoles; el lunes de su semana es el 5-10


def _gluten_catalog(db):
    add_store(db, 1, "supermercado")
    add_product(db, 10, "Galletas Sin Gluten Mantequilla", 1, "Galletas")
    add_product(db, 11, "Galletas Soda", 1, "Galletas")
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    build_measures(db)
    build_brands(db)
    build_attributes(db)
    db.commit()


def _buy(db, user, product, days_ago, source="synthetic", vertical="supermercado", **line):
    order_line = {
        "entity_type": "catalog_item",
        "entity_id": str(product),
        "concept_id": "galletas",
        "unit_price": 2000,
    }
    events_store.record_order(
        db, user, f"s-{days_ago}", f"c-{user}-{days_ago}-{product}", vertical, [{**order_line, **line}],
        source=source, ts=SEG_NOW - timedelta(days=days_ago),
    )  # fmt: skip


def _segments(db, user):
    return {r[0]: r[1] for r in db.execute("SELECT segment_id, level FROM user_segments WHERE user_id = %s", (user,))}


def test_three_gluten_free_purchases_make_the_segment_and_two_do_not(db):
    _gluten_catalog(db)
    for days in (1, 3, 5):
        _buy(db, "u-gf", 10, days)
    for days in (1, 3):
        _buy(db, "u-two", 10, days)
    _buy(db, "u-plain", 11, 1)
    db.commit()

    counts = build_segments(db, "synthetic", now=SEG_NOW)

    assert "compra-sin-gluten" in _segments(db, "u-gf")
    assert "compra-sin-gluten" not in _segments(db, "u-two") and "compra-sin-gluten" not in _segments(db, "u-plain")
    row = db.execute(
        "SELECT signals, source, evidence FROM user_segments"
        " WHERE user_id = 'u-gf' AND segment_id = 'compra-sin-gluten'"
    ).fetchone()
    assert row[0] == 3 and row[1] == "regla" and row[2]["top"][0]["id"] in ("galletas", "sin-gluten")
    assert counts["usuarios"] == 3 and counts["filas"] == db.execute("SELECT count(*) FROM user_segments").fetchone()[0]
    assert db.execute("SELECT sensitive FROM segment_defs WHERE segment_id = 'compra-sin-gluten'").fetchone()[0]


def test_segments_never_mix_sources_and_prototype_rows_survive_a_synthetic_run(db):
    _gluten_catalog(db)
    for days in (1, 3, 5):
        _buy(db, "u-proto", 10, days, source="prototype")
        _buy(db, "u-syn", 10, days)
    db.commit()
    build_segments(db, "prototype", now=SEG_NOW)
    proto_before = _segments(db, "u-proto")
    assert proto_before and not _segments(db, "u-syn")

    build_segments(db, "synthetic", now=SEG_NOW)

    assert _segments(db, "u-proto") == proto_before and _segments(db, "u-syn")


def test_build_segments_is_idempotent_within_a_week_and_keeps_curated_rows(db):
    _gluten_catalog(db)
    for days in (1, 3, 5):
        _buy(db, "u-gf", 10, days)
    db.commit()
    build_segments(db, "synthetic", now=SEG_NOW)
    db.execute(
        "INSERT INTO user_segments (user_id, segment_id, score, level, signals, source)"
        " VALUES ('u-gf', 'vegano', 9, 'alto', 0, 'curado')"
    )

    build_segments(db, "synthetic", now=SEG_NOW + timedelta(hours=3))
    again = build_segments(db, "synthetic", now=SEG_NOW + timedelta(hours=3))

    assert "vegano" in _segments(db, "u-gf")  # lo curado no se pisa
    assert (
        db.execute("SELECT count(*) FROM user_segment_history WHERE week = '2026-10-05'").fetchone()[0]
        == (db.execute("SELECT count(*) FROM user_segments WHERE source = 'regla'").fetchone()[0])
    )
    assert again["filas"] == db.execute("SELECT count(*) FROM user_segments WHERE source = 'regla'").fetchone()[0]
    assert db.execute("SELECT count(DISTINCT week) FROM user_segment_history").fetchone()[0] == 1

    build_segments(db, "synthetic", now=SEG_NOW + timedelta(days=7))
    assert db.execute("SELECT count(DISTINCT week) FROM user_segment_history").fetchone()[0] == 2


def test_a_user_whose_events_name_no_concept_or_item_gets_no_taste_segments(db):
    build_concepts(db)
    events_store.record(
        db,
        [events_store.Event("ghost", "s1", "app_open", ts=SEG_NOW - timedelta(days=1)) for _ in range(5)],
        source="synthetic",
    )
    db.commit()

    build_segments(db, "synthetic", now=SEG_NOW)

    families = {
        r[0]
        for r in db.execute(
            "SELECT DISTINCT d.family FROM user_segments s JOIN segment_defs d USING (segment_id)"
            " WHERE s.user_id = 'ghost'"
        )
    }
    assert families <= {"relacion"}  # sí es «nuevo»; ningún gusto sale de eventos sin concepto ni ítem


def test_relationship_segments_come_from_metrics(db):
    _gluten_catalog(db)
    _buy(db, "u-old", 10, 50)
    _buy(db, "u-new", 10, 2)
    db.commit()

    metrics = user_metrics(db, "synthetic", now=SEG_NOW)
    build_segments(db, "synthetic", now=SEG_NOW)

    assert round(metrics["u-old"]["dias_sin_pedido"]) == 50 and round(metrics["u-new"]["dias_sin_pedido"]) == 2
    assert "en-riesgo" in _segments(db, "u-old") and "activo" in _segments(db, "u-new")
    assert "en-riesgo" not in _segments(db, "u-new")


def test_load_signals_joins_attributes_brand_price_and_basket(db):
    _gluten_catalog(db)
    _buy(db, "u1", 10, 2)
    _buy(db, "u1", 10, 4, from_suggestion=True)
    db.commit()

    signals = load_signals(db, "synthetic")["u1"]
    order_lines = sorted((s for s in signals if s.type == "order_line"), key=lambda s: s.ts)

    assert len(order_lines) == 2 and all("sin-gluten" in s.attributes for s in order_lines)
    assert order_lines[0].concept == "galletas" and order_lines[0].group == "snacks"
    assert order_lines[0].from_suggestion and not order_lines[1].from_suggestion
    assert order_lines[0].basket_items == 1 and order_lines[0].basket_total == 2000
    assert order_lines[0].vertical == "supermercado" and order_lines[0].event_key != order_lines[1].event_key
    assert load_signals(db, "prototype") == {}


def test_a_single_user_recalculation_touches_only_that_user(db):
    _gluten_catalog(db)
    for days in (1, 3, 5):
        _buy(db, "u-a", 10, days)
        _buy(db, "u-b", 10, days)
    db.commit()
    build_segments(db, "synthetic", now=SEG_NOW)
    db.execute("DELETE FROM user_segments WHERE user_id = 'u-a'")
    db.execute("UPDATE user_segments SET score = 99 WHERE user_id = 'u-b' AND segment_id = 'compra-sin-gluten'")

    counts = build_segments(db, "synthetic", user_id="u-a", now=SEG_NOW)

    assert "compra-sin-gluten" in _segments(db, "u-a") and counts["usuarios"] == 1
    score = db.execute("SELECT score FROM user_segments WHERE user_id = 'u-b' AND segment_id = 'compra-sin-gluten'")
    assert score.fetchone()[0] == 99  # el otro usuario no se recalculó


def test_afin_a_edges_come_from_segment_rules_and_skip_the_sensitive_ones(db):
    build_concepts(db)

    build_relations(db)
    total = db.execute("SELECT count(*) FROM knowledge_edges WHERE relation = 'afin_a'").fetchone()[0]
    build_relations(db)

    edges = _edges(db, "afin_a")
    assert edges[("segment", "cervecero", "concept", "cerveza")][0] == 1.0
    assert ("segment", "vegano", "attribute", "vegano") in edges
    assert ("segment", "farmacia-frecuente", "vertical", "farmacia") not in edges  # sensible: no sirve para sugerir
    assert not any(k[1] in {"compra-sin-gluten", "tabaco", "vapeo", "embarazo"} for k in edges)
    assert db.execute("SELECT count(*) FROM knowledge_edges WHERE relation = 'afin_a'").fetchone()[0] == total > 100


def test_synthetic_population_fills_most_families(db):
    from datetime import date

    from rappi_ia.events.synth import generate

    for store_id, vertical in enumerate(
        ["supermercado", "licores", "conveniencia", "mall", "farmacia", "chocolateria"], start=1
    ):
        add_store(db, store_id, vertical, vertical.title())
    catalog = [  # (tienda, categoría, nombres)
        (1, "Leche natural", ["Leche entera 1 L", "Leche descremada 1 L"]),
        (1, "Frutas", ["Manzana 1 kg", "Plátano 1 kg"]),
        (1, "Res", ["Posta rosada", "Lomo vetado"]),
        (1, "Pañales", ["Pañales Huggies talla G", "Pañales Babysec talla M"]),
        (1, "Alimento para perros", ["Dog Chow adulto 3 kg", "Pedigree adulto 8 kg"]),
        (1, "Alimento para gatos", ["Whiskas adulto 1 kg", "Cat Chow adulto 1 kg"]),
        (1, "Galletas", ["Galletas sin gluten mantequilla", "Galletas sin gluten chips", "Galletas soda"]),
        (1, "Café", ["Café molido 250 g", "Café instantáneo 100 g"]),
        (1, "Snacks salados", ["Papas fritas 180 g", "Ramitas 150 g"]),
        (1, "Chocolates", ["Chocolate con leche 100 g", "Chocolate amargo 100 g"]),
        (2, "Cervezas", ["Cerveza lata 470 cc", "Cerveza rubia 350 cc"]),
        (2, "Pisco", ["Pisco 35 grados 1 L"]),
        (3, "Cervezas", ["Cerveza express lata", "Cerveza express botella"]),
        (3, "Energizantes", ["Energética 473 ml", "Energética sin azúcar 473 ml"]),
        (3, "Gaseosas", ["Gaseosa cola 1,5 L", "Gaseosa cola zero 1,5 L"]),
        (6, "Chocolates", ["Bombones surtidos", "Trufas de chocolate"]),
    ]
    pid = 100
    for store, category, names in catalog:
        for name in names:
            pid += 1
            add_product(db, pid, name, store, category)
            add_price(db, store, pid, 1000 + pid)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    build_measures(db)
    build_brands(db)
    build_attributes(db)
    generate(db, users=400, weeks=20, seed=5, until=date(2026, 9, 27))

    build_segments(db, "synthetic", now=datetime(2026, 9, 27, 12, tzinfo=UTC))

    families = {
        r[0]
        for r in db.execute(
            "SELECT DISTINCT d.family FROM user_segments s JOIN segment_defs d USING (segment_id)"
            " JOIN app_users u USING (user_id) WHERE u.source = 'synthetic'"
        )
    }
    assert len(families) >= 8, sorted(families)


def test_the_gluten_free_persona_prefers_items_with_the_attribute(db, monkeypatch):
    from dataclasses import replace
    from datetime import date

    from rappi_ia.events import synth

    add_store(db, 1, "supermercado")
    for pid, name in enumerate(
        ["Galletas sin gluten mantequilla", "Galletas sin gluten chips", "Galletas soda", "Galletas dulces"], start=100
    ):
        add_product(db, pid, name, 1, "Galletas")
        add_price(db, 1, pid, 1000 + pid)
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    build_measures(db)
    build_brands(db)
    build_attributes(db)
    persona = replace(
        next(p for p in synth.PERSONAS if p.id == "sin-gluten"), share=1.0, interests={"supermercado": {"galletas": 1}}
    )
    monkeypatch.setattr(synth, "PERSONAS", [persona])
    monkeypatch.setattr(synth, "ARCHETYPES", {"retail": 1.0})  # pide en el súper: el único vertical del catálogo
    synth.generate(db, users=60, weeks=20, seed=5, until=date(2026, 9, 27))

    build_segments(db, "synthetic", now=datetime(2026, 9, 27, 12, tzinfo=UTC))

    gluten = db.execute("SELECT count(*) FROM user_segments WHERE segment_id = 'compra-sin-gluten'").fetchone()[0]
    assert gluten > 10  # elige ítems con el atributo y el segmento aparece


def test_layer_report_summarizes_segments_and_hides_small_sensitive_groups(db):
    _gluten_catalog(db)
    for days in (1, 3, 5):
        _buy(db, "u-gf", 10, days)
    db.commit()
    build_segments(db, "synthetic", now=SEG_NOW)

    report = layer_report(db, sample=1)

    assert "## Segmentos por familia" in report and "## Segmentos sin ningún usuario" in report
    assert "cervecero" in report.split("## Segmentos sin ningún usuario")[1]  # nadie lo cumple
    assert "compra-sin-gluten" not in report.split("## Segmentos más grandes")[1].split("## Segmentos sin")[0]  # k < 5


# ── correcciones de la revisión de la etapa 4 ──


def test_forgetting_a_concept_also_forgets_the_segments_its_items_gave(db):
    """Las líneas de pedido conservan su ítem aunque «Olvidar» les quite el concepto: el ítem (y su atributo sin gluten)
    no puede devolverle a la persona el segmento que pidió borrar."""
    _gluten_catalog(db)
    for days in (1, 3, 5):
        _buy(db, "u-proto", 10, days, source="prototype")
    db.commit()
    build_segments(db, "prototype", now=SEG_NOW)
    assert "compra-sin-gluten" in _segments(db, "u-proto")

    events_store.forget(db, "u-proto", "galletas")

    assert "compra-sin-gluten" not in _segments(db, "u-proto")


def test_events_from_rappi_hoy_mode_never_become_signals(db):
    """«Rappi hoy» no deja huella de gusto: el prototipo le quita el concepto al evento y deja el ítem y el texto."""
    _gluten_catalog(db)
    events_store.record(
        db,
        [
            events_store.Event(
                "u-hoy", f"s{i}", "view_item", ts=SEG_NOW - timedelta(days=i), entity_type="catalog_item",
                entity_id="10", payload={"mode": "actual"},
            )
            for i in range(1, 5)
        ]
        + [
            events_store.Event("u-hoy", f"c{i}", "chat", ts=SEG_NOW - timedelta(days=i), query="test de embarazo",
                               payload={"mode": "actual"})
            for i in range(1, 5)
        ]
        + [events_store.Event("u-hoy", "z1", "chat", ts=SEG_NOW - timedelta(days=1), query="test de embarazo")],
        source="prototype",
    )  # fmt: skip
    db.commit()

    assert load_signals(db, "prototype") == {}
    build_segments(db, "prototype", now=SEG_NOW)
    assert "embarazo" not in _segments(db, "u-hoy") and "compra-sin-gluten" not in _segments(db, "u-hoy")


def test_one_checkout_is_one_occasion_however_many_items_it_has(db):
    _gluten_catalog(db)
    add_product(db, 12, "Galletas Sin Gluten Avena", 1, "Galletas")
    add_product(db, 13, "Galletas Sin Gluten Coco", 1, "Galletas")
    db.commit()
    build_search_documents(db)
    build_attributes(db)
    lines = [
        {"entity_type": "catalog_item", "entity_id": str(p), "concept_id": "galletas", "unit_price": 2000}
        for p in (10, 12, 13)
    ]
    events_store.record_order(
        db, "u-one", "s-one", "c-one", "supermercado", lines, source="synthetic", ts=SEG_NOW - timedelta(days=1)
    )
    for p in (10, 12, 13):  # lo que el mismo pedido dejó en el registro: vista y carro de cada ítem
        events_store.record(
            db,
            [
                events_store.Event("u-one", "s-one", kind, ts=SEG_NOW - timedelta(days=1), concept_id="galletas",
                                   entity_type="catalog_item", entity_id=str(p), cart_id="c-one")
                for kind in ("view_item", "cart_add")
            ],
            source="synthetic",
        )  # fmt: skip
    for days in (3, 5):
        _buy(db, "u-three", 10, days)
    _buy(db, "u-three", 10, 1)
    db.commit()

    build_segments(db, "synthetic", now=SEG_NOW)

    assert "compra-sin-gluten" not in _segments(db, "u-one")  # nueve eventos, una sola ocasión
    assert "compra-sin-gluten" in _segments(db, "u-three")  # tres pedidos en tres días
    assert db.execute(
        "SELECT signals FROM user_segments WHERE user_id = 'u-three' AND segment_id = 'compra-sin-gluten'"
    ).fetchone() == (3,)


def test_price_percentile_is_measured_in_the_vertical_of_the_event(db):
    """Un producto en dos verticales se compara con los de cada una; antes se duplicaba y valía cualquiera."""
    add_store(db, 1, "supermercado")
    add_store(db, 2, "conveniencia")
    for pid, price in [(10, 5000), (11, 1000), (12, 2000), (13, 3000)]:
        add_product(db, pid, f"Galletas {pid}", 1, "Galletas")
        add_price(db, 1, pid, price)
    for pid, price in [(14, 1000), (15, 2000), (16, 3000)]:
        add_product(db, pid, f"Galletas {pid}", 2, "Galletas")
        add_price(db, 2, pid, price)
    db.execute("INSERT INTO store_products (store_id, sku, master_product_id) VALUES (2, 'sku-10-b', 10)")
    db.execute(
        "INSERT INTO price_snapshots (run_id, store_id, sku, price, in_stock)"
        " SELECT run_id, 2, 'sku-10-b', 500, true FROM price_snapshots LIMIT 1"
    )
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    _buy(db, "u1", 10, 2, vertical="supermercado")
    _buy(db, "u1", 10, 4, vertical="conveniencia")
    db.commit()

    percentile = {s.vertical: s.price_percentile for s in load_signals(db, "synthetic")["u1"] if s.type == "order_line"}

    assert percentile == {"supermercado": 1.0, "conveniencia": 0.0}
    assert len([s for s in load_signals(db, "synthetic")["u1"] if s.type == "order_line"]) == 2  # sin filas duplicadas


def test_a_malformed_event_payload_cannot_break_the_segment_build(db):
    _gluten_catalog(db)
    events_store.record(
        db,
        [events_store.Event("u-bad", "s1", "cart_add", concept_id="galletas", payload={"from_suggestion": "si"})],
        source="prototype",
    )
    db.commit()

    assert "u-bad" in load_signals(db, "prototype")
    build_segments(db, "prototype", now=SEG_NOW)  # no revienta


def test_forgetting_a_concept_also_clears_the_users_earlier_history(db):
    _gluten_catalog(db)
    for days in (1, 3, 5):
        _buy(db, "u-proto", 10, days, source="prototype")
    db.commit()
    build_segments(db, "prototype", now=SEG_NOW)
    db.execute(
        "INSERT INTO user_segment_history (week, user_id, segment_id, score, level)"
        " VALUES ('2026-09-28', 'u-proto', 'compra-sin-gluten', 9, 'alto')"
    )

    events_store.forget(db, "u-proto", "galletas")

    assert (
        db.execute(
            "SELECT count(*) FROM user_segment_history WHERE user_id = 'u-proto' AND week < '2026-10-05'"
        ).fetchone()[0]
        == 0
    )
    assert db.execute(
        "SELECT count(*) FROM user_segment_history WHERE user_id = 'u-proto' AND segment_id = 'compra-sin-gluten'"
    ).fetchone() == (0,)


# ── contrato `capa` (etapa 5) ──


def _seed_segment_defs(db):
    build_segments(db, "synthetic", now=SEG_NOW)  # siembra segment_defs aunque no haya nadie


def _person(db, user, source="synthetic"):
    db.execute("INSERT INTO app_users (user_id, source) VALUES (%s, %s) ON CONFLICT DO NOTHING", (user, source))


def test_capa_user_segments_never_returns_sensitive_segments(db):
    _seed_segment_defs(db)
    _person(db, "u1")
    for segment in ("compra-sin-gluten", "tabaco", "cervecero"):
        db.execute(
            "INSERT INTO user_segments (user_id, segment_id, score, level, signals) VALUES ('u1', %s, 5, 'medio', 3)",
            (segment,),
        )

    rows = db.execute("SELECT user_id, segment_id, segment_name, source FROM capa.user_segments").fetchall()

    assert rows == [("u1", "cervecero", "Cervecero", "synthetic")]


def _members(db, segment, count, level="medio", source="synthetic", prefix="m", week="2026-10-05"):
    for i in range(count):
        user = f"{prefix}-{segment}-{source}-{level}-{i}"
        _person(db, user, source)
        db.execute(
            "INSERT INTO user_segment_history (week, user_id, segment_id, score, level)"
            " VALUES (%s, %s, %s, 5, %s) ON CONFLICT DO NOTHING",
            (week, user, segment, level),
        )


def _sizes(db):
    return {
        (r[0], r[1], r[2]): r[3] for r in db.execute("SELECT source, segment_id, level, users FROM capa.segment_sizes")
    }


def test_capa_segment_sizes_hides_a_sensitive_segment_below_five_people(db):
    _seed_segment_defs(db)
    for i in range(8):  # personas de la fuente que no están en ningún segmento
        _person(db, f"bystander-{i}")
    _members(db, "compra-sin-gluten", 4)
    _members(db, "cervecero", 1)

    assert _sizes(db) == {("synthetic", "cervecero", "medio"): 1}  # el sensible con 4 no aparece; el común con 1 sí

    _members(db, "compra-sin-gluten", 1, prefix="x")
    assert _sizes(db)[("synthetic", "compra-sin-gluten", "todos")] == 5


def test_capa_segment_sizes_counts_sensitive_people_across_levels_and_never_splits_them(db):
    """5 personas repartidas 3 y 2 entre niveles son 5: se muestran juntas, sin revelar la división (con k por celda se
    ocultaban 5 y se mostraban 18, y quien sumaba niveles obtenía menos que el total)."""
    _seed_segment_defs(db)
    for i in range(8):
        _person(db, f"bystander-{i}")
    _members(db, "compra-sin-gluten", 3, level="medio")
    _members(db, "compra-sin-gluten", 2, level="alto")

    assert _sizes(db) == {("synthetic", "compra-sin-gluten", "todos"): 5}


def test_capa_segment_sizes_never_pools_sources_and_hides_a_segment_that_is_everyone(db):
    _seed_segment_defs(db)
    for i in range(8):
        _person(db, f"bystander-{i}")
    _members(db, "compra-sin-gluten", 3)  # synthetic: 3
    _members(db, "compra-sin-gluten", 2, source="prototype")  # prototype: 2; juntas serían 5
    assert _sizes(db) == {}

    for i in range(6):  # toda una fuente en el segmento: el que lo ve sabe que cada persona lo tiene
        _members(db, "tabaco", 1, source="prototype", prefix=f"all{i}")
    assert not any(k[1] == "tabaco" for k in _sizes(db))


def test_every_capa_view_and_column_has_a_spanish_comment(db):
    views = db.execute(
        """SELECT c.oid, c.relname, obj_description(c.oid, 'pg_class') FROM pg_class c
           JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'capa' AND c.relkind = 'v'"""
    ).fetchall()
    assert {name for _oid, name, _c in views} >= {
        *("items", "item_attributes", "item_unit_prices", "unit_price_ratios", "item_brands", "canonical_products"),
        *("knowledge_edges", "segment_defs", "user_segments", "segment_sizes", "layer_runs"),
    }
    for oid, name, comment in views:
        assert comment, f"capa.{name} sin comentario"
        for column, text in db.execute(
            """SELECT a.attname, col_description(a.attrelid, a.attnum) FROM pg_attribute a
               WHERE a.attrelid = %s AND a.attnum > 0 AND NOT a.attisdropped""",
            (oid,),
        ):
            assert text, f"capa.{name}.{column} sin comentario"


def test_capa_items_describes_products_and_dishes_in_one_place(db):
    add_store(db, 1, "supermercado")
    add_store(db, 2, "restaurantes")
    add_product(db, 10, "Coca-Cola Original 1.5 L", 1, "Gaseosas")
    add_price(db, 1, 10, 2490)
    db.execute(
        "UPDATE catalog_items SET trademark = 'Coca-Cola', quantity = 1.5, unit_type = 'l' WHERE master_product_id = 10"
    )
    add_dish(db, 500, "Pizza Familiar", 2, "Pizzas")
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    build_measures(db)
    build_brands(db)

    rows = {
        r[0]: r[1:]
        for r in db.execute(
            """SELECT entity_id, entity_type, vertical, name, concept_id, concept_group, brand_name, unit, total
               FROM capa.items"""
        )
    }

    assert rows["10"] == (
        "catalog_item",
        "supermercado",
        "Coca-Cola Original 1.5 L",
        "gaseosas",
        "bebidas",
        "Coca-Cola",
        "ml",
        1500.0,
    )
    assert rows["500"][:4] == ("menu_item", "restaurantes", "Pizza Familiar", "pizza")


def test_capa_user_segments_evidence_never_names_what_a_sensitive_segment_looks_at(db):
    from rappi_ia.layers.segments import SENSITIVE_SEGMENTS, load_segment_rules

    _gluten_catalog(db)
    add_product(db, 20, "Pañales Huggies talla G", 1, "Pañales")
    db.commit()
    build_search_documents(db)
    build_attributes(db)
    for days in (1, 2, 3, 4, 5, 6):
        _buy(db, "u-deal", 20, days, concept_id="panales", unit_price=9000)
    db.commit()

    build_segments(db, "synthetic", now=SEG_NOW)

    hidden = {c for r in load_segment_rules()[1] if r.sensitive for c in r.signals.get("concepts", ())}
    exposed = db.execute("SELECT evidence::text FROM capa.user_segments WHERE user_id = 'u-deal'").fetchall()
    assert exposed  # tiene segmentos comunes (relación, momentos…)
    assert not any(concept in text for (text,) in exposed for concept in hidden)
    assert SENSITIVE_SEGMENTS  # y los sensibles siguen existiendo en la tabla interna


def test_layer_run_records_when_it_really_finished(db):
    run = start_layer_run(db, "measures", "2026-10-06")
    db.execute("SELECT pg_sleep(0.05)")
    finish_layer_run(db, run, {})

    started, finished = db.execute(
        "SELECT started_at, finished_at FROM layer_runs WHERE run_id = %s", (run,)
    ).fetchone()

    assert finished > started  # antes valían lo mismo: se tomaba `now()` de la misma transacción


def test_capa_layer_runs_and_segment_defs_expose_lineage_and_rules(db):
    _seed_segment_defs(db)

    run = db.execute("SELECT layer, status, rules_version FROM capa.layer_runs WHERE layer = 'segments'").fetchone()
    rule = db.execute("SELECT sensitive, rule ->> 'min_signals' FROM capa.segment_defs WHERE segment_id = 'tabaco'")

    from rappi_ia.layers.segments import load_segment_rules

    assert run[0] == "segments" and run[1] == "done" and run[2].startswith(load_segment_rules()[0] + "+")
    assert rule.fetchone() == (True, "3")


def test_quality_sample_is_fixed_and_carries_what_a_judge_needs(db):
    from rappi_ia.layers.quality import build_quality_sample

    _gluten_catalog(db)
    add_store(db, 2, "restaurantes", "La Pizzería")
    add_dish(db, 500, "Pizza Napolitana", 2, "Pizzas")
    db.commit()
    build_search_documents(db)
    build_concepts(db)

    sample = build_quality_sample(db)

    assert sample == build_quality_sample(db)  # semilla fija
    gluten = next(r for r in sample if r["kind"] == "atributo" and r["clave"] == "sin-gluten")
    assert gluten["nombre"] == "Galletas Sin Gluten Mantequilla" and gluten["categoria"] == "Galletas"
    assert gluten["afirmacion"].startswith("Sin gluten")
    dish = next(r for r in sample if r["kind"] == "concepto" and r["entity_type"] == "menu_item")
    assert dish["tienda"] == "La Pizzería" and dish["categoria"] == "Pizzas" and "Pizza" in dish["afirmacion"]
    assert len({r["id"] for r in sample}) == len(sample)
