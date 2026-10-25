"""«Sin resultado» cuando la consulta no nombra un concepto (`retrieval.hybrid._unmet`): con una ocasión decide el τ de
la vertical; sin ocasión, el de la búsqueda agrupada (`UNNAMED_TAU`). En la base real, «sofá de tres cuerpos» en Turbo
(coseno 0,821) pasaba el τ de Turbo (0,79) y mostraba pisco Tres Erres."""

import pytest

from rappi_ia.retrieval import hybrid
from rappi_ia.retrieval.hybrid import UNNAMED_TAU, _unmet, named_occasion


@pytest.fixture(autouse=True)
def turbo_tau(monkeypatch):
    monkeypatch.setattr(hybrid, "thresholds", lambda: {"turbo": 0.79})


def unmet(cosine, names_occasion=False, strict=0, names_concept=False, concept_here=False, has_words=True):
    return _unmet("turbo", strict, cosine, concept_here, names_concept, True, has_words, names_occasion)


def test_without_concept_or_occasion_the_vertical_tau_is_not_enough():
    flagged, reason = unmet(0.821)

    assert flagged and reason == f"sin coincidencia léxica ni concepto ni ocasión; coseno máx 0.821 < τ {UNNAMED_TAU}"
    assert not unmet(UNNAMED_TAU)[0]  # muy cercano: lo mismo que deja entrar a una vertical en la búsqueda agrupada


def test_with_an_occasion_the_vertical_tau_decides():
    """«regalo para mi polola»: lo pedido son productos que su nombre no dice; ahí los vecinos vectoriales sirven."""
    assert unmet(0.78, names_occasion=True) == (True, "sin coincidencia léxica ni concepto; coseno máx 0.780 < τ 0.79")
    assert not unmet(0.80, names_occasion=True)[0]


def test_the_occasion_does_not_change_the_other_conditions():
    assert not unmet(0.5, strict=1)[0]  # algo calza todas las palabras
    assert not unmet(0.5, names_concept=True, concept_here=True)[0]
    assert unmet(0.95, names_concept=True)[0]  # el concepto nombrado no está en la vertical
    assert not unmet(0.5, has_words=False)[0]  # «té»: sin palabras, el coseno solo no basta


@pytest.mark.parametrize(
    ("query", "occasion"),
    [
        ("regalo para mi polola", "regalo"),
        ("algo calentito para la once", "once"),
        ("sofá de tres cuerpos", None),
        ("colchón 2 plazas", None),
    ],
)
def test_named_occasion(query, occasion):
    found = named_occasion(query)
    assert (found.id if found else None) == occasion
