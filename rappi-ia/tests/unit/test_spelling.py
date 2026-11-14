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
    # "nutela" aparece en 4 platos (con el error del restaurante): "nutella", en 964.
    assert spelling.choose("nutela", 4, [("nutella", 964)]) == "nutella"
    assert spelling.choose("nutela", 4, [("nutella", 39)]) is None


def test_choose_leaves_short_words_and_far_words_alone():
    assert spelling.choose("sofa", 0, [("soft", 50)]) is None  # bajo 5 letras, un cambio suele ser otra palabra
    assert spelling.choose("tonto", 0, [("tinto", 500)]) is None  # con 5, solo una letra que suena igual
    assert spelling.choose("lenobo", 0, [("lenovo", 14)]) == "lenovo"  # 6 letras: una edición
    assert spelling.choose("lenobo", 0, [("lenovos", 50)]) is None
    assert spelling.choose("carosi", 0, [("carozzi", 80)]) is None  # dos ediciones solo desde 9 letras
    assert spelling.choose("cancelar", 0, [("canela", 900)]) is None
    assert spelling.choose("paracetamool", 0, [("paracetamol", 300)]) == "paracetamol"
    assert spelling.choose("chorrillanaa", 0, [("chorillana", 30)]) == "chorillana"  # 9 letras o más: dos


def test_a_five_letter_word_changes_only_a_letter_that_sounds_alike():
    """Con 5 letras, solo la única candidata a una edición con mucho más uso, y solo si suena igual: "suchi" (16 platos,
    los de un local que se llama así) → "sushi" (45 mil)."""
    assert spelling.choose("suchi", 16, [("sushi", 45008), ("such", 2)]) == "sushi"
    assert spelling.choose("arros", 0, [("arroz", 18741)]) == "arroz"
    assert spelling.choose("bodka", 0, [("vodka", 356)]) == "vodka"
    assert spelling.choose("quezo", 0, [("queso", 900)]) == "queso"
    assert spelling.choose("mckai", 0, [("mckay", 93)]) == "mckay"
    assert spelling.choose("suchi", 0, [("sushi", 500), ("suchi", 400)]) == "sushi"  # la escrita no es candidata


@pytest.mark.parametrize(
    ("word", "own", "candidates"),
    [
        ("tonto", 0, [("tinto", 500)]),  # una vocal cambiada es otra palabra
        ("palta", 0, [("plata", 593)]),  # dos letras dadas vuelta, también
        ("cosas", 0, [("casas", 300)]),
        ("sprit", 0, [("sprite", 200)]),  # una letra de más o de menos no es una letra que suena igual
        ("amrgo", 0, [("amargo", 41)]),
        ("pisza", 0, [("pizza", 9692), ("pieza", 246)]),  # dos candidatas: no se sabe cuál quiso
        ("suchi", 16, [("sushi", 1000)]),  # no 100 veces más que la escrita
        ("bodka", 0, [("vodka", 19)]),  # la candidata no es una palabra real del catálogo
    ],
)
def test_a_five_letter_word_is_left_alone_otherwise(word, own, candidates):
    assert spelling.choose(word, own, candidates) is None


def test_sound_alike_letters():
    assert spelling.sound_alike("suchi", "sushi")
    assert spelling.sound_alike("bodka", "vodka")
    assert spelling.sound_alike("gabon", "jabon")
    assert not spelling.sound_alike("tonto", "tinto")
    assert not spelling.sound_alike("sofa", "soft")
    assert not spelling.sound_alike("pissa", "pizza")  # dos letras
    assert not spelling.sound_alike("sprit", "sprite")


def test_one_edit_forms_are_every_word_one_edit_away():
    forms = spelling.one_edit_forms("suchi")
    assert {"sushi", "such", "suchis", "scuhi", "sachi"} <= set(forms)
    assert "suchi" not in forms
    assert all(spelling.edit_distance("suchi", form) == 1 for form in forms)


def test_choose_skips_a_word_with_the_same_root():
    """La búsqueda léxica ya junta "cuerpos" con "cuerpo": cambiarla no busca nada distinto y solo ensucia el aviso.
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
    # Un saludo de dos palabras también es una búsqueda: "tardes de lluvia", "buenos aires".
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
    assert not recovered(True, shown, "cerveza", 3)  # "sin resultado" nunca se recupera
    assert not recovered(False, shown, "cerveza", 0)  # sin nada que comparar, no mide


@pytest.mark.parametrize("query", ["sushi barato", "pizza barata", "cerveza economica", "vino caro", "whisky premium"])
def test_price_words_are_never_corrected(query, monkeypatch):
    """ "sushi barato" pasaba a "sushi barto" (una palabra de un solo plato): el orden por precio no es un error."""
    asked = []

    def fixes(_conn, _vertical, words, _matched=False):
        asked.extend(words)
        return {word: word[:-1] for word in words}  # cambiaría cualquier palabra que le pidan

    monkeypatch.setattr(spelling, "_fixes", fixes)
    assert spelling.correct_query(None, query, "restaurantes") is None
    assert not set(asked) & spelling.PRICE_WORDS


def test_with_a_match_only_a_fixed_name_changes_the_query(monkeypatch):
    """Con algo que ya calza (`matched`), sacar las muletillas no es una corrección, y el nombre no se corrige si la
    consulta trae otra palabra de ese mismo nombre ("suchi tacna" busca el local)."""
    monkeypatch.setattr(
        spelling, "_fixes", lambda _c, _v, words, _m=False: {"suchi": "sushi"} if "suchi" in words else {}
    )
    monkeypatch.setattr(spelling, "name_words", lambda _c, word: frozenset({"suchi", "tacna", "antofagasta"}))
    assert spelling.correct_query(None, "eh quiero un sushi", "restaurantes", matched=True) is None
    assert spelling.correct_query(None, "hand roll suchi", "restaurantes", matched=True) == "hand roll sushi"
    assert spelling.correct_query(None, "suchi tacna", "restaurantes", matched=True) is None
