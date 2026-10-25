"""Las personas simuladas (events/synth.py): la asiática y la parte que le deja el carrete.

Sin base de datos: el catálogo se arma a mano con los ítems que cada persona podría comprar.
"""

import io
import math
import random
from collections import Counter
from datetime import datetime, timedelta

import pytest

from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.events import synth
from rappi_ia.motor.combos import SERVICE_COMBO, load_combos

ASIAN_CONCEPTS = {"sushi", "asiatica", "despensa-asiatica", "bebidas-asiaticas", "snacks-asiaticos"}
ASIAN_VERTICALS = {"restaurantes", "supermercado", "turbo", "conveniencia"}
ALL_GROUPS = "rest+turbo+retail"  # el arquetipo que deja a la persona con todos sus verticales
START = datetime(2026, 4, 1, tzinfo=synth.CHILE)
END = START + timedelta(weeks=26)


def _persona(persona_id: str) -> synth.Persona:
    return next(p for p in synth.PERSONAS if p.id == persona_id)


def _catalog(persona: synth.Persona) -> synth.Catalog:
    """Tres ítems por cada (vertical, concepto) que la persona compra: no falta nada que comprar."""
    items = {
        (vertical, concept): [("catalog_item", f"{vertical}-{concept}-{n}", 4000.0 + 500 * n) for n in range(3)]
        for vertical, concepts in persona.interests.items()
        for concept in concepts
    }
    return synth.Catalog(items=items, edges={}, names={}, ranked={})


def _simulate(persona: synth.Persona, users: int = 60, seed: int = 7) -> dict[str, str]:
    """Corre a `users` personas con el generador con semilla y devuelve lo que escribió (pedidos, líneas y eventos)."""
    rng = random.Random(seed)
    catalog = _catalog(persona)
    buffers = {key: io.StringIO() for key in ("users", "events", "orders", "lines")}
    counts = {"usuarios": 0, "eventos": 0, "pedidos": 0}
    for n in range(users):
        state = synth.UserState(
            f"syn-{seed}-{n:05d}",
            persona,
            "Santiago",
            8.0,
            ALL_GROUPS,
            synth.effective_interests(persona, ALL_GROUPS),
        )
        synth._simulate_user(rng, catalog, state, START + timedelta(days=n % 40), END, START, buffers, counts)
    return {key: buffer.getvalue() for key, buffer in buffers.items()}


def test_there_is_an_asian_persona_that_buys_in_the_four_verticals():
    persona = _persona("asiatico")

    assert set(persona.interests) == ASIAN_VERTICALS
    assert set().union(*persona.interests.values()) == ASIAN_CONCEPTS
    assert persona.interests["restaurantes"].keys() == {"sushi", "asiatica"}  # lo que se pide hecho


def test_every_concept_of_the_asian_persona_exists_in_the_taxonomy():
    concepts = load_taxonomy().concepts

    assert concepts.keys() >= ASIAN_CONCEPTS


def test_its_share_comes_out_of_the_party_persona():
    """Achicar el carrete y sumar al asiático: lo que gana uno lo pierde el otro."""
    asian, party = _persona("asiatico"), _persona("carrete")

    assert asian.share == pytest.approx(0.08)
    assert party.share == pytest.approx(0.14)
    assert asian.share + party.share == pytest.approx(0.22)  # el carrete tenía 0,22 solo


def test_the_party_persona_still_exists_and_keeps_its_interests():
    party = _persona("carrete")

    assert set(party.interests) == {"licores", "conveniencia", "restaurantes"}


def test_the_asian_persona_orders_sushi_and_the_new_concepts():
    """Con la semilla fija, sus pedidos pasan por sushi, comida asiática y los tres conceptos nuevos."""
    out = _simulate(_persona("asiatico"))

    ordered = {line.split("\t")[4] for line in out["lines"].splitlines()}  # concept_id de cada línea de pedido

    assert ordered == ASIAN_CONCEPTS


def test_its_orders_come_from_restaurants_supermarket_turbo_and_express():
    out = _simulate(_persona("asiatico"))

    verticals = {line.split("\t")[5] for line in out["orders"].splitlines()}

    assert verticals == ASIAN_VERTICALS


def test_the_generator_is_deterministic_with_the_same_seed():
    persona = _persona("asiatico")

    assert _simulate(persona, seed=11) == _simulate(persona, seed=11)
    assert _simulate(persona, seed=11) != _simulate(persona, seed=12)


