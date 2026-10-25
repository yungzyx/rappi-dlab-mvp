"""La predicción del motor (motor/predict.py): el próximo vertical de una persona, su combinación de este mes y el
paso de combinación que más retención suma."""

from datetime import UTC, datetime, timedelta

import pytest
from psycopg.types.json import Jsonb

from rappi_ia.events import store as events
from rappi_ia.layers.runs import finish_layer_run, start_layer_run
from rappi_ia.motor.combos import LEARNED_RETENTION_MIN_USERS, Step
from rappi_ia.motor.model import DEFAULT_ORDER, DEFAULT_WEIGHTS
from rappi_ia.motor.predict import (
    _learned_fine_retention,
    _learned_retention,
    current_fine,
    latest_weights,
    next_verticals,
    step_signal,
    target_step,
)

NOW = datetime(2026, 10, 10, 15, tzinfo=UTC)


def _order(db, user, vertical, days_ago, now=NOW):
    events.record_order(
        db,
        user,
        f"s-{vertical}-{days_ago}",
        f"c-{vertical}-{days_ago}",
        vertical,
        [{"entity_type": "catalog_item", "entity_id": "1", "concept_id": None, "unit_price": 1000}],
        ts=now - timedelta(days=days_ago),
    )


def test_next_verticals_puts_the_most_used_first(db):
    for days_ago in (2, 9, 16):
        _order(db, "u1", "farmacia", days_ago)
    _order(db, "u1", "restaurantes", 20)
    db.commit()

    ranked = next_verticals(db, "u1", now=NOW)

    assert [s.vertical for s in ranked][:2] == ["farmacia", "restaurantes"]
    assert sorted(s.vertical for s in ranked) == sorted(DEFAULT_ORDER)
    top = ranked[0]
    assert top.affinity > 0.5 and top.transition == 0 and top.popularity == 0  # Farmacia: solo lo propio
    assert ranked == sorted(ranked, key=lambda s: -s.score)


def test_next_verticals_uses_the_population_tables(db):
    """Sin historia propia (pero con un último pedido), mandan la transición y la popularidad de la población."""
    _order(db, "u1", "restaurantes", 40)
    db.commit()
    db.execute(
        """INSERT INTO vertical_transitions (data_source, from_vertical, to_vertical, n, prob)
           VALUES ('synthetic', 'restaurantes', 'mall', 9, 0.9), ('synthetic', 'restaurantes', 'licores', 1, 0.1)"""
    )

    ranked = next_verticals(db, "u1", now=NOW, population="synthetic")

    mall = next(s for s in ranked if s.vertical == "mall")
    licores = next(s for s in ranked if s.vertical == "licores")
    assert ranked[1].vertical == "mall"  # la afinidad propia (restaurantes) va primero
    assert mall.transition == pytest.approx(0.9)
    assert licores.transition == 0  # Licores nunca sube por datos de otros


def test_next_verticals_without_history_is_the_default_order(db):
    assert [s.vertical for s in next_verticals(db, "nadie", now=NOW)] == list(DEFAULT_ORDER)
    assert [s.vertical for s in next_verticals(db, None, now=NOW)] == list(DEFAULT_ORDER)


def _opened(db, user, service, days_ago, now=NOW, mode=None):
    payload = {"servicio": service, **({"mode": mode} if mode else {})}
    events.record(
        db, [events.Event(user, "s-servicio", "service_opened", ts=now - timedelta(days=days_ago), payload=payload)]
    )


def test_current_fine_counts_verticals_and_services_of_the_last_30_days(db):
    _order(db, "u1", "restaurantes", 3)
    _order(db, "u1", "supermercado", 10)
    _order(db, "u1", "turbo", 45)  # fuera de la ventana
    _opened(db, "u1", "rappifavor", 5)
    _opened(db, "u1", "rappitravel", 5, mode="actual")  # «Rappi hoy» no enseña
    _opened(db, "u1", "rappitravel", 40)  # fuera de la ventana
    db.commit()

    assert current_fine(db, "u1", now=NOW) == "restaurantes+supermercado+favor"
    assert current_fine(db, "nadie", now=NOW) == "ninguna"


