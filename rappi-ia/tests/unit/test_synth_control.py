"""El grupo de control de los simulados (events/synth.py, "Experimentos"): "Mochi apagado", con el sorteo estable de la
API, sin eventos de Mochi, con la oferta del carro retenida y la pregunta in-app en los dos grupos. Sus efectos son
supuestos propios, no resultados.

Sin base de datos: el catálogo se arma a mano, con una arista curada para que haya oferta del carro.
"""

import io
import json
import random
from collections import Counter
from datetime import datetime, timedelta

import pytest

from rappi_ia.events import experiments, synth

START = datetime(2026, 4, 1, tzinfo=synth.CHILE)
END = START + timedelta(weeks=26)
MOCHI_EVENTS = {
    "ask",
    "suggestion_shown",
    "suggestion_accepted",
    "suggestion_dismissed",
    "offer_eligible",
    "offer_why_open",
    "service_shown",
    "service_opened",
    "agent_visibility",
}


def _catalog() -> synth.Catalog:
    """Lo que pide la persona "delivery" en Restaurantes y, como complemento curado, gaseosas en Turbo."""
    persona = next(p for p in synth.PERSONAS if p.id == "delivery")
    items = {
        ("restaurantes", concept): [("menu_item", f"{concept}-{n}", 8000.0 + n) for n in range(3)]
        for concept in persona.interests["restaurantes"]
    }
    items[("turbo", "gaseosas")] = [("catalog_item", f"gaseosa-{n}", 1500.0 + n) for n in range(3)]
    edges = {concept: [("gaseosas", 0.8)] for concept in persona.interests["restaurantes"]}
    return synth.Catalog(items=items, edges=edges, names={}, ranked={"gaseosas": ["turbo"]})


def _simulate(variant: str, users: int = 40, seed: int = 7) -> dict[str, list[list[str]]]:
    """Corre a `users` personas "delivery" en la variante y devuelve las filas que escribió, por tabla."""
    persona = next(p for p in synth.PERSONAS if p.id == "delivery")
    rng = random.Random(seed)
    catalog = _catalog()
    buffers = {key: io.StringIO() for key in ("users", "sessions", "events", "orders", "lines", "items")}
    counts = {"usuarios": 0, "eventos": 0, "pedidos": 0}
    for n in range(users):
        state = synth.UserState(
            f"syn-{seed}-{n:05d}",
            persona,
            "Santiago",
            6.0,
            "rest",
            synth.effective_interests(persona, "rest"),
            variant=variant,
        )
        synth._simulate_user(rng, catalog, state, START + timedelta(days=n % 40), END, START, buffers, counts, seed)
    return {key: [line.split("\t") for line in buffer.getvalue().splitlines()] for key, buffer in buffers.items()}


def _events(rows: list[list[str]]) -> list[dict]:
    """Los eventos escritos, con las columnas que miran estos tests (el orden de `generate`)."""
    return [
        {
            "user": r[0],
            "session": r[1],
            "seq": int(r[18]),
            "type": r[3],
            "payload": json.loads(r[14]),
            "surface": r[19],
            "origin": r[20],
        }
        for r in rows
    ]


def test_the_variant_uses_the_apis_stable_draw_with_its_own_share():
    ids = [f"syn-7-{n:05d}" for n in range(4000)]
    variants = [synth.draw_variant(user_id) for user_id in ids]

    assert variants == [synth.draw_variant(user_id) for user_id in ids]
    for user_id, variant in zip(ids, variants, strict=True):
        in_control = experiments.bucket(user_id, experiments.OFFERS_CONTROL) < synth.SYNTH_CONTROL_PCT
        assert variant == (experiments.CONTROL if in_control else experiments.TREATMENT)
    share = Counter(variants)[experiments.CONTROL] / len(ids)
    assert share == pytest.approx(synth.SYNTH_CONTROL_PCT / 100, abs=0.03)


def test_the_control_group_has_no_mochi_events_and_its_cart_offers_are_withheld():
    events = _events(_simulate(experiments.CONTROL)["events"])
    types = Counter(e["type"] for e in events)

    assert not MOCHI_EVENTS & set(types)
    assert types["offer_withheld"] > 0
    withheld = [e for e in events if e["type"] == "offer_withheld"]
    assert {(e["origin"], e["surface"]) for e in withheld} == {(synth.OFFER_ORIGIN, synth.OFFER_SURFACE)}
    assert {e["payload"]["variant"] for e in withheld} == {experiments.CONTROL}
    # La pregunta in-app sale también sin Mochi: solo la P1, sin Mochi a la vista.
    surveys = [e for e in events if e["type"].startswith("survey_")]
    assert surveys and {e["payload"]["question"] for e in surveys} == {"p1"}
    assert {e["payload"]["mochi"] for e in surveys} == {False}


