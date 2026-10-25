import pytest

from rappi_ia.layers.attributes import detect_attributes, load_attribute_rules

VERSION, RULES = load_attribute_rules()


def _ids(found):
    return {d.attribute_id: d for d in found}


def _detect(entity_type="catalog_item", name="", category=None, description=None, rappi=None, group=None):
    return _ids(detect_attributes(entity_type, name, category, description, rappi, RULES, group))


def test_a_rappi_flag_wins_with_its_own_confidence_and_evidence():
    found = _detect(name="Pan de molde", rappi={"gluten_free": True})
    d = found["sin-gluten"]
    assert (d.source, d.confidence, d.evidence) == ("rappi", 0.95, "gluten_free")


def test_a_phrase_in_the_name_is_a_rule_with_its_evidence():
    d = _detect(name="Pan Sin Gluten")["sin-gluten"]
    assert (d.source, d.confidence, d.evidence) == ("regla", 0.8, "sin gluten")


def test_an_explicit_false_from_rappi_blocks_the_phrase():
    assert "sin-gluten" not in _detect(name="Pan Sin Gluten", rappi={"gluten_free": False})


def test_traces_warning_does_not_make_a_product_nut_free_and_contains_cancels():
    found = _detect(name="Galletas sin gluten", description="Puede contener trazas de maní.")
    assert "sin-gluten" in found and "sin-mani" not in found
    assert "sin-gluten" not in _detect(name="Galletas", description="Contiene gluten. Sin gluten no.")


def test_text_after_the_leaflet_warnings_does_not_count():
    found = _detect(name="Jarabe", description="Indicación: tos. Advertencias: producto sin azúcar no apto.")
    assert "sin-azucar" not in found


def test_rappi_values_set_the_attribute():
    assert "mujer" in _detect(name="Shampoo", rappi={"gender": "Femenino"})
    assert "adulto-mayor" in _detect(name="Vitaminas", rappi={"life_stage_human": "Adulto Mayor"})
    assert "perro" in _detect(name="Alimento", rappi={"type_of_pet": "Perro y Gato"})
    assert "gato" in _detect(name="Alimento", rappi={"type_of_pet": "Perro y Gato"})


def test_a_dish_gets_dish_attributes_and_never_product_only_ones():
    found = _detect("menu_item", name="Burger vegana picante para 2")
    assert {"vegano", "picante", "para-compartir"} <= set(found)
    assert "perro" not in _detect("menu_item", name="Perro caliente", rappi=None)  # solo productos
    assert "kosher" not in _detect("menu_item", name="Pizza kosher")


def test_hot_dog_is_not_spicy_and_a_dog_food_is_for_dogs():
    assert "picante" not in _detect("menu_item", name="Hot dog con tomate")
    assert "perro" in _detect(name="Alimento para perro adulto", group="mascotas")
    assert "perro" not in _detect(name="Perro caliente congelado", group="mascotas")


def test_pet_words_only_count_inside_the_pets_group():
    """«Gato Vino Cabernet» es un vino y «Audífonos Cat» no son para gatos; el campo de Rappi sí vale siempre."""
    assert "gato" not in _detect(name="Gato Vino Cabernet Sauvignon 1 L", group="alcohol")
    assert "gato" not in _detect(name="Audífonos Bluetooth Cat P47m", group="tecnologia")
    assert "gato" in _detect(name="Collar", rappi={"type_of_pet": "Gato"}, group="tecnologia")


def test_a_dish_description_lists_ingredients_so_only_diet_uses_it():
    found = _detect(
        "menu_item", name="Hamburguesa clásica", description="Con papas fritas y salsa picante. Sin gluten."
    )
    assert "frito" not in found and "picante" not in found and "con-acompanamiento" not in found
    assert "sin-gluten" in found
    assert "frito" in _detect("menu_item", name="Pollo frito")


def test_two_attributes_can_share_the_same_words():
    assert {"sin-azucar", "light"} <= set(_detect(name="Bebida Light sin azúcar", group="bebidas"))


def test_plural_and_singular_are_the_same_word():
    assert "ninos" in _detect(name="Juguete para niños") and "ninos" in _detect(name="Juguete para niño")


def test_every_attribute_has_family_and_unique_id():
    families = {"dieta", "alergenos", "publico", "formato", "precio", "origen", "sustentable", "ocasion", "platos"}
    ids = [r.attribute_id for r in RULES]
    assert len(ids) == len(set(ids)) and {r.family for r in RULES} <= families
    assert all(r.phrases or r.rappi or r.derived for r in RULES)


