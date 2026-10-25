"""Piloto de Jev (roles A y B contra las planillas juzgadas), siempre con `FakeJev`."""

import json
from argparse import Namespace
from datetime import date

import pytest

from fakes.jev import FakeJev
from rappi_ia import cli, config, jev
from rappi_ia.concepts.jev_map import build_questions
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.eval import jev_pilot, sheets
from rappi_ia.eval.sheets import pair_id
from rappi_ia.jev import JevAnswer

TAXONOMY = load_taxonomy()

# Planilla A de prueba: (categoría, grupo, concepto de control, concepto que escribió la persona).
CATEGORIES = [
    ("Papas fritas", "sin_mapear", "", "snacks-salados"),
    ("Cervezas artesanales", "sin_mapear", "", "cerveza"),
    ("Analgésicos", "sin_mapear", "", "medicamentos"),
    ("Variedades", "sin_mapear", "", "ninguno"),
    ("Frutas de estación", "juez", "frutas", "frutas"),
    ("Hortalizas", "juez", "verduras", "verduras"),
    ("Manzanas", "acuerdo", "frutas", "frutas"),
    ("Lechugas", "acuerdo", "verduras", "verduras"),
]
# Lo que dice Jev por variante: (concepto, confianza, salud sensible, solo adultos).
SPANISH = {
    "Papas fritas": ("snacks-salados", 0.95, 0.05, 0.05),
    "Cervezas artesanales": ("cerveza", 0.9, 0.05, 0.95),
    "Analgésicos": ("medicamentos", 0.9, 0.95, 0.05),
    "Variedades": ("ninguno", 0.9, 0.05, 0.05),
    "Frutas de estación": ("frutas", 0.8, 0.05, 0.05),
    "Hortalizas": ("frutas", 0.7, 0.05, 0.05),  # error con confianza baja: precisión < 90 % hasta T = 0,75
    "Manzanas": ("frutas", 0.95, 0.05, 0.05),
    "Lechugas": ("verduras", 0.95, 0.05, 0.05),
}
# En inglés, los analgésicos van solos a snacks y sin que la guardia lo note: falla en todo T.
ENGLISH = SPANISH | {"Analgésicos": ("snacks-salados", 0.97, 0.1, 0.05)}

# Planilla B de prueba: (consulta, id, nivel de la persona, juez por concepto, probabilidades de Jev).
PAIRS = [
    ("cerveza", "1", 2, True, {"2": 1.0}),
    ("cerveza", "2", 2, False, {"1": 0.2, "2": 0.8}),
    ("pisco", "3", 2, True, {"1": 0.4, "2": 0.6}),
    ("pisco", "4", 0, True, {"0": 1.0}),
    ("vino", "5", 0, False, {"0": 0.8, "1": 0.2}),
    ("vino", "6", 1, False, {"1": 1.0}),
]


def jev_answer(concept, conf, health, adults) -> dict:
    return {
        "concepto": JevAnswer(choice=concept, confidence=conf, probabilities={concept: conf}),
        "mezcla": JevAnswer(noul=0.05),
        "salud_sensible": JevAnswer(noul=health),
        "solo_adultos": JevAnswer(noul=adults),
    }


SPANISH_INSTRUCTIONS = build_questions(TAXONOMY, "es")["concepto"]["instructions"]


def variant_of(questions) -> str:
    return "es" if questions["concepto"]["instructions"] == SPANISH_INSTRUCTIONS else "en"


def pilot_responder(es=SPANISH, en=ENGLISH, pairs=PAIRS, tokens=1000):
    """Responde las dos preguntas del piloto: categorías (por variante) y relevancia (por par)."""
    gains = {(q, f"Producto {i}"): probs for q, i, _, _, probs in pairs}
    fake_holder = {}

    def respond(state, questions):
        fake_holder["fake"].stats.input_tokens += tokens
        if "relevancia" in questions:
            probs = gains[(state["consulta"], state["resultado"]["nombre"])]
            return {"relevancia": JevAnswer(score=2.0, probabilities=probs, confidence=0.9)}
        table = es if variant_of(questions) == "es" else en
        return jev_answer(*table[state["categoria"]])

    fake = FakeJev(responder=respond)
    fake_holder["fake"] = fake
    return fake


