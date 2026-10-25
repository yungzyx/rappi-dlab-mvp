"""Keywords ambiguas de la taxonomía y guardia de los conceptos sensibles (capa 2)."""

from collections import defaultdict

import numpy as np
import pytest

from rappi_ia.agent.understand import Understander
from rappi_ia.concepts.assign import Assignment, MappedName, assign_catalog_item, concept_matcher
from rappi_ia.concepts.knn import ItemText, _decide
from rappi_ia.concepts.taxonomy import load_taxonomy, sensitive_concepts
from rappi_ia.retrieval.hybrid import _query_concepts
from rappi_ia.text import assistant_words, normalize, tokens


@pytest.fixture(scope="module")
def matcher():
    return concept_matcher(load_taxonomy())


def test_no_keyword_belongs_to_two_concepts():
    """Con una keyword en dos conceptos, gana el que aparece primero en el archivo: una regla que nadie decidió."""
    owners = defaultdict(set)
    for concept in load_taxonomy().concepts.values():
        for keyword in (concept.name, *concept.keywords, *concept.query_keywords, *concept.product_keywords):
            owners[normalize(keyword)].add(concept.id)
    assert {kw: sorted(ids) for kw, ids in owners.items() if len(ids) > 1} == {}


def test_the_agent_name_never_reads_a_query_as_a_product():
    """«Mochi» es el agente y también un postre: con «mochi» entre las palabras de una consulta, «Mochi, ¿qué me
    recomiendas?» pedía snacks asiáticos. Ninguna palabra que lee consultas (nombres, keywords, query_keywords,
    ocasiones y servicios) puede tener el nombre del agente; en `product_keywords` sí, porque solo nombran productos
    («Kai Mochi Helado»)."""
    names = assistant_words()
    taxonomy = load_taxonomy()
    words = [
        *((c.id, kw) for c in taxonomy.concepts.values() for kw in (c.name, *c.keywords, *c.query_keywords)),
        *((o.id, kw) for o in taxonomy.occasions.values() for kw in (o.name, *o.keywords)),
        *((s.id, kw) for s in taxonomy.services.values() for kw in (s.name, *s.keywords)),
    ]
    assert [(owner, kw) for owner, kw in words if names & set(tokens(kw))] == []


@pytest.mark.parametrize(
    ("name", "concept"),
    [
        # «aceite» a secas mandaba 27 productos a condimentos (aceites esenciales, de difusor, suplementos). Otras
        # palabras sueltas siguen siendo ambiguas («orégano» en cápsulas, «roll» en Roll-On): las corrigen la
        # categoría y el kNN, no una regla por nombre.
        ("Aceite Esencial de Lavanda 10 ml", None),
        ("Aceite Para Difusores Paz Calma", "decoracion"),
        ("Aceite de Oliva Extra Virgen Chef 1 L", "aceites-condimentos"),
        ("Aceite Vegetal Belmont 1 L", "aceites-condimentos"),
        ("Straight 8 Corrector De Postura", None),
        ("Corrector de Ojeras Maybelline", "maquillaje"),
        ("Corrector Líquido Artel", "utiles"),
        ("Plumón Permanente Sharpie Negro", "utiles"),
        ("Plumón de Cama 2 Plazas Blanco", "textil-hogar"),
        ("Jarabe de Arce Canadiense 250 ml", None),
        ("Jarabe para la Tos Infantil", "medicamentos"),
    ],
)
def test_ambiguous_keywords_need_their_context(matcher, name, concept):
    a = assign_catalog_item("9", name, None, {}, matcher)
    assert (a.concept_id if a else None) == concept


# Palabras sueltas que también son comida, utensilios o cosmética: un concepto sensible no puede tenerlas a secas.
AMBIGUOUS_FOR_SENSITIVE = {
    "puro",
    "puros",
    "pipa",
    "pipas",
    "moledor",
    "lubricante",
    "medicamento",
    "medicamentos",
    "boquilla",
    "encendedor",
    "belmont",
}


def test_sensitive_concepts_avoid_ambiguous_single_words():
    sensitive = [c for c in load_taxonomy().concepts.values() if c.sensitive]
    found = {c.id: sorted({normalize(k) for k in c.keywords} & AMBIGUOUS_FOR_SENSITIVE) for c in sensitive}
    assert {k: v for k, v in found.items() if v} == {}


