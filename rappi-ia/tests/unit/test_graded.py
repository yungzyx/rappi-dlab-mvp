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
    """Lista condensada: «x» no tiene juicio y se salta; el ideal sale de los tres pares juzgados, aunque «c» ya no se
    muestre."""
    judgments = _judged("té", {"a": 1, "b": 2, "c": 2})

    row = score([_list("té", ["a", "x", "b"])], judgments)["consultas"][0]

    dcg = 1 / math.log2(2) + 2 / math.log2(3)
    ideal = 2 / math.log2(2) + 2 / math.log2(3) + 1 / math.log2(4)
    assert row["ndcg@10"] == pytest.approx(dcg / ideal)
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
