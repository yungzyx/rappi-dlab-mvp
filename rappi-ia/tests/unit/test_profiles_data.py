"""Perfiles de gusto y destinos (offers/perfiles.toml y offers/destinos.toml): los datos y su validación."""

import pytest
from rappi_scraper.storage.search import VERTICALS

from rappi_ia.concepts.taxonomy import load_complements, load_taxonomy
from rappi_ia.layers.segments import load_segment_rules
from rappi_ia.offers.guards import is_offerable, offerable_vertical
from rappi_ia.offers.profiles import load_destinations, load_profiles

# (vertical, conceptos, palabras) de cada peldaño, en orden: la tabla de la especificación.
LADDERS = {
    "asiatico": [
        ("restaurantes", ("sushi", "asiatica"), ()),
        ("turbo", ("despensa-asiatica",), ()),
        ("conveniencia", ("snacks-asiaticos", "bebidas-asiaticas"), ()),
        ("supermercado", ("despensa-asiatica", "bebidas-asiaticas"), ()),
        ("chocolateria", ("chocolates", "te"), ("matcha",)),  # Lindor Matcha está en la categoría «Tés»
    ],
    "cafe": [
        ("supermercado", ("cafe",), ()),
        ("turbo", ("cafe",), ()),
        ("conveniencia", ("cafe",), ()),
        (
            "mall",
            ("electrohogar", "cocina-menaje"),
            ("cafetera", "molinillo de cafe", "molinillo electrico", "prensa francesa"),
        ),
        ("chocolateria", ("chocolates",), ("cafe",)),  # las palabras quedan sin tildes, como se comparan
    ],
    "italiano": [
        ("supermercado", ("pastas", "quesos", "salsas", "aceites-condimentos"), ()),
        ("conveniencia", ("pastas", "salsas"), ()),
        ("turbo", ("quesos", "pastas"), ()),
        ("mall", ("cocina-menaje",), ("pizza", "rallador", "pasta")),
        ("chocolateria", ("postres", "pasteleria"), ("tiramis", "cannoli", "amaretti", "panettone")),
    ],
    "mascotas": [
        ("conveniencia", ("alimento-perro",), ()),
        ("turbo", ("alimento-perro",), ()),
        ("mall", ("accesorios-mascota",), ("perro", "juguete", "pelota", "correa", "collar", "arnes")),
        ("supermercado", ("alimento-perro",), ()),  # el perfil es de perro: sin comida de gato
    ],
    "carrete": [
        ("turbo", ("hielo", "gaseosas"), ()),
        ("conveniencia", ("snacks-salados",), ()),
        ("supermercado", ("frutos-secos", "snacks-salados", "salsas"), ()),
        ("mall", ("decoracion",), ("vaso", "guirnalda", "globo", "cotillon")),
        ("restaurantes", ("pizza", "picoteo"), ()),
    ],
}
SEGMENTS = {
    "asiatico": ("sushi", "asiatica", "japonesa", "china"),
    "cafe": ("cafetero", "cafe-de-especialidad"),
    "italiano": ("italiana", "pastas", "pizzero"),
    "mascotas": ("tiene-perro",),
    "carrete": ("fiestero",),
}
TRIPS = {"asiatico": "japon", "cafe": "colombia", "italiano": "italia", "mascotas": None, "carrete": None}


def test_the_five_profiles_load_and_the_asian_one_is_the_only_main():
    profiles = load_profiles()
    assert list(profiles) == ["asiatico", "cafe", "italiano", "mascotas", "carrete"]
    assert [p.id for p in profiles.values() if p.main] == ["asiatico"]
    asian = profiles["asiatico"]
    assert (asian.name, asian.emoji, asian.min_level) == ("Amante de lo asiático", "🥢", "medio")
    assert all(p.min_level == "medio" for p in profiles.values())


def test_ladders_segments_and_trips_follow_the_spec():
    for profile in load_profiles().values():
        assert [(s.vertical, s.concepts, s.words) for s in profile.ladder] == LADDERS[profile.id], profile.id
        assert profile.segments == SEGMENTS[profile.id]
        assert profile.trip == TRIPS[profile.id]
        assert all(step.text for step in profile.ladder)


