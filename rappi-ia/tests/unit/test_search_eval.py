from types import SimpleNamespace

from rappi_ia.eval import search_eval
from rappi_ia.eval.search_eval import (
    ABLATION,
    SHOWN,
    QueryRun,
    calibrate_tau,
    negative_diagnosis,
    paired_comparison,
    render_markdown,
    run_queries,
    summarize,
    thresholds_after_saving,
    unmet_quality,
)


def run(query, tipo, cosine, vertical="licores", strict=0, names_concept=False, in_vertical=False, names_occasion=True):
    """Por defecto la consulta nombra una ocasión: sin concepto, es el caso en que decide el τ de la vertical."""
    run = QueryRun(vertical, query, tipo, "hibrido", [1] * 10, strict, cosine, in_vertical, names_concept)
    run.names_occasion = names_occasion
    return run


def test_calibrate_tau_ignores_negatives_that_do_not_depend_on_tau():
    """Negativas que cortan por coincidencia léxica o por concepto nombrado dan el mismo recall con cualquier τ:
    no hay nada que calibrar (antes devolvía 0,70, el primer candidato de la grilla)."""
    runs = [
        run("pañales", "negativa", 0.95, strict=3),
        run("zapatillas", "negativa", 0.80, names_concept=True),
        run("pisco", "exacta", 0.93),
    ]
    assert calibrate_tau(runs) == {}


def test_calibrate_tau_proposes_nothing_when_no_tau_detects_a_negative():
    runs = [run("neumáticos", "negativa", 0.99), run("pisco", "exacta", 0.93)]
    assert calibrate_tau(runs) == {}


def test_calibrate_tau_breaks_ties_with_the_lowest_tau():
    """Entre 0,76 y 0,90 todos detectan la negativa sin falsas alarmas: se elige el más prudente."""
    runs = [run("neumáticos", "negativa", 0.75), run("pisco", "exacta", 0.90)]
    assert calibrate_tau(runs) == {"licores": 0.76}


def test_calibrate_tau_accepts_one_false_alarm_in_ten():
    """Con τ = 0,86 detecta las 10 negativas y marca una positiva: precisión 10/11 ≥ 0,9, recall 1."""
    negatives = [run(f"neg {i}", "negativa", 0.71 + 0.01 * i) for i in range(9)] + [run("neg 9", "negativa", 0.85)]
    assert calibrate_tau([*negatives, run("pisco", "exacta", 0.80)]) == {"licores": 0.86}


def test_report_shows_current_and_proposed_tau_per_vertical():
    runs = [run("neumáticos", "negativa", 0.75), run("pisco", "exacta", 0.90)]
    current = {"licores": 0.7, "mall": 0.7}
    proposed = calibrate_tau(runs)
    report = render_markdown(summarize(runs), unmet_quality(runs, current), current, proposed, saved=False, model="e5")
    assert "| licores | 0.7 | 0.76 |" in report
    assert "| mall | 0.7 | sin propuesta |" in report
    assert "ningún τ entre 0,70 y 0,95" in report
    assert "con los τ vigentes" in report


