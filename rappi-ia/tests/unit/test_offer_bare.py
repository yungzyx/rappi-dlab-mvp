"""`_bare`: el nombre que no dice qué producto es, y que el kit de una ocasión se salta."""

import pytest

from rappi_ia.agent.tools import Product
from rappi_ia.concepts.taxonomy import Concept
from rappi_ia.offers.engine import _bare

CONCEPT = Concept("pollo-preparado", "Pollo frito y asado", "🍗", "comida")


def product(name: str) -> Product:
    return Product("p1", "catalog_item", "1", name, "supermercado", CONCEPT.id, 1000.0, None, None, None)


@pytest.mark.parametrize(
    "name",
    [
        "POLLO",
        "Queso",
        "el Pollo",  # el artículo no cuenta como palabra
        "Las Papas",
        "Nutella",  # una marca sola tampoco dice qué es: se salta a propósito
    ],
)
def test_a_one_word_name_is_bare(name):
    assert _bare(product(name), CONCEPT)


@pytest.mark.parametrize("name", ["Pollo frito y asado", "POLLO FRITO Y ASADO", "pollo  frito y asado"])
def test_a_name_equal_to_the_concept_is_bare(name):
    assert _bare(product(name), CONCEPT)


@pytest.mark.parametrize(
    "name", ["Pollo asado entero", "Queso gouda laminado", "Nutella 350 g", "Pollo frito y asado 1 kg"]
)
def test_a_name_that_says_what_it_is_is_not_bare(name):
    assert not _bare(product(name), CONCEPT)
