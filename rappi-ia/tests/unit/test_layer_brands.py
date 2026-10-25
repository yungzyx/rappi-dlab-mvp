import pytest

from rappi_ia.layers.brands import brand_index, infer_brand, load_brand_rules, norm_brand, roll_up

VERSION, RULES = load_brand_rules()


@pytest.mark.parametrize("raw", ["Coca-Cola", "COCA COLA", "Coca Cola S.A.", "cocacola", "Coca  Cola Ltda"])
def test_different_writings_of_a_brand_share_one_key(raw):
    assert norm_brand(raw, RULES).compact == norm_brand("Coca-Cola", RULES).compact


def test_a_line_is_not_the_same_key_as_its_brand_until_it_is_rolled_up():
    assert norm_brand("Soprole Next", RULES).compact != norm_brand("Soprole", RULES).compact


@pytest.mark.parametrize("raw", ["", "  ", "Nan", "Genérica", "Sin Marca", "-", "N/A", None])
def test_junk_trademarks_are_not_brands(raw):
    assert norm_brand(raw, RULES) is None


def test_roll_up_lines_under_a_big_enough_parent():
    counts = {
        "soprole": 190,
        "soprole next": 3,
        "coca cola": 50,
        "coca cola zero": 8,
        "san": 4,
        "san jose": 30,
        "ab": 99,
    }
    parent = roll_up(counts)
    assert parent["soprole next"] == "soprole" and parent["coca cola zero"] == "coca cola"
    assert parent["san jose"] == "san jose"  # «san» tiene menos de 10 productos: no es un padre
    assert parent["soprole"] == "soprole"


def test_a_parent_must_be_a_real_brand_not_a_word():
    parent = roll_up({"gran": 500, "gran reserva": 40, "lider": 200, "lider express": 5})
    assert (
        parent["lider express"] == "lider" and parent["gran reserva"] == "gran"
    )  # umbral por cantidad, no por palabra


def test_the_brand_is_read_from_the_start_of_the_name_only():
    index = brand_index({"soprole": 190, "tio nacho": 40, "pan": 45, "kraft": 30, "iphone": 9}, RULES)
    assert infer_brand("Soprole Leche Condensada", index) == "soprole"
    assert infer_brand("Tío Nacho Shampoo Keratina", index) == "tio nacho"
    assert infer_brand("Mayo Kraft Real 208g", index) is None  # en el medio: no
    assert infer_brand("Pan Hallulla", index) is None  # palabra común (name_stop)
    assert infer_brand("Lámina Iphone 12", index) is None
    assert infer_brand("", index) is None


def test_a_curated_family_is_the_parent_even_if_the_brand_alone_never_appears():
    counts = {"coca cola original": 29, "coca cola sin azucar": 17, "coca cola zero": 8}
    assert roll_up(counts)["coca cola zero"] == "coca cola zero"  # sin familia, ninguna marca padre declarada
    parent = roll_up(counts, frozenset({"coca cola"}))
    assert set(parent.values()) == {"coca cola"}
    assert norm_brand("Jack Daniel's", RULES).spaced == "jack daniels"


def test_inferred_brands_must_fit_the_concept_group_of_the_item():
    from rappi_ia.layers.brands import inference_ok

    declared = {"belleza": 40, "salud": 1}
    assert inference_ok(declared, "belleza") and not inference_ok(declared, "frescos")
    assert not inference_ok(declared, "salud")  # un solo ítem declarado no basta
    assert inference_ok(declared, None)  # sin concepto no se puede juzgar


def test_a_brand_must_appear_in_the_names_of_its_own_items_to_be_searched_in_other_names():
    from rappi_ia.layers.brands import name_support

    names = ["Corona Cerveza 330", "Corona Extra", "Cerveza Rubia", "Corona Light"]
    assert name_support("corona", names) == 0.75
    assert name_support("ao", ["Microlab Adaptador Vga", "Cable Hdmi"]) == 0


def test_curated_aliases_and_blocked_children():
    assert norm_brand("Kem Xtreme", RULES).spaced == "kem"
    assert norm_brand("La Roche", RULES).spaced == "la roche posay"
    parent = roll_up({"austral": 30, "austral organics": 8}, blocked=frozenset({"austral organics"}))
    assert parent["austral organics"] == "austral organics"


def test_store_brands_are_compared_without_spaces():
    assert "casaideas" in {s.replace(" ", "") for s in RULES.store_brands}
    assert norm_brand("Casa Ideas", RULES).compact == "casaideas"


def test_retailer_names_used_as_trademark_need_the_name_to_carry_them():
    from rappi_ia.layers.brands import trademark_fits

    assert not trademark_fits("Unimarc", "Hielo Nórdico 2 kg", RULES)
    assert trademark_fits("Unimarc", "Unimarc Arroz Grado 1", RULES)
    assert trademark_fits("Soprole", "Yoghurt Natural", RULES)


def test_families_are_searched_in_names_too():
    from rappi_ia.layers.brands import brand_index

    index = brand_index({"coca cola original": 29}, RULES)
    assert infer_brand("Coca Cola Lata 350 cc", index) == "coca cola"
    assert infer_brand("Casaideas Taza", index) == "casaideas"


def test_chain_names_lose_the_turbo_suffix():
    from rappi_ia.layers.brands import chain_name

    assert chain_name("Burger King Turbo") == chain_name("Burger King®") == "Burger King®".rstrip("®")
    assert chain_name("Mcdonald's - Turbo") == "Mcdonald's"
