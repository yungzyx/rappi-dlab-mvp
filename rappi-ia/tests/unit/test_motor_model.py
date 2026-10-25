from datetime import UTC, date, datetime, timedelta

import pytest

from rappi_ia.motor.data import Line, Order, Signal
from rappi_ia.motor.model import (
    DEFAULT_ORDER,
    DEFAULT_WEIGHTS,
    PROTOTYPE_MIN_USERS,
    ComboMonth,
    affinity,
    combo_months,
    combo_stats,
    combo_steps,
    cross_sell,
    popularity,
    rank_verticals,
    replenishment,
    transitions,
    trends,
)

NOW = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)
T0 = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)
SENSITIVE = frozenset({"preservativos"})
_seq = iter(range(1, 1_000_000))


def order(user, ts, vertical, *concepts, cart=None, total=1000.0, suggested=(), entity=None):
    """Un pedido armado a mano: una línea por concepto (producto `catalog_item` con id = concepto, salvo `entity`)."""
    lines = tuple(Line(c, "catalog_item", entity or c or "sin-concepto", c in suggested) for c in (concepts or (None,)))
    n = next(_seq)
    return Order(user, f"o{n}", cart, ts, vertical, total, lines)


def day(n: int, hour: int = 15) -> datetime:
    return T0 + timedelta(days=n, hours=hour - 15)


# Afinidad


def test_affinity_decays_by_half_in_30_days():
    signals = [
        Signal("u1", NOW, "order", "turbo"),
        Signal("u2", NOW - timedelta(days=30), "order", "turbo"),
        Signal("u2", NOW - timedelta(days=30), "view_item", "mall"),
    ]
    aff = affinity(signals, NOW)
    assert aff["u1"] == {"turbo": pytest.approx(5.0)}
    assert aff["u2"]["turbo"] == pytest.approx(2.5)
    assert aff["u2"]["mall"] == pytest.approx(0.15)


def test_affinity_ignores_signals_older_than_180_days():
    signals = [
        Signal("u1", NOW - timedelta(days=181), "order", "turbo"),
        Signal("u1", NOW - timedelta(days=179), "search", "mall"),
        Signal("u1", NOW + timedelta(days=1), "order", "farmacia"),  # después de `now`: no cuenta
        Signal("u2", NOW - timedelta(days=200), "cart_add", "turbo"),
    ]
    aff = affinity(signals, NOW)
    assert set(aff) == {"u1"}
    assert set(aff["u1"]) == {"mall"}


# Transiciones


def test_split_cart_is_not_a_transition():
    orders = [
        order("u1", day(0), "turbo", cart="c1"),
        order("u1", day(0, 16), "supermercado", cart="c1"),  # el mismo carro repartido en dos verticales
        order("u1", day(3), "restaurantes", cart="c2"),
    ]
    trans = transitions(orders)
    assert "turbo" not in trans
    assert trans["supermercado"]["restaurantes"] == pytest.approx(2 / 9)


def test_transitions_are_smoothed_and_sum_to_one():
    orders = [
        order("u1", day(0), "turbo"),
        order("u1", day(1), "restaurantes"),
        order("u1", day(2), "turbo"),
        order("u1", day(3), "restaurantes"),
        order("u2", day(4), "mall"),  # otra persona: no sigue la cadena de u1
    ]
    trans = transitions(orders)
    assert set(trans) == {"turbo", "restaurantes"}
    assert trans["turbo"]["restaurantes"] == pytest.approx(3 / 10)
    assert trans["turbo"]["mall"] == pytest.approx(1 / 10)
    assert trans["restaurantes"]["turbo"] == pytest.approx(2 / 9)
    for row in trans.values():
        assert set(row) == set(DEFAULT_ORDER)
        assert sum(row.values()) == pytest.approx(1.0)


# Combinaciones


def at(y, m, d, hour=15):
    return datetime(y, m, d, hour, tzinfo=UTC)


def test_last_month_without_next_month_has_no_retention():
    orders = [
        order("u1", at(2026, 8, 10), "restaurantes"),
        order("u1", at(2026, 9, 1, 2), "turbo"),  # 22:00 del 31 de agosto en Santiago: cuenta en agosto
        order("u1", at(2026, 9, 10), "restaurantes"),
        order("u1", at(2026, 10, 5), "restaurantes"),  # aquí terminan los datos: octubre está incompleto
        order("u2", at(2026, 8, 12), "mall"),
    ]
    months = {(m.user_id, m.month): m for m in combo_months(orders)}
    assert months["u1", date(2026, 8, 1)] == ComboMonth("u1", date(2026, 8, 1), "rest+turbo", 2, 2000.0, True)
    assert months["u1", date(2026, 9, 1)].retained is None  # su M+1 (octubre) no está completo
    assert months["u1", date(2026, 10, 1)].retained is None
    assert months["u2", date(2026, 8, 1)].retained is False


