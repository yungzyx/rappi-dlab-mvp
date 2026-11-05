"""Lo que se muestra de lo encontrado (agent/tools._focus), sin base: en el concepto nombrado, primero lo que dice lo
pedido en su nombre; sin concepto nombrado, si varios productos lo dicen en su nombre, lo demás tiene que ser de su
concepto o muy cercano."""

import pytest

from rappi_ia.agent import tools
from rappi_ia.agent.tools import TAIL_MIN_NAMED, _focus
from rappi_ia.retrieval.hybrid import UNNAMED_TAU, Hit, RetrievalResult


def _hit(entity_id: str, name: str, concept: str | None, cosine: float | None = 0.8) -> Hit:
    return Hit("turbo", "catalog_item", entity_id, f"{name}. Categoría: Prueba", {}, 0.0, concept, cosine)


def _result(query: str, concepts: list[str], hits: list[Hit], unmet: bool = False) -> RetrievalResult:
    return RetrievalResult("turbo", query, hits, concepts, 4, 0.85, bool(concepts), unmet, None)


def _ids(hits: list[Hit]) -> list[str]:
    return [h.entity_id for h in hits]


CUCHUFLIES = [
    _hit("1", "Cuchuflíes Medios Original 12u", "chocolates", 0.849),
    _hit("2", "Esponja Sqeezy The Pink Stuff", "limpieza", 0.810),
    _hit("3", "Bogati Cuchuflíes Cubiertos en Chocolate", "galletas", 0.834),
    _hit("4", "Cuchillo Compostable", "papeles-desechables", 0.809),
    _hit("5", "Cuchuflí Enteros Original 6u", "chocolates", 0.845),
    _hit("6", "Galletas de Champaña", "galletas", 0.79),
    _hit("7", "Alfajor de manjar", "golosinas", UNNAMED_TAU + 0.01),
    _hit("8", "Traperos Piso Flotante 8u", "limpieza", None),
]


def test_after_what_says_it_in_its_name_only_its_concept_or_a_very_close_neighbor():
    """ "cuchuflíes" en Turbo: 4 cuchuflíes y después esponjas, un cuchillo y traperos, vecinos vectoriales sin
    relación. Ahora queda lo del concepto de los que lo dicen (galletas, chocolates) o lo que pasa el coseno de una
    consulta sin concepto ni ocasión (UNNAMED_TAU), en su orden."""
    shown = _focus(CUCHUFLIES, _result("cuchuflíes", [], CUCHUFLIES))

    assert _ids(shown) == ["1", "3", "5", "6", "7"]


def test_the_tail_rule_follows_the_threshold(monkeypatch):
    monkeypatch.setattr(tools, "UNNAMED_TAU", 0.80)

    shown = _focus(CUCHUFLIES, _result("cuchuflíes", [], CUCHUFLIES))

    assert _ids(shown) == ["1", "2", "3", "4", "5", "6", "7"]  # lo que no tiene coseno no pasa ningún umbral


def test_with_few_products_that_say_it_the_neighbors_stay():
    """Con menos de TAIL_MIN_NAMED, la coincidencia puede ser casual ("bombomes" calza con "Café Bombom" por el
    stemming; un plato mal escrito, "Shawarna carne", no dice el concepto de los demás): queda lo encontrado."""
    hits = [CUCHUFLIES[0], *[h for h in CUCHUFLIES if "Cuchu" not in h.content]]
    assert sum("Cuchu" in h.content for h in hits) < TAIL_MIN_NAMED

    assert _ids(_focus(hits, _result("cuchuflíes", [], hits))) == _ids(hits)


def test_unmet_still_shows_nothing():
    assert _focus(CUCHUFLIES, _result("cuchuflíes", [], CUCHUFLIES, unmet=True)) == []


@pytest.mark.parametrize(
    ("query", "names", "first"),
    [
        # "sin" cuenta: "harina con polvos" no es lo pedido, aunque diga las otras palabras
        (
            "harina sin polvos de hornear",
            ["Harina con Polvos de Hornear 1 kg", "Harina Integral 1 kg", "Harina sin Polvos de Hornear 1 kg"],
            ["3", "1", "2"],
        ),
        # en un concepto grueso (celulares), el cargador antes que el cable
        (
            "cargador tipo c",
            ["Cable Tipo C a Tipo C 1 m", "Cargador Rápido 25 W Tipo C", "Carcasa iPhone 13"],
            ["2", "1", "3"],
        ),
    ],
)
def test_within_the_named_concept_what_says_it_in_its_name_goes_first(query, names, first):
    hits = [_hit(str(i), name, "x") for i, name in enumerate(names, start=1)]

    assert _ids(_focus(hits, _result(query, ["x"], hits))) == first


def test_without_a_concept_the_order_does_not_change():
    """Sin concepto nombrado no se reordena: un plato con el error de tipeo en su nombre ("Chorillana") no pasa
    delante del que lo escribe bien ("Chorrillana Mongoliana")."""
    hits = [_hit("1", "Chorrillana Mongoliana", "picoteo"), *[_hit(str(i), "Chorillana", "picoteo") for i in (2, 3, 4)]]

    assert _ids(_focus(hits, _result("chorillana", [], hits))) == ["1", "2", "3", "4"]


MEDICINES = [
    _hit("1", "Aspirina 100mg 42 Comprimidos", "medicamentos"),
    _hit("2", "Esomeprazol 40 Mg X 30 Cápsulas", "medicamentos"),
    _hit("3", "Rumada (10/10 mg)", "medicamentos"),  # una estatina con la categoría de los analgésicos
    _hit("4", "Acido Acetilsalicílico (100 Mg)", "medicamentos"),
    _hit("5", "Paracetamol 500 mg 16 Comprimidos", "medicamentos"),
    # un paracetamol cuya ficha nombra la aspirina: cuenta solo el nombre
    Hit(
        "turbo",
        "catalog_item",
        "6",
        "Tapsin Infantil 16 Comprimidos. Para los alérgicos al ácido acetilsalicílico",
        {},
        0.0,
        "medicamentos",
        0.8,
    ),
]


def test_a_named_medicine_shows_only_what_names_it_or_its_active_ingredient():
    """ "aspirina" en Farmacia mostraba Aspirina, un esomeprazol y una estatina, y dejaba fuera el ácido
    acetilsalicílico: ahora solo lo que dice aspirina o su principio activo, sin el resto de `medicamentos`."""
    assert _ids(_focus(MEDICINES, _result("aspirina", ["medicamentos"], MEDICINES))) == ["1", "4"]
    assert _ids(_focus(MEDICINES, _result("paracetamol", ["medicamentos"], MEDICINES))) == ["5"]


def test_without_a_named_medicine_the_concept_stays_whole():
    assert _ids(_focus(MEDICINES, _result("remedios", ["medicamentos"], MEDICINES))) == _ids(MEDICINES)


def test_a_named_medicine_with_nothing_that_names_it_shows_nothing():
    others = MEDICINES[1:3]
    assert _focus(others, _result("ibuprofeno", ["medicamentos"], others)) == []
