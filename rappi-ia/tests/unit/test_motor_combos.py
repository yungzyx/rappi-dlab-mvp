from itertools import combinations

import pytest

from rappi_ia.motor.combos import (
    FINE_ORDER,
    GROUP_ORDER,
    Step,
    combo_key,
    combo_of_verticals,
    expected_fine_retention,
    expected_retention,
    fine_churn_factor,
    fine_key,
    fine_of,
    group_counts,
    load_combos,
    next_fine_step,
)


def test_every_vertical_has_one_group():
    c = load_combos()
    assert sorted(c.group_of) == sorted(
        ["restaurantes", "turbo", "supermercado", "conveniencia", "farmacia", "licores", "mall", "chocolateria"]
    )
    assert c.group_of["mall"] == "retail" and c.group_of["turbo"] == "turbo"
    assert GROUP_ORDER == ("rest", "turbo", "retail")


def test_combo_key_is_canonical():
    assert combo_key(["retail", "rest", "turbo"]) == "rest+turbo+retail"
    assert combo_key([]) == "ninguna"
    assert combo_of_verticals(["mall", "restaurantes", "farmacia"]) == "rest+retail"
    assert combo_of_verticals([]) == "ninguna"


def test_rappi_table_is_loaded_verbatim():
    c = load_combos()
    r = c.rappi["rest+turbo+retail"]
    assert (r.users, r.pct_users, r.orders_per_user, r.retention_m1, r.spend_per_user) == (56000, 4.7, 10.5, 0.93, 257)
    assert set(c.rappi) == {
        "rest",
        "turbo",
        "rest+turbo",
        "retail",
        "rest+retail",
        "rest+turbo+retail",
        "turbo+retail",
        "favor",
    }
    assert (c.rappi_total.users, c.rappi_total.retention_m1, c.rappi_total.spend_per_user) == (1180000, 0.55, 68)
    assert "correlación, no un efecto" in c.source_note


def test_learned_retention_needs_enough_people_and_blends():
    assert expected_retention("rest", {"rest": (10, 0.9)}) == 0.47
    assert expected_retention("rest", {"rest": (100, 0.67)}) == pytest.approx((0.47 * 100 + 0.67 * 100) / 200)
    assert expected_retention("ninguna") is None
    assert expected_retention("ninguna", {"ninguna": (50, 0.3)}) == 0.3  # Rappi no tiene la fila: solo la aprendida
    assert expected_retention("ninguna", {"ninguna": (5, 0.3)}) is None


def test_combo_of_verticals_accepts_a_generator():
    """Recorre su argumento dos veces: con un generador devolvía siempre «ninguna»."""
    assert combo_of_verticals(v for v in ["restaurantes", "supermercado"]) == "rest+retail"


# --- Combinaciones finas: verticales del catálogo más RappiFavor y RappiTravel ---

REST_TURBO_SUPER = "restaurantes+turbo+supermercado"
ALL_OFFERABLE = "restaurantes+turbo+supermercado+conveniencia+mall+chocolateria"
# Lo que se le puede ofrecer a alguien que lo usa todo: Farmacia y Licores van igual, para probar que se saltan.
EVERY_CANDIDATE = ["farmacia", "licores", "conveniencia", "mall", "chocolateria", "favor", "travel"]


def test_fine_order_and_keys():
    expected = "restaurantes turbo supermercado conveniencia mall chocolateria farmacia licores favor travel"
    assert expected.split() == list(FINE_ORDER)
    assert fine_key(["travel", "supermercado", "restaurantes", "favor"]) == "restaurantes+supermercado+favor+travel"
    assert fine_key([]) == "ninguna"
    assert fine_of(["mall", "restaurantes", "mall"], ["travel"]) == "restaurantes+mall+travel"
    assert fine_of(v for v in ["turbo"]) == "turbo"
    assert fine_of([]) == "ninguna"
    with pytest.raises(ValueError):
        fine_key(["otra"])
    with pytest.raises(ValueError):
        fine_of(["favor"])  # un servicio no es un vertical del catálogo
    with pytest.raises(ValueError):
        fine_of([], ["turbo"])  # ni un vertical es un servicio


def test_services_and_assumption_come_from_the_toml():
    c = load_combos()
    assert c.services == {"favor": "rappifavor", "travel": "rappitravel"}
    a = c.diminishing
    assert (a.reduction_base, a.decay, a.service) == (0.10, 0.5, 0.05)
    assert "supuesto propio" in a.note and "nunca llega a 100 %" in a.note


def test_group_counts_count_catalog_verticals_only():
    assert group_counts("restaurantes+supermercado+conveniencia+farmacia+favor") == {"rest": 1, "retail": 3}
    assert group_counts("favor+travel") == {}
    assert group_counts("ninguna") == {}


