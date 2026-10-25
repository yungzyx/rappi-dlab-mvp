"""Regla de decisión del kNN: cuándo los vecinos confirman, reemplazan o no tocan el concepto actual."""

import numpy as np
import pytest

from rappi_ia.concepts.assign import Assignment
from rappi_ia.concepts.knn import ItemText, _decide, _labels

ITEM = ItemText("catalog_item", "1", "Wok Surtidos GRA30BV11")
MODEL = "knn/test"


def _current(concept: str, method: str, confidence: float = 0.9) -> Assignment:
    return Assignment("catalog_item", "1", concept, method, confidence, None, "x")


def _neighbors(concepts: list[str], sim: float = 0.9):
    return np.full(len(concepts), sim, dtype=np.float32), np.array(concepts)


def test_neighbors_confirm_current_concept_and_raise_confidence():
    sims, concepts = _neighbors(["cocina-menaje"] * 15)
    decision = _decide(_current("cocina-menaje", "llm", 0.7), ITEM, sims, concepts, MODEL)
    assert (decision.concept_id, decision.method, decision.confidence) == ("cocina-menaje", "llm", 1.0)


def test_neighbors_replace_a_keyword_rule_only_with_strong_agreement():
    """Con mayoría simple (60 %) los vecinos acertaban el 35 % en platos (juicio de precisión del 06-10-2026)."""
    sims, concepts = _neighbors(["cocina-menaje"] * 13 + ["asiatica"] * 2)
    decision = _decide(_current("asiatica", "regla", 0.7), ITEM, sims, concepts, MODEL)
    assert (decision.concept_id, decision.method, decision.model_version) == ("cocina-menaje", "embedding", MODEL)
    assert "antes x" in decision.source
    rule = _current("asiatica", "regla", 0.7)
    assert _decide(rule, ITEM, *_neighbors(["cocina-menaje"] * 9 + ["asiatica"] * 6), MODEL) == rule


def test_neighbors_override_category_only_with_strong_agreement():
    strong = _neighbors(["computacion"] * 13 + ["accesorios-mascota"] * 2)
    weak = _neighbors(["computacion"] * 9 + ["accesorios-mascota"] * 6)
    category = _current("accesorios-mascota", "llm", 0.9)
    assert _decide(category, ITEM, *strong, MODEL).concept_id == "computacion"
    assert _decide(category, ITEM, *weak, MODEL) == category


def test_unassigned_item_gets_concept_only_with_strong_agreement():
    assert _decide(None, ITEM, *_neighbors(["cafe"] * 13 + ["te"] * 2), MODEL).concept_id == "cafe"
    assert _decide(None, ITEM, *_neighbors(["cafe"] * 10 + ["te"] * 5), MODEL) is None  # 67 %: no alcanza
    split = ["cafe"] * 5 + ["te"] * 5 + ["galletas"] * 5
    assert _decide(None, ITEM, *_neighbors(split), MODEL) is None


def test_closer_neighbors_weigh_more():
    sims = np.array([0.95] * 5 + [0.40] * 10, dtype=np.float32)
    concepts = np.array(["pizza"] * 5 + ["pastas"] * 10)
    assert _decide(None, ITEM, sims, concepts, MODEL).concept_id == "pizza"


def test_a_rule_needs_strong_agreement_to_enter_a_sensitive_concept():
    """«Wrap» con 60 % de vecinos papelillos quedaba como accesorio para fumar (y oculto en la búsqueda)."""
    item = ItemText("catalog_item", "1", "Wrap Integral Pack 6")
    rule = Assignment("catalog_item", "1", "panaderia", "regla", 0.7, None, "nombre:wrap")
    majority = _neighbors(["accesorios-fumador"] * 9 + ["panaderia"] * 6)
    strong = _neighbors(["accesorios-fumador"] * 13 + ["panaderia"] * 2)
    assert _decide(rule, item, *majority, MODEL) == rule
    assert _decide(rule, item, *strong, MODEL).concept_id == "accesorios-fumador"
    dish = ItemText("menu_item", "1", "Hand Rolls Opc 1")  # un plato que nombra un plato no se mueve
    sushi = Assignment("menu_item", "1", "sushi", "regla", 0.7, None, "nombre:rolls")
    assert _decide(sushi, dish, *strong, MODEL) == sushi


def test_an_unassigned_item_still_enters_a_sensitive_concept_with_majority():
    """Medicamentos sin categoría («Panadol (160 mg)») los encuentra el kNN con mayoría: sin concepto, la búsqueda
    no los filtraría como sensibles."""
    neighbors = _neighbors(["medicamentos"] * 9 + ["vitaminas"] * 6)
    assert _decide(None, ITEM, *neighbors, MODEL).concept_id == "medicamentos"


def test_a_sensitive_rule_moves_to_another_sensitive_concept_with_majority():
    tobacco = _current("cigarrillos", "regla", 0.7)
    decision = _decide(tobacco, ITEM, *_neighbors(["accesorios-fumador"] * 9 + ["cigarrillos"] * 6), MODEL)
    assert decision.concept_id == "accesorios-fumador"


def test_neighbors_never_replace_the_name_of_a_dish_that_names_a_dish():
    """«Pollo Asado Entero + Bebida» quedaba como sushi: los combos con bebida se parecen entre sí."""
    dish = ItemText("menu_item", "1", "Pollo Asado Entero + Bebida 1.5 L")
    roast = Assignment("menu_item", "1", "pollo-preparado", "regla", 0.7, None, "nombre:pollo asado")
    assert _decide(roast, dish, *_neighbors(["sushi"] * 15), MODEL) == roast