def test_every_concept_vertical_and_segment_exists():
    concepts = load_taxonomy().concepts
    segments = {rule.id: rule for rule in load_segment_rules()[1]}
    for profile in load_profiles().values():
        assert all(s in segments and not segments[s].sensitive for s in profile.segments), profile.id
        for step in profile.ladder:
            assert step.vertical in VERTICALS
            assert all(c in concepts for c in step.concepts), (profile.id, step.concepts)


def test_no_step_names_what_the_offer_guards_block():
    concepts = load_taxonomy().concepts
    for profile in load_profiles().values():
        for step in profile.ladder:
            assert offerable_vertical(step.vertical), (profile.id, step.vertical)
            assert all(is_offerable(concepts[c]) for c in step.concepts), (profile.id, step.concepts)


def test_the_party_profile_has_no_alcohol():
    concepts = load_taxonomy().concepts
    named = [concepts[c] for step in load_profiles()["carrete"].ladder for c in step.concepts]
    assert not [c.id for c in named if c.age_restricted or c.parent == "alcohol"]


# Nombres de la base real (14-10-2026) que calzan o no un peldaño con palabras: la palabra va al comienzo de una
# palabra del nombre, y `evitar` saca lo que dice la palabra sin ser lo que promete el peldaño (un limpiador «en pasta»,
# juguetes de cocina con concepto `cocina-menaje`).
@pytest.mark.parametrize(
    ("profile", "vertical", "name", "fits"),
    [
        ("carrete", "mall", "Vaso Polipapel Lunares Colores Surtidos", True),
        ("carrete", "mall", "Guirnalda Feliz Cumpleaños Unicornio Grande", True),
        ("carrete", "mall", "Posavasos Chile X 6", False),
        ("carrete", "mall", "Alfombra Mat Secavasos de Goma 38 x 51 cm Casaideas", False),
        ("italiano", "mall", "Cortador Pizza O Ruleta Mt", True),
        ("italiano", "mall", "Olla Para Pasta 24 Cm, 5 Piezas. Magehogar", True),
        ("italiano", "mall", "Rallador y Rebanador Manual Sumo Slicer", True),
        ("italiano", "mall", "Limpia Ollas En Pasta De 500 Gr Para Aceros Y Cocinas.", False),
        ("italiano", "mall", "Juego De Pizza De Madera Melissa & Doug", False),
        ("italiano", "mall", "Set De Pastas Hape", False),
        ("italiano", "chocolateria", "Tiramisú individual", True),
        ("cafe", "mall", "Cafetera Francesa de Vidrio 600 mL", True),
        ("cafe", "mall", "Cafetera + Accesorios Hape Juguetes De Madera", False),
        ("cafe", "mall", "Molinillo Eléctrico De Café Y Granos 150w Color Cromo", True),
        ("cafe", "mall", "Molinillo de Sal Néctar 21 cm Le Creuset", False),  # de sal y pimienta, no de café
        ("cafe", "mall", "Set de Molinillos S&P Cereza 11 cm Le Creuset", False),
        ("carrete", "mall", 'Guirnalda Globo Foil "un Pene Forever" Rose Gold', False),  # despedida de soltera
        ("carrete", "mall", "Set Globo Metálico Soltera Corbatín", False),
        ("mascotas", "mall", "Buddy Pet Pelota Con Cuerda Para Perros", True),
        ("mascotas", "mall", "Set Libros Para Colorear Casaideas", False),  # en «Otros accesorios mascotas»
        ("mascotas", "mall", "Puzzle Redondo 500 Piezas Perros Del Mundo", False),
        ("mascotas", "mall", "Rascador Para Gatos Con Pelota", False),  # el perfil es de perro
        ("mascotas", "mall", "Collar Para Gato Con Cascabel", False),
        ("mascotas", "mall", "Arnés Para Gatito Ajustable", False),
        # Marcado alimento-perro en la base real.
        ("mascotas", "supermercado", "Royal Canin Alimento para Gato Gastrointestinal", False),
        ("mascotas", "supermercado", "Pedigree Alimento para Perro Adulto", True),
        ("cafe", "chocolateria", "Bombones de Café", True),
        ("asiatico", "chocolateria", "Lindor Matcha", True),
        ("asiatico", "chocolateria", "Lindor Leche", False),
        ("asiatico", "turbo", "Kikkoman Salsa de Soya", True),  # sin palabras, calza todo
        # La despensa italiana no es ketchup, mayonesa ni ramen (salían en el súper y en Express de la base real).
        ("italiano", "supermercado", "Kraft Aderezo de Mayonesa", False),
        ("italiano", "supermercado", "Heinz Salsa de Tomate Ketchup", False),
        ("italiano", "supermercado", "Gourmet Salsa Pesto Receta Italiana", True),
        ("italiano", "conveniencia", "Hellmann's Salsa de Tomate Ketchup", False),
        ("italiano", "conveniencia", "Ramen Tostado Instantáneo Yakisoba Nissin 100 Gr", False),
        ("italiano", "conveniencia", "Mostaza Dijon 200 g", False),
        ("italiano", "conveniencia", "Coliseo Pasta Fettuccine Speciale", True),
        ("italiano", "mall", "Plato de Pizza Perruno 22 x 1 x 22 cm Casaideas", False),  # un plato para perro
        ("carrete", "mall", "Corona Blanca Guirnalda Feliz Navidad Decoración De Hogar Puertas 40 Cm", False),
    ],
)
def test_a_step_with_words_takes_them_at_the_start_of_a_word_and_avoids_what_it_does_not_promise(
    profile, vertical, name, fits
):
    step = next(s for s in load_profiles()[profile].ladder if s.vertical == vertical)
    assert step.fits(name) is fits