def test_archetypes_follow_rappi_shares_with_the_calibration():
    """El sorteo de las altas es la parte de cada combinación en la tabla de Rappi (combos.toml, sin Favor) por su
    factor de calibración: la mezcla que se parece a la de Rappi es la de personas-mes, no la de altas. Restaurantes
    sigue siendo la mayoría de las altas."""
    shares = {c: r.pct_users for c, r in load_combos().rappi.items() if c != SERVICE_COMBO}
    assert set(synth.ARCHETYPE_CALIBRATION) == set(shares)
    weights = {c: share * synth.ARCHETYPE_CALIBRATION[c] for c, share in shares.items()}
    expected = {c: w / sum(weights.values()) for c, w in weights.items()}
    assert pytest.approx(expected) == synth.ARCHETYPES
    assert max(synth.ARCHETYPES, key=synth.ARCHETYPES.get) == "rest"
    rng = random.Random(1)
    n = 20000
    counts = Counter(synth.draw_archetype(rng) for _ in range(n))
    assert set(counts) == set(shares)
    assert counts["rest"] / n == pytest.approx(expected["rest"], abs=0.015)


def test_effective_interests_stay_in_the_archetype_groups():
    familia = _persona("familia")
    eff = synth.effective_interests(familia, "rest+turbo")
    assert set(eff) <= {"restaurantes", "turbo"} and eff["turbo"]  # turbo sale del súper de la familia
    assert "panales" not in eff["turbo"] and "alimentacion-bebe" not in eff["turbo"]  # sin bebé fuera del súper
    assert eff["restaurantes"] == familia.interests["restaurantes"]


def test_what_goes_to_turbo_has_no_alcohol_baby_health_or_sensitive_concepts():
    concepts = load_taxonomy().concepts
    for persona in synth.PERSONAS:
        for archetype in synth.ARCHETYPES:
            eff = synth.effective_interests(persona, archetype)
            copied = set(eff.get("turbo", {})) - set(persona.interests.get("turbo", {}))
            for concept in copied:
                c = concepts[concept]
                assert not (c.sensitive or c.age_restricted or c.parent in ("bebe", "salud")), (persona.id, concept)


def test_missing_groups_use_the_generic_interests():
    delivery = _persona("delivery")  # solo restaurantes
    eff = synth.effective_interests(delivery, "turbo+retail")
    assert eff == {"turbo": synth.GENERIC_INTERESTS["turbo"], "supermercado": synth.GENERIC_INTERESTS["supermercado"]}
    rutina = _persona("rutina")  # solo súper
    assert synth.effective_interests(rutina, "rest")["restaurantes"] == synth.GENERIC_INTERESTS["restaurantes"]


def test_generic_interests_have_no_alcohol_baby_health_or_sensitive_concepts():
    concepts = load_taxonomy().concepts
    for interests in synth.GENERIC_INTERESTS.values():
        for concept in interests:
            c = concepts[concept]
            assert not (c.sensitive or c.age_restricted or c.parent in ("bebe", "salud")), concept


def test_fallback_concepts_prefer_what_the_catalog_has():
    """Con un catálogo, lo que se copia a un grupo vacío se queda con lo que ese vertical vende: sin eso, toda la
    persona del arquetipo terminaría en búsquedas sin resultado."""
    familia = _persona("familia")
    catalog = synth.Catalog(
        items={("turbo", "gaseosas"): [("catalog_item", "t-1", 990.0)]}, edges={}, names={}, ranked={}
    )
    assert synth.effective_interests(familia, "turbo", catalog) == {"turbo": {"gaseosas": 2}}


def test_cadence_follows_orders_per_user():
    """El ritmo da, entre los meses con algún pedido, los pedidos por persona de la tabla: λ / (1 − e^−λ) = 1,9 en
    «rest». Quien abandona más carros necesita más sesiones para los mismos pedidos."""
    familia = _persona("familia")
    assert synth.archetype_cadence("rest+turbo+retail", familia) < synth.archetype_cadence("rest+turbo", familia)
    assert synth.archetype_cadence("rest+turbo", familia) < synth.archetype_cadence("rest", familia)
    rate = synth.monthly_order_rate("rest")
    assert rate / (1 - math.exp(-rate)) == pytest.approx(1.9)
    share = (1 - synth.TRIP) * (1 - synth.BROWSE_ONLY) * (1 - familia.abandon)
    assert synth.archetype_cadence("rest", familia) == pytest.approx(30 * share / rate)
    assert synth.archetype_cadence("rest", _persona("hogar")) < synth.archetype_cadence("rest", familia)