def write_sheets(sheet_dir, ids_dir, categories=CATEGORIES, pairs=PAIRS, blank_categories=0, blank_pairs=0):
    """Las dos planillas llenas (con `blank_*` filas sin juicio al final) y sus ids versionados."""
    category_rows, category_ids = [], []
    for i, (name, group, control, human) in enumerate(categories):
        category_rows.append(
            {
                "vertical": "supermercado",
                "categoria": name,
                "ejemplos": f"{name} 1 | {name} 2",
                "concepto_propuesto": control,
                "concepto_correcto": "" if i >= len(categories) - blank_categories else human,
            }
        )
        category_ids.append(
            {"clave": name.lower(), "vertical": "supermercado", "grupo": group, "concepto_propuesto": control}
        )
    sheets.write_csv(sheet_dir / sheets.CATEGORY_SHEET, sheets.CATEGORY_COLUMNS, category_rows)
    sheets.write_json(ids_dir / sheets.CATEGORY_IDS_FILE.name, {"semilla": 7, "categorias": category_ids})

    verdicts = {level: word for word, level in sheets.VERDICTS.items()}
    search_rows, search_ids = [], []
    for i, (query, entity_id, human, auto, _) in enumerate(pairs):
        pid = pair_id("licores", query, "catalog_item", entity_id)
        search_rows.append(
            {
                "id": pid,
                "consulta": query,
                "vertical": "licores",
                "posicion": i + 1,
                "nombre": f"Producto {entity_id}",
                "categoria": "",
                "tienda": "Botillería",
                "juicio": "" if i >= len(pairs) - blank_pairs else verdicts[human],
            }
        )
        search_ids.append(
            {
                "id": pid,
                "vertical": "licores",
                "consulta": query,
                "tipo": "directa",
                "posicion": i + 1,
                "estrato": "top3" if i < 3 else "4-10",
                "relevante_auto": auto,
                "discrepa": False,
                "entity_type": "catalog_item",
                "entity_id": entity_id,
            }
        )
    sheets.write_csv(sheet_dir / sheets.SEARCH_SHEET, sheets.SEARCH_COLUMNS, search_rows)
    sheets.write_json(ids_dir / sheets.SEARCH_IDS_FILE.name, {"semilla": 7, "pares": search_ids})


@pytest.fixture
def dirs(tmp_path):
    sheet_dir, ids_dir = tmp_path / "data" / "eval", tmp_path / "ids"
    sheet_dir.mkdir(parents=True)
    ids_dir.mkdir()
    return Namespace(tmp=tmp_path, sheets=sheet_dir, ids=ids_dir, proposal=tmp_path / "jev-adopcion.propuesta.json")


def run(db, dirs, fake, **kwargs):
    return jev_pilot.run_pilot(
        db, fake, TAXONOMY, sheet_dir=dirs.sheets, ids_dir=dirs.ids, proposal_path=dirs.proposal, **kwargs
    )


# --- requisitos ------------------------------------------------------------------------------------------------------


def test_requirements_list_everything_that_is_missing(dirs):
    blocking, warnings = jev_pilot.requirements(False, sheet_dir=dirs.sheets, ids_dir=dirs.ids)

    text = "\n".join(blocking)
    assert "TYPESAFE_API_KEY" in text
    assert sheets.CATEGORY_SHEET in text and sheets.SEARCH_SHEET in text
    assert "jev-planillas" in text
    assert warnings == []


def test_requirements_count_what_is_left_to_judge(dirs):
    write_sheets(dirs.sheets, dirs.ids, blank_categories=2, blank_pairs=1)  # 6 de 8 y 5 de 6: bajo el 90 %

    blocking, _ = jev_pilot.requirements(True, sheet_dir=dirs.sheets, ids_dir=dirs.ids)

    assert len(blocking) == 2
    assert "2 de 8" in blocking[0] and sheets.CATEGORY_SHEET in blocking[0] and "8 de 8" in blocking[0]
    assert "1 de 6" in blocking[1] and sheets.SEARCH_SHEET in blocking[1] and "6 de 6" in blocking[1]


def test_requirements_pass_with_key_and_judged_sheets(dirs):
    write_sheets(dirs.sheets, dirs.ids)
    assert jev_pilot.requirements(True, sheet_dir=dirs.sheets, ids_dir=dirs.ids) == ([], [])


def full_size_sheets(dirs, blank_categories=0, blank_pairs=0):
    """Del tamaño real: 100 categorías y 200 pares."""
    categories = [(f"Categoría {i}", "sin_mapear", "", "frutas") for i in range(100)]
    pairs = [(f"consulta {i}", str(i), 2, True, {"2": 1.0}) for i in range(200)]
    write_sheets(dirs.sheets, dirs.ids, categories, pairs, blank_categories, blank_pairs)


