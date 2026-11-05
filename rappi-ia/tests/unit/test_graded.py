"""El juez de tres niveles de la búsqueda (eval/graded.py): juicio LLM de pares, no humano."""

import json
import math

import pytest

from rappi_ia.eval import graded
from rappi_ia.eval.graded import Judged, load_judgments, pending, score, shown_lists
from rappi_ia.eval.search_eval import SHOWN, QueryRun
from rappi_ia.eval.sheets import pair_id, write_csv


def _pid(query: str, entity_id: str, vertical: str = "turbo") -> str:
    return pair_id(vertical, query, "catalog_item", entity_id)


def _judged(query: str, levels: dict[str, int]) -> dict[str, Judged]:
    return {_pid(query, eid): Judged("turbo", query, level) for eid, level in levels.items()}


def _list(query: str, ids: list[str], tipo: str = "exacta") -> dict:
    return {"vertical": "turbo", "consulta": query, "tipo": tipo, "productos": [["catalog_item", i] for i in ids]}


def test_ndcg_skips_what_has_no_judgment_and_takes_the_ideal_from_every_judged_pair():
    """Lista condensada: "x" no tiene juicio y se salta; el ideal sale de los tres pares juzgados, aunque "c" ya no se
    muestre."""
    judgments = _judged("té", {"a": 1, "b": 2, "c": 2})

    row = score([_list("té", ["a", "x", "b"])], judgments)["consultas"][0]

    dcg = 1 / math.log2(2) + 2 / math.log2(3)
    ideal = 2 / math.log2(2) + 2 / math.log2(3) + 1 / math.log2(4)
    assert row["ndcg"] == pytest.approx(dcg / ideal)
    assert (row["mostrados"], row["juzgados"]) == (3, 2)


def test_p_at_3_counts_an_empty_or_unjudged_slot_as_not_serving():
    judgments = _judged("té", {"a": 2, "b": 1})

    row = score([_list("té", ["a", "x"])], judgments)["consultas"][0]

    assert row["p@3"] == pytest.approx(1 / 3) and row["util@3"] == pytest.approx(1 / 3)


def test_only_queries_with_some_judged_pair_are_scored_and_summed_by_type():
    judgments = {**_judged("té", {"a": 2}), **_judged("café", {"b": 0})}
    lists = [_list("té", ["a"]), _list("café", ["b"], tipo="necesidad"), _list("mate", ["c"])]

    scores = score(lists, judgments)

    assert scores["total"]["n"] == 2 and set(scores["por_tipo"]) == {"exacta", "necesidad"}
    assert scores["total"]["no_sirve"] == 0.5  # uno de los dos mostrados con juicio no sirve


def test_pending_lists_each_unjudged_pair_once_and_only_for_scored_queries():
    judgments = _judged("té", {"a": 2})
    lists = [_list("té", ["a", "x", "x"]), _list("mate", ["y"])]

    assert [p["entity_id"] for p in pending(lists, judgments)] == ["x"]


def test_shown_lists_keep_the_shown_row_of_positive_queries():
    item = {"entity_type": "catalog_item", "entity_id": "a", "texto": "Té", "concepto": "te", "tienda": None}
    runs = [
        QueryRun("turbo", "té", "exacta", SHOWN, [1], 1, 0.9, True, items=[item]),
        QueryRun("turbo", "té", "exacta", "hibrido", [1], 1, 0.9, True, items=[item]),
        QueryRun("turbo", "sofá", "negativa", SHOWN, [], 0, 0.7, False),
    ]

    assert shown_lists(runs) == [_list("té", ["a"])]


def _files(tmp_path, complement: list[dict] | None = None):
    pairs = tmp_path / "ids.json"
    pairs.write_text(json.dumps({"pares": [{"id": _pid("té", "a"), "vertical": "turbo", "consulta": "té"}]}))
    llm = tmp_path / "llm.json"
    llm.write_text(json.dumps({"juicios": {_pid("té", "a"): "a medias"}}))
    extra = tmp_path / "complemento.json"
    if complement is not None:
        extra.write_text(json.dumps({"pares": complement}))
    return llm, pairs, extra


def _pair(entity_id: str, verdict: str, pid: str | None = None) -> dict:
    return {
        "id": pid or _pid("té", entity_id),
        "vertical": "turbo",
        "consulta": "té",
        "entity_type": "catalog_item",
        "entity_id": entity_id,
        "juicio": verdict,
    }