def _state(archetype: str, orders_by_vertical: dict) -> synth.UserState:
    persona = _persona("delivery")
    return synth.UserState(
        "syn-x",
        persona,
        "Santiago",
        8.0,
        archetype,
        synth.effective_interests(persona, archetype),
        True,
        orders_by_vertical,
    )


def test_the_combination_of_the_last_30_days_sets_the_retention():
    """El supuesto explícito: pedir en otro grupo cambia la combinación y con ella la retención (0,76 de rest+retail
    en vez de 0,47 de rest, su arquetipo). La supervivencia es esa retención dividida por la probabilidad de pedir en
    un mes con el ritmo del arquetipo (así la retención M+1 medida se parece a la de Rappi), con tope."""
    now = END - timedelta(days=1)
    moved = _state("rest+turbo", {"restaurantes": [now - timedelta(days=5)], "supermercado": [now - timedelta(days=3)]})
    survival = 0.76 / synth.month_order_probability("rest+turbo")
    assert synth._stay_probability(moved, now, 30) == pytest.approx(survival)
    assert synth._stay_probability(moved, now, 15) == pytest.approx(survival**0.5)
    slow = _state("rest", moved.orders_by_vertical)  # pide poco: 0,76 / 0,77 pasaría de 0,99
    assert synth._stay_probability(slow, now, 30) == pytest.approx(synth.MAX_SURVIVAL)


def test_each_extra_vertical_inside_a_group_adds_retention_with_diminishing_returns():
    """El supuesto propio de la escalera fina: dentro de «retail», Súper + Express rinde más que solo Súper, y el
    tercero menos; nunca llega a 1."""
    now = END - timedelta(days=1)
    recent = [now - timedelta(days=3)]
    one = _state("rest+retail", {"restaurantes": recent, "supermercado": recent})
    two = _state("rest+retail", {**one.orders_by_vertical, "conveniencia": recent})
    three = _state("rest+retail", {**two.orders_by_vertical, "mall": recent})
    p1, p2, p3 = (synth._stay_probability(x, now, 30) for x in (one, two, three))
    q = synth.month_order_probability("rest+retail")

    assert p1 == pytest.approx(0.76 / q)
    assert p2 == pytest.approx((1 - 0.24 * 0.9) / q)
    assert p3 == pytest.approx((1 - 0.24 * 0.9 * 0.95) / q)
    assert p1 < p2 < p3 < 1


def test_without_recent_orders_the_retention_is_the_archetype_one():
    now = END - timedelta(days=1)
    survival = 0.47 / synth.month_order_probability("rest")
    assert synth._stay_probability(_state("rest", {}), now, 30) == pytest.approx(survival)
    old = _state("rest", {"supermercado": [now - timedelta(days=45)]})  # fuera de los 30 días
    assert synth._stay_probability(old, now, 30) == pytest.approx(survival)


def test_simulated_suggestions_follow_the_offer_guards():
    """El agente real nunca ofrece alcohol ni productos de Farmacia o Licores: el simulado tampoco."""
    item = [("catalog_item", "x", 990.0)]
    catalog = synth.Catalog(
        items={("licores", "cerveza"): item, ("farmacia", "gaseosas"): item, ("supermercado", "gaseosas"): item},
        edges={"pizza": [("cerveza", 0.7), ("gaseosas", 0.6)], "frutas": [("vitaminas", 0.9)]},
        names={},
        ranked={"cerveza": ["licores"], "gaseosas": ["farmacia", "supermercado"], "vitaminas": ["supermercado"]},
    )
    assert synth._suggestion(catalog, "pizza", "restaurantes") == ("gaseosas", "supermercado", 0.6)
    assert synth._suggestion(catalog, "frutas", "supermercado") is None  # salud