def test_churn_reduction_diminishes_within_a_group():
    assert fine_churn_factor("restaurantes+supermercado") == 1
    assert fine_churn_factor("restaurantes+supermercado+conveniencia") == pytest.approx(0.90)  # 2.ª: −10 %
    assert fine_churn_factor("restaurantes+supermercado+conveniencia+mall") == pytest.approx(0.90 * 0.95)  # 3.ª: −5 %
    assert fine_churn_factor("supermercado+conveniencia+mall+chocolateria") == pytest.approx(0.90 * 0.95 * 0.975)
    assert fine_churn_factor("restaurantes+favor") == pytest.approx(0.95)  # cada servicio usado: −5 %
    assert fine_churn_factor("restaurantes+favor+travel") == pytest.approx(0.95 * 0.95)
    assert fine_churn_factor("favor") == 1  # solo Favor: es la base (la fila «favor» de Rappi), no reduce
    assert fine_churn_factor("favor+travel") == pytest.approx(0.95)


def test_expected_fine_retention_reduces_what_does_not_come_back():
    assert expected_fine_retention("restaurantes") == 0.47
    assert expected_fine_retention("restaurantes+supermercado+conveniencia") == pytest.approx(1 - 0.24 * 0.90)
    assert expected_fine_retention("restaurantes+favor") == pytest.approx(1 - 0.53 * 0.95)
    assert expected_fine_retention("ninguna") is None


def test_expected_fine_retention_of_services_only():
    assert expected_fine_retention("favor") == 0.44
    assert expected_fine_retention("favor+travel") == pytest.approx(1 - 0.56 * 0.95)
    assert expected_fine_retention("travel") is None
    assert expected_fine_retention("favor", {"favor": (100, 0.64)}) == pytest.approx(0.54)


def test_expected_fine_retention_never_reaches_one_and_grows_inside_the_groups():
    """Nunca llega a 1, y sumar un servicio o una vertical de un grupo que ya se usa siempre sube la retención (un
    grupo nuevo cambia la base de Rappi, que no siempre sube: «favor» 0,44 contra «retail» 0,41)."""
    group_of = load_combos().group_of
    for k in range(1, len(FINE_ORDER) + 1):
        for members in combinations(FINE_ORDER, k):
            fine = fine_key(members)
            value = expected_fine_retention(fine)
            assert value is None or value < 1, members
            groups = {group_of[m] for m in members if m in group_of}
            if not groups:
                continue
            for extra in FINE_ORDER:
                if extra not in members and group_of.get(extra, "servicio") in {*groups, "servicio"}:
                    assert expected_fine_retention(fine_key([*members, extra])) > value, (members, extra)


def test_expected_fine_retention_blends_learned_values():
    fine = "restaurantes+supermercado+conveniencia"
    assumed = 1 - 0.24 * 0.90
    assert expected_fine_retention(fine, learned_fine={fine: (10, 0.6)}) == pytest.approx(assumed)
    assert expected_fine_retention(fine, learned_fine={fine: (100, 0.6)}) == pytest.approx((assumed + 0.6) / 2)
    # La gruesa aprendida mueve la base: (0,76·100 + 0,56·100) / 200 = 0,66, y después la reducción
    assert expected_fine_retention(fine, {"rest+retail": (100, 0.56)}) == pytest.approx(1 - 0.34 * 0.90)
    assert expected_fine_retention("travel", learned_fine={"travel": (40, 0.5)}) == 0.5  # sin base: solo lo aprendido


# Los cinco casos de la Review Focus, con candidatos armados a mano.


def test_review_retail_continues_inside_retail_never_pharmacy_or_liquor():
    step = next_fine_step(REST_TURBO_SUPER, EVERY_CANDIDATE)
    assert step == Step(
        vertical="conveniencia",
        current=REST_TURBO_SUPER,
        target=REST_TURBO_SUPER.replace("supermercado", "supermercado+conveniencia"),
        gain=pytest.approx(0.07 * 0.10),
        used_assumption=True,
    )
    assert next_fine_step(REST_TURBO_SUPER, ["farmacia", "licores"]) is None
    assert next_fine_step(REST_TURBO_SUPER, ["mall", "conveniencia"]).vertical == "mall"  # empate: orden de la persona


def test_review_everything_offerable_steps_to_a_service():
    step = next_fine_step(ALL_OFFERABLE, EVERY_CANDIDATE)
    churn = 0.07 * 0.90 * 0.95 * 0.975
    assert (step.vertical, step.target, step.used_assumption) == ("favor", ALL_OFFERABLE + "+favor", True)
    assert step.gain == pytest.approx(churn * 0.05)
    assert next_fine_step(ALL_OFFERABLE, ["travel", "favor"]).vertical == "travel"  # empate: el orden de la persona
    assert next_fine_step(ALL_OFFERABLE + "+favor", EVERY_CANDIDATE).vertical == "travel"
    assert next_fine_step(ALL_OFFERABLE + "+favor+travel", EVERY_CANDIDATE) is None


