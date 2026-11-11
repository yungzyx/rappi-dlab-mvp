"""La consulta de cada arista de complementos (`complements.toml`, cuarto campo): con ella, `suggest_complement` busca
los productos del destino por lo que la persona espera y no por el nombre del concepto ("Salsas y aderezos" traía salsa
agridulce y aliño César para los Doritos; "Limpieza", sahumerios), y solo vale lo que dice alguna de sus palabras en el
nombre (`_saying`). Con una búsqueda falsa: cada texto trae su lista de productos y si su nombre dice el texto o la
búsqueda los trajo por otra cosa (la cercanía de vectores, una raíz en la descripción)."""

import tomllib
from types import SimpleNamespace

import pytest

from rappi_ia.agent import tools
from rappi_ia.agent.tools import Product, SearchOutcome, suggest_complement
from rappi_ia.concepts.taxonomy import DATA_DIR, complement_queries, load_complements, load_taxonomy
from rappi_ia.offers.guards import is_offerable
from rappi_ia.text import tokens

CONCEPTS = load_taxonomy().concepts


# ── Los datos ────────────────────────────────────────────────────────────────


def test_the_edges_that_brought_wrong_products_have_their_query():
    queries = complement_queries()
    assert "dip" in queries[("snacks-salados", "salsas")]  # los Doritos: un dip, no salsa agridulce
    assert "salsa de tomate" in queries[("pastas", "salsas")]  # los tallarines: salsa para pastas, no kétchup
    assert "lavaloza" in queries[("papeles-desechables", "limpieza")]  # el papel: limpieza de verdad, no sahumerios
    assert all(query == query.strip() and query for query in queries.values())


def test_no_edge_is_written_twice():
    """`complement_queries` es un diccionario: una arista repetida en el TOML dejaría una de sus consultas sin aviso."""
    edges = tomllib.loads((DATA_DIR / "complements.toml").read_text(encoding="utf-8"))["edges"]
    pairs = [(edge[0], edge[1]) for edge in edges]
    assert [pair for pair in set(pairs) if pairs.count(pair) > 1] == []


def test_every_query_has_words_to_match():
    """Una consulta sin palabras que calzar (solo "de", "la"…) no encuentra nada y la arista vuelve siempre al nombre
    del concepto, sin aviso."""
    empty = [edge for edge, query in complement_queries().items() if not any(len(w) >= 3 for w in tokens(query))]
    assert empty == []


def test_mayonnaise_goes_with_the_burger_before_the_pasta():
    weights = {(source, target): weight for source, target, weight in load_complements() if source == "salsas"}
    assert max(weights, key=weights.get) == ("salsas", "carnes")
    assert weights[("salsas", "pastas")] < weights[("salsas", "panaderia")]


def test_the_hardware_store_offers_garden_tools_and_not_the_car():
    """Pilas y ampolletas traían un sahumerio ("Plantas y jardín") y un cubreauto: el jardín se busca con su texto y el
    auto salió."""
    offered = [t for s, t, _ in load_complements() if s == "ferreteria" and is_offerable(CONCEPTS[t])]
    assert offered == ["jardin"]
    assert "pala" in complement_queries()[("ferreteria", "jardin")]


