"""Las compras cruzadas de una persona (motor/recommend.py): reglas de la población desde sus conceptos recientes,
mezcladas con lo más pedido, con las guardias de ofertas."""

from datetime import UTC, datetime, timedelta

import pytest

from rappi_ia.concepts.store import seed_taxonomy
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.events import store as events
from rappi_ia.layers.runs import finish_layer_run, start_layer_run
from rappi_ia.motor.recommend import CROSS_SELL_LAMBDA, cross_picks, latest_lambda

# Lo más pedido de la población (pedidos recientes por concepto y vertical).
TRENDS = {
    ("sushi", "restaurantes"): 500,  # la persona ya lo pidió: no se repite
    ("helados", "farmacia"): 300,  # Farmacia nunca
    ("cerveza", "supermercado"): 200,  # alcohol nunca
    ("panales", "supermercado"): 150,  # bebé nunca
    ("snacks-salados", "supermercado"): 100,
    ("salsas", "turbo"): 40,
    ("pizza", "restaurantes"): 30,  # la pidió hace 40 días: fuera de la ventana, sí sale
    ("helados", "turbo"): 20,
}
# Reglas desde sushi en Restaurantes (lift); las de conceptos bloqueados tampoco suben nada.
RULES = {("salsas", "turbo"): 3.0, ("cerveza", "supermercado"): 5.0, ("panales", "supermercado"): 4.0}


def _order(db, vertical, concept, days_ago, mode="propuesta"):
    events.record_order(
        db, "u1", f"s-{days_ago}", f"c-{days_ago}", vertical,
        [{"entity_type": "catalog_item", "entity_id": "1", "concept_id": concept, "unit_price": 1000}],
        ts=datetime.now(UTC) - timedelta(days=days_ago), mode=mode,
    )  # fmt: skip


@pytest.fixture
def population(db):
    seed_taxonomy(db, load_taxonomy())
    for (concept, vertical), n in TRENDS.items():
        db.execute(
            """INSERT INTO trends (data_source, scope, vertical, item_key, concept_id, orders_now)
               VALUES ('synthetic', 'concepto', %s, %s, %s, %s)""",
            (vertical, concept, concept, n),
        )
    for (concept, vertical), lift in RULES.items():
        db.execute(
            """INSERT INTO cross_sell_rules (data_source, from_concept, from_vertical, to_concept, to_vertical, lift)
               VALUES ('synthetic', 'sushi', 'restaurantes', %s, %s, %s)""",
            (concept, vertical, lift),
        )
    _order(db, "restaurantes", "sushi", 3)
    _order(db, "restaurantes", "pizza", 40)
    _order(db, "supermercado", "snacks-salados", 2, mode="actual")  # «Rappi hoy» no cuenta como ya pedido
    db.commit()
    return db


def test_cross_picks_mix_rules_with_the_most_ordered_and_respect_the_guards(population):
    picks = cross_picks(population, "u1", population="synthetic")

    assert [(p.concept_id, p.vertical) for p in picks] == [
        ("salsas", "turbo"),  # 40 × (1 + 1 × 2) = 120 > 100
        ("snacks-salados", "supermercado"),
        ("pizza", "restaurantes"),
    ]
    assert (picks[0].from_concept, picks[0].lift) == ("sushi", pytest.approx(3.0))
    assert picks[0].score == pytest.approx(120 / sum(TRENDS.values()))
    assert picks[1].from_concept is None and picks[1].lift is None


def test_cross_picks_only_in_the_given_verticals(population):
    picks = cross_picks(population, "u1", verticals=["turbo"], population="synthetic", k=5)
    assert [(p.concept_id, p.vertical) for p in picks] == [("salsas", "turbo"), ("helados", "turbo")]


def test_cross_picks_use_the_lambda_of_the_last_run(population):
    run = start_layer_run(population, "motor", "v")
    finish_layer_run(population, run, {"fuente": "synthetic", "lambda_cruzada": 0.0})

    picks = cross_picks(population, "u1", population="synthetic")
    assert [p.concept_id for p in picks][:2] == ["snacks-salados", "salsas"]  # λ = 0: solo lo más pedido


def test_cross_picks_without_history_is_the_most_ordered(population):
    picks = cross_picks(population, "nadie", population="synthetic")
    assert [p.concept_id for p in picks] == ["sushi", "snacks-salados", "salsas"]


def test_latest_lambda_default_without_runs(db):
    assert latest_lambda(db, "synthetic") == CROSS_SELL_LAMBDA == 1.0
    run = start_layer_run(db, "motor", "v")
    finish_layer_run(db, run, {"fuente": "prototype", "lambda_cruzada": 2.0})
    assert latest_lambda(db, "prototype") == 2.0
    assert latest_lambda(db, "synthetic") == 1.0


def test_cross_picks_can_bring_every_pair_and_take_the_lambda_from_the_caller(population):
    every = cross_picks(population, "u1", population="synthetic", k=None)
    assert [(p.concept_id, p.vertical) for p in every] == [
        ("salsas", "turbo"),
        ("snacks-salados", "supermercado"),
        ("pizza", "restaurantes"),
        ("helados", "turbo"),
    ]
    plain = cross_picks(population, "u1", population="synthetic", k=None, lam=0.0)  # sin empuje: lo más pedido
    assert [(p.concept_id, p.vertical) for p in plain][:2] == [("snacks-salados", "supermercado"), ("salsas", "turbo")]
