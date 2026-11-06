"""Los complementos de "Para ti" (`api.app._complements`) se buscan a la vez y dan lo mismo que uno tras otro: las filas
en el orden de los intereses, sin repetir un complemento (el que repite el de una fila anterior se busca otra vez sin
él), hasta `limit`, y con las preferencias de la persona en cada hilo. Con un `suggest_complement` falso."""

import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from rappi_ia.api import app as api
from rappi_ia.offers import preferences

# Interés → sus complementos, del mejor al peor; "te" no tiene ninguno con productos.
COMPLEMENTS = {
    "hamburguesa": ["gaseosas", "papas-fritas"],
    "pizza": ["gaseosas", "helados"],
    "te": [],
    "sushi": ["gaseosas", "helados", "salsas"],
    "pan": ["cafe"],
}
INTERESTS = list(COMPLEMENTS)


class FakeConn(str):
    def commit(self):
        pass

    def rollback(self):
        pass


class Spares:
    """Conexiones extra falsas, todas las que se pidan; anota cuántas hubo afuera a la vez."""

    def __init__(self):
        self.out = 0
        self.max_out = 0
        self.lock = threading.Lock()

    @contextmanager
    def __call__(self):
        with self.lock:
            self.out += 1
            self.max_out = max(self.max_out, self.out)
        try:
            yield FakeConn(f"extra-{self.max_out}")
        finally:
            with self.lock:
                self.out -= 1


@pytest.fixture
def calls(monkeypatch):
    """`suggest_complement` falso: el primer complemento del interés que no está en `exclude`. Los primeros intereses
    tardan más, para que en paralelo terminen al final. Anota (interés, exclude, preferencias, hilo) de cada llamada."""
    seen = []

    def suggest(conn, sources, current, embedder, exclude=frozenset()):
        (concept,) = sources
        seen.append((concept, set(exclude), preferences.active(), threading.current_thread().name))
        time.sleep(0.02 * (len(INTERESTS) - INTERESTS.index(concept)))
        picked = next((c for c in COMPLEMENTS[concept] if c not in exclude), None)
        return SimpleNamespace(concept=picked) if picked else None

    monkeypatch.setattr(api, "suggest_complement", suggest)
    return seen


def one_after_another(limit: int) -> list[tuple[str, str]]:
    """El ciclo de antes: cada interés, sin los complementos de las filas anteriores."""
    shown, rows = set(), []
    for concept in INTERESTS[: api.COMPLEMENT_SOURCES]:
        if suggestion := api.suggest_complement(FakeConn("peticion"), [concept], None, None, shown):
            shown.add(suggestion.concept)
            rows.append((concept, suggestion.concept))
        if len(rows) >= limit:
            break
    return rows


def complements(limit: int, spare) -> list[tuple[str, str]]:
    found = api._complements(FakeConn("peticion"), INTERESTS, None, None, limit, spare)
    return [(concept, suggestion.concept) for concept, suggestion in found]


@pytest.mark.parametrize("limit", [1, 2, 3, 6])
def test_same_rows_as_one_after_another(calls, limit):
    expected = one_after_another(limit)
    calls.clear()

    assert complements(limit, Spares()) == expected
    assert complements(limit, None) == expected


def test_a_repeated_complement_is_searched_again_without_it(calls):
    spares = Spares()

    rows = complements(3, spares)

    # La pizza también daba gaseosas (como la hamburguesa): se buscó otra vez sin ellas. El té no tiene, y el sushi,
    # el cuarto interés, se busca en serie (después) sin las dos de antes. El pan (quinto) nunca.
    assert rows == [("hamburguesa", "gaseosas"), ("pizza", "helados"), ("sushi", "salsas")]
    assert spares.max_out == 2  # los tres primeros a la vez: la conexión del request y dos extra
    assert [(concept, exclude) for concept, exclude, *_ in calls[3:]] == [
        ("pizza", {"gaseosas"}),
        ("sushi", {"gaseosas", "helados"}),
    ]
    assert {concept for concept, *_ in calls[:3]} == {"hamburguesa", "pizza", "te"}
    assert all(name.startswith("busqueda-vertical") for *_, name in calls[:3])


def test_only_the_first_limit_are_searched_ahead(calls):
    assert complements(1, Spares()) == [("hamburguesa", "gaseosas")]
    assert [concept for concept, *_ in calls] == ["hamburguesa"]


def test_each_thread_uses_the_persons_preferences(calls):
    mine = object()  # las preferencias de la persona: aquí basta con saber que llegan a cada búsqueda

    with preferences.applied(mine):
        complements(3, Spares())

    assert [active for _, _, active, _ in calls] == [mine] * len(calls)
