"""La evaluación del motor por fechas (motor/evaluate.py), con pedidos armados a mano."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from rappi_ia.motor.data import Line, Order, Signal
from rappi_ia.motor.evaluate import (
    GRID_B,
    GRID_C,
    GRID_LAMBDA,
    evaluate,
    evaluate_cross_sell,
    evaluate_next_vertical,
    evaluate_replenishment,
    evaluate_step,
    make_split,
    not_evaluated,
    rank_metrics,
    report,
    tune,
    tune_lambda,
)

T0 = datetime(2026, 5, 1, 15, 0, tzinfo=UTC)
_seq = iter(range(1, 1_000_000))


def order(user, days, vertical, *concepts, suggested=False):
    lines = tuple(Line(c, "catalog_item", c, suggested) for c in concepts)
    return Order(user, f"o{next(_seq)}", None, T0 + timedelta(days=days), vertical, 1000.0, lines)


def signals_of(orders):
    return [Signal(o.user_id, o.ts, "order", o.vertical) for o in orders]


def test_rank_metrics_values():
    m = rank_metrics(["a", "b", "c"], {"b"})
    assert (m["hit1"], m["hit3"], m["mrr"]) == (0, 1, 0.5)
    assert m["ndcg"] == pytest.approx(1 / 1.5849625, rel=1e-6)
    assert rank_metrics(["a", "b", "c"], {"a", "b"})["ndcg"] == pytest.approx(1.0)
    assert rank_metrics(["a", "b"], set()) == {"hit1": 0, "hit3": 0, "mrr": 0.0, "ndcg": 0.0}


def test_split_needs_84_days():
    short = [order("u1", 0, "turbo"), order("u1", 83, "turbo")]
    assert make_split(short) is None
    assert make_split([]) is None

    orders = [order("u1", 0, "turbo"), order("u1", 84, "turbo")]
    split = make_split(orders)
    assert split.test_end > orders[-1].ts  # el último pedido entra en la prueba
    assert split.test_end - split.valid_end == timedelta(days=28)
    assert split.valid_end - split.train_end == timedelta(days=28)


def _graduates(n=60):
    """Personas que piden tres veces en Supermercado y después pasan a Mall, empezando en días escalonados: la afinidad
    no ve venir Mall (nunca lo pidieron) y las transiciones de quienes pasaron antes, sí. Los clientes fijos de
    Restaurantes hacen que lo popular no sea Mall (la popularidad sola no lo adivina)."""
    orders = []
    for i in range(n):
        start = 2 * i
        orders += [order(f"u{i}", start + d, "supermercado") for d in (0, 7, 14)]
        orders.append(order(f"u{i}", start + 21, "mall"))
    orders += [order(f"r{i}", d + i % 4, "restaurantes") for i in range(20) for d in range(0, 140, 4)]
    return sorted(orders, key=lambda o: o.ts)


def test_tune_picks_transitions_when_people_alternate():
    orders = _graduates()
    signals = signals_of(orders)
    split = make_split(orders)

    weights = tune(orders, signals, split)
    assert weights["afinidad"] == 1
    assert weights["transicion"] > 0
    assert weights["transicion"] in GRID_B and weights["popularidad"] in GRID_C

    test = evaluate_next_vertical(orders, signals, split.valid_end, split.test_end, weights)
    assert set(test) >= {"orden_fijo", "popularidad", "afinidad", "transicion", "combinado"}
    assert test["combinado"]["ndcg"] > test["afinidad"]["ndcg"]
    assert test["combinado"]["personas"] == test["afinidad"]["personas"] > 0


def test_tune_ties_go_to_the_smallest_weights():
    # Todos piden siempre lo mismo: cualquier peso da el mismo nDCG y gana (b, c) = (0, 0).
    orders = sorted((order(f"u{i}", d + i, "turbo") for i in range(10) for d in range(0, 120, 10)), key=lambda o: o.ts)
    weights = tune(orders, signals_of(orders), make_split(orders))
    assert weights == {"afinidad": 1.0, "transicion": 0.0, "popularidad": 0.0}


def test_evaluate_cross_sell_precision_and_coverage():
    cut = T0 + timedelta(days=100)
    orders = []
    # 12 personas aprenden la regla: sushi en Restaurantes → salsa de soya en Turbo.
    for i in range(12):
        orders += [order(f"a{i}", 10 + i, "restaurantes", "sushi"), order(f"a{i}", 12 + i, "turbo", "salsa-soya")]
    # Otras 12 piden pan en Supermercado (lo más pedido de los últimos 28 días, sin relación con sushi).
    orders += [order(f"b{i}", 80 + i, "supermercado", "pan") for i in range(12)]
    # Personas que vuelven a pedir después del corte (las únicas que se evalúan): x, y, w pidieron sushi hace poco;
    # x compra la soya, y no, y w la compra solo porque se la sugirieron (no cuenta). z no tiene regla que aplique.
    orders += [order("x", 95, "restaurantes", "sushi"), order("x", 103, "turbo", "salsa-soya")]
    orders += [order("y", 96, "restaurantes", "sushi"), order("y", 104, "restaurantes", "sushi")]
    orders += [order("w", 97, "restaurantes", "sushi"), order("w", 105, "turbo", "salsa-soya", suggested=True)]
    orders += [order("z", 90, "supermercado", "pan"), order("z", 105, "supermercado", "pan")]
    orders.sort(key=lambda o: o.ts)

    out = evaluate_cross_sell(orders, frozenset(), cut, cut + timedelta(days=28))
    # Los a y b no vuelven a pedir: no cuentan (si no, la precisión mediría el abandono).
    assert out["personas"] == 4
    assert out["personas_con_prediccion"] == 3
    assert out["cobertura"] == pytest.approx(3 / 4)
    assert out["precision3"] == pytest.approx(1 / 3)  # x 1/1, y 0/1, w 0/1
    assert out["aciertos_sobre_3"] == pytest.approx((1 / 3) / 3)
    baseline = out["lo_mas_pedido"]
    assert baseline["precision3"] == 0 and baseline["aciertos_sobre_3"] == 0
    assert baseline["cobertura"] == pytest.approx(1.0)


def _mixable():
    """Una regla sushi en Restaurantes → salsas en Turbo (lift ≈ 2,17) que aprenden 12 personas al principio, cuatro
    pares de Supermercado que son lo más pedido antes de la validación (4 pedidos cada uno) y salsas en Turbo detrás
    (2). Cinco personas piden sushi justo antes de la validación y salsas en Turbo durante ella: lo más pedido solo no
    las acierta; la mezcla, sí, desde λ = 1 (con 0,5 la regla no alcanza a subir salsas sobre los cuatro)."""
    orders = [order(f"d{i}", 5, "mall", "ropa") for i in range(20)]
    for i in range(12):
        orders += [order(f"a{i}", 10 + i, "restaurantes", "sushi"), order(f"a{i}", 12 + i, "turbo", "salsas")]
    orders += [order(f"b{i}", 60 + i, "supermercado", "pan", "leche", "huevos", "cafe") for i in range(4)]
    orders += [order(f"c{i}", 70, "turbo", "salsas") for i in range(2)]
    for i in range(5):
        orders += [order(f"v{i}", 75, "restaurantes", "sushi"), order(f"v{i}", 90, "turbo", "salsas")]
    orders.append(order("z", 140, "mall", "ropa"))  # el final de los datos: la validación es [84, 112)
    return sorted(orders, key=lambda o: o.ts)


def test_mix_beats_the_most_ordered_when_rules_apply():
    orders = _mixable()
    split = make_split(orders)

    plain = evaluate_cross_sell(orders, frozenset(), split.train_end, split.valid_end, lam=0)
    mixed = evaluate_cross_sell(orders, frozenset(), split.train_end, split.valid_end, lam=1)

    assert plain["personas"] == mixed["personas"] == 5
    assert plain["mezcla"]["precision3"] == plain["lo_mas_pedido"]["precision3"] == 0  # λ = 0: lo más pedido
    assert mixed["mezcla"]["precision3"] == pytest.approx(1 / 3)  # salsas, y dos de Supermercado que no pide
    assert mixed["mezcla"]["personas_con_prediccion"] == 5
    assert mixed["mezcla"]["precision3_mismas_personas"] == pytest.approx(1 / 3)
    assert mixed["precision3"] == 1  # las reglas solas: una recomendación y acierta


def test_tune_lambda_picks_the_best_precision_and_the_smallest_on_ties():
    orders = _mixable()
    assert tune_lambda(orders, frozenset(), make_split(orders)) == 1  # 1, 2 y 4 empatan; 0 y 0,5 no aciertan
    assert set(GRID_LAMBDA) == {0, 0.5, 1, 2, 4}

    graduates = _graduates()  # sin conceptos: ningún λ recomienda nada y gana el menor
    assert tune_lambda(graduates, frozenset(), make_split(graduates)) == 0

    nobody = sorted((order(f"u{i}", d, "turbo", "pan") for i in range(5) for d in (0, 2, 88, 90)), key=lambda o: o.ts)
    assert tune_lambda(nobody, frozenset(), make_split(nobody)) is None


def test_evaluate_stores_the_lambda_and_reports_the_mix():
    orders = _mixable()
    results = evaluate(orders, signals_of(orders), frozenset())

    assert results["lambda_cruzada"] == 1
    assert results["validacion"]["precision3_mezcla"] == pytest.approx(1 / 3, abs=1e-4)
    assert {"precision3", "lo_mas_pedido", "mezcla"} <= set(results["compra_cruzada"])  # reglas, base y mezcla
    text = report(results, "synthetic")
    assert "| Mezcla |" in text and "λ = 1" in text

    nobody = sorted((order(f"u{i}", d, "turbo", "pan") for i in range(5) for d in (0, 2, 88, 90)), key=lambda o: o.ts)
    assert evaluate(nobody, signals_of(nobody), frozenset(), previous_lambda=2.0)["lambda_cruzada"] == 2.0


def test_evaluate_replenishment_error_in_days():
    cut = T0 + timedelta(days=100)
    orders = [order("u1", d, "supermercado", "leche") for d in (70, 80, 90)]  # le toca el día 100
    orders.append(order("u1", 103, "supermercado", "leche"))  # la compra 3 días tarde
    orders += [order("u2", d, "turbo", "pan") for d in (80, 87, 94)]  # le toca el día 101 y no vuelve
    orders += [order("u3", d, "turbo", "cafe") for d in (10, 20, 30)]  # le tocaba el día 40: fuera de la ventana
    orders.sort(key=lambda o: o.ts)

    out = evaluate_replenishment(orders, frozenset(), cut, cut + timedelta(days=28))
    assert out["n"] == 2
    assert out["error_mediano_dias"] == 3
    assert out["acierto_7_dias"] == pytest.approx(0.5)


def test_report_warns_on_synthetic():
    orders = _graduates()
    results = evaluate(orders, signals_of(orders), frozenset())
    json.dumps(results)  # va a `counts` de la corrida

    text = report(results, "synthetic")
    assert "Datos simulados: esto prueba la mecánica del motor, no su efecto" in text
    for label in ("Orden fijo", "Solo afinidad", "Solo transiciones", "Combinado", "Lo más pedido"):
        assert label in text
    assert "orden_fijo" not in text and "lo_mas_pedido" not in text  # los ids quedan en el JSON
    assert "aciertos / recomendaciones hechas (hasta 3)" in text
    assert "Datos simulados" not in report(results, "prototype")


def test_report_labels_the_prototype_as_mvp_use():
    orders = _graduates()
    results = evaluate(orders, signals_of(orders), frozenset())

    for text in (report(results, "prototype"), not_evaluated("prototype", "pocos días", {}, "hoy")):
        assert "Uso del MVP, pocas personas: no es evidencia." in text
    assert "Uso del MVP" not in report(results, "synthetic")


def test_without_people_to_validate_keeps_the_previous_weights():
    # Pedidos al principio y al final: nadie pide antes y durante la validación.
    orders = [order(f"u{i}", d, "turbo") for i in range(5) for d in (0, 2, 88, 90)]
    orders.sort(key=lambda o: o.ts)
    split = make_split(orders)
    assert split is not None
    assert tune(orders, signals_of(orders), split) is None

    previous = {"afinidad": 1.0, "transicion": 2.0, "popularidad": 0.5}
    results = evaluate(orders, signals_of(orders), frozenset(), previous)
    assert results["pesos"] == previous
    assert results["validacion"]["personas"] == 0
    assert results["validacion"]["aviso"]
    assert results["validacion"]["aviso"] in report(results, "synthetic")


def test_not_evaluated_stub_says_so():
    text = not_evaluated("prototype", "sin evaluar", {"afinidad": 1.0}, "2026-10-16 03:20")
    assert "no se evaluó" in text and "prototype" in text and "2026-10-16 03:20" in text


def test_evaluate_without_enough_data_is_none():
    orders = [order("u1", 0, "turbo"), order("u1", 10, "turbo")]
    assert evaluate(orders, signals_of(orders), frozenset()) is None


def test_step_follows_the_ladder_and_beats_the_most_added():
    cut = T0 + timedelta(days=100)
    end = cut + timedelta(days=28)
    weights = {"afinidad": 1.0, "transicion": 0.3, "popularidad": 0.1}
    orders = []
    # Antes de la prueba, 10 personas de Supermercado suman Mall: la línea base propone Mall.
    for i in range(10):
        orders += [order(f"b{i}", 60, "supermercado"), order(f"b{i}", 90, "mall")]
    # 5 personas de Restaurantes suman Turbo en la prueba: la escalera gruesa propone Turbo (0,82 contra 0,76).
    for i in range(5):
        orders += [order(f"r{i}", 95, "restaurantes"), order(f"r{i}", 105, "turbo")]
    # Sin pedidos en 30 días pero sí en 90: entra con su combinación de 90 días.
    orders += [order("lapsed", 40, "restaurantes"), order("lapsed", 103, "turbo")]
    # Solo suma Farmacia (la escalera nunca la propone) o no tiene pedidos en 90 días: no cuentan.
    orders += [order("f", 95, "restaurantes"), order("f", 104, "farmacia")]
    orders += [order("old", 5, "restaurantes"), order("old", 106, "turbo")]
    orders.sort(key=lambda o: o.ts)

    out = evaluate_step(orders, signals_of(orders), cut, end, weights)
    assert out["personas"] == 6
    assert out["con_paso"] == 6
    assert out["escalera"] == 1.0
    assert out["mas_sumada"] == 0.0  # Mall: nadie de Restaurantes lo sumó


def test_step_inside_retail_never_farmacia():
    cut = T0 + timedelta(days=100)
    end = cut + timedelta(days=28)
    weights = {"afinidad": 1.0, "transicion": 0.0, "popularidad": 0.0}
    # Rest + Turbo + Supermercado con mucha afinidad por Farmacia: el paso sigue dentro de Retail (Mall, primero entre
    # los que le faltan en el orden fijo) y nunca es Farmacia.
    base = [order("u", 90, v) for v in ("restaurantes", "turbo", "supermercado")]
    base += [order("u", 91, "farmacia"), order("u", 92, "farmacia")]
    adds_mall = sorted([*base, order("u", 101, "farmacia"), order("u", 102, "mall")], key=lambda o: o.ts)
    out = evaluate_step(adds_mall, signals_of(adds_mall), cut, end, weights)
    assert (out["personas"], out["con_paso"], out["escalera"]) == (1, 1, 1.0)

    adds_chocolate = sorted([*base, order("u", 102, "chocolateria")], key=lambda o: o.ts)
    out = evaluate_step(adds_chocolate, signals_of(adds_chocolate), cut, end, weights)
    assert (out["personas"], out["escalera"]) == (1, 0.0)

    # Mall ya estaba en su combinación de 30 días: no suma nada nuevo y no cuenta.
    had_mall = sorted([*base, order("u", 93, "mall"), order("u", 102, "mall")], key=lambda o: o.ts)
    assert evaluate_step(had_mall, signals_of(had_mall), cut, end, weights)["personas"] == 0


def test_evaluate_reports_the_step():
    orders = _graduates()
    results = evaluate(orders, signals_of(orders), frozenset())

    step = results["paso"]
    assert set(step) == {"personas", "con_paso", "escalera", "mas_sumada"}
    text = report(results, "synthetic")
    assert "## Paso de la escalera" in text
    assert "| Paso de la escalera |" in text and "| La vertical que más se suma |" in text
    assert "## Paso de la escalera" not in report({**results, "paso": None}, "synthetic")