def test_current_fine_of_a_lapsed_person_is_the_one_of_90_days(db):
    _order(db, "u1", "restaurantes", 40)
    _order(db, "u1", "mall", 80)
    _order(db, "u1", "turbo", 100)  # fuera de los 90 días
    _opened(db, "u1", "rappitravel", 60)
    _opened(db, "u2", "rappifavor", 3)  # abrió un servicio pero no pide: sin combinación
    _order(db, "u3", "turbo", 120)
    db.commit()

    assert current_fine(db, "u1", now=NOW) == "restaurantes+mall+travel"
    assert current_fine(db, "u2", now=NOW) == "ninguna"
    assert current_fine(db, "u3", now=NOW) == "ninguna"


def test_target_step_for_a_restaurant_only_person_is_turbo(db):
    """La escalera gruesa sigue mandando: un grupo nuevo suma más que una vertical extra dentro de un grupo."""
    now = datetime.now(UTC)
    _order(db, "u1", "restaurantes", 2, now=now)
    _order(db, "u1", "restaurantes", 5, now=now)
    db.commit()

    step = target_step(db, "u1")

    assert (step.vertical, step.current, step.target) == ("turbo", "restaurantes", "restaurantes+turbo")
    assert step.gain > 0 and not step.used_assumption
    assert target_step(db, "nadie") is None


def test_target_step_inside_retail_is_another_retail_vertical_never_pharmacy_or_liquor(db):
    now = datetime.now(UTC)
    for vertical in ("restaurantes", "turbo", "supermercado"):
        _order(db, "u1", vertical, 2, now=now)
    for vertical in ("farmacia", "licores"):  # lo que más abre: aun así, nunca es el paso
        events.record(db, [events.Event("u1", "s1", "vertical_open", ts=now, vertical=vertical) for _ in range(9)])
    db.commit()

    step = target_step(db, "u1")

    assert step.vertical in ("conveniencia", "mall", "chocolateria")
    assert step.current == "restaurantes+turbo+supermercado"
    assert step.used_assumption


def _all_offerable(db, user, now):
    for vertical in ("restaurantes", "turbo", "supermercado", "conveniencia", "mall", "chocolateria"):
        _order(db, user, vertical, 2, now=now)


def test_target_step_with_every_offerable_vertical_is_a_service_and_then_none(db):
    now = datetime.now(UTC)
    _all_offerable(db, "u1", now)
    db.commit()

    step = target_step(db, "u1")
    assert (step.vertical, step.target) == ("favor", step.current + "+favor")

    _opened(db, "u1", "rappifavor", 1, now=now)
    db.commit()
    assert target_step(db, "u1").vertical == "travel"

    _opened(db, "u1", "rappitravel", 1, now=now)
    db.commit()
    assert target_step(db, "u1") is None


def test_target_step_of_a_lapsed_person_uses_90_days(db):
    now = datetime.now(UTC)
    _order(db, "u1", "restaurantes", 60, now=now)
    _order(db, "u2", "restaurantes", 120, now=now)
    db.commit()

    assert target_step(db, "u1").vertical == "turbo"
    assert target_step(db, "u2") is None


def _learned(db, combo, retention_n, source="synthetic", nivel="grueso"):
    db.execute(
        """INSERT INTO combo_stats (data_source, nivel, combo, user_months, retention_m1, retention_n)
           VALUES (%s, %s, %s, %s, 0.5, %s)""",
        (source, nivel, combo, retention_n, retention_n),
    )


COARSE_STEP = Step("turbo", "restaurantes", "restaurantes+turbo", 0.1, False)
FINE_STEP = Step("mall", "restaurantes+turbo+supermercado", "restaurantes+turbo+supermercado+mall", 0.01, True)


