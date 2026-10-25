"""Corrección de errores de tipeo (retrieval/spelling.py): las reglas sin base de datos."""

import pytest

from rappi_ia.retrieval import spelling


@pytest.mark.parametrize(
    ("a", "b", "distance"),
    [
        ("nutela", "nutella", 1),
        ("bodka", "vodka", 1),
        ("jhonnie", "johnnie", 1),  # trasposición: una sola edición
        ("hamburgesa", "hamburguesa", 1),
        ("cuchuflis", "cuchuflies", 1),
        ("sofa", "sofa", 0),
        ("carosi", "carozzi", 2),
    ],
)
def test_edit_distance_counts_a_transposition_as_one_edit(a, b, distance):
    assert spelling.edit_distance(a, b) == distance


def test_transpositions_are_candidates_of_their_own():
    """Los trigramas casi no ven una trasposición en una palabra corta: se buscan tal cual."""
    assert "oliva" in spelling.transpositions("olvia")
    assert spelling.transpositions("aab") == ["aba"]  # dar vuelta dos letras iguales no cambia nada


def test_a_double_letter_can_be_single():
    assert spelling.single_forms("oreoo") == ["oreo"]
    assert spelling.single_forms("pinno") == ["pino"]
    assert spelling.single_forms("arroz") == ["aroz"]
    assert spelling.single_forms("pisco") == []


def test_repeated_letters_collapse_to_one_or_two():
    assert spelling.repeat_forms("cervezaaaa") == ["cerveza", "cervezaa"]
    assert spelling.repeat_forms("piscooo") == ["pisco", "piscoo"]
    assert spelling.repeat_forms("cerveza") == []  # sin una letra tres veces seguidas, nada que probar
    assert spelling.repeat_forms("lleeeeche") == ["lleche", "lleeche"]


def test_choose_prefers_the_closest_word_and_then_the_most_common():
    candidates = [("nutella", 964), ("nutellla", 1), ("nutelatte", 1)]
    assert spelling.choose("nutela", 0, candidates) == "nutella"
    # Dos a una edición: gana la que más documentos tiene.
    assert spelling.choose("heladoo", 0, [("helado", 300), ("helados", 900), ("heladera", 18)]) == "helados"
    assert spelling.choose("bluetoth", 0, [("bluetooh", 17), ("bluetooth", 413)]) == "bluetooth"  # no la errata
    assert spelling.choose("aspirna", 0, [("aspira", 2), ("aspirina", 2)]) == "aspirina"  # empate: falta una letra


def test_choose_needs_a_word_the_vertical_has_ten_times_more():
    # «nutela» aparece en 4 platos (con el error del restaurante): «nutella», en 964.
    assert spelling.choose("nutela", 4, [("nutella", 964)]) == "nutella"
    assert spelling.choose("nutela", 4, [("nutella", 39)]) is None


def test_choose_leaves_short_words_and_far_words_alone():
    assert spelling.choose("sofa", 0, [("soft", 50)]) is None  # bajo 6 letras, un cambio suele ser otra palabra
    assert spelling.choose("tonto", 0, [("tinto", 500)]) is None
    assert spelling.choose("lenobo", 0, [("lenovo", 14)]) == "lenovo"  # 6 letras: una edición
    assert spelling.choose("lenobo", 0, [("lenovos", 50)]) is None
    assert spelling.choose("carosi", 0, [("carozzi", 80)]) is None  # dos ediciones solo desde 9 letras
    assert spelling.choose("cancelar", 0, [("canela", 900)]) is None
    assert spelling.choose("paracetamool", 0, [("paracetamol", 300)]) == "paracetamol"
    assert spelling.choose("chorrillanaa", 0, [("chorillana", 30)]) == "chorillana"  # 9 letras o más: dos


def test_choose_skips_a_word_with_the_same_root():
    """La búsqueda léxica ya junta «cuerpos» con «cuerpo»: cambiarla no busca nada distinto y solo ensucia el aviso.
    La raíz la da Postgres (`_excluded`, que también saca las stopwords)."""
    assert spelling.choose("cuerpos", 1, [("cuerpo", 30)], frozenset({"cuerpo"})) is None
    assert spelling.choose("trufass", 0, [("trufas", 30), ("trufa", 50)], frozenset()) == "trufas"
    assert spelling.choose("heladoo", 0, [("helado", 300), ("helados", 900)], frozenset({"helados"})) == "helado"


def test_words_to_skip_are_fillers_of_spoken_requests():
    words = spelling.query_words("Eh, quiero este... una Coca porfa")
    assert [w.surface for w in words if not w.skip] == ["coca"]
    # En medio de la frase quedan: sin ellas sería otra consulta.
    assert [w.surface for w in spelling.query_words("te quiero mochi") if not w.skip] == ["te", "quiero", "mochi"]
    assert [w.surface for w in spelling.query_words("no guardes lo que busco") if w.skip] == []
    assert [w.surface for w in spelling.query_words("mmm una coca") if not w.skip] == ["coca"]
    # Un saludo de dos palabras también es una búsqueda: «tardes de lluvia», «buenos aires».
    assert not any(w.skip for w in spelling.query_words("tardes de lluvia"))
    assert not any(w.skip for w in spelling.query_words("buenos aires"))
    # Una frase larga es una conversación: se busca entera.
    assert not any(w.skip for w in spelling.query_words("necesito que me compren algo en una ferretería"))
    assert all(w.skip for w in spelling.query_words("holaaaa"))
    assert [w.surface for w in spelling.query_words("Pañales talla G")] == ["pañales", "talla", "g"]
    assert [w.word for w in spelling.query_words("Pañales talla G")] == ["panales", "talla", "g"]


def test_a_typo_is_recovered_when_it_shows_as_much_of_what_was_meant():
    from rappi_ia.eval.typo_eval import is_meant, recovered

    assert is_meant("Huggies Pañal Natural Care Recién Nacido", "pañales huggies")
    assert not is_meant("Pampers Pañales Premium Care", "pañales huggies")
    assert is_meant("Papas Fritas Individual", "papas fritas")
    shown = ["Cerveza Corona", "Cerveza Escudo", "Maní salado", "Cerveza Kunstmann", "Hielo"]
    assert recovered(False, shown, "cerveza", 3)
    assert not recovered(False, shown[2:], "cerveza", 3)
    assert recovered(False, shown[2:], "cerveza", 1)  # lo que se quiso escribir trae uno solo: basta ese
    assert not recovered(True, shown, "cerveza", 3)  # «sin resultado» nunca se recupera
    assert not recovered(False, shown, "cerveza", 0)  # sin nada que comparar, no mide