def test_neighbors_still_fix_a_flavour_word_and_keep_a_protein_word():
    """«Pistacho» en una heladería es un helado (la palabra es un sabor); «Pescado frito - reineta» es pescado."""
    flavour = Assignment("menu_item", "1", "frutos-secos", "regla", 0.7, None, "nombre:pistacho")
    gelato = ItemText("menu_item", "1", "Pistacho")
    assert _decide(flavour, gelato, *_neighbors(["helados"] * 15), MODEL).concept_id == "helados"
    fish = Assignment("menu_item", "2", "pescados-mariscos", "regla", 0.7, None, "nombre:pescado")
    dish = ItemText("menu_item", "2", "PESCADO FRITO - REINETA")
    assert _decide(fish, dish, *_neighbors(["platos-listos"] * 15), MODEL) == fish


def test_jev_assignments_do_not_vote_as_knn_labels():
    """Un mapeo de Jev lo hizo una máquina sin revisión: no sirve de etiqueta para los vecinos de otros productos."""
    items = [ItemText("catalog_item", str(i), f"Producto {i}") for i in range(3)]
    current = {
        ("catalog_item", str(i)): Assignment("catalog_item", str(i), "cerveza", method, 0.9, None, "x")
        for i, method in enumerate(["curado", "llm", "jev"])
    }
    label_idx, label_concepts = _labels(items, current)
    assert sorted(label_idx) == [0, 1] and label_concepts == ["cerveza", "cerveza"]


SOY = ItemText("catalog_item", "1", "Kikkoman Salsa de Soya")
REFINED = Assignment("catalog_item", "1", "despensa-asiatica", "regla", 0.7, None, "nombre:salsa de soya", "salsas")


def test_neighbors_do_not_undo_an_asian_name_that_refined_a_food_category():
    """Las vecinas de «Kikkoman Salsa de Soya» son las salsas de su categoría: votarían salsas y deshacían la regla."""
    assert _decide(REFINED, SOY, *_neighbors(["salsas"] * 15), MODEL) == REFINED


@pytest.mark.parametrize("voted", ["cerveza", "vapeo", "juguetes-infantiles"])
def test_alcohol_sensitive_and_non_food_neighbors_still_win_over_a_refined_name(voted):
    assert _decide(REFINED, SOY, *_neighbors([voted] * 15), MODEL).concept_id == voted


def test_an_asian_name_without_a_food_category_is_an_ordinary_rule():
    """«Peluche Bubble Tea» sin categoría (o con una dudosa): sus vecinas lo corrigen como a cualquier regla."""
    item = ItemText("catalog_item", "1", "Peluche Bubble Tea")
    rule = Assignment("catalog_item", "1", "bebidas-asiaticas", "regla", 0.7, None, "nombre:bubble tea")
    assert _decide(rule, item, *_neighbors(["juguetes-infantiles"] * 15), MODEL).concept_id == "juguetes-infantiles"
    assert _decide(rule, item, *_neighbors(["te"] * 15), MODEL).concept_id == "te"


@pytest.mark.parametrize(("current", "voted"), [("cocteles", "cafe"), ("alimentacion-bebe", "lacteos")])
def test_neighbors_never_take_a_product_out_of_alcohol_or_baby(current, voted):
    """En la base real del 14-10-2026 un «Espresso Martini» listo pasaba a café y una fórmula Similac a lácteos."""
    category = _current(current, "llm", 0.9)
    assert _decide(category, ITEM, *_neighbors([voted] * 15), MODEL) == category


def test_neighbors_still_move_a_product_between_alcohol_concepts():
    assert _decide(_current("cocteles", "llm", 0.9), ITEM, *_neighbors(["pisco"] * 15), MODEL).concept_id == "pisco"


def test_neighbors_still_fix_a_dish_that_only_names_a_drink():
    """«Pizza Margarita» calza la regla de cócteles; en los platos los vecinos la devuelven a pizza (y las ofertas
    bloquean el alcohol de un menú por el nombre y la sección)."""
    dish = ItemText("menu_item", "1", "Margarita Familiar")
    rule = Assignment("menu_item", "1", "cocteles", "regla", 0.7, None, "nombre:margarita")
    assert _decide(rule, dish, *_neighbors(["pizza"] * 15), MODEL).concept_id == "pizza"


def test_neighbors_never_take_a_dish_out_of_the_alcohol_its_section_gave():
    """«Jengibre Sour» de una sección «Aperitivos» (base real del 22-10-2026) pasaba de licores a salsas, y «sour» con
    salsas es la salsa agridulce para las guardias: se podía ofrecer. Lo que la sección deja en alcohol ya pasó por la
    comida que la sección no decide (`assign._solid_food`)."""
    dish = ItemText("menu_item", "1", "Jengibre Sour. Bebida de jengibre con un toque ácido, ideal como aperitivo.")
    section = Assignment("menu_item", "1", "licores", "regla", 0.7, None, "seccion-nombre:Aperitivos")
    assert _decide(section, dish, *_neighbors(["salsas"] * 15), MODEL) == section
    assert _decide(section, dish, *_neighbors(["pisco"] * 15), MODEL).concept_id == "pisco"  # entre alcoholes, sí
