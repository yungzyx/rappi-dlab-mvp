"""Rol B: Jev como juez de la búsqueda, con los juicios en caché (siempre con `FakeJev`, sin red)."""

import math
import re

import pytest

from conftest import add_dish, add_product, add_store
from fakes.jev import FakeJev
from rappi_ia import cli, jev
from rappi_ia.eval import judge, search_eval
from rappi_ia.eval.judge import CRITERIA, JevJudgment, expected_gain, judge_pairs, pairs_from_runs
from rappi_ia.eval.search_eval import SHOWN, QueryRun, render_markdown, summarize
from rappi_ia.eval.sheets import pair_id
from rappi_ia.jev import JevAnswer


def levels(p0, p1, p2) -> dict:
    return {"score": JevAnswer(score=2.0, probabilities={"0": p0, "1": p1, "2": p2}, confidence=0.9)}


def pair(query="cerveza", vertical="licores", entity_type="catalog_item", entity_id="1", tienda="Botillería"):
    return {
        "consulta": query,
        "vertical": vertical,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "nombre": "(del buscador)",
        "tienda": tienda,
    }


def pid(p) -> str:
    return pair_id(p["vertical"], p["consulta"], p["entity_type"], p["entity_id"])


@pytest.fixture
def catalog(db):
    add_store(db, 1, "licores", "Botillería")
    add_product(db, 1, "Cerveza Cristal 6 pack", 1, category="Cervezas")
    add_product(db, 2, "Pisco Mistral 35°", 1, category="Piscos")
    add_store(db, 2, "restaurantes", "Pizzería Don Luigi")
    add_dish(db, 7, "Pizza napolitana", 2, "Pizzas")
    db.commit()


def judge_with(client_answers=None, **kwargs):
    return FakeJev(
        answers={"relevancia": levels(0.1, 0.2, 0.7)["score"]} if client_answers is None else client_answers, **kwargs
    )


# --- ganancia esperada --------------------------------------------


def test_expected_gain_from_probabilities():
    assert expected_gain({"0": 0.2, "1": 0.3, "2": 0.5}) == pytest.approx(0.65)
    assert expected_gain({"0": 1.0, "1": 0.0, "2": 0.0}) == 0.0
    assert expected_gain({"0": 0.0, "1": 0.0, "2": 1.0}) == 1.0
    assert expected_gain({"0": 0.0, "1": 1.0, "2": 0.0}) == 0.5
    assert expected_gain({"0": 2, "1": 0, "2": 2}) == pytest.approx(0.5)  # sin normalizar: se reparte sobre el total
    assert expected_gain({"0": 0.0, "1": 0.0, "2": 0.0}) is None  # sin masa no hay juicio
    assert expected_gain({}) is None


@pytest.mark.parametrize(
    ("answer", "gain"),
    [
        (JevAnswer(score=2.0), 1.0),  # sin probabilidades: el nivel que dio Jev
        (JevAnswer(score=1.0, probabilities={"alto": 0.9, "bajo": 0.1}), 0.5),  # claves que no son los niveles
        (JevAnswer(score=1.0, probabilities={"0": 0.0, "1": 0.0, "2": 0.0}), 0.5),  # sin masa
        (JevAnswer(score=7.0), 1.0),  # fuera de rango: se acota
        (JevAnswer(score=-1.0), 0.0),
    ],
)
def test_falls_back_to_the_score_when_probabilities_are_unusable(db, catalog, answer, gain):
    client = FakeJev(answers={"relevancia": answer})

    judgments = judge_pairs(db, client, [pair()])
    again = judge_pairs(db, client, [pair()])

    assert judgments[pid(pair())] == JevJudgment(gain, {})
    assert db.execute("SELECT score, probabilities FROM eval_judgments").fetchall() == [(gain, {})]
    assert again == judgments and len(client.calls) == 1  # se guardó: no se vuelve a pagar


def test_an_answer_with_neither_probabilities_nor_score_is_not_a_judgment(db, catalog):
    client = FakeJev(answers={"relevancia": JevAnswer()})

    assert judge_pairs(db, client, [pair()]) == {}
    assert db.execute("SELECT count(*) FROM eval_judgments").fetchone()[0] == 0