def test_every_trip_is_a_question_with_two_sourced_facts():
    destinations = load_destinations()
    assert list(destinations) == ["japon", "colombia", "italia"]
    for destination in destinations.values():
        assert destination.text.startswith("¿Y si un día vas a ") and destination.text.endswith("?")
        assert len(destination.facts) == 2, destination.id
        assert all(f.text and f.source and f.url.startswith("https://") for f in destination.facts), destination.id
    assert [f.source for f in destinations["japon"].facts] == ["UNESCO", "Wikipedia"]
    assert "35 COM 8B.43" in destinations["colombia"].facts[0].source


def test_the_three_approved_graph_edges_exist_below_the_first_cross_sell():
    """Las aristas se aprobaron, no su peso. El primer complemento de lo asiático sigue siendo el postre; el del sushi,
    desde el 17-10-2026, son las bebidas asiáticas (antes empataban postres, vino y gaseosas y ganaban las gaseosas)."""
    weights = {(source, target): weight for source, target, weight in load_complements()}
    new = [("sushi", "despensa-asiatica"), ("sushi", "bebidas-asiaticas"), ("asiatica", "snacks-asiaticos")]
    assert all(edge in weights for edge in new)
    assert weights[new[0]] < weights[("sushi", "postres")]
    others = [w for (source, target), w in weights.items() if source == "sushi" and target != "bebidas-asiaticas"]
    assert weights[new[1]] > max(others)
    assert weights[("sushi", "gaseosas")] < weights[("sushi", "postres")]
    assert weights[new[2]] < weights[("asiatica", "postres")]


# ── Validación: un error de datos se detecta al cargar, en español y con el id ────────────────────────────────

VALID_PROFILE = """
[[perfil]]
id = "prueba"
nombre = "Prueba"
emoji = "🧪"
segmentos = ["sushi"]
nivel_minimo = "medio"
viaje = "japon"
gusto = "probar"

[[perfil.escalera]]
vertical = "turbo"
conceptos = ["hielo"]
texto = "Uno"

[[perfil.escalera]]
vertical = "supermercado"
conceptos = ["gaseosas"]
palabras = ["Colá", "Té Verde"]
evitar = ["Limpiá"]
texto = "Dos"
"""