def test_judgments_join_the_llm_file_and_the_complement(tmp_path):
    judged = load_judgments(*_files(tmp_path, [_pair("b", "no sirve")]))

    assert judged == {
        _pid("té", "a"): Judged("turbo", "té", 1),
        _pid("té", "b"): Judged("turbo", "té", 0),
    }


@pytest.mark.parametrize(
    "pair",
    [_pair("a", "sirve"), _pair("b", "sirve", pid="P0000000000")],
    ids=["juzgado dos veces", "id que no corresponde"],
)
def test_a_pair_judged_twice_or_with_a_wrong_id_is_an_error(tmp_path, pair):
    with pytest.raises(ValueError):
        load_judgments(*_files(tmp_path, [pair]))


def test_import_adds_the_new_judgments_without_catalog_texts(tmp_path, monkeypatch):
    llm, _, extra = _files(tmp_path)
    monkeypatch.setattr(graded, "LLM_FILE", llm)
    sheet = tmp_path / "pendientes.csv"
    row = {"nombre": "Té verde 20 bolsitas", "categoria": "Té", "tienda": "Tienda"}
    write_csv(
        sheet,
        graded.PENDING_COLUMNS,
        [
            {**_pair("b", ""), **row, "juicio": "sirve"},
            {**_pair("a", ""), **row, "juicio": "no sirve"},  # ya juzgado el 25-10: queda como estaba
            {**_pair("c", ""), **row, "juicio": ""},  # sin juicio: no entra
        ],
    )

    assert graded.import_sheet(sheet, extra) == 1
    saved = json.loads(extra.read_text())["pares"]
    assert saved == [_pair("b", "sirve")]


def test_fully_judged_queries_are_scored_apart_and_the_report_warns_when_pairs_lack_a_judgment():
    """Un producto sin juicio cambia el total sin que la búsqueda cambie: el reporte lo dice primero y da aparte las
    consultas con todo lo mostrado juzgado."""
    judgments = {**_judged("té", {"a": 2, "b": 2}), **_judged("café", {"c": 2, "d": 2})}
    scores = score([_list("té", ["a", "b"]), _list("café", ["x", "c"])], judgments)

    assert scores["completas"]["n"] == 1 and scores["completas"]["ndcg"] == 1.0
    assert scores["total"]["ndcg"] < 1.0
    report = graded.render_markdown(scores)
    assert "**1 productos sin juicio: la cifra total no es comparable.**" in report
    assert report.index("no es comparable") < report.index("| Total |")
    assert "| Solo consultas juzgadas completas | 1 | 1.0 |" in report


def test_the_report_does_not_warn_when_everything_shown_is_judged():
    scores = score([_list("té", ["a"])], _judged("té", {"a": 2}))

    assert "no es comparable" not in graded.render_markdown(scores)


def test_ndcg_counts_only_the_first_k_places_when_asked():
    """Mochi muestra 6: con k=6 su ideal son los 6 mejores juzgados, no los 10."""
    judgments = _judged("té", {str(i): 2 for i in range(10)})

    row = score([_list("té", [str(i) for i in range(6)])], judgments, k=6)["consultas"][0]

    assert row["ndcg"] == pytest.approx(1.0)


def test_regressions_flag_a_lost_serving_product_in_the_top_three_and_fewer_products():
    judgments = _judged("té", {"a": 2, "b": 2, "c": 1, "d": 2})
    before = [_list("té", ["a", "b", "c", "d"]), _list("mate", ["m", "n"])]
    now = [_list("té", ["a", "c", "x"]), _list("mate", ["n", "m"])]

    found = graded.regressions(before, now, judgments)

    assert found == [
        'turbo "té": "sirve" entre los 3 primeros 2 → 1 (1 sin juicio: júzgalos con `rappi-ia eval-graded`)',
        'turbo "té": muestra 3 productos (antes 4)',
    ]


def test_regressions_accept_a_reorder_that_keeps_the_serving_products():
    judgments = _judged("té", {"a": 2, "b": 2, "c": 1})

    assert graded.regressions([_list("té", ["a", "b", "c"])], [_list("té", ["c", "b", "a"])], judgments) == []


def test_latest_lists_go_by_the_date_in_the_name(tmp_path):
    for name in ("antes-2026-10-25", "despues-2026-10-25", "2026-11-05", "despues-2026-09-30"):
        (tmp_path / f"tres-niveles-listas-{name}.json").write_text("{}")

    assert graded.latest_lists(tmp_path).name == "tres-niveles-listas-2026-11-05.json"
    with pytest.raises(FileNotFoundError):
        graded.latest_lists(tmp_path / "vacia")
