"""`build_concepts` contra `rappi_ia_test`: carga la taxonomía y asigna conceptos con procedencia."""

import csv

from conftest import add_dish, add_product, add_store
from rappi_ia.concepts.pipeline import build_concepts
from rappi_ia.concepts.report import CATEGORY_MAP_COLUMNS, coverage_report, render_text, write_category_proposals
from rappi_ia.concepts.store import CATEGORY_MAP_CSV


def _seed(db):
    add_store(db, 1, "licores", "Botillería")
    add_store(db, 2, "restaurantes", "Pizzería")
    add_product(db, 100, "Cerveza Escudo 350 cc", 1, "Cervezas")
    add_product(db, 101, "Papas Lays Clásicas 180 g", 1, "Snacks salados")
    add_product(db, 102, "Producto sin pistas", 1)
    add_dish(db, 500, "Pizza pepperoni familiar", 2, "Pizzas", ["Pizzas"])
    add_dish(db, 501, "Especial de la casa", 2, "Pizzas", ["Pizzas"])
    db.commit()


def test_build_concepts_assigns_with_provenance(db):
    _seed(db)
    counts = build_concepts(db)

    assert counts["productos_con_concepto"] == 2 and counts["platos_con_concepto"] == 2
    rows = dict(
        db.execute(
            "SELECT entity_id, concept_id || '|' || method || '|' || source FROM item_concepts ORDER BY 1"
        ).fetchall()
    )
    assert rows["100"] == "cerveza|llm|categoria:Cervezas"
    assert rows["101"] == "snacks-salados|llm|categoria:Snacks salados"
    assert rows["500"].lower() == "pizza|regla|nombre:pizza"
    assert rows["501"].startswith("pizza|llm|")  # por la sección o la cocina "Pizzas"
    assert "102" not in rows
    assert db.execute("SELECT count(*) FROM concept_edges WHERE method = 'curado'").fetchone()[0] > 50


def test_build_concepts_is_idempotent_and_drops_stale_rules(db):
    _seed(db)
    build_concepts(db)
    db.execute(
        "UPDATE catalog_items SET name = 'Producto renombrado', category_id = NULL WHERE master_product_id = 101"
    )
    db.commit()

    build_concepts(db)

    ids = [r[0] for r in db.execute("SELECT entity_id FROM item_concepts ORDER BY 1")]
    assert ids == ["100", "500", "501"]


def test_the_description_of_a_dish_reaches_the_aperitivo_rule(db):
    """En una sección «Aperitivos», un plato con nombre de comida sale del alcohol solo si la descripción tampoco lo
    dice: la descripción tiene que llegar desde la base."""
    add_store(db, 3, "restaurantes", "Bar")
    add_dish(db, 600, "Queso Mantecoso Laminado", 3, "Aperitivos")
    add_dish(db, 601, "Pepino Tonic", 3, "Aperitivos")
    db.execute("UPDATE menu_items SET description = 'Gin, pepino y agua tónica' WHERE item_id = 601")
    db.commit()

    build_concepts(db)

    rows = dict(db.execute("SELECT entity_id, concept_id FROM item_concepts").fetchall())
    assert "600" not in rows
    assert rows["601"] == "licores"


def test_coverage_report_by_vertical(db):
    _seed(db)
    build_concepts(db)
    report = coverage_report(db)
    assert report["totales"]["catalog_item"] == {"total": 3, "mapped": 2, "pct": 66.7}
    assert report["por_vertical"]["licores"]["mapped"] == 2
    assert report["por_vertical"]["restaurantes"] == {"total": 2, "mapped": 2, "pct": 100.0}


def test_categories_without_a_reviewed_mapping_are_reported_with_a_suggestion(db, tmp_path):
    """Las categorías nuevas de cada domingo no están en category_map.csv: el reporte las muestra y propone concepto."""
    _seed(db)
    add_product(db, 200, "Cerveza Kunstmann Torobayo 330 cc", 1, "Novedades de temporada")
    add_product(db, 201, "Cerveza Austral Calafate 330 cc", 1, "Novedades de temporada")
    add_product(db, 202, "Producto misterioso", 1, "Novedades de temporada")
    db.commit()
    build_concepts(db)

    report = coverage_report(db)

    assert report["categorias_sin_mapear"] == [
        {
            "nombre": "Novedades de temporada",
            "productos": 3,
            "sin_concepto": 1,
            "sugerido": "cerveza",
            "con_sugerido": 2,
        }
    ]  # Cervezas y Snacks salados ya están en category_map.csv
    assert "Novedades de temporada (3 productos, 1 sin concepto)" in render_text(report)

    path = tmp_path / "categorias-sin-mapear.csv"
    write_category_proposals(report["categorias_sin_mapear"], path)
    [row] = list(csv.DictReader(path.open(encoding="utf-8")))
    assert list(row) == CATEGORY_MAP_COLUMNS  # mismo formato que category_map.csv, para revisar y copiar
    assert (row["nombre"], row["concept_id"], row["confianza"], row["metodo"]) == (
        "Novedades de temporada",
        "cerveza",
        "0.67",
        "sugerido",
    )


def test_a_weak_suggestion_is_not_proposed(tmp_path):
    """1 de 67 productos con un concepto (p. ej. «Pesca deportiva» → carbón) es ruido, no una sugerencia."""
    path = tmp_path / "categorias-sin-mapear.csv"
    rows = [{"nombre": "Pesca Deportiva", "productos": 46, "sin_concepto": 45, "sugerido": "carbon", "con_sugerido": 1}]
    write_category_proposals(rows, path)
    [row] = list(csv.DictReader(path.open(encoding="utf-8")))
    assert (row["concept_id"], row["confianza"]) == ("ninguno", "0.02")


def test_categories_reviewed_without_a_concept_are_not_reported_again(db):
    """Una fila «ninguno» de category_map.csv es una revisión hecha: no vuelve como «sin mapeo revisado»."""
    with CATEGORY_MAP_CSV.open(encoding="utf-8") as f:
        reviewed = next(
            r["nombre"] for r in csv.DictReader(f) if r["tipo"] == "categoria" and r["concept_id"] == "ninguno"
        )
    _seed(db)
    add_product(db, 300, "Cerveza Kunstmann Torobayo 330 cc", 1, reviewed)
    add_product(db, 301, "Producto misterioso", 1, "Novedades de temporada")
    db.commit()
    build_concepts(db)

    assert [row["nombre"] for row in coverage_report(db)["categorias_sin_mapear"]] == ["Novedades de temporada"]