@pytest.mark.parametrize(
    "text",
    [
        "Puro Llano",
        "Risotto el Puro Perú",
        "Jugo de uva puro",
        "Moledor de pimienta",
        "Lubricante para lentes de contacto",
        "la Pipa Burger",
        "Dosificador de medicamentos",
    ],
)
def test_ambiguous_words_do_not_make_anything_sensitive(matcher, text):
    """«aceite de coco puro» llevaba a Licores con papelillos y el aviso +18; «Puro Llano» desaparecía de la búsqueda.
    Se revisan todas las coincidencias, no solo la mejor: la consulta usa todos los conceptos que nombra."""
    assert [m for m in matcher.matches(text) if m.target in sensitive_concepts()] == []


@pytest.mark.parametrize(
    ("text", "concept"),
    [
        ("cigarros", "cigarrillos"),
        ("unos puchos", "cigarrillos"),
        ("habanos cubanos", "cigarrillos"),
        ("cigarro electrónico", "vapeo"),
        ("vapeo", "vapeo"),  # el nombre de un sensible ya no es keyword: el que sirve para pedirlo va explícito
        ("pipa para fumar", "accesorios-fumador"),
        ("lubricante íntimo", "bienestar-sexual"),
        ("Kama Sutra Lubricante Con Sabor Néctar Divino Frutilla", "bienestar-sexual"),
    ],
)
def test_sensitive_concepts_are_still_found_by_name(matcher, text, concept):
    assert matcher.best(text).target == concept


@pytest.mark.parametrize(
    ("text", "concept"),
    [
        ("necesito medicamentos", "medicamentos"),
        ("un medicamento", "medicamentos"),
        ("quiero medicamentos porfa", "medicamentos"),
        ("lubricante", "bienestar-sexual"),
        ("tienen lubricante", "bienestar-sexual"),
        # Artículos, «algún», «venden» o «barato» no nombran otra cosa: la palabra sigue siendo todo el pedido.
        ("necesito los medicamentos", "medicamentos"),
        ("quiero algún medicamento", "medicamentos"),
        ("venden medicamentos", "medicamentos"),
        ("medicamentos baratos", "medicamentos"),
        ("venden lubricante", "bienestar-sexual"),
        ("algo de lubricante", "bienestar-sexual"),
        ("lubricante ocular", "medicamentos"),
    ],
)
def test_queries_ask_for_sensitive_concepts_with_words_that_do_not_assign_them(text, concept):
    """«Medicamentos» y «lubricante» a secas no asignan productos (un dosificador o un lubricante para lentes no son
    sensibles), pero en una consulta nombran el concepto: sin él, la búsqueda oculta los sensibles y
    «necesito medicamentos» mostraba vaselina y agua bidestilada."""
    assert Understander().understand(None, text, "farmacia").concepts[:1] == [concept]
    assert _query_concepts(text)[:1] == [concept]


@pytest.mark.parametrize(
    "text",
    [
        "lubricante wd-40",
        "aceite lubricante",
        "lubricante para bisagras",
        "lubricante para lentes de contacto",
        "pastillero para medicamentos",
        "dosificador de medicamentos",
        "organizador de medicamentos",
        "medicamento homeopático",
    ],
)
def test_words_that_only_ask_for_a_sensitive_concept_count_only_on_their_own(text):
    """«medicamentos» y «lubricante» piden el concepto cuando son todo el pedido. Con otras palabras son un complemento,
    y el foco en el sensible ocultaba lo pedido: «lubricante wd-40» mostraba lubricantes íntimos con el aviso +18 y
    «pastillero para medicamentos», analgésicos."""
    assert not set(Understander().understand(None, text, "farmacia").concepts) & sensitive_concepts()
    assert not set(_query_concepts(text)) & sensitive_concepts()


def test_a_doubtful_sensitive_category_is_not_replaced_by_a_rule(matcher):
    """Conservar el concepto sensible salvo que el candidato también lo sea: un medicamento no pasa a «cerveza»."""
    categories = {"farmacia varios": MappedName("medicamentos", "llm", 0.5, "v1")}
    a = assign_catalog_item("10", "Cerveza de Levadura en Cápsulas", "Farmacia varios", categories, matcher)
    assert (a.concept_id, a.method) == ("medicamentos", "llm")


def test_neighbors_never_take_an_item_out_of_a_sensitive_concept():
    """Un medicamento rodeado de vitaminas sigue siendo medicamento; solo otro concepto sensible puede reemplazarlo."""
    item = ItemText("catalog_item", "1", "Producto de farmacia")
    medicine = Assignment("catalog_item", "1", "medicamentos", "llm", 0.9, None, "x")
    sims = np.full(15, 0.9, dtype=np.float32)
    assert _decide(medicine, item, sims, np.array(["vitaminas"] * 15), "knn/test") == medicine
    assert _decide(medicine, item, sims, np.array(["salud-sexual"] * 15), "knn/test").concept_id == "salud-sexual"