def test_combo_stats_reproduce_shares_and_retention():
    orders = [
        order("a", at(2026, 8, 3), "restaurantes", total=100),
        order("a", at(2026, 9, 3), "restaurantes", total=100),
        order("b", at(2026, 8, 4), "restaurantes", total=100),
        order("b", at(2026, 8, 5), "turbo", total=300),
        order("c", at(2026, 8, 6), "restaurantes", total=100),
        order("c", at(2026, 8, 7), "turbo", total=100),
        order("c", at(2026, 8, 8), "mall", total=100),
        order("c", at(2026, 9, 9), "turbo", total=100),
        order("c", at(2026, 10, 2), "turbo", total=100),
    ]
    months = combo_months(orders)
    stats = combo_stats(months)
    assert stats["rest"]["user_months"] == 2
    assert stats["rest"]["pct_users"] == pytest.approx(100 * 2 / 6)
    assert stats["rest"]["pct_orders"] == pytest.approx(100 * 2 / 9)
    assert stats["rest"]["orders_per_user"] == pytest.approx(1.0)
    assert stats["rest"]["retention_m1"] == pytest.approx(1.0)  # solo agosto de «a» cuenta: septiembre no tiene M+1
    assert stats["rest"]["retention_n"] == 1
    assert stats["rest+turbo"]["retention_m1"] == pytest.approx(0.0)
    assert stats["rest+turbo"]["spend_per_user"] == pytest.approx(400.0)
    assert stats["rest+turbo+retail"]["retention_m1"] == pytest.approx(1.0)
    assert stats["turbo"]["user_months"] == 2
    assert stats["turbo"]["retention_n"] == 0
    assert stats["turbo"]["retention_m1"] is None
    assert combo_steps(months) == {
        ("rest", "rest"): (1, 1.0),
        ("rest+turbo", "ninguna"): (1, 1.0),
        ("rest+turbo+retail", "turbo"): (1, 1.0),
    }


def test_fine_combos_count_each_vertical_and_keep_the_coarse_retention():
    """El nivel fino separa los verticales dentro de un grupo (supermercado y mall son «retail» en el grueso); la
    retención se mide igual."""
    orders = [
        order("a", at(2026, 8, 3), "supermercado"),
        order("a", at(2026, 8, 9), "mall"),
        order("a", at(2026, 9, 3), "turbo"),
        order("b", at(2026, 8, 4), "supermercado"),
        order("b", at(2026, 8, 5), "supermercado"),
        order("c", at(2026, 8, 6), "restaurantes"),
        order("c", at(2026, 8, 7), "supermercado"),
        order("c", at(2026, 10, 2), "turbo"),
    ]
    coarse, fine = combo_months(orders), combo_months(orders, fine=True)

    assert {m.combo for m in coarse if m.user_id in "ab" and m.month == date(2026, 8, 1)} == {"retail"}
    assert {(m.user_id, m.combo) for m in fine if m.month == date(2026, 8, 1)} == {
        ("a", "supermercado+mall"),
        ("b", "supermercado"),
        ("c", "restaurantes+supermercado"),
    }
    assert [(m.retained, m.orders) for m in coarse] == [(m.retained, m.orders) for m in fine]
    stats = combo_stats(fine)
    assert stats["supermercado+mall"]["retention_m1"] == pytest.approx(1.0)  # «a» pidió en septiembre
    assert stats["supermercado"]["retention_m1"] == pytest.approx(0.0)  # «b» no volvió
    assert stats["supermercado"]["pct_users"] == pytest.approx(100 / 5)
    assert combo_steps(fine)[("supermercado+mall", "turbo")] == (1, 1.0)
    assert combo_steps(fine)[("supermercado", "ninguna")] == (1, 1.0)


# Compra cruzada


def _fillers(n=10):
    """Personas que solo piden pan en el súper: la población contra la que se mide el lift."""
    return [order(f"f{i}", day(1), "supermercado", "pan") for i in range(n)]


def _sushi_then(users, concept, vertical, after=timedelta(days=3), suggested=False, same_cart=False):
    out = []
    for i in range(users):
        cart = f"carro{i}" if same_cart else None
        out.append(order(f"s{concept}{i}", day(0), "restaurantes", "sushi", cart=cart))
        out.append(
            order(
                f"s{concept}{i}",
                day(0) + after,
                vertical,
                concept,
                cart=cart,
                suggested=(concept,) if suggested else (),
            )
        )
    return out


