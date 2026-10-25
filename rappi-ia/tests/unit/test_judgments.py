import pytest

from rappi_ia.eval.judgments import build_sample, human_report, sheet_report
from rappi_ia.eval.search_eval import ABLATION, SHOWN, QueryRun


def _item(entity_id, concept):
    return {
        "entity_type": "catalog_item",
        "entity_id": entity_id,
        "texto": f"Producto {entity_id}",
        "concepto": concept,
    }


def _run(query, mode, ids, concepts=("pisco",)):
    items = [_item(i, "pisco" if i.startswith("p") else "vino") for i in ids]
    relevance = [1 if it["concepto"] in concepts else 0 for it in items]
    return QueryRun("licores", query, "exacta", mode, relevance, 0, 0.9, True, items=items)


RUNS = [
    _run("pisco", "hibrido", ["p1", "p2", "v1"]),
    _run("pisco", ABLATION, ["p1", "v1", "v2"]),  # difiere en p2 (solo con refuerzo) y v2 (solo sin él)
    _run("pisco", "vector", ["p1", "v3"]),
    _run("pisco", "lexico", ["p1"]),
    _run("ron", "hibrido", ["r1"], concepts=("ron",)),
    _run("ron", ABLATION, ["r1"], concepts=("ron",)),
]


def test_sample_prioritizes_items_where_the_concept_bonus_changes_the_top_10():
    """La pregunta abierta es si el refuerzo mejora: los ítems que solo aparecen con o sin él la responden."""
    sample = build_sample(RUNS, n_diff=2, n_random=0)

    assert {(p["consulta"], p["entity_id"]) for p in sample} == {("pisco", "p2"), ("pisco", "v2")}
    p2 = next(p for p in sample if p["entity_id"] == "p2")
    assert p2["origen"] == "diferencia"
    assert p2["modos"] == ["hibrido"]
    assert p2["relevante_auto"] is True


def test_sample_adds_random_pairs_from_every_mode_without_duplicates():
    sample = build_sample(RUNS, n_diff=2, n_random=10)

    keys = [(p["vertical"], p["consulta"], p["entity_type"], p["entity_id"]) for p in sample]
    assert len(keys) == len(set(keys)) == 6  # p1, p2, v1, v2, v3 de «pisco» y r1 de «ron»
    assert {p["origen"] for p in sample} == {"diferencia", "al_azar"}
    assert all(p["id"] and p["texto"] for p in sample)


def test_sample_ignores_the_products_shown_row():
    """«mostrado» repite ítems del híbrido y trae otros del puesto 11 al 20: sumarlo cambiaría la muestra versionada."""
    shown = _run("pisco", SHOWN, ["p1", "p9"])

    assert build_sample([*RUNS, shown], n_diff=2, n_random=10) == build_sample(RUNS, n_diff=2, n_random=10)


def test_sample_is_reproducible_and_grouped_by_query():
    first = build_sample(RUNS, n_diff=1, n_random=2, seed=3)

    assert first == build_sample(RUNS, n_diff=1, n_random=2, seed=3)
    queries = [p["consulta"] for p in first]
    assert queries == sorted(queries)  # juzgar una consulta de corrido es más rápido


def _pair(pid, auto, modes):
    return {"id": pid, "relevante_auto": auto, "modos": modes, "origen": "diferencia"}


def test_human_report_measures_the_automatic_judge_and_the_concept_bonus():
    sample = [
        _pair("a", True, ["hibrido"]),  # solo con refuerzo
        _pair("b", True, ["hibrido"]),
        _pair("c", False, [ABLATION]),  # solo sin refuerzo
        _pair("d", False, [ABLATION]),
        _pair("e", True, ["hibrido", ABLATION, "vector"]),
    ]
    judgments = {"a": "relevante", "b": "no", "c": "relevante", "d": "relevante", "e": "nose"}

    report = human_report(sample, judgments)

    assert report["juzgados"] == 4 and report["no_se"] == 1
    # Juez automático: marcó a y b relevantes (acertó 1 de 2) y se perdió c y d.
    assert report["juez_auto"] == {"precision": 0.5, "recall": 0.333, "acuerdo": 0.25}
    assert report["refuerzo"] == {
        "solo_con_refuerzo": {"n": 2, "relevantes": 0.5},
        "solo_sin_refuerzo": {"n": 2, "relevantes": 1.0},
    }


def test_human_report_without_judgments_is_empty_not_an_error():
    report = human_report([_pair("a", True, ["hibrido"])], {})
    assert report["juzgados"] == 0
    assert report["juez_auto"] == {"precision": None, "recall": None, "acuerdo": None}


def _sheet_pair(pair_id, estrato, auto):
    return {"id": pair_id, "estrato": estrato, "relevante_auto": auto}


def test_sheet_report_gives_kappa_of_people_against_the_concept_judge():
    """Personas: sirve/sirve/no sirve/a medias. Juez por concepto: relevante/no/no/relevante. En binario («sirve»
    contra el resto): personas 1,1,0,0 y juez 1,0,0,1 → acuerdo 0,5, azar 0,5, κ = 0. Ponderado: personas 2,2,0,1 y
    juez 2,0,0,2."""
    pairs = [
        _sheet_pair("a", "top3", True),
        _sheet_pair("b", "top3", False),
        _sheet_pair("c", "4-10", False),
        _sheet_pair("d", "4-10", True),
    ]
    human = {"a": 2, "b": 2, "c": 0, "d": 1, "no-esta": 2}

    report = sheet_report(pairs, human)

    assert report["juzgados"] == 4 and report["sin_juicio"] == 0 and report["desconocidos"] == 1
    assert report["acuerdo"] == 0.5
    assert report["kappa"] == 0.0
    # Ponderado a mano: desacuerdo observado (0+2+0+1)/4/2 = 0,375; esperado con marginales personas (1,1,2) y juez
    # (2,0,2): 16/16/2 = 0,5; κ = 1 - 0,375/0,5 = 0,25.
    assert report["kappa_ponderado"] == pytest.approx(0.25)
    assert report["por_estrato"] == {"top3": {"n": 2, "acuerdo": 0.5}, "4-10": {"n": 2, "acuerdo": 0.5}}


def test_sheet_report_without_judgments_has_no_kappa():
    report = sheet_report([_sheet_pair("a", "top3", True)], {})

    assert report["juzgados"] == 0 and report["sin_juicio"] == 1 and report["kappa"] is None
