"""Cuántas personas hacen falta para medir un efecto sobre una proporción, y el intervalo de una diferencia
(docs/plan-piloto.md). Aproximación normal: prueba de dos proporciones, α = 0,05 a dos colas y potencia 0,8."""

from math import ceil, sqrt
from statistics import NormalDist

ALPHA = 0.05
POWER = 0.8
# El efecto más grande del plan de piloto: bajo el mínimo para medirlo, la diferencia entre grupos no es concluyente.
PILOT_MIN_EFFECT = 0.05

_Z_ALPHA = NormalDist().inv_cdf(1 - ALPHA / 2)
_Z_POWER = NormalDist().inv_cdf(POWER)


def sample_size(base: float, effect: float, control_share: float) -> tuple[int, int]:
    """(control, tratamiento): las personas que pide cada grupo para detectar que la proporción pasa de `base` (en
    control) a `base + effect` (en tratamiento), con `control_share` de las personas en control. Con N el total:

        N = (z_α/2 · √(p̄·(1 − p̄)·(1/k + 1/(1 − k))) + z_β · √(p₀·(1 − p₀)/k + p₁·(1 − p₁)/(1 − k)))² / δ²

    con k la parte en control, p₀ = base, p₁ = base + δ y p̄ = k·p₀ + (1 − k)·p₁; cada grupo, redondeado hacia arriba."""
    if not 0 < control_share < 1:
        raise ValueError("control_share debe estar entre 0 y 1")
    k, p0, p1 = control_share, base, base + effect
    pooled = k * p0 + (1 - k) * p1
    total = (
        _Z_ALPHA * sqrt(pooled * (1 - pooled) * (1 / k + 1 / (1 - k)))
        + _Z_POWER * sqrt(p0 * (1 - p0) / k + p1 * (1 - p1) / (1 - k))
    ) ** 2 / effect**2
    return ceil(k * total), ceil((1 - k) * total)


def difference_ci(treated: tuple[int, int], control: tuple[int, int]) -> tuple[float, float, float]:
    """(diferencia, desde, hasta) en proporción: tratamiento − control, con su intervalo de 95 % (Wald, varianzas sin
    juntar), recortado a [−1, 1]. Cada grupo es (personas que cumplen, personas)."""
    pt, pc = treated[0] / treated[1], control[0] / control[1]
    half = _Z_ALPHA * sqrt(pt * (1 - pt) / treated[1] + pc * (1 - pc) / control[1])
    return pt - pc, max(-1.0, pt - pc - half), min(1.0, pt - pc + half)