def test_review_catalog_goes_before_services():
    # Chocolatería (4.ª de Retail) quita 2,5 % y Favor 5 %: igual va primero la vertical del catálogo.
    fine = "turbo+supermercado+conveniencia+mall"
    step = next_fine_step(fine, ["favor", "chocolateria"])
    assert (step.vertical, step.gain) == ("chocolateria", pytest.approx(0.20 * 0.90 * 0.95 * 0.025))


def test_review_no_orders_means_no_step():
    assert next_fine_step("ninguna", EVERY_CANDIDATE) is None
    assert next_fine_step("travel", ["restaurantes"]) is None  # sin retención esperada de partida


def test_review_coarse_ladder_still_leads():
    step = next_fine_step("restaurantes", ["supermercado", "conveniencia", "turbo", "favor"])
    assert step == Step("turbo", "restaurantes", "restaurantes+turbo", pytest.approx(0.82 - 0.47), False)
    # Un grupo nuevo suma más que cualquier vertical extra dentro de un grupo.
    step = next_fine_step("restaurantes+supermercado", ["conveniencia", "mall", "turbo"])
    assert (step.vertical, step.gain) == ("turbo", pytest.approx(0.93 - 0.76))


def test_next_fine_step_uses_learned_values():
    learned_fine = {"restaurantes+turbo": (400, 0.40)}  # lo aprendido le baja la ganancia a Turbo
    step = next_fine_step("restaurantes", ["turbo", "supermercado"], learned_fine=learned_fine)
    assert step.vertical == "supermercado"


def test_learned_fine_only_corrects_within_the_group_so_the_coarse_ladder_holds():
    # Como en la población simulada: todo lo aprendido queda bajo la tabla de Rappi, y Restaurantes + Súper (pocas
    # personas) aprendió más que su grupo. Mezclar la fina directo hundía más a Restaurantes + Turbo (muchas personas)
    # y la escalera proponía Súper; corrigiendo solo dentro del grupo, Turbo sigue primero.
    learned_coarse = {"rest": (1577, 0.378), "rest+turbo": (209, 0.699), "rest+retail": (203, 0.690)}
    learned_fine = {
        "restaurantes": (1577, 0.378),
        "restaurantes+turbo": (209, 0.699),
        "restaurantes+supermercado": (57, 0.737),
        "restaurantes+conveniencia": (108, 0.611),
    }
    step = next_fine_step("restaurantes", ["supermercado", "conveniencia", "turbo"], learned_coarse, learned_fine)
    assert step.vertical == "turbo"
    rest_turbo = (0.82 * 100 + 0.699 * 209) / 309  # igual a su grupo: el nivel es el de la gruesa mezclada
    assert expected_fine_retention("restaurantes+turbo", learned_coarse, learned_fine) == pytest.approx(rest_turbo)
    rest_retail = (0.76 * 100 + 0.690 * 203) / 303
    w = 57 / 157
    assert expected_fine_retention("restaurantes+supermercado", learned_coarse, learned_fine) == pytest.approx(
        rest_retail + w * (0.737 - 0.690)
    )


def test_a_fine_row_above_its_group_raises_it():
    fine = "restaurantes+turbo+supermercado+conveniencia"
    coarse = {"rest+turbo+retail": (100, 0.90)}
    blended = (0.93 + 0.90) / 2
    assumed = 1 - (1 - blended) * 0.90
    above = expected_fine_retention(fine, coarse, {fine: (100, 0.95)})
    assert above == pytest.approx(0.5 * assumed + 0.5 * (blended + 0.05))
    assert above > expected_fine_retention(fine, coarse)
    assert expected_fine_retention(fine, coarse, {fine: (100, 0.85)}) < expected_fine_retention(fine, coarse)
    assert expected_fine_retention(fine, {"rest+turbo+retail": (10_000, 0.0)}, {fine: (10_000, 1.0)}) < 1


def test_a_learned_correction_of_the_current_combo_does_not_stall_the_ladder():
    # Restaurantes + Turbo + Súper aprendió más que su grupo; Express no tiene fina aprendida: parte de la actual y le
    # aplica la reducción del supuesto (la 2.ª de Retail quita 10 % de lo que no vuelve).
    fine = "restaurantes+turbo+supermercado"
    learned_coarse = {"rest+turbo+retail": (116, 0.914)}
    learned_fine = {fine: (37, 0.946)}
    current = expected_fine_retention(fine, learned_coarse, learned_fine)
    step = next_fine_step(fine, ["conveniencia", "mall"], learned_coarse, learned_fine)
    assert (step.vertical, step.used_assumption) == ("conveniencia", True)
    assert step.gain == pytest.approx((1 - current) * 0.10)
    # Sin nada aprendido, partir de la actual o desde cero da lo mismo.
    assert next_fine_step(fine, ["conveniencia"]).gain == pytest.approx(
        expected_fine_retention(fine + "+conveniencia") - expected_fine_retention(fine)
    )
