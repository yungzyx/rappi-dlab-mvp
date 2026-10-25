"""La mezcla de «lo más pedido» con la compra cruzada (motor/recommend.py)."""

import pytest

from rappi_ia.motor.recommend import mix_scores

POPULAR = {("pan", "supermercado"): 0.5, ("salsas", "turbo"): 0.2, ("helados", "turbo"): 0.1}


def test_lambda_zero_is_popularity():
    assert mix_scores(POPULAR, {("salsas", "turbo"): 3.0}, 0) == POPULAR


def test_a_rule_with_lift_3_lifts_a_pair_over_a_more_popular_one():
    scores = mix_scores(POPULAR, {("salsas", "turbo"): 3.0}, 1)

    assert scores[("salsas", "turbo")] == pytest.approx(0.2 * (1 + 1 * 2))
    assert scores[("salsas", "turbo")] > scores[("pan", "supermercado")]
    assert scores[("pan", "supermercado")] == pytest.approx(0.5)  # sin regla, su popularidad


def test_a_lift_under_one_never_lowers_and_a_pair_without_popularity_is_left_out():
    scores = mix_scores(POPULAR, {("helados", "turbo"): 0.5, ("sushi", "restaurantes"): 9.0}, 4)

    assert scores[("helados", "turbo")] == pytest.approx(0.1)
    assert ("sushi", "restaurantes") not in scores
