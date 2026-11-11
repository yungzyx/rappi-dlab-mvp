"""`_city_first`: lo de la ciudad de la demo antes que lo de otra, cada parte en su orden, sin sacar nada."""

from rappi_ia.agent.tools import Product, _city_first


def product(entity_id: str, in_city: bool) -> Product:
    return Product(
        f"cat-{entity_id}",
        "catalog_item",
        entity_id,
        entity_id,
        "supermercado",
        None,
        1000.0,
        None,
        None,
        None,
        in_city=in_city,
    )


def test_what_only_another_city_sells_goes_after_the_city_in_its_order():
    found = [product("a", False), product("b", True), product("c", False), product("d", True)]
    assert [p.entity_id for p in _city_first(found)] == ["b", "d", "a", "c"]


def test_all_of_one_city_keeps_the_order():
    assert [p.entity_id for p in _city_first([product("a", True), product("b", True)])] == ["a", "b"]
    assert [p.entity_id for p in _city_first([product("a", False), product("b", False)])] == ["a", "b"]


def test_a_product_is_of_the_city_unless_said_otherwise():
    assert Product("cat-1", "catalog_item", "1", "x", "supermercado", None, 1.0, None, None, None).in_city
    assert "in_city" not in product("a", False).to_dict()  # solo ordena: la app no lo recibe