def test_ninety_percent_judged_runs_with_a_warning(dirs):
    full_size_sheets(dirs, blank_categories=10, blank_pairs=20)

    blocking, warnings = jev_pilot.requirements(True, sheet_dir=dirs.sheets, ids_dir=dirs.ids)

    assert blocking == []
    assert len(warnings) == 2
    assert "faltaron 10 de 100 por juzgar; las cifras usan las juzgadas" in warnings[0]
    assert "faltaron 20 de 200 por juzgar; las cifras usan las juzgadas" in warnings[1]


@pytest.mark.parametrize(("blank_categories", "blank_pairs"), [(11, 0), (0, 21)])
def test_less_than_ninety_percent_judged_blocks(dirs, blank_categories, blank_pairs):
    full_size_sheets(dirs, blank_categories, blank_pairs)

    blocking, warnings = jev_pilot.requirements(True, sheet_dir=dirs.sheets, ids_dir=dirs.ids)

    assert len(blocking) == 1 and warnings == []
    assert ("90 de 100" if blank_categories else "180 de 200") in blocking[0]


def test_an_old_ids_file_without_entities_asks_to_regenerate(dirs):
    write_sheets(dirs.sheets, dirs.ids)
    path = dirs.ids / sheets.SEARCH_IDS_FILE.name
    document = json.loads(path.read_text(encoding="utf-8"))
    for entry in document["pares"]:
        del entry["entity_type"], entry["entity_id"]
    path.write_text(json.dumps(document), encoding="utf-8")

    blocking, _ = jev_pilot.requirements(True, sheet_dir=dirs.sheets, ids_dir=dirs.ids)

    assert len(blocking) == 1 and "rappi-ia jev-planillas" in blocking[0]


def test_cli_without_key_lists_what_is_missing_and_does_not_call_jev(db, dirs, monkeypatch, capsys):
    monkeypatch.setattr(config, "DATA_DIR", dirs.tmp / "data")
    monkeypatch.setattr(sheets, "EVAL_DIR", dirs.ids)
    write_sheets(dirs.sheets, dirs.ids, blank_pairs=6)
    monkeypatch.setattr(jev, "client_or_none", lambda: None)
    called = []
    monkeypatch.setattr(jev_pilot, "run_pilot", lambda *a, **k: called.append(1))

    cli.cmd_jev_piloto(db, Namespace())  # sale sin error: no hay nada roto, solo falta algo

    out = capsys.readouterr().out
    assert "TYPESAFE_API_KEY" in out and "6 de 6" in out
    assert called == [] and not (dirs.sheets / jev_pilot.REPORT_NAME).exists()


# --- rol A: categorías -----------------------------------------------------------------------------------------------


def test_category_metrics_per_threshold(dirs):
    write_sheets(dirs.sheets, dirs.ids)
    rows = jev_pilot.load_category_rows(dirs.sheets, dirs.ids)
    answers = [jev_answer(*SPANISH[r["state"]["categoria"]]) for r in rows]

    low = jev_pilot.category_metrics(rows, answers, TAXONOMY, 0.6)
    high = jev_pilot.category_metrics(rows, answers, TAXONOMY, 0.75)

    assert low["mapeadas"] == 7 and low["precision"] == pytest.approx(6 / 7)
    assert low["cobertura"] == pytest.approx(3 / 4) and low["control"] == 1.0 and low["sensibles"] == 0
    assert high["mapeadas"] == 6 and high["precision"] == 1.0 and high["cobertura"] == pytest.approx(3 / 4)


def test_state_is_what_the_person_saw(dirs):
    write_sheets(dirs.sheets, dirs.ids)
    row = jev_pilot.load_category_rows(dirs.sheets, dirs.ids)[0]
    assert set(row["state"]) == {"vertical", "categoria", "ejemplos"}
    assert row["state"]["ejemplos"] == [f"{row['state']['categoria']} 1", f"{row['state']['categoria']} 2"]


def test_a_sensitive_category_mapped_alone_to_a_plain_concept_is_counted(dirs):
    write_sheets(dirs.sheets, dirs.ids)
    rows = jev_pilot.load_category_rows(dirs.sheets, dirs.ids)
    answers = [jev_answer(*ENGLISH[r["state"]["categoria"]]) for r in rows]

    metrics = jev_pilot.category_metrics(rows, answers, TAXONOMY, 0.95)

    assert metrics["sensibles"] == 1
    assert not jev_pilot.category_criteria(metrics)["sensibles"]