def test_only_declared_properties_are_read_from_a_product_description():
    """«Olla… apta para vidrio y microondas, hecha en Chile» no es un envase de vidrio ni un producto chileno."""
    description = "Apta para vidrio y microondas. Producto chileno. Sin gluten certificado."
    found = _detect(name="Olla de cocción 7 L", description=description)
    assert "vidrio" not in found and "chileno" not in found
    assert "sin-gluten" in found  # dieta sí se lee de la descripción


def test_baby_back_ribs_and_globe_bulbs_are_not_baby_or_birthday_items():
    assert "bebe" not in _detect("menu_item", name="Costillas Baby Back Ribs")
    assert "cumpleanos" not in _detect(name="Ampolleta Led Vintage Globo", category="Ampolletas")
    assert "cumpleanos" in _detect(name="Globos de cumpleaños x 20")


def test_phrases_never_start_with_a_symbol():
    """«+ papas» se normaliza a «papas»: todo plato con papas era «con acompañamiento»."""
    for rule in RULES:
        for phrase in (*rule.phrases, *rule.negations):
            assert phrase[0].isalnum(), (rule.attribute_id, phrase)
    assert "con-acompanamiento" not in _detect("menu_item", name="Papas Fritas (Caja Mediana)")
    assert "bebida-incluida" not in _detect("menu_item", name="Bebida 250 ML")
    assert "postre-incluido" not in _detect("menu_item", name="Postre de 3 Leches")
    assert "bebida-incluida" in _detect("menu_item", name="Hamburguesa mas bebida")


def test_one_person_is_not_shareable():
    assert "para-compartir" not in _detect("menu_item", name="Tequeños (X2)")


def test_diet_attributes_stay_inside_food_groups():
    assert "sin-alcohol" not in _detect(name="Enjuague bucal sin alcohol", group="salud")
    assert "sin-alcohol" in _detect(name="Cerveza sin alcohol", group="alcohol")
    assert "integral" not in _detect(name="Carcasa Otterbox protección integral", group="tecnologia")
    assert "integral" in _detect(name="Pan de molde integral", group="despensa")
    assert "light" not in _detect(name="Corrector Fit me Light", group="belleza")
    assert "light" in _detect(name="Mayonesa Light", group="despensa")
    assert "organico" not in _detect(name="Bandeja Estilo Moderno Organico", group="hogar")


def test_vegan_is_also_vegetarian():
    found = _detect(name="Hamburguesa vegana de lentejas")
    assert "vegano" in found and found["vegetariano"].source == "derivado"
    assert found["vegetariano"].evidence == "vegano"


@pytest.mark.parametrize(
    "name",
    [
        "Bebida Vegetal Barista Avena 1 L",
        "Leche De Almendras 1lt Sabor Original",
        "Vilay Bebida de Almendras Vainilla",
        "Leche de Coco Tarro 400 ml",
        "Notmilk Chocolate",
        "Mr. Seitán Bistec de Seitán",
    ],
)
def test_plant_drinks_and_seitan_are_vegan(name):
    found = _detect(name=name, group="frescos")
    assert "vegano" in found and "vegetariano" in found


@pytest.mark.parametrize(
    "name", ["Massaman Curry Pechuga de pollo en leche de coco", "Seitán Furay Queso Crema", "Cóctel con leche de coco"]
)
def test_plant_ingredient_phrases_do_not_make_a_dish_vegan(name):
    """«Leche de coco» o «seitán» en un plato es un ingrediente, no una garantía: solo valen en productos."""
    assert "vegano" not in _detect(entity_type="menu_item", name=name, group="comida")


@pytest.mark.parametrize("name", ["Leche Condensada Azucarada", "Bombón Nutella de Cabra", "Leche Entera 1 L"])
def test_milk_is_not_vegan_just_because_the_category_says_plant_milk(name):
    assert "vegano" not in _detect(name=name, category="Leche vegetal", group="frescos")


@pytest.mark.parametrize(
    ("name", "category", "absent"),
    [
        ("Family Set Pañuelos", None, "familiar"),
        ("Muñeca Baby Alive", "Muñecas y Bebés", "bebe"),
        ("Baby Doll Lencería", None, "bebe"),
        ("Manzana Pink Lady", None, "mujer"),
        ("Empanada de pino", None, "fiestas-patrias"),
        ("Azúcar Light con Stevia", None, "sin-azucar"),
        ("Bolso De Viaje", "Maletas y organizadores de viaje", "tamano-viaje"),
        ("Jumbo Crayones Gigante", None, "familiar"),
    ],
)
def test_phrases_that_matched_brands_and_proper_names_are_gone(name, category, absent):
    assert absent not in _detect(name=name, category=category)