def test_simulated_suggestions_skip_items_the_agent_would_not_offer():
    """El agente real no ofrece un producto que en esa vertical solo venden tiendas Farmacia, Sex shop o Smoking shop,
    ni uno cuyo nombre dice bebé: el simulado tampoco lo sugiere, y una vertical sin otro ítem del concepto se salta."""
    ok, blocked = ("catalog_item", "1", 990.0), ("catalog_item", "2", 990.0)
    catalog = synth.Catalog(
        items={("supermercado", "gaseosas"): [blocked], ("conveniencia", "gaseosas"): [blocked, ok]},
        edges={"pizza": [("gaseosas", 0.6)]},
        names={},
        ranked={"gaseosas": ["supermercado", "conveniencia"]},
        unofferable={("supermercado", "catalog_item", "2"), ("conveniencia", "catalog_item", "2")},
    )
    assert synth._suggestion(catalog, "pizza", "restaurantes") == ("gaseosas", "conveniencia", 0.6)
    rng = random.Random(1)
    assert {catalog.pick(rng, "conveniencia", "gaseosas", offer=True) for _ in range(20)} == {ok}
    assert blocked in {catalog.pick(rng, "conveniencia", "gaseosas") for _ in range(20)}  # pedirlo, sí


class _Coin:
    """Un `rng` que siempre saca lo mismo: 0 (cae bajo cualquier probabilidad) o 0,99."""

    def __init__(self, value: float):
        self.value, self.draws = value, 0

    def random(self) -> float:
        self.draws += 1
        return self.value


def test_a_suggestion_can_go_to_turbo_when_turbo_sells_the_concept():
    """Con la moneda a favor, el complemento va a Turbo si Turbo lo vende (con algo que el agente ofrecería); si no,
    o sin `rng`, al primero del orden del agente. Solo se sortea cuando Turbo es una alternativa."""
    ok, blocked = ("catalog_item", "1", 990.0), ("catalog_item", "2", 990.0)
    catalog = synth.Catalog(
        items={("supermercado", "gaseosas"): [ok], ("turbo", "gaseosas"): [ok], ("turbo", "galletas"): [blocked],
               ("supermercado", "galletas"): [ok]},
        edges={"pizza": [("gaseosas", 0.6)], "cafe": [("galletas", 0.5)]},
        names={},
        ranked={"gaseosas": ["supermercado", "turbo"], "galletas": ["supermercado", "turbo"]},
        unofferable={("turbo", "catalog_item", "2")},
    )  # fmt: skip
    assert synth._suggestion(catalog, "pizza", "restaurantes", _Coin(0.0)) == ("gaseosas", "turbo", 0.6)
    assert synth._suggestion(catalog, "pizza", "restaurantes", _Coin(0.99)) == ("gaseosas", "supermercado", 0.6)
    assert synth._suggestion(catalog, "pizza", "restaurantes") == ("gaseosas", "supermercado", 0.6)
    no_turbo = _Coin(0.0)
    assert synth._suggestion(catalog, "cafe", "conveniencia", no_turbo) == ("galletas", "supermercado", 0.5)
    assert synth._suggestion(catalog, "pizza", "turbo", no_turbo) == ("gaseosas", "supermercado", 0.6)
    assert no_turbo.draws == 0  # sin Turbo como alternativa no se gasta el azar: lo demás no cambia


def test_a_preferred_item_offered_by_the_agent_passes_the_same_guard():
    """Con un atributo preferido, lo que el agente ofrece tampoco trae un ítem que no ofrecería."""
    ok, blocked = ("catalog_item", "1", 990.0), ("catalog_item", "2", 990.0)
    catalog = synth.Catalog(
        items={("supermercado", "galletas"): [blocked, ok]},
        edges={},
        names={},
        ranked={},
        preferred={("supermercado", "galletas", "sin-gluten"): [blocked]},
        unofferable={("supermercado", "catalog_item", "2")},
    )
    rng = random.Random(1)
    assert {catalog.pick(rng, "supermercado", "galletas", "sin-gluten", offer=True) for _ in range(30)} == {ok}
    assert blocked in {catalog.pick(rng, "supermercado", "galletas", "sin-gluten") for _ in range(30)}  # pedirlo, sí


def test_signups_spread_over_the_whole_period():
    """Las altas llegan parejas, como cohortes mensuales: el último cuarto del período recibe cerca de un cuarto."""
    rng = random.Random(1)
    signups = [synth.draw_signup(rng, START, 26) for _ in range(2000)]
    assert all(START <= s < END for s in signups)
    last_quarter = sum(1 for s in signups if s >= START + (END - START) * 0.75)
    assert 0.20 <= last_quarter / len(signups) <= 0.30, last_quarter
