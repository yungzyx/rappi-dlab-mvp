from rappi_ia.layers.canonical import name_key

COCA = {"coca", "cola"}


def test_the_same_product_written_two_ways_has_one_key():
    a = name_key("Coca-Cola Original 1.5L", COCA)
    b = name_key("Coca Cola Original 1,5 L", COCA)
    assert a == b == "original"


def test_the_size_and_the_pack_do_not_make_a_different_product():
    assert name_key("Cerveza Cristal Lata 6 x 350 ml", {"cristal"}) == name_key(
        "Cristal Cerveza Lata 350 cc", {"cristal"}
    )


def test_variants_that_change_the_product_stay_apart():
    assert name_key("Coca-Cola Zero 1.5L", COCA) != name_key("Coca-Cola Original 1.5L", COCA)
    assert name_key("Leche Sin Lactosa 1 L", {"colun"}) != name_key("Leche Con Lactosa 1 L", {"colun"})


def test_model_numbers_are_kept():
    assert name_key("Cargador iPhone 20W", {"apple"}) != name_key("Cargador iPhone 35W", {"apple"})


def test_word_order_does_not_matter():
    assert name_key("Original Coca-Cola 1.5 L", COCA) == name_key("Coca-Cola Original 1.5 L", COCA)


def test_dimensions_and_model_numbers_survive_the_pack_noise_removal():
    assert name_key("Pizarra Blanca 20 x 30 cm", set()) != name_key("Pizarra Blanca 40 x 30 cm", set())
    assert name_key("Hoco Audífonos X12", {"hoco"}) != name_key("Hoco Audífonos X15", {"hoco"})
    assert name_key("Pañal Talla 1 x 50", set()) != name_key("Pañal Talla 2 x 50", set())


def test_unit_counts_are_part_of_the_product():
    """«12 Unidades» y «4 Unidades» (o un pack y la unidad) no son el mismo producto aunque ambos midan «1 und»."""
    assert name_key("Your Goal 12 Unidades", {"your", "goal"}) != name_key("Your Goal 4 Unidades", {"your", "goal"})
    assert name_key("Duracell Aa 1 Unidad", {"duracell"}) != name_key("Duracell Aa 2 Unidades", {"duracell"})
    assert name_key("Soprole Yoghurt Pack", {"soprole"}) != name_key("Soprole Yoghurt", {"soprole"})


def test_filler_words_and_the_run_together_brand_do_not_split_a_product():
    brand = {"coca", "cola", "cocacola"}
    assert name_key("Coca-Cola Bebida Gaseosa Original 1.5L", brand) == name_key("Cocacola Original 1,5 L", brand)


def test_a_combo_has_no_canonical_key():
    assert name_key("Alto 1lt + Coca 1.5lt", set()) == ""
