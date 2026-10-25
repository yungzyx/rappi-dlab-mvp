"""Migración 030: caché de juicios de Jev y el método `jev` en los mapeos y asignaciones de conceptos."""

import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from conftest import add_product, add_store
from rappi_ia.concepts.pipeline import build_concepts
from rappi_ia.concepts.report import coverage_report, render_text
from rappi_ia.concepts.store import load_category_map

JUDGMENT = ("cerveza fría", "licores", "catalog_item", "100", "jev", "jev-2026-10")


def _insert_judgment(db, key=JUDGMENT, score=0.8):
    db.execute(
        """INSERT INTO eval_judgments (query, vertical, entity_type, entity_id, judge, model_version, score,
                                       probabilities)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (*key, score, Jsonb({"relevante": 0.8, "irrelevante": 0.2})),
    )


def _insert_jev_mapping(db, name="Novedades de temporada", concept="cerveza"):
    db.execute(
        """INSERT INTO category_map (source_kind, source_key, source_name, concept_id, method, confidence,
                                     model_version)
           VALUES ('categoria', lower(%s), %s, %s, 'jev', 0.9, 'jev-2026-10')""",
        (name, name, concept),
    )


def test_eval_judgments_roundtrip(db):
    _insert_judgment(db)
    db.commit()

    row = db.execute("SELECT score, probabilities, created_at IS NOT NULL FROM eval_judgments").fetchone()
    assert row == (pytest.approx(0.8), {"relevante": 0.8, "irrelevante": 0.2}, True)

    # Misma clave: no se duplica; otra versión del modelo sí es otro juicio.
    with pytest.raises(errors.UniqueViolation):
        _insert_judgment(db)
    db.rollback()
    _insert_judgment(db, (*JUDGMENT[:5], "jev-2026-11"), 0.3)
    assert db.execute("SELECT count(*) FROM eval_judgments").fetchone()[0] == 2


def test_eval_judgments_only_accepts_the_jev_judge(db):
    with pytest.raises(errors.CheckViolation):
        _insert_judgment(db, ("q", "licores", "catalog_item", "1", "llm", "v1"))


@pytest.mark.parametrize(
    ("key", "score"),
    [(("q", "licores", "store", "1", "jev", "v1"), 0.5), (JUDGMENT, 1.5), (JUDGMENT, -0.1)],
    ids=["tipo-desconocido", "puntaje-sobre-1", "puntaje-negativo"],
)
def test_eval_judgments_checks_entity_type_and_score_range(db, key, score):
    with pytest.raises(errors.CheckViolation):
        _insert_judgment(db, key, score)


def test_category_map_accepts_jev(db):
    build_concepts(db)  # siembra la taxonomía
    _insert_jev_mapping(db)
    db.execute(
        """INSERT INTO item_concepts (entity_type, entity_id, concept_id, method, confidence)
           VALUES ('catalog_item', '1', 'cerveza', 'jev', 0.9)"""
    )
    db.commit()
    with pytest.raises(errors.CheckViolation):
        db.execute(
            """INSERT INTO category_map (source_kind, source_key, source_name, concept_id, method, confidence)
               VALUES ('categoria', 'x', 'X', 'cerveza', 'otro', 0.9)"""
        )


def test_load_category_map_keeps_jev_rows(db):
    build_concepts(db)  # una corrida de `concepts` ya recargó el CSV
    _insert_jev_mapping(db, "Novedades de temporada", "cerveza")
    # «Cervezas» está en el CSV curado: si Jev también la mapeó, gana la persona.
    db.execute("DELETE FROM category_map WHERE source_key = 'cervezas'")
    _insert_jev_mapping(db, "Cervezas", "snacks-salados")
    db.commit()

    build_concepts(db)

    rows = dict(db.execute("SELECT source_key, method || '|' || concept_id FROM category_map").fetchall())
    assert rows["novedades de temporada"] == "jev|cerveza"
    assert rows["cervezas"] == "llm|cerveza"  # la fila de category_map.csv
    assert load_category_map(db, []) == 0  # sin filas en el CSV tampoco se borran los de Jev
    assert db.execute("SELECT count(*) FROM category_map WHERE method = 'jev'").fetchone()[0] == 1


def test_build_concepts_uses_jev_mapping_like_others(db):
    add_store(db, 1, "licores", "Botillería")
    add_product(db, 200, "Cerveza Kunstmann Torobayo 330 cc", 1, "Novedades de temporada")
    add_product(db, 202, "Producto misterioso", 1, "Novedades de temporada")
    db.commit()
    build_concepts(db)
    assert db.execute("SELECT count(*) FROM item_concepts WHERE method = 'jev'").fetchone()[0] == 0
    assert [r["nombre"] for r in coverage_report(db)["categorias_sin_mapear"]] == ["Novedades de temporada"]

    _insert_jev_mapping(db)
    db.commit()
    counts = build_concepts(db)

    assert counts["productos_con_concepto"] == 2
    rows = db.execute(
        "SELECT entity_id, concept_id, method, source, model_version FROM item_concepts WHERE entity_id = '202'"
    ).fetchall()
    assert rows == [("202", "cerveza", "jev", "categoria:Novedades de temporada", "jev-2026-10")]
    # Corre otra vez y los de método jev se recalculan, no se acumulan ni se pierden.
    build_concepts(db)
    assert db.execute("SELECT count(*) FROM item_concepts WHERE method = 'jev'").fetchone()[0] == 2

    # Un mapeo hecho por máquina cuenta como mapeado (no vuelve a proponerse) y se informa aparte.
    report = coverage_report(db)
    assert report["categorias_sin_mapear"] == []
    assert report["mapeos_jev"] == 1
    assert "Jev: 1 categorías mapeadas" in render_text(report)