def test_the_step_signal_names_the_population_only_when_its_retention_weighed_in(db):
    rappi = {"kind": "combinacion", "id": "restaurantes→restaurantes+turbo", "source": "rappi"}
    assert step_signal(db, COARSE_STEP, "synthetic") == rappi

    _learned(db, "rest", LEARNED_RETENTION_MIN_USERS - 1)  # muy pocas personas: no pesa
    _learned(db, "rest+turbo", 500, source="prototype")  # otra población
    assert step_signal(db, COARSE_STEP, "synthetic") == rappi

    _learned(db, "rest+turbo", LEARNED_RETENTION_MIN_USERS)  # la combinación objetivo
    assert step_signal(db, COARSE_STEP, "synthetic")["source"] == "rappi+poblacion:synthetic"
    db.execute("DELETE FROM combo_stats WHERE data_source = 'synthetic' AND combo = 'rest+turbo'")
    db.execute("UPDATE combo_stats SET retention_n = %s WHERE combo = 'rest'", (LEARNED_RETENTION_MIN_USERS,))
    assert step_signal(db, COARSE_STEP, "synthetic")["source"] == "rappi+poblacion:synthetic"  # o la actual


def test_the_step_signal_declares_the_assumption_and_the_learned_fine_retention(db):
    fine = {
        "kind": "combinacion",
        "id": "restaurantes+turbo+supermercado→restaurantes+turbo+supermercado+mall",
        "source": "rappi+supuesto",
    }
    assert step_signal(db, FINE_STEP, "synthetic") == fine

    _learned(db, FINE_STEP.target, LEARNED_RETENTION_MIN_USERS - 1, nivel="fino")  # muy pocas: no pesa
    assert step_signal(db, FINE_STEP, "synthetic") == fine

    _learned(db, FINE_STEP.current, LEARNED_RETENTION_MIN_USERS, nivel="fino")
    assert step_signal(db, FINE_STEP, "synthetic")["source"] == "rappi+supuesto+poblacion:synthetic"


def test_a_fine_row_does_not_leak_into_the_coarse_readers(db):
    """`combo_stats` guarda dos niveles: la retención aprendida de la escalera gruesa solo lee el grueso."""
    for combo in ("rest+turbo", "rest"):  # un nombre fino que coincide con uno grueso
        _learned(db, combo, 500, nivel="fino")
    assert _learned_retention(db, "synthetic") == {}
    assert step_signal(db, COARSE_STEP, "synthetic")["source"] == "rappi"

    _learned(db, "rest", 500)  # la misma combinación, a nivel grueso
    assert _learned_retention(db, "synthetic") == {"rest": (500, 0.5)}


def test_a_coarse_row_does_not_leak_into_the_fine_reader(db):
    _learned(db, "restaurantes", 500)  # grueso con un nombre que parece fino
    _learned(db, "restaurantes+turbo", 40, nivel="fino")
    assert _learned_fine_retention(db, "synthetic") == {"restaurantes+turbo": (40, 0.5)}


def test_latest_weights_default_without_runs(db):
    assert latest_weights(db, "synthetic") == DEFAULT_WEIGHTS

    tuned = {"afinidad": 1.0, "transicion": 0.5, "popularidad": 0.05}
    run = start_layer_run(db, "motor", "v")
    finish_layer_run(db, run, {"fuente": "prototype", "pesos": tuned})
    running = start_layer_run(db, "motor", "v")  # todavía corriendo, con pesos de la misma fuente: no cuenta
    db.execute(
        "UPDATE layer_runs SET counts = %s WHERE run_id = %s",
        (Jsonb({"fuente": "prototype", "pesos": {"afinidad": 9.0, "transicion": 9.0, "popularidad": 9.0}}), running),
    )

    assert latest_weights(db, "prototype") == tuned
    assert latest_weights(db, "synthetic") == DEFAULT_WEIGHTS