def test_each_negative_says_why_it_was_or_was_not_detected():
    runs = [
        run("iphone 15 pro max", "negativa", 0.84, vertical="supermercado", strict=4),
        run("neumáticos", "negativa", 0.83),
        run("sofá", "negativa", 0.79),
        run("pizza familiar", "negativa", 0.90, vertical="mall", names_concept=True, in_vertical=True),
        run("palta hass", "negativa", 0.90, vertical="mall", names_concept=True, in_vertical=False),
        run("pisco", "exacta", 0.95),
    ]

    rows = {r["consulta"]: r for r in negative_diagnosis(runs, {"licores": 0.8})}

    assert set(rows) == {"iphone 15 pro max", "neumáticos", "sofá", "pizza familiar", "palta hass"}
    assert rows["iphone 15 pro max"] == {
        "vertical": "supermercado",
        "consulta": "iphone 15 pro max",
        "detectada": False,
        "causa": "4 coincidencias léxicas estrictas",
        "desactualizada": True,  # con 3 o más, probablemente el catálogo ya lo tiene
    }
    assert (rows["neumáticos"]["detectada"], rows["neumáticos"]["causa"]) == (False, "coseno 0.830 ≥ τ 0.8")
    assert (rows["sofá"]["detectada"], rows["sofá"]["causa"]) == (True, "coseno 0.790 < τ 0.8")
    assert rows["pizza familiar"]["causa"] == "el concepto nombrado está en el vertical"
    palta = rows["palta hass"]
    assert (palta["detectada"], palta["causa"]) == (True, "el concepto nombrado no está en el vertical")
    assert not rows["neumáticos"]["desactualizada"]
    one = negative_diagnosis([run("leche en polvo", "negativa", 0.9, strict=1)], {})
    assert one[0]["causa"] == "1 coincidencia léxica estricta"


def test_a_query_without_words_is_never_unmet_and_does_not_calibrate_tau():
    """Misma regla que la búsqueda: «té» es stopword y no se marca por coseno. Si contara, una positiva así parecería
    una falsa alarma y empujaría τ (aquí no habría propuesta)."""
    tea = QueryRun("licores", "té", "exacta", "hibrido", [1] * 10, 0, 0.75, False, has_words=False)
    runs = [tea, run("neumáticos", "negativa", 0.80)]

    assert calibrate_tau(runs) == {"licores": 0.81}
    assert unmet_quality(runs, {"licores": 0.81})["falsas_alarmas"] == 0
    stopwords = QueryRun("licores", "de la", "negativa", "hibrido", [], 0, 0.7, False, has_words=False)
    assert negative_diagnosis([stopwords], {})[0] | {"vertical": None} == {
        "vertical": None,
        "consulta": "de la",
        "detectada": False,
        "causa": "sin palabras que buscar (solo stopwords)",
        "desactualizada": False,
    }


def test_run_queries_keeps_whether_the_query_had_words(monkeypatch):
    monkeypatch.setattr(search_eval, "retrieve", lambda *args, **kwargs: _result(has_words=False))
    outcome = SimpleNamespace(result=_result(has_words=False), products=[])
    monkeypatch.setattr(search_eval, "search_products", lambda *args, **kwargs: outcome)
    queries = [{"vertical": "licores", "query": "té", "concepts": ["te"], "tipo": "exacta"}]

    assert {r.has_words for r in run_queries(None, object(), queries)} == {False}


def test_without_concept_or_occasion_the_tau_of_the_vertical_does_not_decide():
    """Como la búsqueda: sin concepto ni ocasión decide el τ de la búsqueda agrupada (0,85). Esas consultas no calibran
    el τ de la vertical, que solo decide en las que nombran una ocasión."""
    sofa = run("sofá de tres cuerpos", "negativa", 0.821, vertical="turbo", names_occasion=False)
    runs = [
        sofa,
        run("cuchuflis", "exacta", 0.86, vertical="turbo", names_occasion=False),
        run("regalo para mi polola", "exacta", 0.80, vertical="turbo"),
    ]
    taus = {"turbo": 0.79}

    assert calibrate_tau(runs) == {}
    quality = unmet_quality(runs, taus)
    assert (quality["detectadas"], quality["falsas_alarmas"]) == (1, 0)
    assert negative_diagnosis([sofa], taus) == [
        {
            "vertical": "turbo",
            "consulta": "sofá de tres cuerpos",
            "detectada": True,
            "causa": "sin concepto ni ocasión: coseno 0.821 < τ 0.85",
            "desactualizada": False,
        }
    ]


