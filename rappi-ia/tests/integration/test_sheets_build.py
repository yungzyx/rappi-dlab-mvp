"""Las planillas para juzgar a mano contra el catálogo de prueba (`seed_demo`) y la búsqueda de verdad."""

import csv
import json

import pytest

from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents
from rappi_ia.eval import sheets
from rappi_ia.eval.search_eval import SHOWN, run_queries
from rappi_ia.eval.sheets import SheetInUse, build_sheets

QUERIES = [
    {"vertical": "licores", "query": "cerveza", "concepts": ["cerveza"], "tipo": "exacta"},
    {"vertical": "licores", "query": "vino tinto", "concepts": ["vino"], "tipo": "exacta"},
    {"vertical": "licores", "query": "algo para el carrete", "concepts": ["cerveza"], "tipo": "necesidad"},
    {"vertical": "supermercado", "query": "gaseosa", "concepts": ["gaseosas"], "tipo": "exacta"},
    {"vertical": "supermercado", "query": "papas fritas", "concepts": ["snacks-salados"], "tipo": "exacta"},
    {"vertical": "supermercado", "query": "bicicleta", "concepts": [], "tipo": "negativa"},
    {"vertical": "restaurantes", "query": "pizza", "concepts": ["pizza"], "tipo": "exacta"},
]
MAP_ROWS = [
    {"tipo": "categoria", "nombre": "Cervezas", "concept_id": "cerveza", "revision": "juez"},
    {"tipo": "categoria", "nombre": "Gaseosas", "concept_id": "gaseosas", "revision": "juez"},
    {"tipo": "categoria", "nombre": "Pisco", "concept_id": "pisco", "revision": "acuerdo"},
    {"tipo": "categoria", "nombre": "Categoría que no existe", "concept_id": "pisco", "revision": "acuerdo"},
    {"tipo": "seccion_menu", "nombre": "Pizzas", "concept_id": "pizza", "revision": "juez"},  # no es categoría
]


@pytest.fixture
def runs(db):
    seed_demo(db)
    embedder = HashEmbedder()
    embed_search_documents(db, embedder)
    return run_queries(db, embedder, QUERIES, modes=(SHOWN,))


def _rows(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _build(db, runs, tmp_path, **kwargs):
    return build_sheets(db, runs, tmp_path / "data", tmp_path / "git", map_rows=MAP_ROWS, pairs=6, **kwargs)


def test_search_sheet_has_the_pairs_the_user_saw_with_their_texts_and_no_judgment(db, runs, tmp_path):
    summary = _build(db, runs, tmp_path)

    rows = _rows(tmp_path / "data" / sheets.SEARCH_SHEET)
    assert len(rows) == summary["pares"] == 6
    assert list(rows[0]) == sheets.SEARCH_COLUMNS
    assert {r["juicio"] for r in rows} == {""}
    assert "bicicleta" not in {r["consulta"] for r in rows}  # las negativas no esperan resultado
    assert all(r["nombre"] and r["vertical"] and 1 <= int(r["posicion"]) <= 10 for r in rows)
    assert all(r["categoria"] and r["tienda"] for r in rows)
    beer = next(r for r in rows if "cerveza" in r["nombre"].lower() and r["vertical"] == "licores")
    assert beer["categoria"] == "Cervezas" and "prueba" in beer["tienda"].lower()


def test_versioned_ids_carry_no_catalog_text(db, runs, tmp_path):
    _build(db, runs, tmp_path)

    searched = json.loads((tmp_path / "git" / sheets.SEARCH_IDS_FILE.name).read_text(encoding="utf-8"))
    categorized = json.loads((tmp_path / "git" / sheets.CATEGORY_IDS_FILE.name).read_text(encoding="utf-8"))
    for row in _rows(tmp_path / "data" / sheets.SEARCH_SHEET):
        assert row["nombre"] not in json.dumps(searched, ensure_ascii=False)
        assert row["tienda"] not in json.dumps(searched, ensure_ascii=False)
    assert {pair["id"] for pair in searched["pares"]} == {
        r["id"] for r in _rows(tmp_path / "data" / sheets.SEARCH_SHEET)
    }
    assert all(set(c) == {"clave", "vertical", "grupo", "concepto_propuesto"} for c in categorized["categorias"])


def test_category_sheet_mixes_the_groups_with_examples_and_the_proposed_concept(db, runs, tmp_path):
    summary = _build(db, runs, tmp_path)

    assert summary["categorias"]["juez"] == 2 and summary["categorias"]["acuerdo"] == 1  # solo categorías con productos
    rows = {r["categoria"]: r for r in _rows(tmp_path / "data" / sheets.CATEGORY_SHEET)}
    beer = rows["Cervezas"]
    assert beer["vertical"] == "licores" and beer["concepto_propuesto"] == "cerveza" and beer["concepto_correcto"] == ""
    examples = beer["ejemplos"].split(" | ")
    assert 1 <= len(examples) <= sheets.EXAMPLES and any("Cerveza" in e for e in examples)
    assert "Categoría que no existe" not in rows and "Pizzas" not in rows


def test_sheets_are_the_same_with_the_same_seed(db, runs, tmp_path):
    _build(db, runs, tmp_path / "uno")
    _build(db, runs, tmp_path / "dos")

    for name in (sheets.SEARCH_SHEET, sheets.CATEGORY_SHEET, sheets.README_FILE):
        assert (tmp_path / "uno" / "data" / name).read_bytes() == (tmp_path / "dos" / "data" / name).read_bytes()


def test_a_filled_sheet_is_never_overwritten_without_force(db, runs, tmp_path):
    _build(db, runs, tmp_path)
    path = tmp_path / "data" / sheets.SEARCH_SHEET
    rows = _rows(path)
    rows[0]["juicio"] = "sirve"
    sheets.write_csv(path, sheets.SEARCH_COLUMNS, rows)

    with pytest.raises(SheetInUse, match="1 juicios"):
        _build(db, runs, tmp_path)
    assert sheets.read_search_sheet(path) == {rows[0]["id"]: 2}  # sigue ahí

    _build(db, runs, tmp_path, force=True)
    assert sheets.read_search_sheet(path) == {}


def test_readme_explains_how_to_fill_in_and_lists_the_concepts(db, runs, tmp_path):
    _build(db, runs, tmp_path)

    text = (tmp_path / "data" / sheets.README_FILE).read_text(encoding="utf-8")
    for expected in ("Numbers", "Excel", "sirve", "a medias", "no sirve", "ninguno", "`cerveza`", "CSV"):
        assert expected in text