def test_stores_expected_gain_and_raw_distribution_not_the_level(db, catalog):
    client = FakeJev(answers={"relevancia": levels(0.2, 0.3, 0.5)["score"]})

    judgments = judge_pairs(db, client, [pair()])

    only = judgments[pid(pair())]
    assert only == JevJudgment(gain=pytest.approx(0.65), probabilities={"0": 0.2, "1": 0.3, "2": 0.5})
    row = db.execute("SELECT judge, model_version, score, probabilities FROM eval_judgments").fetchall()
    assert row == [("jev", "jev-falso", pytest.approx(0.65), {"0": 0.2, "1": 0.3, "2": 0.5})]


def test_asks_with_the_three_levels_and_the_pair_resolved_from_the_database(db, catalog):
    client = judge_with()

    judge_pairs(
        db,
        client,
        [
            pair(entity_id="1"),
            pair(
                entity_type="menu_item",
                entity_id="7",
                vertical="restaurantes",
                query="pizza",
                tienda="Pizzería Don Luigi",
            ),
        ],
    )

    states = {call[0]["resultado"]["nombre"]: call for call in client.calls}
    state, questions = states["Cerveza Cristal 6 pack"]
    assert state == {
        "consulta": "cerveza",
        "vertical": "licores",
        "resultado": {"nombre": "Cerveza Cristal 6 pack", "categoria": "Cervezas", "tienda": "Botillería"},
    }
    assert list(questions) == ["relevancia"]
    assert questions["relevancia"]["type"] == "score"
    assert (
        questions["relevancia"]["criteria"]
        == [
            "No sirve: es otro tipo de producto",
            "Sirve a medias: está relacionado o es un sustituto razonable",
            "Sirve: es lo que pide la consulta",
        ]
        == CRITERIA
    )
    dish = states["Pizza napolitana"][0]["resultado"]
    assert dish == {"nombre": "Pizza napolitana", "categoria": "Pizzas", "tienda": "Pizzería Don Luigi"}


# --- caché --------------------------------------------


def test_second_run_uses_cache(db, catalog):
    client = judge_with()
    pairs = [pair(entity_id="1"), pair(entity_id="2")]

    first = judge_pairs(db, client, pairs)
    asked = len(client.calls)
    second = judge_pairs(db, client, pairs)

    assert asked == 2 and len(client.calls) == 2  # la segunda corrida no pregunta nada
    assert second == first and len(second) == 2


def test_only_asks_for_what_is_missing_and_a_failure_is_not_cached(db, catalog):
    client = judge_with(fail_when=lambda state: state["resultado"]["nombre"].startswith("Pisco"))
    pairs = [pair(entity_id="1"), pair(entity_id="2")]

    first = judge_pairs(db, client, pairs)

    assert set(first) == {pid(pairs[0])}  # el que falló no está ni se guardó
    assert db.execute("SELECT count(*) FROM eval_judgments").fetchone()[0] == 1
    client.fail_when = None
    again = judge_pairs(db, client, pairs)
    assert set(again) == {pid(p) for p in pairs}
    assert [c[0]["resultado"]["nombre"] for c in client.calls] == [
        "Cerveza Cristal 6 pack",
        "Pisco Mistral 35°",
        "Pisco Mistral 35°",
    ]  # a la cerveza no se le volvió a preguntar


def test_new_model_version_asks_again(db, catalog):
    pairs = [pair(entity_id="1")]
    old = judge_with(model="jev-1")
    judge_pairs(db, old, pairs)

    new = judge_with(client_answers={"relevancia": levels(0.9, 0.1, 0.0)["score"]}, model="jev-2")
    judgments = judge_pairs(db, new, pairs)

    assert len(new.calls) == 1  # otro modelo es otro juicio
    assert judgments[pid(pairs[0])].gain == pytest.approx(0.05)
    versions = db.execute("SELECT model_version, score FROM eval_judgments ORDER BY 1").fetchall()
    assert versions == [("jev-1", pytest.approx(0.8)), ("jev-2", pytest.approx(0.05))]  # el viejo se conserva


def test_judging_does_not_depend_on_adoption(db, catalog, monkeypatch, tmp_path):
    """El piloto juzga antes de que nadie adopte a Jev: `judge_pairs` no mira el archivo de adopción."""
    monkeypatch.setattr(jev, "ADOPTION_FILE", tmp_path / "no-existe.json")
    assert not jev.load_adoption().juez

    assert judge_pairs(db, judge_with(), [pair()])