def test_run_queries_keeps_whether_the_query_names_an_occasion(monkeypatch):
    monkeypatch.setattr(search_eval, "retrieve", lambda *args, **kwargs: _result(names_occasion=True))
    outcome = SimpleNamespace(result=_result(names_occasion=True), products=[])
    monkeypatch.setattr(search_eval, "search_products", lambda *args, **kwargs: outcome)
    queries = [{"vertical": "mall", "query": "regalo para mi polola", "concepts": ["joyeria"], "tipo": "necesidad"}]

    assert {r.names_occasion for r in run_queries(None, object(), queries)} == {True}


def test_report_lists_the_cause_of_each_negative():
    runs = [run("neumáticos", "negativa", 0.83), run("pisco", "exacta", 0.95)]
    taus = {"licores": 0.8}
    report = render_markdown(summarize(runs), unmet_quality(runs, taus), taus, {}, saved=False, model="e5")
    assert "| licores | neumáticos | no | coseno 0.830 ≥ τ 0.8 |" in report


def _result(hits=(), unmet=False, query_concepts=(), has_words=True, names_occasion=False):
    return SimpleNamespace(
        hits=list(hits),
        strict_lexical_matches=0,
        max_cosine=0.9,
        concept_in_vertical=True,
        query_concepts=list(query_concepts),
        unmet=unmet,
        has_words=has_words,
        names_occasion=names_occasion,
    )


def _hit(entity_id, concept):
    return SimpleNamespace(
        entity_type="catalog_item", entity_id=entity_id, content=f"Ítem {entity_id}", concept_id=concept
    )


def _product(entity_id, concept):
    return SimpleNamespace(
        entity_type="catalog_item", entity_id=entity_id, name=f"Ítem {entity_id}", concept=concept, store=None
    )


def test_ablation_runs_hybrid_without_the_concept_bonus(monkeypatch):
    """El refuerzo reordena con la misma etiqueta con que se juzga: la ablación mide la búsqueda sin él."""
    calls = []

    def fake_retrieve(conn, vertical, query, embedder, k, mode, concepts=None):
        calls.append((mode, concepts))
        return _result()

    monkeypatch.setattr(search_eval, "retrieve", fake_retrieve)
    monkeypatch.setattr(
        search_eval, "search_products", lambda *args, **kwargs: SimpleNamespace(result=_result(), products=[])
    )
    query = {"vertical": "licores", "query": "pisco", "concepts": ["pisco"], "tipo": "exacta"}

    runs = run_queries(None, object(), [query])

    assert [r.mode for r in runs] == ["lexico", "vector", "hibrido", ABLATION, SHOWN]
    assert calls[-1] == ("hibrido", [])


def test_shown_row_judges_the_products_the_user_sees(monkeypatch):
    """`retrieve` traía 10 alfajores (galletas), pero _focus se quedaba con el único de golosinas, el concepto que
    la consulta detectaba: la evaluación daba nDCG 1 y el usuario veía 1 producto. La fila «mostrado» lo mide."""
    hits = [_hit(str(i), "galletas") for i in range(9)] + [_hit("9", "golosinas")]
    calls = []

    def fake_search_products(conn, vertical, query, concepts, embedder, k, correct=False):
        calls.append((vertical, query, concepts, k, correct))
        return SimpleNamespace(
            result=_result(hits, query_concepts=["golosinas"]), products=[_product("9", "golosinas")]
        )

    monkeypatch.setattr(search_eval, "retrieve", lambda *args, **kwargs: _result(hits, query_concepts=["golosinas"]))
    monkeypatch.setattr(search_eval, "search_products", fake_search_products)
    query = {"vertical": "chocolateria", "query": "alfajores", "concepts": ["galletas", "golosinas"], "tipo": "exacta"}

    runs = {r.mode: r for r in run_queries(None, object(), [query])}

    # Como /search: la consulta detecta sus conceptos y, si nada calza, se corrigen los errores de tipeo.
    assert calls == [("chocolateria", "alfajores", None, 10, True)]
    assert runs["hibrido"].relevance == [1] * 10
    assert runs[SHOWN].relevance == [1]
    assert runs[SHOWN].items == [
        {"entity_type": "catalog_item", "entity_id": "9", "texto": "Ítem 9", "concepto": "golosinas", "tienda": None}
    ]
    summary = summarize(list(runs.values()))
    assert summary[SHOWN]["total"]["ndcg@10"] < summary["hibrido"]["total"]["ndcg@10"] == 1.0
    report = render_markdown(summary, unmet_quality(list(runs.values()), {}), {}, {}, saved=False, model="e5")
    assert f"| {SHOWN} | 0.1 |" in report