def _write(tmp_path, text, name="perfiles.toml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_a_valid_profile_file_loads(tmp_path):
    profile = load_profiles(_write(tmp_path, VALID_PROFILE))["prueba"]
    assert (profile.main, profile.ladder[1].words, profile.trip) == (False, ("cola", "te verde"), "japon")
    assert (profile.ladder[0].avoid, profile.ladder[1].avoid) == ((), ("limpia",))
    assert profile.likes == "probar"
    no_likes = VALID_PROFILE.replace('gusto = "probar"\n', "")
    without = load_profiles(_write(tmp_path, no_likes, "sin-gusto.toml"))["prueba"]
    assert without.likes is None  # `gusto` es opcional


def test_each_profile_says_what_the_person_likes():
    """La frase que sigue a «Por tu gusto por…» en el momento `perfil`."""
    assert {p.id: p.likes for p in load_profiles().values()} == {
        "asiatico": "lo asiático",
        "cafe": "el café",
        "italiano": "lo italiano",
        "mascotas": "consentir a tu perro",
        "carrete": "armar carrete",
    }


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('conceptos = ["hielo"]', 'conceptos = ["no-existe"]', "prueba.*no-existe"),
        ('conceptos = ["hielo"]', 'conceptos = ["cerveza"]', "prueba.*cerveza"),  # +18: el agente no lo ofrece
        ('conceptos = ["hielo"]', 'conceptos = ["medicamentos"]', "prueba.*medicamentos"),
        ('vertical = "turbo"', 'vertical = "luna"', "prueba.*luna"),
        ('vertical = "turbo"', 'vertical = "licores"', "prueba.*licores"),
        ('segmentos = ["sushi"]', 'segmentos = ["no-existe"]', "prueba.*no-existe"),
        ('segmentos = ["sushi"]', 'segmentos = ["vapeo"]', "prueba.*vapeo"),  # un segmento sensible no arma perfiles
        ('nivel_minimo = "medio"', 'nivel_minimo = "altisimo"', "prueba.*altisimo"),
        ('viaje = "japon"', 'viaje = "marte"', "prueba.*marte"),
        ('texto = "Uno"', 'texto = "Uno"\nconcepto = ["hielo"]', "prueba.*concepto"),  # una clave mal escrita
        ('nombre = "Prueba"\n', "", "prueba.*nombre"),
        ('palabras = ["Colá", "Té Verde"]', 'palabras = "Colá"', "prueba.*palabras.*lista"),  # un texto, no una lista
        ('palabras = ["Colá", "Té Verde"]', 'palabras = ["Colá", ""]', "prueba.*palabras.*vac"),
        ('evitar = ["Limpiá"]', 'evitar = ["¿?"]', "prueba.*evitar.*vac"),  # sin letras, queda vacía
        ('evitar = ["Limpiá"]', 'evitar = "Limpiá"', "prueba.*evitar.*lista"),
        ('gusto = "probar"', 'gusto = ""', "prueba.*gusto"),
    ],
)
def test_a_bad_profile_names_its_id_and_the_bad_value(tmp_path, old, new, message):
    assert old in VALID_PROFILE
    with pytest.raises(ValueError, match=message):
        load_profiles(_write(tmp_path, VALID_PROFILE.replace(old, new, 1)))


def test_a_ladder_needs_two_steps(tmp_path):
    one_step = VALID_PROFILE[: VALID_PROFILE.rindex("[[perfil.escalera]]")]
    with pytest.raises(ValueError, match="prueba.*2 peldaños"):
        load_profiles(_write(tmp_path, one_step))


def test_only_one_profile_can_be_the_main_one(tmp_path):
    first = VALID_PROFILE.replace('nivel_minimo = "medio"', 'nivel_minimo = "medio"\nprincipal = true')
    second = first.replace('id = "prueba"', 'id = "otra"')
    with pytest.raises(ValueError, match="principal.*otra"):
        load_profiles(_write(tmp_path, first + second))


