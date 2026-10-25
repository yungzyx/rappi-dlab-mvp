"""Los simulados con la mezcla de combinaciones de Rappi (events/synth.py), medidos con SQL sobre app_orders.

Sobre el catálogo inventado de la demo: prueba la mecánica, no un efecto.
"""

from collections import Counter
from datetime import date, timedelta

import pytest

from rappi_ia.demo.seed import seed_demo
from rappi_ia.events.synth import generate
from rappi_ia.motor.combos import SERVICE_COMBO, combo_of_verticals, load_combos
from rappi_ia.motor.data import load_orders
from rappi_ia.motor.model import combo_months, combo_stats

# Fecha fija para que la simulación sea la misma cada día (no depende de hoy). El mes de UNTIL queda incompleto: el
# anterior (LAST_FULL) es el último completo y no tiene su M+1 completo.
UNTIL = date(2026, 10, 4)
LAST_MONTH = UNTIL.replace(day=1)
LAST_FULL = (LAST_MONTH - timedelta(days=1)).replace(day=1)


@pytest.fixture
def simulated(db):
    seed_demo(db)
    # Con 1.200, rest+turbo+retail quedaba en 19 al llevar la mitad de los complementos a Turbo (TURBO_SUGGESTION); con
    # 1.500, en 18 al pasar el sushi a las bebidas asiáticas (cambian los complementos que acepta el agente simulado).
    generate(db, users=1800, weeks=26, seed=3, until=UNTIL)
    return db


def _user_months(db) -> dict[tuple[str, date], str]:
    """La combinación de cada persona en cada mes calendario con pedidos."""
    verticals: dict[tuple[str, date], set[str]] = {}
    for user, month, vertical in db.execute(
        """SELECT DISTINCT user_id, date_trunc('month', ts AT TIME ZONE 'America/Santiago')::date, vertical
           FROM app_orders WHERE source = 'synthetic'"""
    ):
        verticals.setdefault((user, month), set()).add(vertical)
    return {key: combo_of_verticals(found) for key, found in verticals.items()}


def test_synthetic_users_mostly_order_only_restaurants(simulated):
    combos = Counter(_user_months(simulated).values())
    assert combos.most_common(1)[0][0] == "rest", combos


def test_more_groups_retain_more_in_the_simulation(simulated):
    months = _user_months(simulated)
    kept: dict[str, list[bool]] = {}
    for (user, month), combo in months.items():
        following = date(month.year + month.month // 12, month.month % 12 + 1, 1)
        if following >= LAST_MONTH:
            continue
        kept.setdefault(combo, []).append((user, following) in months)
    retention = {combo: sum(flags) / len(flags) for combo, flags in kept.items()}
    assert len(kept["rest+turbo+retail"]) >= 20, kept.keys()
    assert retention["rest+turbo+retail"] > retention["rest"], retention


def test_activity_does_not_collapse_at_the_end(simulated):
    """La población activa no se vacía hacia el final: el último mes completo conserva buena parte de la del pico."""
    active: Counter[date] = Counter()
    for _user, month in _user_months(simulated):
        active[month] += 1
    assert active[LAST_FULL] >= 0.4 * max(active.values()), sorted(active.items())


def test_the_mix_and_the_retention_track_the_rappi_table(simulated):
    """Medido como el motor (personas-mes, nivel grueso), sobre el catálogo de prueba: la retención de Restaurantes
    queda a 0,1 de la de Rappi, rest+turbo+retail retiene más que todas y cada combinación de dos o más grupos retiene
    más que cada una de un solo grupo. Esta prueba cuida la retención y las regresiones gruesas de la mezcla, no la
    calibración fina: el catálogo de prueba es chico, muchas búsquedas no encuentran nada y la mezcla queda a 3,7 puntos
    en la peor fila (Restaurantes, 70,7 % contra 67,0 %); el generador anterior a la calibración quedaba a 3,3, así que
    la mezcla (a 4 puntos, Restaurantes la mayor) no los distingue, y la retención sí (0,315 contra 0,47). La
    calibración se revisa con el catálogo real: scripts/calibrar_simulados.py (3.000 personas, 5 semillas: cada fila a
    menos de 2 puntos)."""
    stats = combo_stats(combo_months(load_orders(simulated, "synthetic")))
    rappi = {c: r for c, r in load_combos().rappi.items() if c != SERVICE_COMBO}
    total = sum(r.pct_users for r in rappi.values())
    for combo, row in rappi.items():
        assert stats[combo]["pct_users"] == pytest.approx(100 * row.pct_users / total, abs=4), (combo, stats)
    assert max(stats, key=lambda c: stats[c]["pct_users"]) == "rest"
    retention = {c: s["retention_m1"] for c, s in stats.items()}
    assert max(retention, key=retention.get) == "rest+turbo+retail", retention
    single = [retention[c] for c in ("rest", "turbo", "retail")]
    assert min(r for c, r in retention.items() if "+" in c) > max(single), retention
    assert retention["rest"] == pytest.approx(rappi["rest"].retention_m1, abs=0.1)