def test_cross_sell_needs_ten_people_and_lift():
    rules = cross_sell(_sushi_then(10, "despensa-asiatica", "turbo") + _fillers(), SENSITIVE)
    [rule] = [r for r in rules if r.from_concept == "sushi"]
    assert (rule.from_vertical, rule.to_concept, rule.to_vertical) == ("restaurantes", "despensa-asiatica", "turbo")
    assert (rule.users_from, rule.users_both) == (10, 10)
    assert rule.confidence == pytest.approx(1.0)
    assert rule.lift == pytest.approx(2.0)  # 1.0 / (10 de 20 personas piden despensa asiática en Turbo)
    assert cross_sell(_sushi_then(9, "despensa-asiatica", "turbo") + _fillers(), SENSITIVE) == []


def test_cross_sell_needs_lift_over_threshold():
    # Todas las personas piden despensa asiática en Turbo: confianza 1, lift 1,0 → no es regla.
    assert cross_sell(_sushi_then(10, "despensa-asiatica", "turbo"), SENSITIVE) == []


def test_cross_sell_window_includes_day_fourteen():
    rules = cross_sell(_sushi_then(10, "despensa-asiatica", "turbo", after=timedelta(days=14)) + _fillers(), SENSITIVE)
    assert [(r.from_concept, r.to_concept) for r in rules] == [("sushi", "despensa-asiatica")]


def test_split_cart_is_not_cross_sell():
    # La app manda un /orders por vertical con el mismo carro, segundos después: es una sola compra.
    split = _sushi_then(10, "despensa-asiatica", "turbo", after=timedelta(seconds=5), same_cart=True)
    assert cross_sell(split + _fillers(), SENSITIVE) == []


def test_cross_sell_skips_suggested_lines_and_sensitive():
    assert cross_sell(_sushi_then(10, "despensa-asiatica", "turbo", suggested=True) + _fillers(), SENSITIVE) == []
    assert cross_sell(_sushi_then(10, "preservativos", "farmacia") + _fillers(), SENSITIVE) == []
    late = _sushi_then(10, "despensa-asiatica", "turbo", after=timedelta(days=15))
    assert cross_sell(late + _fillers(), SENSITIVE) == []
    same_vertical = _sushi_then(10, "gyozas", "restaurantes") + _fillers()
    assert cross_sell(same_vertical, SENSITIVE) == []


# Tendencias


def test_trends_rank_and_growth():
    end = date(2026, 10, 14)
    now_day = datetime(2026, 10, 10, 15, tzinfo=UTC)
    prev_day = datetime(2026, 9, 10, 15, tzinfo=UTC)
    orders = []
    for i in range(12):  # 12 pedidos ahora en Turbo de 6 personas, con café; 3 además con pan
        extra = ("pan",) if i < 3 else ()
        orders.append(order(f"u{i % 6}", now_day, "turbo", "cafe", *extra, "preservativos"))
    orders += [order("p", prev_day, "turbo", "cafe") for _ in range(4)]
    orders += [order("r", now_day, "restaurantes", "sushi") for _ in range(3)]
    orders += [order("r", prev_day, "restaurantes", "sushi") for _ in range(10)]
    orders.append(order("x", datetime(2026, 9, 16, 15, tzinfo=UTC), "mall", "ropa"))  # = fin - 28 días: anterior
    orders.append(order("x", datetime(2026, 10, 15, 15, tzinfo=UTC), "mall", "ropa"))  # después del fin: fuera
    rows = {(r.scope, r.vertical, r.item_key): r for r in trends(orders, end, SENSITIVE)}

    turbo = rows["vertical", "turbo", "turbo"]
    assert (turbo.orders_now, turbo.orders_prev, turbo.users_now, turbo.rank) == (12, 4, 6, 1)
    assert turbo.growth == pytest.approx((12 - 4) / 5)
    assert rows["vertical", "restaurantes", "restaurantes"].growth == pytest.approx((3 - 10) / 10)
    assert ("vertical", "mall", "mall") not in rows  # sin pedidos en la ventana reciente

    cafe, pan = rows["concepto", "turbo", "cafe"], rows["concepto", "turbo", "pan"]
    assert (cafe.rank, cafe.orders_now, cafe.orders_prev, cafe.concept_id) == (1, 12, 4, "cafe")
    assert (pan.rank, pan.orders_now, pan.growth) == (2, 3, pytest.approx(3 / 5))
    assert ("concepto", "turbo", "preservativos") not in rows

    product = rows["producto", "turbo", "catalog_item:cafe"]
    assert (product.entity_type, product.entity_id, product.concept_id, product.rank) == (
        "catalog_item",
        "cafe",
        "cafe",
        1,
    )
    assert ("producto", "turbo", "catalog_item:preservativos") not in rows