def test_shown_unmet_follows_the_agent_rule(monkeypatch):
    """Mochi registra «sin resultado» solo si no muestra productos: con la búsqueda marcándolo y productos a la
    vista (las arenas para gato de «pasaje de avión»), no cuenta. Por síntomas tampoco: los medicamentos se ocultan
    por la regla 6d, no por falta de surtido («tengo tos» era una falsa alarma que Mochi no anota)."""
    outcomes = {
        "pasaje de avión": SimpleNamespace(result=_result(unmet=True), products=[_product("1", "accesorios-mascota")]),
        "neumáticos": SimpleNamespace(result=_result(unmet=True), products=[]),
        "pisco": SimpleNamespace(result=_result(), products=[]),
        "tengo tos": SimpleNamespace(result=_result(unmet=True), products=[]),
        "me siento mal": SimpleNamespace(result=_result(unmet=True), products=[]),
    }
    monkeypatch.setattr(search_eval, "retrieve", lambda *args, **kwargs: _result())
    monkeypatch.setattr(search_eval, "search_products", lambda conn, v, query, *args, **kwargs: outcomes[query])
    queries = [{"vertical": "supermercado", "query": q, "concepts": [], "tipo": "negativa"} for q in outcomes]

    shown = {r.query: r.shown_unmet for r in run_queries(None, object(), queries) if r.mode == SHOWN}

    assert shown == {
        "pasaje de avión": False,
        "neumáticos": True,
        "pisco": False,
        "tengo tos": False,
        "me siento mal": False,
    }


def test_report_measures_unmet_as_the_agent_records_it():
    hybrid = [
        run("pasaje de avión", "negativa", 0.79),
        run("neumáticos", "negativa", 0.75),
        run("pisco", "exacta", 0.9),
    ]
    shown = [
        QueryRun("licores", "pasaje de avión", "negativa", SHOWN, [0] * 6, 0, 0.79, False, shown_unmet=False),
        QueryRun("licores", "neumáticos", "negativa", SHOWN, [], 0, 0.75, False, shown_unmet=True),
        QueryRun("licores", "pisco", "exacta", SHOWN, [1] * 6, 0, 0.9, False, shown_unmet=False),
    ]
    taus = {"licores": 0.8}

    quality = unmet_quality([*hybrid, *shown], taus)

    assert (quality["detectadas"], quality["recall"]) == (2, 1.0)  # la búsqueda (retrieve) detecta las dos
    assert (quality["mostrado"]["detectadas"], quality["mostrado"]["recall"]) == (1, 0.5)
    assert quality["mostrado"]["no_detectadas_detalle"] == ["licores: pasaje de avión"]
    report = render_markdown(summarize([*hybrid, *shown]), quality, taus, {}, saved=False, model="e5")
    assert "Lo que registra el agente" in report
    assert "detectadas: 1 · falsas alarmas: 0 · precisión: 1.0 · recall: 0.5" in report
    assert "- La búsqueda las marca, pero se muestran productos: licores: pasaje de avión" in report


