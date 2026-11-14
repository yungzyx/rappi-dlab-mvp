"""Los simulados con grupo de control (events/synth.py, "Experimentos") en las consultas del panel de hipótesis
(`analytics/queries.py: experiment_results`): cada grupo con sus personas, el control sin Mochi y la pregunta in-app en
los dos. Las diferencias salen de supuestos del generador: aquí se prueba la mecánica, no un efecto."""

from datetime import date

import pytest

from rappi_ia.analytics import queries
from rappi_ia.demo.seed import seed_demo
from rappi_ia.events import experiments, synth
from rappi_ia.events.synth import generate

UNTIL = date(2026, 10, 4)


@pytest.fixture
def simulated(db, monkeypatch):
    """80 personas simuladas de 10 semanas, con la P3, ocultar y silenciar más seguidos que de costumbre (así aparecen
    con el catálogo de prueba)."""
    monkeypatch.setattr(synth, "MOCHI_HIDE", 0.05)
    monkeypatch.setattr(synth, "MOCHI_QUIET", 0.05)
    monkeypatch.setattr(synth, "WHY_OPEN", 1.0)
    monkeypatch.setattr(synth, "SURVEY_SHOWN", 0.8)
    seed_demo(db)
    return generate(db, users=80, weeks=10, seed=5, until=UNTIL)


def _offers_control(db) -> dict:
    result = queries.experiment_results(db, "synthetic")["experimentos"]
    return next(e for e in result if e["id"] == experiments.OFFERS_CONTROL)


def _by_variant(rows: list[dict]) -> dict[str, dict]:
    return {row["variante"]: row for row in rows}


def test_every_simulated_person_gets_an_offers_variant_and_both_groups_have_people(db, simulated):
    rows = dict(
        db.execute(
            """SELECT variant, count(*) FROM experiment_assignments
               WHERE experiment_id = %s AND source = 'synthetic' GROUP BY 1""",
            (experiments.OFFERS_CONTROL,),
        ).fetchall()
    )
    assert sum(rows.values()) == simulated["usuarios"] == 80
    assert rows == {variant: simulated[variant] for variant in (experiments.TREATMENT, experiments.CONTROL)}
    assert all(rows.values())
    # Las sesiones repiten la variante de su persona; lo simulado no toca la población del prototipo.
    mismatched = db.execute(
        """SELECT count(*) FROM app_sessions s JOIN experiment_assignments a
               ON a.user_id = s.user_id AND a.experiment_id = %s
           WHERE s.source = 'synthetic' AND s.variants ->> %s IS DISTINCT FROM a.variant""",
        (experiments.OFFERS_CONTROL, experiments.OFFERS_CONTROL),
    ).fetchone()[0]
    assert mismatched == 0
    assert db.execute("SELECT count(*) FROM experiment_assignments WHERE source = 'prototype'").fetchone()[0] == 0


def test_the_control_group_has_no_mochi_events_in_the_base(db, simulated):
    by_type = dict(
        db.execute(
            """SELECT e.type, count(*) FROM app_events e
               JOIN experiment_assignments a ON a.user_id = e.user_id AND a.experiment_id = %s
               WHERE e.source = 'synthetic' AND a.variant = %s GROUP BY 1""",
            (experiments.OFFERS_CONTROL, experiments.CONTROL),
        ).fetchall()
    )
    mochi = {"ask", "suggestion_shown", "suggestion_accepted", "offer_eligible", "service_shown", "agent_visibility"}
    assert not mochi & set(by_type)
    assert by_type.get("offer_withheld", 0) > 0 and by_type.get("survey_answer", 0) > 0


def test_the_hypotheses_panel_compares_both_simulated_groups(db, simulated):
    experiment = _offers_control(db)
    groups = _by_variant(experiment["variantes"])
    assert groups[experiments.TREATMENT]["personas"] > 0 and groups[experiments.CONTROL]["personas"] > 0

    offers = {variant: row["ofertas"] for variant, row in groups.items()}
    assert offers[experiments.CONTROL]["mostradas"] == offers[experiments.CONTROL]["aceptadas"] == 0
    assert offers[experiments.CONTROL]["retenidas"] > 0
    assert offers[experiments.TREATMENT]["retenidas"] == 0 and offers[experiments.TREATMENT]["mostradas"] > 0
    assert all(o["personas_con_oferta"] > 0 for o in offers.values())

    # H3: las dos variantes responden la P1; la P3 (y su promedio) solo existe en tratamiento.
    survey = _by_variant(experiment["encuesta"]["variantes"])
    assert all(survey[v]["respondidas"] > 0 for v in (experiments.TREATMENT, experiments.CONTROL))
    assert experiment["encuesta"]["diferencia"] is not None
    p3 = _by_variant(
        [{"variante": row["variante"], **row["p3"]} for row in queries.survey(db, "synthetic")["por_grupo"]]
    )
    assert p3[experiments.CONTROL]["mostradas"] == 0 and p3[experiments.TREATMENT]["mostradas"] > 0

    # Adopción y apagado: el control en 0 por diseño; en tratamiento, quienes usaron, ocultaron o silenciaron a Mochi.
    adoption = _by_variant(experiment["adopcion"]["variantes"])
    for key in ("usaron", "ocultos", "silenciaron"):
        assert adoption[experiments.CONTROL][key] == 0
        assert adoption[experiments.TREATMENT][key] > 0

    # H1 y H2 con la forma de siempre, por grupo.
    assert {row["variante"] for row in experiment["retencion"]["variantes"]} == set(groups)
    assert {row["variante"] for row in experiment["frecuencia"]["variantes"]} == set(groups)
    assert experiment["frecuencia"]["diferencia"] is not None


def test_the_same_seed_gives_the_same_groups_and_answers(db, simulated):
    def snapshot():
        return db.execute(
            """SELECT a.variant, e.type, count(*) FROM app_events e
               JOIN experiment_assignments a ON a.user_id = e.user_id AND a.experiment_id = %s
               WHERE e.source = 'synthetic' GROUP BY 1, 2 ORDER BY 1, 2""",
            (experiments.OFFERS_CONTROL,),
        ).fetchall()

    first = snapshot()
    generate(db, users=80, weeks=10, seed=5, until=UNTIL)
    assert snapshot() == first