@pytest.mark.parametrize(
    "edge, error",
    [
        ('["snacks-salados", "salsas", 0.4, ""]', "Consulta vacía"),
        ('["snacks-salados", "salsas", 0.4, 3]', "Consulta vacía o que no es texto"),
        ('["snacks-salados", "salsas", 0.4, "dip", "otro"]', "5 campos"),
        ('["snacks-salados", "salsas"]', "2 campos"),
    ],
)
def test_a_malformed_edge_fails_on_load(tmp_path, edge, error):
    path = tmp_path / "complements.toml"
    path.write_text(f"edges = [\n  {edge},\n]\n", encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        complement_queries(path)


def test_an_edge_without_query_has_none(tmp_path):
    path = tmp_path / "complements.toml"
    path.write_text(
        'edges = [\n  ["snacks-salados", "gaseosas", 0.6],\n  ["snacks-salados", "salsas", 0.4, " dip "],\n]\n'
    )
    assert complement_queries(path) == {("snacks-salados", "salsas"): "dip"}
    assert load_complements(path) == (("snacks-salados", "gaseosas", 0.6), ("snacks-salados", "salsas", 0.4))


# ── La búsqueda ──────────────────────────────────────────────────────────────

# Texto buscado → (nombre, concepto, ¿su nombre dice alguna palabra del texto?), en el orden de la búsqueda.
CATALOG = {
    CONCEPTS["salsas"].name: [
        ("Salsa Agridulce", "salsas", True),
        ("Gourmet Aliño para Ensalada Cesar Light", "salsas", True),
        ("By María Salsa Ketchup Clásico", "salsas", True),
    ],
    complement_queries()[("snacks-salados", "salsas")]: [
        ("Salsa Agridulce", "salsas", False),  # la trajo la cercanía de vectores
        ("Buka Dip Untable Cheddar", "salsas", True),
        ("Nachos de maíz", "snacks-salados", True),  # calza, pero es de otro concepto
        ("Guacamole Natural", "salsas", True),
    ],
    complement_queries()[("pastas", "salsas")]: [
        ("Pomarola Salsa de Tomates Italiana", "salsas", True),
        ("Carozzi Salsa de Tomate Toscana a la Bolognesa", "salsas", True),
        ("Gourmet Aliño para Ensalada Cesar Light", "salsas", False),
        ("Salsa Pesto Genovesa", "salsas", True),
    ],
    CONCEPTS["limpieza"].name: [
        ("Sahumerio Momentos Limpieza - Aromanza", "limpieza", True),
        ("Smart Clean Lavaloza Limón", "limpieza", True),
        ("Sahumerio Tibetano Energia Limpia - Aromanza", "limpieza", False),
    ],
    complement_queries()[("papeles-desechables", "limpieza")]: [
        ("Sahumerio Tibetano Energia Limpia - Aromanza", "limpieza", False),
        ("Toddo Lavaloza Verde", "limpieza", True),
        ("Igenix Limpiador Desinfectante Cloro gel", "limpieza", True),
    ],
}


class FakeConn:
    """Solo responde la consulta de las aristas de `suggest_complement` y la de las marcas de `_brand_first`."""

    def __init__(self, edges, brands=None):
        self.edges = edges
        self.brands = brands or {}  # nombre del producto → brand_key

    def execute(self, sql, params=None):
        if "item_brands" in sql:
            kinds, entities = params
            return [(k, e, self.brands[e]) for k, e in zip(kinds, entities, strict=True) if e in self.brands]
        assert "concept_edges" in sql
        return SimpleNamespace(fetchall=lambda: self.edges)


@pytest.fixture
def searched(monkeypatch):
    """La búsqueda falsa, en una sola vertical; anota cada texto buscado."""
    texts = []

    def search(conn, vertical, query, concepts, embedder, k=6, offer=False, **_):
        texts.append(query)
        rows = CATALOG.get(query, [])
        products = [
            Product(str(i), "catalog_item", str(i), name, vertical, concept, 1990.0, None, "Tienda", None)
            for i, (name, concept, _) in enumerate(rows)
        ]
        return SearchOutcome(SimpleNamespace(hits=[]), products[:k])

    def saying(conn, products, text):
        said = {name for name, _, says in CATALOG.get(text, []) if says}
        return [p for p in products if p.name in said]

    monkeypatch.setattr(tools, "search_products", search)
    monkeypatch.setattr(tools, "_saying", saying)
    monkeypatch.setattr(tools, "_verticals_for", lambda conn, concept, current: ["supermercado"])
    return texts


def names(suggestion):
    return [p.name for p in suggestion.products]


def test_doritos_get_a_dip_not_sweet_and_sour_sauce(searched):
    chosen = suggest_complement(FakeConn([("snacks-salados", "salsas", 0.4)]), ["snacks-salados"], None, None)

    assert chosen.concept == "salsas"
    assert names(chosen) == ["Buka Dip Untable Cheddar", "Guacamole Natural"]
    assert searched == [complement_queries()[("snacks-salados", "salsas")]]


def test_noodles_get_a_pasta_sauce(searched):
    chosen = suggest_complement(FakeConn([("pastas", "salsas", 0.8)]), ["pastas"], None, None)

    assert names(chosen) == [
        "Pomarola Salsa de Tomates Italiana",
        "Carozzi Salsa de Tomate Toscana a la Bolognesa",
        "Salsa Pesto Genovesa",
    ]


def test_paper_towels_get_real_cleaning_products(searched):
    chosen = suggest_complement(
        FakeConn([("papeles-desechables", "limpieza", 0.6)]), ["papeles-desechables"], None, None
    )

    assert names(chosen) == ["Toddo Lavaloza Verde", "Igenix Limpiador Desinfectante Cloro gel"]
    assert not any("Sahumerio" in name for name in names(chosen))


def test_without_a_query_it_searches_the_concept_name_as_always(searched):
    """Una arista sin consulta (aprendida, o curada sin el cuarto campo): el nombre, y vale todo lo del concepto."""
    assert ("conservas", "salsas") not in complement_queries()

    chosen = suggest_complement(FakeConn([("conservas", "salsas", 0.3)]), ["conservas"], None, None)

    assert searched == [CONCEPTS["salsas"].name]
    assert names(chosen) == [
        "Salsa Agridulce",
        "Gourmet Aliño para Ensalada Cesar Light",
        "By María Salsa Ketchup Clásico",
    ]


def test_if_nothing_says_the_query_it_falls_back_to_the_concept_name(searched, monkeypatch):
    monkeypatch.setitem(
        CATALOG, complement_queries()[("snacks-salados", "salsas")], [("Salsa Agridulce", "salsas", False)]
    )

    chosen = suggest_complement(FakeConn([("snacks-salados", "salsas", 0.4)]), ["snacks-salados"], None, None)

    assert searched == [complement_queries()[("snacks-salados", "salsas")], CONCEPTS["salsas"].name]
    assert names(chosen)[0] == "Salsa Agridulce"  # mejor la oferta de siempre que ninguna


def product(name, concept="salsas"):
    return Product(name, "catalog_item", name, name, "supermercado", concept, 1990.0, None, "Tienda", None)


def test_the_brand_they_buy_goes_first_even_if_the_search_leaves_it_further_down(searched, monkeypatch):
    """Con la consulta de la arista, la marca que la persona compra se busca aparte (`_brand_products`): el dip de su
    marca no está entre los primeros de la búsqueda, pero calza la consulta y va primero."""
    asked = []

    def brand_products(conn, vertical, text, concept, brands):
        asked.append((text, concept, dict(brands)))
        return [product("Dip Sabor Marca Querida")]

    monkeypatch.setattr(tools, "_brand_products", brand_products)
    conn = FakeConn([("snacks-salados", "salsas", 0.4)], {"Dip Sabor Marca Querida": "querida"})

    chosen = suggest_complement(conn, ["snacks-salados"], None, None, prefer_brands={"querida": 3})

    query = complement_queries()[("snacks-salados", "salsas")]
    assert asked == [(query, "salsas", {"querida": 3})]
    assert chosen.brand == "querida"
    assert names(chosen) == ["Dip Sabor Marca Querida", "Buka Dip Untable Cheddar", "Guacamole Natural"]


def test_without_a_product_of_their_brand_that_says_the_query_the_offer_is_the_usual(searched, monkeypatch):
    monkeypatch.setattr(tools, "_brand_products", lambda conn, vertical, text, concept, brands: [])

    chosen = suggest_complement(
        FakeConn([("snacks-salados", "salsas", 0.4)]), ["snacks-salados"], None, None, prefer_brands={"otra": 1}
    )

    assert chosen.brand is None
    assert names(chosen) == ["Buka Dip Untable Cheddar", "Guacamole Natural"]
