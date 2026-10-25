"""«de el» → «del» y «a el» → «al»: las plantillas interpolan etiquetas como «el súper» después de «de» o «a»."""

from rappi_ia.text import contract_articles


def test_de_el_becomes_del():
    assert contract_articles("Aún no pruebas lo de el súper.") == "Aún no pruebas lo del súper."
    assert contract_articles("Tu kit «Once»: pan, de el súper y Express.") == "Tu kit «Once»: pan, del súper y Express."


def test_a_el_becomes_al():
    assert contract_articles("Vamos a el súper.") == "Vamos al súper."


def test_proper_names_and_other_words_are_left_alone():
    assert contract_articles("Un plato de El Bodegón") == "Un plato de El Bodegón"
    assert contract_articles("Para el súper, en el súper, de Express") == "Para el súper, en el súper, de Express"
    assert contract_articles("de elote y a elegir") == "de elote y a elegir"  # solo el artículo entero
    assert contract_articles("") == ""