def test_a_failed_answer_counts_as_not_mapped(dirs):
    write_sheets(dirs.sheets, dirs.ids)
    rows = jev_pilot.load_category_rows(dirs.sheets, dirs.ids)
    answers = [None for _ in rows]

    metrics = jev_pilot.category_metrics(rows, answers, TAXONOMY, 0.6)

    assert metrics["mapeadas"] == 0 and metrics["cobertura"] == 0.0
    assert metrics["precision"] is None and metrics["control"] is None
    assert not any(jev_pilot.category_criteria(metrics)[name] for name in ("precision", "cobertura", "control"))


GOOD = {"precision": 0.95, "cobertura": 0.6, "control": 0.95, "sensibles": 0}


@pytest.mark.parametrize(
    ("change", "failed"),
    [
        ({}, None),
        ({"precision": 0.89}, "precision"),
        ({"precision": None}, "precision"),
        ({"cobertura": 0.49}, "cobertura"),
        ({"control": 0.85}, "control"),
        ({"control": None}, "control"),
        ({"sensibles": 1}, "sensibles"),
    ],
)
def test_each_category_criterion_passes_and_fails(change, failed):
    result = jev_pilot.category_criteria(GOOD | change)
    assert {name for name, ok in result.items() if not ok} == ({failed} if failed else set())


def test_exact_targets_pass():
    exact = {"precision": 0.9, "cobertura": 0.5, "control": 0.9, "sensibles": 0}
    assert all(jev_pilot.category_criteria(exact).values())


def test_t_auto_is_the_smallest_threshold_that_meets_everything(dirs):
    write_sheets(dirs.sheets, dirs.ids)
    rows = jev_pilot.load_category_rows(dirs.sheets, dirs.ids)

    spanish = jev_pilot.evaluate_variant(rows, [jev_answer(*SPANISH[r["state"]["categoria"]]) for r in rows], TAXONOMY)
    english = jev_pilot.evaluate_variant(rows, [jev_answer(*ENGLISH[r["state"]["categoria"]]) for r in rows], TAXONOMY)

    assert [t for t, _ in [(m["t"], m) for m in spanish["umbrales"]]] == list(jev_pilot.THRESHOLDS)
    assert spanish["t_auto"] == 0.75
    assert english["t_auto"] is None
    assert jev_pilot.choose_variant({"es": spanish, "en": english}) == "es"
    assert jev_pilot.choose_variant({"es": english, "en": spanish}) == "en"
    assert jev_pilot.choose_variant({"es": english, "en": english}) is None


def test_thresholds_grid():
    assert jev_pilot.THRESHOLDS == (0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95)


# --- rol B: juez -----------------------------------------------------------------------------------------------------


def test_jev_says_sirve_from_an_expected_gain_of_three_quarters():
    assert [jev_pilot.jev_level(g) for g in (0.0, 0.24, 0.25, 0.5, 0.74, 0.75, 1.0)] == [0, 0, 1, 1, 1, 2, 2]


def test_judge_kappas_against_people(dirs):
    write_sheets(dirs.sheets, dirs.ids)
    pairs, human = jev_pilot.load_search_pairs(dirs.sheets, dirs.ids)
    gains = {pair_id("licores", q, "catalog_item", i): probs for q, i, _, _, probs in PAIRS}
    from rappi_ia.eval.judge import JevJudgment, expected_gain

    judgments = {key: JevJudgment(expected_gain(p), p) for key, p in gains.items()}

    result = jev_pilot.judge_kappas(pairs, human, judgments)

    assert result["n"] == 6
    assert result["kappa_jev"] == 1.0 and result["kappa_ponderado_jev"] == 1.0
    assert result["kappa_concepto"] == pytest.approx(0.333, abs=1e-3)
    assert all(jev_pilot.judge_criteria(result).values())


def test_pairs_jev_did_not_judge_are_left_out_for_both_judges(dirs):
    write_sheets(dirs.sheets, dirs.ids)
    pairs, human = jev_pilot.load_search_pairs(dirs.sheets, dirs.ids)
    from rappi_ia.eval.judge import JevJudgment

    only = pair_id("licores", "cerveza", "catalog_item", "1")
    result = jev_pilot.judge_kappas(pairs, human, {only: JevJudgment(1.0, {})})

    assert result["n"] == 1 and result["sin_juicio_jev"] == 5