def test_trends_min_users_drops_concepts_and_products_but_not_verticals():
    end = date(2026, 10, 14)
    when = datetime(2026, 10, 10, 15, tzinfo=UTC)
    orders = [order(f"u{i}", when, "turbo", "cafe") for i in range(PROTOTYPE_MIN_USERS)]
    orders += [order("solo", when, "turbo", "pan") for _ in range(3)]  # tres pedidos, una sola persona
    rows = {(r.scope, r.item_key): r for r in trends(orders, end, SENSITIVE, PROTOTYPE_MIN_USERS)}

    assert ("concepto", "pan") not in rows and ("producto", "catalog_item:pan") not in rows
    assert ("concepto", "cafe") in rows and ("producto", "catalog_item:cafe") in rows
    turbo = rows["vertical", "turbo"]
    assert (turbo.orders_now, turbo.users_now) == (PROTOTYPE_MIN_USERS + 3, PROTOTYPE_MIN_USERS + 1)
    assert rows["concepto", "cafe"].rank == 1  # el ranking se arma con lo que queda
    assert ("concepto", "pan") in {(r.scope, r.item_key) for r in trends(orders, end, SENSITIVE)}  # sin mínimo, sale


# Recompra


def test_replenishment_needs_three_days_and_regularity():
    orders = [
        order("u1", day(0), "turbo", "cafe"),
        order("u1", day(14), "supermercado", "cafe"),
        order("u1", day(14, 18), "turbo", "cafe"),  # dos el mismo día cuentan como uno
        order("u1", day(28), "turbo", "cafe"),
        order("u2", day(0), "turbo", "pan"),  # intervalos 1 y 29: irregular
        order("u2", day(1), "turbo", "pan"),
        order("u2", day(30), "turbo", "pan"),
        order("u3", day(0), "turbo", "te"),  # solo dos días
        order("u3", day(7), "turbo", "te"),
        *(order("u4", day(7 * k), "farmacia", "preservativos") for k in range(4)),  # sensible
    ]
    [r] = replenishment(orders, SENSITIVE)
    assert (r.user_id, r.concept_id, r.vertical, r.orders) == ("u1", "cafe", "turbo", 3)
    assert r.interval_days == pytest.approx(14)
    assert r.cv == pytest.approx(0.0)
    assert r.last_ts == day(28)
    assert r.due_on == date(2026, 9, 29) + timedelta(days=14)


def test_replenishment_keeps_cv_at_the_limit():
    # Intervalos 7 y 28: media 17,5, desviación 10,5 → cv = 0,6 justo en el tope: se queda.
    orders = [order("u1", day(n), "turbo", "cafe") for n in (0, 7, 35)]
    [r] = replenishment(orders, SENSITIVE)
    assert r.cv == pytest.approx(0.6)
    assert r.interval_days == pytest.approx(17.5)
    assert r.due_on == date(2026, 10, 6) + timedelta(days=18)  # round(17,5) = 18 (al par)


def test_replenishment_vertical_tie_goes_to_the_most_recent():
    orders = [
        order("u1", day(0), "turbo", "cafe"),
        order("u1", day(14), "supermercado", "cafe"),
        order("u1", day(28), "turbo", "cafe"),
        order("u1", day(42), "supermercado", "cafe"),
    ]
    [r] = replenishment(orders, SENSITIVE)
    assert r.vertical == "supermercado"


# Popularidad y ranking


def test_popularity_is_the_share_of_recent_orders():
    orders = [
        order("u1", NOW - timedelta(days=1), "turbo"),
        order("u2", NOW - timedelta(days=2), "turbo"),
        order("u3", NOW - timedelta(days=27), "mall"),
        order("u4", NOW - timedelta(days=29), "farmacia"),  # fuera de los 28 días
    ]
    assert popularity(orders, NOW) == pytest.approx({"turbo": 2 / 3, "mall": 1 / 3})
    assert popularity([], NOW) == {}


def test_pharmacy_and_liquor_rise_only_by_own_signals():
    trans = {"restaurantes": {"farmacia": 0.9, "licores": 0.5}}
    pop = {"farmacia": 0.9, "mall": 0.1}
    ranked = rank_verticals({}, "restaurantes", trans, pop, DEFAULT_WEIGHTS)
    order_ = [v for v, _ in ranked]
    assert order_[0] == "mall"
    assert order_.index("farmacia") >= DEFAULT_ORDER.index("farmacia")
    assert dict(ranked)["farmacia"] == 0.0 and dict(ranked)["licores"] == 0.0
    own = rank_verticals({"farmacia": 2.0, "turbo": 1.0}, "restaurantes", trans, pop, DEFAULT_WEIGHTS)
    assert own[0] == ("farmacia", pytest.approx(2 / 3))


def test_rank_without_any_signal_is_the_default_order():
    ranked = rank_verticals({}, None, {}, {}, DEFAULT_WEIGHTS)
    assert [v for v, _ in ranked] == list(DEFAULT_ORDER)
    assert all(score == 0 for _, score in ranked)