@pytest.mark.parametrize(
    ("text", "concept"),
    [
        ("Perro Caliente Especial", "sandwiches"),
        ("perros calientes", "sandwiches"),
        ("Calzones Rotos 3 Unidades", "pasteleria"),
        ("Aros de Cebolla", "picoteo"),
        ("Aros de Cebollas 10 Unds", "picoteo"),
    ],
)
def test_dish_names_are_food_not_pets_or_clothes(matcher, text, concept):
    """«perro», «calzones» y «aros» sueltos son mascotas, ropa interior y joyería; estos platos llevan su frase."""
    assert matcher.best(text).target == concept


@pytest.mark.parametrize(
    ("text", "concept"),
    [
        ("pasta de dientes", "cuidado-oral"),  # «pasta» suelta es fideos
        ("acondicionador", "cuidado-cabello"),
        ("shampoo", "cuidado-cabello"),
        ("alfajores", "galletas"),
        ("pechuga de pollo", "pollo"),
    ],
)
def test_query_words_name_the_concept_their_products_have(matcher, text, concept):
    """La consulta toma su concepto de las keywords y el producto de su categoría: tienen que coincidir. Medido en la
    base: los productos con «acondicionador» están 94 % en cuidado del cabello y los alfajores, en galletas."""
    assert matcher.best(text).target == concept


@pytest.mark.parametrize("text", ["kfc", "pollo frito", "pollo asado", "nuggets", "alitas"])
def test_fried_chicken_is_prepared_food(matcher, text):
    """El pollo fresco no compite en restaurantes: «kfc» llevaba a pollo congelado del minimarket."""
    concept = load_taxonomy().concepts[matcher.best(text).target]
    assert concept.parent == "comida" and concept.prepared, concept


@pytest.mark.parametrize(
    ("name", "category", "mapped"),
    [
        ("Kama Sutra Lubricante Con Sabor Néctar Divino Frutilla", "Agua saborizada", "agua"),
        ("Satisfyer Succionador de Clítoris Pro Penguin", "Estuches y Fundas", "celulares"),
        ("Heaven Hell E-liquid Mango 60 ml", "Cremas de licor", "licores"),
        ("Tabaco Ross Maracuya", "Papas, yucas y tuberculos", "verduras"),
    ],
)
def test_a_sensitive_name_wins_over_a_common_category(matcher, name, category, mapped):
    """Guardia simétrica: un producto con nombre sensible mal categorizado no entra a un concepto común (el
    lubricante era el primer resultado de «agua con sabor frutilla»)."""
    categories = {category.lower(): MappedName(mapped, "llm", 0.85, "v1")}
    a = assign_catalog_item("11", name, category, categories, matcher)
    assert a.concept_id in sensitive_concepts() and a.method == "regla", a


def test_a_sensitive_category_keeps_its_concept_over_another_sensitive_name(matcher):
    categories = {"preservativos": MappedName("salud-sexual", "llm", 0.95, "v1")}
    a = assign_catalog_item("12", "Preservativos Durex Con Lubricante íntimo", "Preservativos", categories, matcher)
    assert (a.concept_id, a.method) == ("salud-sexual", "llm")


@pytest.mark.parametrize(
    ("name", "category", "mapped"),
    [
        ("Vaso Con Boquilla Desde 6 Meses Avent", "Vajillas de Bebe", "articulos-bebe"),
        ("Wilton Set 4 Boquillas De Plástico Para Manga Pastelera", "Utensilios de repostería", "cocina-menaje"),
        ("Aceite Belmont 250ml", "Aceite", "aceites-condimentos"),
        ("Ronson Encendedor Recargable Electrolite", "Carbón, Leña y chispa", "carbon"),
        ("Naxpet Analgésico Para Perros", "Medicamentos para mascotas", "accesorios-mascota"),
        ("Sucravet Antiácido Uso Veterinario", "Medicamentos para mascotas", "accesorios-mascota"),
        ("Insecto Vibrador Chinita", "Juguetes didácticos", "juguetes-infantiles"),
    ],
)
def test_the_symmetric_guard_does_not_hide_common_products(matcher, name, category, mapped):
    """Con la guardia simétrica, una keyword sensible ambigua («boquilla», «belmont», «encendedor») escondería un
    vaso de bebé, un aceite o un encendedor de parrilla: esas palabras no van en conceptos sensibles. En mascotas y
    juguetes la categoría manda aunque el nombre calce un sensible: un remedio veterinario no es un medicamento
    (category_map.csv lo decidió así) y un insecto vibrador de juguete no es +18."""
    categories = {category.lower(): MappedName(mapped, "llm", 0.9, "v1")}
    assert assign_catalog_item("13", name, category, categories, matcher).concept_id == mapped