def test_saving_tau_does_not_blame_the_shown_products_for_the_new_tau():
    """Con --guardar-tau la calidad se mide con los τ guardados, pero «mostrado» se corrió con los vigentes: con 0,70
    la búsqueda no marcaba «pasaje de avión» (coseno 0,81) y el reporte decía que la marcaba y se mostraban
    productos, porque comparaba contra el 0,82 recién guardado."""
    hybrid = [run("pasaje de avión", "negativa", 0.81, vertical="mall"), run("regalo", "exacta", 0.9, vertical="mall")]
    shown = [
        QueryRun("mall", "pasaje de avión", "negativa", SHOWN, [0] * 6, 0, 0.81, False, shown_unmet=False),
        QueryRun("mall", "regalo", "exacta", SHOWN, [1] * 6, 0, 0.9, False, shown_unmet=False),
    ]
    current, saved = {"mall": 0.7}, {"mall": 0.82}

    quality = unmet_quality([*hybrid, *shown], saved, run_taus=current)
    report = render_markdown(summarize([*hybrid, *shown]), quality, current, saved, saved=True, model="e5")

    assert quality["detectadas"] == 1  # con el τ guardado, la búsqueda sí la marca
    assert "se muestran productos" not in report


def test_report_warns_when_a_current_tau_sits_on_the_floor_of_the_grid():
    """Con τ = 0,70 (el mínimo de la grilla) la regla del coseno no se dispara: los cosenos e5 están sobre 0,76.
    Un vertical sin propuesta lo conserva, así que el reporte lo advierte (sin cambiarlo)."""
    runs = [run("neumáticos", "negativa", 0.75), run("pisco", "exacta", 0.90)]
    current = {"chocolateria": 0.7, "licores": 0.82, "mall": 0.7}

    report = render_markdown(summarize(runs), unmet_quality(runs, current), current, {}, saved=False, model="e5")

    assert "| chocolateria | 0.7 | sin propuesta |" in report  # el valor no se toca
    assert "⚠ τ vigente en el piso de la grilla (0,70): chocolateria, mall." in report
    calibrated = render_markdown(summarize(runs), unmet_quality(runs, {}), {"licores": 0.82}, {}, False, "e5")
    assert "piso de la grilla" not in calibrated


def _mode_run(query, mode, relevant):
    return QueryRun("licores", query, "exacta", mode, [1] * relevant + [0] * (10 - relevant), 0, 0.9, True)


def test_paired_comparison_counts_wins_ties_and_losses_per_query():
    runs = [
        *(_mode_run(q, "hibrido", n) for q, n in [("a", 10), ("b", 8), ("c", 5), ("d", 2)]),
        *(_mode_run(q, "vector", n) for q, n in [("a", 5), ("b", 3), ("c", 5), ("d", 6)]),
    ]

    result = paired_comparison(runs, "hibrido", "vector")

    assert (result["gana"], result["empata"], result["pierde"], result["n"]) == (2, 1, 1, 4)
    low, high = result["ic95"]
    assert low <= result["diferencia"] <= high
    assert result == paired_comparison(runs, "hibrido", "vector")  # misma semilla, mismo intervalo


def test_report_shows_the_paired_comparison():
    runs = [_mode_run("a", "hibrido", 10), _mode_run("a", "vector", 5)]
    comparisons = [paired_comparison(runs, "hibrido", "vector")]
    report = render_markdown(summarize(runs), unmet_quality(runs, {}), {}, {}, False, "e5", comparisons)
    assert "| hibrido vs vector | 1 | 0 | 0 |" in report


def test_saving_keeps_the_current_tau_where_there_is_no_proposal():
    """«Sin propuesta» es «sin evidencia para cambiarlo»: pasar al τ por defecto metió una falsa alarma en Mall."""
    current = {"mall": 0.7, "licores": 0.7}
    assert thresholds_after_saving(current, {"licores": 0.82, "turbo": 0.79}) == {
        "mall": 0.7,
        "licores": 0.82,
        "turbo": 0.79,
    }


def test_report_says_verticals_without_proposal_keep_their_tau():
    runs = [run("neumáticos", "negativa", 0.75), run("pisco", "exacta", 0.90)]
    report = render_markdown(summarize(runs), unmet_quality(runs, {}), {"mall": 0.7}, {}, saved=False, model="e5")
    assert "al guardar, conserva su τ vigente" in report
