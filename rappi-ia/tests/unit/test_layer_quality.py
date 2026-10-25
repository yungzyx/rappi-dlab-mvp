from rappi_ia.layers import quality
from rappi_ia.layers.quality import precision_report, render_precision, wilson_low


def _row(kind, key, source, i):
    return {"id": f"{kind}|{key}|catalog_item|{i}", "kind": kind, "clave": key, "fuente": source, "nombre": f"Ítem {i}"}


def test_wilson_lower_bound_is_conservative_for_small_samples():
    assert wilson_low(10, 10) < 0.8  # 10 de 10 no garantiza más del 80 %
    assert wilson_low(95, 100) > 0.88
    assert wilson_low(0, 0) is None
    assert str(wilson_low(0, 5)) == "0.0"  # nunca «-0»


def test_precision_report_groups_by_kind_key_and_source_and_ignores_doubts():
    sample = [_row("atributo", "vegano", "regla", i) for i in range(6)] + [_row("marca", "lays", "regla", 9)]
    judged = {r["id"]: {"juicio": "si"} for r in sample}
    judged[sample[0]["id"]] = {"juicio": "no", "nota": "lleva leche"}
    judged[sample[1]["id"]] = {"juicio": "dudoso"}

    report = precision_report(sample, judged)

    group = report["grupos"][("atributo", "vegano", "regla")]
    assert (group["n"], group["correctos"], group["dudosos"]) == (5, 4, 1)
    assert group["precision"] == 0.8 and group["errores"] == [("Ítem 0", "lleva leche")]
    assert group["pesimista"] == round(4 / 6, 3)  # si el dudoso fuera un error
    assert report["por_tipo"][("atributo", "regla")]["n"] == 5
    assert report["por_tipo"][("marca", "regla")]["precision"] == 1.0
    assert report["sin_juicio"] == 0


def test_rules_to_review_are_the_imprecise_groups_with_enough_judgments():
    sample = [_row("atributo", "light", "regla", i) for i in range(8)] + [_row("atributo", "keto", "regla", 20)]
    judged = {r["id"]: {"juicio": "no" if i < 4 else "si"} for i, r in enumerate(sample)}
    judged[sample[-1]["id"]] = {"juicio": "no"}

    report = precision_report(sample, judged)

    assert [g[:2] for g in report["revisar"]] == [("atributo", "light")]  # keto: un solo juicio no alcanza


def test_render_precision_is_markdown_with_the_rules_to_review():
    sample = [_row("concepto", "sushi", "regla", i) for i in range(6)]
    judged = {r["id"]: {"juicio": "no", "nota": "aceite roll-on"} for r in sample}

    text = render_precision(precision_report(sample, judged), "juez de prueba")

    assert text.startswith("# Precisión de la capa de datos")
    assert "juez de prueba" in text and "| concepto | regla |" in text and "aceite roll-on" in text
    assert "Si los dudosos fueran errores" in text


def test_after_changes_counts_errors_removed_and_hits_lost():
    from rappi_ia.layers.quality import after_changes

    sample = [_row("concepto", "sushi", "embedding", i) for i in range(4)]
    judged = {sample[0]["id"]: {"juicio": "si"}, sample[1]["id"]: {"juicio": "si"},
              sample[2]["id"]: {"juicio": "no"}, sample[3]["id"]: {"juicio": "no"}}  # fmt: skip
    still = {sample[0]["id"], sample[2]["id"]}  # un acierto y un error siguen; el resto se fue

    result = after_changes(sample, judged, still)

    assert result[("concepto", "embedding")] == {
        "aciertos_que_siguen": 1, "aciertos_perdidos": 1, "errores_que_siguen": 1, "errores_eliminados": 1,
        "precision_antes": 0.5, "precision_despues": 0.5,
    }  # fmt: skip


def test_the_versioned_sample_keeps_no_catalog_text(tmp_path):
    """La muestra va a git: solo ids y afirmaciones; nombres, descripciones y tiendas se leen de la base al juzgar."""
    from rappi_ia.layers.quality import save_sample

    row = {**_row("atributo", "vegano", "regla", 1), "entity_type": "catalog_item", "entity_id": "1"}
    row |= {
        "afirmacion": "Vegano: x",
        "evidencia": "vegano",
        "categoria": "Leches",
        "descripcion": "texto",
        "tienda": "T",
    }
    versioned, local = tmp_path / "muestra.json", tmp_path / "local.json"

    save_sample([row], versioned, local)

    import json

    kept = json.loads(versioned.read_text())["filas"][0]
    assert set(kept) == {"id", "kind", "clave", "fuente", "entity_type", "entity_id"}
    assert json.loads(local.read_text())["filas"][0]["nombre"] == "Ítem 1"


def test_concept_sample_audits_jev_item_concepts():
    assert quality.CONCEPT_SAMPLE[("catalog_item", "jev")] > 0