def test_judging_nothing_asks_nothing(db):
    client = judge_with()
    assert judge_pairs(db, client, []) == {} and client.calls == []


# --- los pares de la evaluación --------------------------------------------


def run(query, mode, items, relevance=None, tipo="exacta", vertical="licores"):
    items = [
        {"entity_type": "catalog_item", "entity_id": str(i), "texto": f"texto {i}", "concepto": "c", "tienda": store}
        for i, store in items
    ]
    return QueryRun(vertical, query, tipo, mode, relevance or [1] * len(items), 0, 0.9, True, items=items)


def test_pairs_from_runs_are_unique_skip_negatives_and_keep_the_store_shown():
    runs = [
        run("cerveza", "lexico", [(1, None), (2, None)]),
        run("cerveza", SHOWN, [(1, "Botillería")]),
        run("bicicleta", "hibrido", [(3, None)], tipo="negativa"),
    ]

    pairs = pairs_from_runs(runs)

    assert sorted((p["consulta"], p["entity_id"], p["tienda"]) for p in pairs) == [
        ("cerveza", "1", "Botillería"),
        ("cerveza", "2", None),
    ]


# --- métricas con ganancias --------------------------------------------


def test_graded_gains_in_the_metrics():
    ideal = sum(1 / math.log2(i + 2) for i in range(10))

    assert search_eval.precision_at_k([1.0, 0.5, 0.0] + [0.0] * 7) == pytest.approx(0.15)
    assert search_eval.ndcg_at_k([1.0, 0.5, 0.0]) == pytest.approx((1 + 0.5 / math.log2(3)) / ideal)
    assert search_eval.ndcg_at_k([1, 0, 0]) == pytest.approx(1 / ideal)  # los binarios siguen igual


def test_jev_means_use_graded_gain_and_binarize_only_the_mrr():
    runs = [run("cerveza", "hibrido", [(1, None), (2, None), (3, None)], relevance=[0, 1, 1])]
    judgments = {
        pair_id("licores", "cerveza", "catalog_item", "1"): JevJudgment(0.4, {}),  # a medias bajo: no es «sirve»
        pair_id("licores", "cerveza", "catalog_item", "2"): JevJudgment(0.5, {}),
        # el 3 no tiene juicio (falló): cuenta 0 y se avisa
    }

    means = judge.jev_means(runs, judgments)["hibrido"]

    assert means["p@10"] == pytest.approx(0.09)
    assert means["mrr"] == pytest.approx(0.5)  # primer resultado con ganancia ≥ 0,5: el segundo
    assert means["ndcg@10"] == pytest.approx(
        (0.4 + 0.5 / math.log2(3)) / sum(1 / math.log2(i + 2) for i in range(10)), abs=1e-3
    )
    assert means["n"] == 1 and means["sin_juicio"] == 1


# --- el reporte con los tres jueces --------------------------------------------


def test_report_shows_three_judges_side_by_side():
    runs = [
        run("cerveza", "hibrido", [(1, None), (2, None)], relevance=[1, 0]),
        run("cerveza", SHOWN, [(1, "Botillería"), (2, "Botillería")], relevance=[1, 0]),
    ]
    judgments = {
        pair_id("licores", "cerveza", "catalog_item", "1"): JevJudgment(1.0, {}),
        pair_id("licores", "cerveza", "catalog_item", "2"): JevJudgment(0.5, {}),
    }
    human = {
        pair_id("licores", "cerveza", "catalog_item", "1"): 2,
        pair_id("licores", "cerveza", "catalog_item", "2"): 0,
    }
    jev_part = judge.jev_report(runs, judgments, human, model="jev-2026-10")

    report = render_markdown(summarize(runs), {"negativas_detalle": []} | _unmet(), {}, {}, False, "e5", jev=jev_part)

    assert "Jev (jev-2026-10)" in report
    assert "| hibrido | 0.1 | 0.15 |" in report  # P@10 del juez por concepto y del juez Jev, lado a lado
    section = report.split("Pares que juzgaron las personas")[1]
    assert "| Juez por concepto | 0.5 |" in section
    assert "| Jev | 0.75 |" in section
    assert "| Personas | 0.5 |" in section
    assert "2 pares" in section


