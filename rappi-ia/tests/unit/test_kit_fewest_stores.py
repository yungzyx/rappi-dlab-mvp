"""ui B10: el kit de una ocasión sale de la menor cantidad de tiendas (`offers/engine.py: _fewest_stores`). Cada tienda
es un pedido con su envío y su mínimo; las verticales del kit ya están elegidas."""

from rappi_ia.agent.tools import Product
from rappi_ia.offers.engine import _fewest_stores


def product(entity_id: str, store_id: int | None, vertical: str = "licores") -> Product:
    return Product(
        f"cat-{entity_id}",
        "catalog_item",
        entity_id,
        entity_id,
        vertical,
        None,
        1000.0,
        None,
        None,
        None,
        store_id=store_id,
    )


def ids(products: list[Product]) -> list[str]:
    return [p.entity_id for p in products]


def test_the_store_that_has_more_of_the_kit_wins_over_each_first_option():
    """La cerveza más barata es de otra botillería, pero la que tiene el pisco también vende cerveza: una tienda."""
    beer = [product("cerveza-oriente", 2), product("cerveza-centro", 1)]
    pisco = [product("pisco-centro", 1)]

    assert ids(_fewest_stores([beer, pisco])) == ["cerveza-centro", "pisco-centro"]


def test_a_store_in_two_verticals_joins_them():
    """Un súper que también es Express: el producto de cada vertical sale de esa tienda."""
    chips = [product("papas-express", 5, "conveniencia"), product("papas-super", 7, "conveniencia")]
    cola = [product("bebida-super", 7, "supermercado")]

    assert ids(_fewest_stores([chips, cola])) == ["papas-super", "bebida-super"]


def test_with_the_same_reach_the_first_concept_keeps_its_best_option():
    first = [product("a1", 1), product("a2", 2)]
    second = [product("b2", 2), product("b1", 1)]

    assert ids(_fewest_stores([first, second])) == ["a1", "b1"]


def test_separate_stores_stay_separate_and_a_product_without_store_keeps_its_first_option():
    beer = [product("cerveza", 1)]
    ice = [product("hielo", 3, "turbo")]
    loose = [product("suelto", None, "turbo")]

    assert ids(_fewest_stores([beer, ice, loose])) == ["cerveza", "hielo", "suelto"]