def test_the_treatment_group_has_mochi_its_cart_offers_are_eligible_and_p3_follows_a_why():
    events = _events(_simulate(experiments.TREATMENT)["events"])
    types = Counter(e["type"] for e in events)

    assert types["ask"] > 0 and types["offer_eligible"] > 0 and types["suggestion_shown"] > 0
    assert types["offer_withheld"] == 0
    shown = [e for e in events if e["type"].startswith("suggestion_")]
    assert {e["origin"] for e in shown} == {synth.OFFER_ORIGIN}
    sessions_with_why = {e["session"] for e in events if e["type"] == "offer_why_open"}
    p3 = [e for e in events if e["type"].startswith("survey_") and e["payload"]["question"] == "p3"]
    assert p3 and {e["session"] for e in p3} <= sessions_with_why
    assert {e["payload"]["trigger"] for e in p3} == {"porque"}
    for e in (e for e in p3 if e["type"] == "survey_answer"):
        assert e["payload"]["answer"] in (1, 2, 3, 4, 5)


def test_some_of_the_treatment_hides_or_silences_mochi_and_then_it_shows_nothing(monkeypatch):
    monkeypatch.setattr(synth, "MOCHI_HIDE", 0.1)
    monkeypatch.setattr(synth, "MOCHI_BACK", 0.0)
    monkeypatch.setattr(synth, "MOCHI_QUIET", 0.1)
    events = _events(_simulate(experiments.TREATMENT)["events"])

    visibility = [e for e in events if e["type"] == "agent_visibility"]
    assert any(e["payload"] == {"visible": False} for e in visibility)
    assert any(e["payload"] == {"visible": True, "quiet": True} for e in visibility)
    # Sin MOCHI_BACK no vuelve: desde la sesión en que lo ocultó, nada de Mochi a la vista. La oferta del carro sigue
    # elegible (la API la anota), pero no se muestra.
    hidden = [e for e in visibility if e["payload"] == {"visible": False}]
    assert hidden
    shown = MOCHI_EVENTS - {"agent_visibility", "offer_eligible"}
    for e in hidden:
        mine = [x["session"] for x in events if x["type"] == "app_open" and x["user"] == e["user"]]
        after = set(mine[mine.index(e["session"]) :])
        assert not [x for x in events if x["session"] in after and x["type"] in shown]
    quiet = {e["session"] for e in visibility if e["payload"].get("quiet")}
    assert not [e for e in events if e["session"] in quiet and e["type"] == "suggestion_shown"]


def test_both_groups_draw_the_same_behavior_only_mochi_changes(monkeypatch):
    # Sin aceptar sugerencias (lo único de Mochi que cambia lo que se pide), los dos grupos piden lo mismo: los sorteos
    # de la conducta siguen el mismo orden y el control solo descarta lo que sería de Mochi. La hora puede correrse: lo
    # que el control busca en vez de preguntarle a Mochi a veces viene de una búsqueda mal escrita (REFORMULATE).
    monkeypatch.setattr(synth, "SUGGESTION_ACCEPT", 0.0)
    treated, control = _simulate(experiments.TREATMENT), _simulate(experiments.CONTROL)

    def without_time(rows):
        return [r[:4] + r[5:] for r in rows]

    assert without_time(treated["orders"]) == without_time(control["orders"])
    assert treated["lines"] == control["lines"]
    assert [r[:3] for r in treated["sessions"]] == [r[:3] for r in control["sessions"]]
    assert {json.loads(r[5])[experiments.OFFERS_CONTROL] for r in control["sessions"]} == {experiments.CONTROL}


def test_the_same_seed_gives_the_same_simulation():
    assert _simulate(experiments.TREATMENT, users=15) == _simulate(experiments.TREATMENT, users=15)
    assert _simulate(experiments.CONTROL, users=15) == _simulate(experiments.CONTROL, users=15)


def test_with_mochi_in_sight_yes_goes_up_by_the_declared_assumption():
    def yes_share(mochi: bool) -> float:
        answers = Counter()
        for n in range(20000):
            visit = synth._Visit(random.Random(n), mochi=mochi, last=START, searched=True, carted=True)
            out: list[tuple[str, dict]] = []

            def emit(kind, when, out=out, **kw):
                out.append((kind, kw.get("payload", {})))

            synth._survey(visit, emit)
            answers.update(p["answer"] for kind, p in out if kind == "survey_answer" and p["question"] == "p1")
        return answers["si"] / sum(answers.values())

    lift = yes_share(True) - yes_share(False)
    assert lift == pytest.approx(synth.SURVEY_YES_LIFT, abs=0.02)