def _unmet():
    return {
        "negativas": 0,
        "detectadas": 0,
        "falsas_alarmas": 0,
        "no_detectadas": 0,
        "precision": None,
        "recall": None,
        "no_detectadas_detalle": [],
        "falsas_alarmas_detalle": [],
    }


def test_report_explains_graded_versus_binary_and_shows_unjudged_next_to_the_metrics():
    runs = [run("cerveza", "hibrido", [(1, None), (2, None)])]
    judgments = {pair_id("licores", "cerveza", "catalog_item", "1"): JevJudgment(1.0, {})}
    jev_part = judge.jev_report(runs, judgments, {}, model="jev-x")

    report = render_markdown(summarize(runs), {"negativas_detalle": []} | _unmet(), {}, {}, False, "e5", jev=jev_part)

    assert "| Sin juicio de Jev (cuentan 0) |" in report
    assert re.search(r"^\| hibrido \| 0\.2 \| 0\.1 .* \| 1 \|$", report, re.MULTILINE)  # 1 resultado sin juicio
    assert "cuentan 0" in report
    assert "no son directamente comparables" in report and "desde 0,5" in report


def test_report_without_jev_has_no_jev_section():
    runs = [run("cerveza", "hibrido", [(1, None)])]
    report = render_markdown(summarize(runs), {"negativas_detalle": []} | _unmet(), {}, {}, False, "e5")
    assert "Jev" not in report


def test_report_says_how_many_pairs_jev_left_unjudged():
    runs = [run("cerveza", "hibrido", [(1, None), (2, None)])]
    jev_part = judge.jev_report(runs, {}, {}, model="jev-x")
    report = render_markdown(summarize(runs), {"negativas_detalle": []} | _unmet(), {}, {}, False, "e5", jev=jev_part)
    assert "2 pares sin juicio de Jev" in report
    assert "Pares que juzgaron las personas" not in report  # sin planilla juzgada no hay tercera columna


# --- la línea de comandos --------------------------------------------


def test_juez_jev_flag_without_a_key_says_so_and_stops(monkeypatch, capsys):
    monkeypatch.setattr(jev, "client_or_none", lambda: None)

    with pytest.raises(SystemExit) as exit_info:
        cli.cmd_eval_search(None, type("A", (), {"solo_lexico": True, "guardar_tau": False, "juez_jev": True})())

    assert "TYPESAFE_API_KEY" in str(exit_info.value)


def test_eval_search_pipeline_end_to_end_with_a_judged_sheet(db, tmp_path, monkeypatch):
    """Las consultas de verdad sobre el catálogo de prueba, Jev falso y una planilla juzgada de las personas."""
    from rappi_ia.demo.seed import seed_demo
    from rappi_ia.embeddings.base import HashEmbedder
    from rappi_ia.embeddings.text_store import embed_search_documents
    from rappi_ia.eval import sheets

    seed_demo(db)
    embedder = HashEmbedder()
    embed_search_documents(db, embedder)
    queries = [{"vertical": "licores", "query": "cerveza", "concepts": ["cerveza"], "tipo": "exacta"}]
    runs = search_eval.run_queries(db, embedder, queries)
    shown = next(r for r in runs if r.mode == SHOWN)
    first = pair_id("licores", "cerveza", shown.items[0]["entity_type"], shown.items[0]["entity_id"])
    monkeypatch.setattr(sheets, "sheet_dir", lambda: tmp_path)
    sheets.write_csv(
        tmp_path / sheets.SEARCH_SHEET,
        sheets.SEARCH_COLUMNS,
        [{"id": first, "consulta": "cerveza", "vertical": "licores", "posicion": 1, "juicio": "a medias"}],
    )
    client = judge_with()

    part = cli._jev_judgment(db, client, runs)
    again = cli._jev_judgment(db, client, runs)

    assert part == again and part["pares_sin_juicio"] == 0
    assert set(part["modos"]) == {r.mode for r in runs}
    assert part["muestra"]["n"] == 1 and part["muestra"]["personas"] == 0.5 and part["muestra"]["jev"] == 0.8
    assert len(client.calls) == len(pairs_from_runs(runs))  # la segunda vez, todo salió de la caché
