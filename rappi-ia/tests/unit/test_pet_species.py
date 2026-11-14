"""Las especies de mascota de complements.toml y cómo se reconocen en los nombres (agent/tools.py)."""

import pytest

from rappi_ia.agent.tools import origin_species, says_species
from rappi_ia.concepts.taxonomy import pet_species


def test_species_come_from_the_toml():
    species = pet_species()
    assert set(species) == {"gato", "perro"}
    assert species["gato"].concepts == {"alimento-gato"} and species["perro"].concepts == {"alimento-perro"}
    assert {"gato", "gatos", "arena"} <= species["gato"].words and {"perro", "cachorro"} <= species["perro"].words


@pytest.mark.parametrize(
    ("name", "gato", "perro"),
    [
        ("Drag Pharma Educador Sanitario Perro", False, True),
        ("Champion Cat Arena Sanitaria Premiun para Gatos Cristales", True, False),
        ("Turbo Clean Arena Aglutinante Café Moka", True, False),  # la arena es de gato
        ("Drag Pharma Shampoo para Perros y Gatos Regepipel Plus", True, True),
        ("Leeby Cama Con Bolsillo Para Cachorros", False, True),
        ("Mpets Pala Sanitaria Plástica Negra", False, False),
        ("Perrito caliente italiano", False, True),  # solo se mira en conceptos de mascotas
    ],
)
def test_a_name_says_its_species(name, gato, perro):
    assert (says_species(name, "gato"), says_species(name, "perro")) == (gato, perro)


def test_the_origin_species_is_one_or_none():
    assert origin_species(["alimento-gato"]) == "gato"
    assert origin_species(["accesorios-mascota"]) is None
    assert origin_species(["accesorios-mascota"], ["Turbo Clean Arena Aglutinante"]) == "gato"
    assert origin_species(["alimento-gato", "alimento-perro"]) is None  # lleva para los dos
    assert origin_species(["alimento-gato"], ["Cama para Perro"]) is None
    assert origin_species(["accesorios-mascota"], ["Shampoo para Perros y Gatos"]) is None