def test_profile_ids_are_unique(tmp_path):
    with pytest.raises(ValueError, match="prueba.*repetido"):
        load_profiles(_write(tmp_path, VALID_PROFILE + VALID_PROFILE))


VALID_DESTINATION = """
[[destino]]
id = "luna"
nombre = "La Luna"
texto = "¿Y si un día vas a la Luna?"

[[destino.hechos]]
texto = "Está lejos."
fuente = "Wikipedia"
url = "https://es.wikipedia.org/wiki/Luna"

[[destino.hechos]]
texto = "Tiene fases."
fuente = "NASA"
url = "https://science.nasa.gov/moon/"
"""


def test_a_valid_destination_file_loads(tmp_path):
    luna = load_destinations(_write(tmp_path, VALID_DESTINATION, "destinos.toml"))["luna"]
    assert (luna.name, luna.facts[0].source) == ("La Luna", "Wikipedia")


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('url = "https://', 'url = "http://', "luna.*https"),
        ('fuente = "Wikipedia"\n', "", "luna.*fuente"),
        ('texto = "¿Y si un día vas a la Luna?"\n', "", "luna.*texto"),
    ],
)
def test_a_bad_destination_names_its_id(tmp_path, old, new, message):
    with pytest.raises(ValueError, match=message):
        load_destinations(_write(tmp_path, VALID_DESTINATION.replace(old, new, 1), "destinos.toml"))


def test_a_destination_needs_facts(tmp_path):
    without_facts = VALID_DESTINATION[: VALID_DESTINATION.index("[[destino.hechos]]")]
    with pytest.raises(ValueError, match="luna.*hechos"):
        load_destinations(_write(tmp_path, without_facts, "destinos.toml"))


@pytest.mark.parametrize("facts", [1, 3])
def test_a_destination_has_exactly_two_facts(tmp_path, facts):
    header, first_fact, _ = VALID_DESTINATION.split("[[destino.hechos]]")
    text = header + "".join(["[[destino.hechos]]" + first_fact] * facts)
    with pytest.raises(ValueError, match="luna.*2 hechos"):
        load_destinations(_write(tmp_path, text, "destinos.toml"))


def test_a_step_query_says_what_its_products_are_called():
    """Sin embeddings la búsqueda es solo léxica: el nombre del concepto («Despensa asiática») no está en ningún
    producto, sus palabras clave sí. Un peldaño con palabras busca sus palabras."""
    from rappi_ia.offers.profiles import _step_query

    steps = {(p.id, s.vertical): s for p in load_profiles().values() for s in p.ladder}
    assert _step_query(steps["asiatico", "turbo"]) == "Despensa asiática salsa de soya salsa de soja"
    assert _step_query(steps["cafe", "supermercado"]) == "Café espresso cappuccino"  # «cafe» es la misma palabra
    # En restaurantes, sin el nombre del concepto; «rolls» no suma nada a «roll».
    assert _step_query(steps["asiatico", "restaurantes"]) == "sushi roll wok chapsui"
    assert _step_query(steps["asiatico", "chocolateria"]) == "matcha"
    assert _step_query(steps["carrete", "mall"]) == "vaso guirnalda globo cotillon"


def test_a_city_is_its_comunas():
    """Un restaurante guarda su comuna (`stores.city`), no la ciudad en que el scraper descubre tiendas. Santiago de
    Chile (la de PROFILE_CITY) son sus comunas, y «Santiago», la ciudad de las personas simuladas, es la misma. Otra
    ciudad es su propia comuna, sin tildes ni mayúsculas («Concepcion», como la escribe el descubrimiento)."""
    from rappi_ia.offers.profiles import city_places

    santiago = city_places("Santiago de Chile")
    assert {"santiago", "providencia", "nunoa", "maipu", "lo barnechea", "puente alto"} <= santiago
    assert not {"vina del mar", "valparaiso", "copiapo", "chillan", "melipilla"} & santiago
    assert city_places("Santiago") == santiago == city_places("santiago de chile")
    assert city_places("Viña del Mar") == {"vina del mar"}
    assert city_places("Concepcion") == city_places("Concepción") == {"concepcion"}