def test_no_contiene_is_a_positive_claim_not_a_negation():
    found = _detect(name="Bebida de almendra", description="No contiene azúcar añadida. No contiene gluten.")
    assert {"sin-azucar", "sin-gluten"} <= set(found)
    assert "sin-gluten" not in _detect(name="Galletas", description="Contiene gluten de trigo.")


@pytest.mark.parametrize(
    ("name", "category", "description", "group", "absent"),
    [  # falsos positivos del juicio de precisión del 06-10-2026
        ("Papelillo Ocb Virgin 1 1/4", "Papel", "Papel de fibra vegetal con fibra natural", "tabaco", "alto-fibra"),
        ("Mascara De Pestañas Microfibras", "Máscaras", "Con fibra que alarga", "belleza", "alto-fibra"),
        ("Ama Jugo Tetra Manzana 200 mL", "Jugos", "Contiene ácidos orgánicos naturales", "bebidas", "organico"),
        ("Maybelline Corrector Instant Anti Age", "Correctores", None, "belleza", "instantaneo"),
        ("Smart Bracelet W9 Fitness Negro", "Relojes", None, "tecnologia", "saludable"),
        ("Herbal Acondicionador Detox Té Verde", "Acondicionador", None, "belleza", "saludable"),
    ],
)
def test_attributes_stay_with_what_the_product_is(name, category, description, group, absent):
    assert absent not in _detect(name=name, category=category, description=description, group=group)


@pytest.mark.parametrize(
    ("name", "absent"),
    [
        ("Pizza Pollo BBQ", "parrilla"),
        ("Costillas bbq 15cm", "parrilla"),
        ("Asado a la Olla con Agregado", "parrilla"),
        ("Camarón Enamorado", "san-valentin"),
        ("Fetuccini Enamorado", "san-valentin"),
    ],
)
def test_dish_names_that_only_sound_like_an_attribute(name, absent):
    assert absent not in _detect(entity_type="menu_item", name=name, group="comida")


def test_the_real_attributes_still_match():
    assert "alto-fibra" in _detect(name="Pan integral alto en fibra", group="despensa")
    assert "organico" in _detect(name="Quinoa orgánica 500 g", group="despensa")
    assert "instantaneo" in _detect(name="Café instantáneo 170 g", group="bebidas")
    assert "parrilla" in _detect(entity_type="menu_item", name="Lomo a la parrilla", group="comida")
    assert "san-valentin" in _detect(name="Caja de bombones San Valentín", group="dulces")


@pytest.mark.parametrize(
    ("name", "description", "group", "rappi", "absent"),
    [  # segunda tanda del juicio de precisión del 06-10-2026
        ("Gaseosa Coca-Cola 3 L", "Bebida sin alcohol", "bebidas", None, "sin-alcohol"),
        ("Listerine Enjuague Bucal Zero Alcohol", None, "salud", {"alcohol_free_pharma": True}, "sin-alcohol"),
        ("Aji-no-men Gallina Picante 80 G", None, "despensa", None, "hombre"),
        ("Fanta Naranja 1.5 L", "Bebida sin alcohol", "bebidas", None, "sin-alcohol"),
        ("Corte Criollo Tapapecho Premium", "Carne con fibra marcada", "frescos", None, "alto-fibra"),
    ],
)
def test_second_round_of_false_positives(name, description, group, rappi, absent):
    assert absent not in _detect(name=name, description=description, group=group, rappi=rappi)


def test_alcohol_free_beer_and_men_products_still_match():
    assert "sin-alcohol" in _detect(name="Cerveza Heineken 0.0 sin alcohol", group="alcohol")
    assert "hombre" in _detect(name="Desodorante Old Spice for men", group="salud")


@pytest.mark.parametrize("name", ["Nivea Men Crema Facial", "Dove Men+Care Desodorante", "Rexona Men Antitranspirante"])
def test_men_products_keep_the_men_attribute(name):
    assert "hombre" in _detect(name=name, group="belleza")


def test_alcohol_free_beer_with_a_soft_drink_concept_is_still_alcohol_free():
    assert "sin-alcohol" in _detect(name="Estrella Galicia Sin Alcohol 330 ml", group="bebidas")


def test_a_dish_without_a_concept_is_still_food_for_food_attributes():
    """Unos 14 mil platos quedaron sin concepto: sin grupo, «saludable» o «integral» no calzaban nunca."""
    assert "saludable" in _detect(entity_type="menu_item", name="Bowl saludable de quinoa", group=None)
    assert "saludable" not in _detect(entity_type="catalog_item", name="Pulsera fitness", group=None)
