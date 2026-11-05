"""Los tamaños del plan de piloto (docs/plan-piloto.md) y el intervalo de una diferencia de proporciones."""

import pytest

from rappi_ia.analytics.power import PILOT_MIN_EFFECT, difference_ci, sample_size
from rappi_ia.motor.combos import load_combos

BASE = 0.47  # la retención M+1 de "solo Restaurantes" en la tabla de Rappi: la base del plan (un supuesto)


def test_the_base_of_the_plan_is_rappis_only_restaurants_row():
    assert load_combos().rappi["rest"].retention_m1 == BASE


@pytest.mark.parametrize(
    ("effect", "control_share", "control", "treated"),
    [
        (0.01, 0.1, 21_754, 195_780),
        (0.02, 0.1, 5_444, 48_988),
        (0.02, 0.5, 9_795, 9_795),
        (0.05, 0.1, 871, 7_836),
        (0.05, 0.5, 1_569, 1_569),
    ],
)
def test_the_sizes_of_the_plan_table(effect, control_share, control, treated):
    """La tabla "Qué haría falta para medirlo" del plan: α 0,05 a dos colas, potencia 0,8, cada grupo hacia arriba."""
    assert sample_size(BASE, effect, control_share) == (control, treated)


def test_a_smaller_effect_or_a_lopsided_split_needs_more_people():
    assert sum(sample_size(BASE, 0.02, 0.1)) > sum(sample_size(BASE, PILOT_MIN_EFFECT, 0.1))
    assert sum(sample_size(BASE, 0.02, 0.1)) > sum(sample_size(BASE, 0.02, 0.5))


@pytest.mark.parametrize("share", [0, 1, -0.1])
def test_a_split_without_both_groups_is_rejected(share):
    with pytest.raises(ValueError):
        sample_size(BASE, 0.05, share)


def test_the_difference_and_its_interval():
    diff, low, high = difference_ci((490, 1000), (470, 1000))
    assert diff == pytest.approx(0.02)
    assert (low, high) == pytest.approx((0.02 - 0.04378, 0.02 + 0.04378), abs=1e-4)


def test_the_interval_stays_between_minus_one_and_one():
    assert difference_ci((1, 3), (1, 1)) == pytest.approx((-2 / 3, -1.0, -0.1333), abs=1e-4)
    assert difference_ci((2, 3), (0, 1)) == pytest.approx((2 / 3, 0.1333, 1.0), abs=1e-4)
