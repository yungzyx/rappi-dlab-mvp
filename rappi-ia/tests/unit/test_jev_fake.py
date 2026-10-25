"""El falso de Jev tiene la misma interfaz que el cliente real."""

from fakes.jev import FakeJev
from rappi_ia.jev import Choice, JevAnswer, Noul, Score

QUESTIONS = {"n": Noul("a"), "c": Choice("b", {"x": "x", "y": "y"}), "s": Score("c", ["a", "b"])}


def test_default_answers_are_deterministic_and_calls_counted():
    fake = FakeJev()
    first = fake.ask("estado", QUESTIONS)
    assert first == fake.ask("estado", QUESTIONS)
    assert first["n"].noul == 0.5 and first["c"].choice == "x" and first["s"].score == 0.0
    assert len(fake.calls) == 2 and fake.stats.requests == 2


def test_configured_answers_and_failures():
    fake = FakeJev(answers={"n": JevAnswer(noul=0.99)}, fail_when=lambda state: state == "malo")
    results = fake.ask_many([("bien", {"n": Noul("a")}), ("malo", {"n": Noul("a")})])
    assert results[0]["n"].noul == 0.99
    assert results[1] is None
    assert fake.stats.failures == 1