@pytest.mark.parametrize(
    ("kappas", "failed"),
    [
        ({"kappa_jev": 0.7, "kappa_concepto": 0.5}, set()),
        ({"kappa_jev": 0.6, "kappa_concepto": 0.5}, set()),
        ({"kappa_jev": 0.59, "kappa_concepto": 0.3}, {"kappa_minimo"}),
        ({"kappa_jev": 0.7, "kappa_concepto": 0.7}, {"mejor_que_concepto"}),
        ({"kappa_jev": 0.5, "kappa_concepto": 0.8}, {"kappa_minimo", "mejor_que_concepto"}),
        ({"kappa_jev": None, "kappa_concepto": None}, {"kappa_minimo", "mejor_que_concepto"}),
    ],
)
def test_each_judge_criterion_passes_and_fails(kappas, failed):
    result = jev_pilot.judge_criteria(kappas)
    assert {name for name, ok in result.items() if not ok} == failed


# --- corrida completa ------------------------------------------------------------------------------------------------


def test_pilot_writes_report_and_proposal(db, dirs, monkeypatch):
    monkeypatch.setattr(config, "JEV_PRICE_PER_MTOK_INPUT", 0.05)
    write_sheets(dirs.sheets, dirs.ids)
    fake = pilot_responder()

    result = run(db, dirs, fake, today=date(2026, 10, 11))

    # 8 categorías × 2 variantes + 6 pares
    assert fake.stats.requests == 22 and fake.stats.input_tokens == 22_000
    assert result["categorias"]["variante"] == "es" and result["categorias"]["t_auto"] == 0.75
    assert result["juez"]["pasa"] is True
    proposal = json.loads(dirs.proposal.read_text(encoding="utf-8"))
    assert proposal == {
        "categorias": True,
        "juez": True,
        "t_auto": 0.75,
        "variante": "es",
        "model_version": fake.model,
        "fecha": "2026-10-11",
    }
    report = (dirs.sheets / jev_pilot.REPORT_NAME).read_text(encoding="utf-8")
    assert "22 llamadas" in report and "22.000 tokens" in report
    assert "US$ 0,0011" in report  # 22.000 tokens × 0,05 US$ por millón
    assert "T_auto = 0,75" in report and "variante «es»" in report
    assert "Mochi" not in report and "chat" not in report.lower()


def test_the_proposal_once_renamed_is_what_map_categories_reads(db, dirs):
    write_sheets(dirs.sheets, dirs.ids)
    run(db, dirs, pilot_responder(es=ENGLISH, en=SPANISH))

    adoption = jev.load_adoption(dirs.proposal)

    assert adoption.categorias and adoption.juez
    assert adoption.t_auto == 0.75 and adoption.variante == "en"


def test_a_failing_pilot_proposes_nothing(db, dirs):
    write_sheets(dirs.sheets, dirs.ids)
    flat = [(q, i, h, a, {"1": 1.0}) for q, i, h, a, _ in PAIRS]  # Jev siempre «a medias»: nunca dice «sirve»

    result = run(db, dirs, pilot_responder(es=ENGLISH, en=ENGLISH, pairs=flat))

    proposal = json.loads(dirs.proposal.read_text(encoding="utf-8"))
    assert proposal["categorias"] is False and proposal["juez"] is False
    assert proposal["t_auto"] == jev.DEFAULT_T_AUTO and proposal["variante"] == "es"
    assert result["categorias"]["variante"] is None
    report = (dirs.sheets / jev_pilot.REPORT_NAME).read_text(encoding="utf-8")
    assert "No se propone" in report


def test_report_starts_with_a_plain_result_and_a_glossary(db, dirs):
    write_sheets(dirs.sheets, dirs.ids)
    run(db, dirs, pilot_responder())

    report = (dirs.sheets / jev_pilot.REPORT_NAME).read_text(encoding="utf-8")

    result = report[: report.index("## Rol A")]
    assert "## Resultado" in result and "## Glosario" in result
    assert "Categorías: sí" in result and "Juez: sí" in result
    assert "renombra eval/jev-adopcion.propuesta.json a eval/jev-adopcion.json y súbelo" in result
    for term in ("κ", "T_auto", "ganancia esperada", "guardias"):
        assert term.lower() in result.lower()


