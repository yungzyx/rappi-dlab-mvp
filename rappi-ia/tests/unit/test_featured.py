"""Lo destacado (offers/featured.py y offers/destacado.toml): las reglas de lo que la app muestra sin que la persona lo
pida, y su validación."""

import pytest

from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.offers.featured import load_rules, main_dish, one_per_concept, side_dish


def test_the_rules_load_and_name_real_concepts():
    rules = load_rules()
    concepts = load_taxonomy().concepts
    assert rules.min_main_price > 0
    assert rules.not_main and rules.not_main <= set(concepts)
    assert rules.side_sections and rules.side_names


def rules_toml(price="3000", out="[]", sections="['x']", names="['y']") -> str:
    return (
        f"[plato_principal]\nprecio_minimo = {price}\nconceptos_fuera = {out}\n"
        f"[relleno]\nsecciones = {sections}\nnombres = {names}\n"
    )


@pytest.mark.parametrize(
    "content, message",
    [
        (rules_toml(price="0"), "precio_minimo"),
        (rules_toml(out="['no-existe']"), "no-existe"),
        (rules_toml(sections="[]"), "secciones"),
        (rules_toml(names="['']"), "nombres"),
        (rules_toml(names="['costo de envio']"), "una sola palabra"),
    ],
)
def test_bad_rules_are_rejected(tmp_path, content, message):
    path = tmp_path / "destacado.toml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_rules.__wrapped__(path)


@pytest.mark.parametrize(
    "name, section, price",
    [
        ("Choclo", "Agregados", 1195),  # el agregado de una pizzería, con el concepto de su cocina
        ("Coca-Cola 350 cc", "Bebidas y jugos", 2000),
        ("Coca-Cola 1.5 L", "Bebidas", 3990),  # la sección lo dice aunque cueste como un plato
        ("Salsa de ajo", "Pizzas", 600),  # el nombre lo dice y cuesta poco
        ("BOLSA", None, None),  # sin precio no se sabe: relleno
        ("Cubiertos desechables", "Otros", 100),
        ("Extra queso", "Pizzas", 1500),
    ],
)
def test_side_dishes(name, section, price):
    assert side_dish(name, section, price)


@pytest.mark.parametrize(
    "name, section, price",
    [
        ("Tropical", "Pizzas", 11990),
        ("Pizza con salsa pomodoro", "Pizzas", 9990),  # «salsa» no es la primera palabra
        ("Promo pizza + bebida", "Pizzas y bebidas", 12990),  # la sección no empieza con «bebidas»
        ("Extra Pepperoni Familiar", "Pizzas", 9500),  # una pizza de Little Caesars, no un agregado
        ("Ceviche mixto", "Entradas y ceviches", 8990),  # las entradas no son relleno
        ("Bigtime refrescante celeste", "Para llevar", 650),  # no es relleno, pero tampoco plato principal (precio)
        ("Empanada de pino", None, 3500),
    ],
)
def test_main_dishes_are_not_side_dishes(name, section, price):
    assert not side_dish(name, section, price)


def test_a_main_dish_costs_at_least_the_minimum_and_is_not_a_dessert():
    rules = load_rules()
    assert main_dish(rules.min_main_price, "pizza")
    assert not main_dish(rules.min_main_price - 1, "pizza")
    assert not main_dish(None, "pizza")  # sin precio no se destaca
    assert not main_dish(9990, "postres")
    assert main_dish(9990, None)  # sin concepto, el precio decide


def test_one_per_concept_first_and_then_the_rest_in_order():
    products = [
        {"id": "a", "concept": "pizza"},
        {"id": "b", "concept": "pizza"},
        {"id": "c", "concept": "sushi"},
        {"id": "d", "concept": None},
        {"id": "e", "concept": "pizza"},
        {"id": "f", "concept": "pollo-preparado"},
    ]
    assert [p["id"] for p in one_per_concept(products, 3)] == ["a", "c", "d"]
    assert [p["id"] for p in one_per_concept(products, 5)] == ["a", "c", "d", "f", "b"]
    assert [p["id"] for p in one_per_concept(products[:2], 3)] == ["a", "b"]  # si no alcanzan, se repite
