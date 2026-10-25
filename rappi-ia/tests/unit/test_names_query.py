"""El nombre de un producto dice lo pedido (agent/tools._names_query): palabras enteras, sin tildes pero con la ñ, en
singular o plural de cualquiera de los dos lados."""

import pytest

from rappi_ia.agent.tools import _names_query


@pytest.mark.parametrize(
    ("query", "name", "says"),
    [
        ("sándwiches", "Sándwich de jamón", True),
        ("sándwich", "Sándwiches surtidos", True),
        ("limones", "Limón sutil", True),
        ("pañales", "Panal de miel", False),
        ("pañales", "Pañal talla G", True),
        ("alfajores", "Alfajor tradicional", True),
        ("flores", "Ron Flor de Caña", True),
        ("detergente para ropa", "Detergente ropa color", True),
        ("algo para mi perro", "Perro", True),
        ("lo que tenga limón", "Limón", False),
        ("televisor 55 pulgadas", "Cable HDMI 1.80 metros", False),
        ("quiero", "Cualquier cosa", False),  # sin palabras que buscar, nada lo dice
    ],
)
def test_the_name_says_the_query(query, name, says):
    assert _names_query(f"{name}. Categoría: Prueba", query) is says


def test_only_the_name_counts_not_the_rest_of_the_document():
    assert not _names_query("Polera Vegan Dealer. Categoría: Ropa", "ropa")