def test_a_report_without_adoption_says_nothing_changes(db, dirs):
    write_sheets(dirs.sheets, dirs.ids)
    flat = [(q, i, h, a, {"1": 1.0}) for q, i, h, a, _ in PAIRS]
    run(db, dirs, pilot_responder(es=ENGLISH, en=ENGLISH, pairs=flat))

    report = (dirs.sheets / jev_pilot.REPORT_NAME).read_text(encoding="utf-8")

    result = report[: report.index("## Rol A")]
    assert "Categorías: no" in result and "Juez: no" in result
    assert "no se adopta: todo sigue igual sin Jev" in result


def test_partial_sheets_run_and_the_report_says_what_was_missing(db, dirs):
    extra = [("ron", str(i), 0, False, {"0": 1.0}) for i in range(7, 11)]  # 10 pares: uno sin juzgar es el 90 %
    write_sheets(dirs.sheets, dirs.ids, pairs=PAIRS + extra, blank_pairs=1)
    fake = pilot_responder(pairs=PAIRS + extra)

    result = run(db, dirs, fake)

    assert fake.stats.requests == 16 + 9  # el par sin juicio de la persona no se le pide a Jev
    assert result["juez"]["n"] == 9
    report = (dirs.sheets / jev_pilot.REPORT_NAME).read_text(encoding="utf-8")
    assert "faltaron 1 de 10 por juzgar; las cifras usan las juzgadas" in report


def test_hitting_the_call_cap_proposes_nothing(db, dirs):
    write_sheets(dirs.sheets, dirs.ids)
    fake = pilot_responder()
    fake.stats.stopped_by_cap = True

    result = run(db, dirs, fake)

    proposal = json.loads(dirs.proposal.read_text(encoding="utf-8"))
    assert proposal["categorias"] is False and proposal["juez"] is False
    assert result["categorias"]["pasa"] and result["juez"]["pasa"]  # las cifras pasaban, pero no son confiables
    assert "JEV_MAX_REQUESTS" in (dirs.sheets / jev_pilot.REPORT_NAME).read_text(encoding="utf-8")


def test_too_many_unanswered_questions_propose_nothing(db, dirs):
    write_sheets(dirs.sheets, dirs.ids)
    fake = pilot_responder()
    answer = fake.responder

    def flaky(state, questions):  # 1 de 8 categorías sin respuesta en español: 87,5 % < 90 %
        if "categoria" in state and state["categoria"] == "Hortalizas" and variant_of(questions) == "es":
            return None
        return answer(state, questions)

    fake.responder = flaky

    run(db, dirs, fake)

    proposal = json.loads(dirs.proposal.read_text(encoding="utf-8"))
    assert proposal["categorias"] is False and proposal["juez"] is False
    report = (dirs.sheets / jev_pilot.REPORT_NAME).read_text(encoding="utf-8")
    assert "Jev respondió 7 de 8" in report


def test_judge_answers_are_cached_for_the_next_run(db, dirs):
    write_sheets(dirs.sheets, dirs.ids)
    run(db, dirs, pilot_responder())

    again = pilot_responder()
    run(db, dirs, again)

    assert again.stats.requests == 16  # solo las categorías: los 6 pares salen de eval_judgments


def test_estimated_cost():
    assert jev_pilot.estimated_cost(2_000_000, 0.042) == pytest.approx(0.084)
    assert jev_pilot.estimated_cost(0, 0.042) == 0


def test_cli_runs_the_pilot_with_key_and_sheets(db, dirs, monkeypatch, capsys):
    monkeypatch.setattr(config, "DATA_DIR", dirs.tmp / "data")
    monkeypatch.setattr(sheets, "EVAL_DIR", dirs.ids)
    monkeypatch.setattr(jev_pilot, "PROPOSAL_FILE", dirs.proposal)
    write_sheets(dirs.sheets, dirs.ids)
    fake = pilot_responder()
    monkeypatch.setattr(jev, "client_or_none", lambda: fake)

    cli.cmd_jev_piloto(db, Namespace())

    out = capsys.readouterr().out
    assert jev_pilot.REPORT_NAME in out and dirs.proposal.name in out and "jev-adopcion.json" in out
    assert "T_auto 0,75" in out and "κ Jev 1,000" in out and "22.000 tokens" in out and "US$ 0,0009" in out
    assert dirs.proposal.exists()
    db.rollback()  # el comando confirmó los juicios en caché
    assert db.execute("SELECT count(*) FROM eval_judgments WHERE judge = 'jev'").fetchone()[0] == 6
