"""Búsqueda fuera de lugar: si la consulta nombra un concepto que el vertical no vende, ahí no se muestra nada (y la
búsqueda agrupada lo muestra donde sí lo venden). Sobre el catálogo de prueba (`seed_demo`) más los casos que marcaba
la revisión semanal (`make eval`: «La búsqueda las marca, pero se muestran productos»)."""

import pytest
from rappi_scraper.storage.search import build_search_documents

from conftest import add_dish, add_product
from rappi_ia.agent.grouped_search import search_grouped
from rappi_ia.agent.tools import search_products
from rappi_ia.concepts.pipeline import build_concepts
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents
from rappi_ia.retrieval import hybrid

EXPRESS, TURBO, LIQUOR, MALL, CHOCOLATE, PASTRY = 9201, 9301, 9401, 9601, 9701, 9806  # tiendas de `seed_demo`
# τ de cada vertical bajo los cosenos del HashEmbedder, como en la base real el 0,79 de Turbo queda bajo el 0,821 de
# «sofá de tres cuerpos»: con el τ de la vertical, esas consultas no eran «sin resultado».
LOW_TAUS = {"turbo": 0.05, "mall": 0.05, "chocolateria": 0.05}


def _price(db, store_id: int, product_id: int, price: int) -> None:
    """En la corrida vigente de `seed_demo`: en la anterior, la tienda dejaría de tener sus otras ofertas vigentes."""
    db.execute(
        """INSERT INTO price_snapshots (run_id, store_id, sku, price, in_stock)
           SELECT max(run_id), %s, %s, %s, true FROM scrape_runs WHERE kind = 'stores'""",
        (store_id, f"sku-{product_id}", price),
    )


@pytest.fixture
def catalog(db):
    """El catálogo de prueba con los dos casos de la revisión semanal: un surtido testimonial del concepto pedido (un
    cable HDMI rotulado como televisores en Turbo, como en la base real) y una coincidencia del stemming en otro
    concepto («pañales» calza con un «panal» de pastelería). Los televisores de verdad están en el mall. Y un sándwich
    con la etiqueta de otro concepto, como los de la base real en Express."""
    seed_demo(db)
    # Turbo con más de cien productos: el cable queda bajo el 1 % del vertical (tools.TESTIMONIAL_SHARE), como en la
    # base real. En un vertical de diez productos, uno solo es surtido de verdad.
    for i in range(120):
        add_product(db, 98500 + i, f"Agua saborizada {i} (prueba)", TURBO, "Aguas saborizadas")
        _price(db, TURBO, 98500 + i, 990)
    add_product(db, 99001, "Cable HDMI 1,8 m (prueba)", TURBO, "Televisores")
    _price(db, TURBO, 99001, 2990)
    for pid, name in [
        (99002, "Televisor smart 55 pulgadas (prueba)"),
        (99003, "Televisor QLED 55 pulgadas (prueba)"),
        (99004, "Televisor LED 43 pulgadas (prueba)"),
    ]:
        add_product(db, pid, name, MALL, "Televisores")
        _price(db, MALL, pid, 299990)
    # La categoría de Rappi «Sandwiches y empanadas» va al concepto empanadas: Express no tiene sándwiches rotulados.
    add_product(db, 99005, "Sándwich de jamón y queso (prueba)", EXPRESS, "Sandwiches y empanadas")
    _price(db, EXPRESS, 99005, 2490)
    # Contraejemplos donde el vertical no vende el concepto pero lo encontrado sí es lo pedido: un limón en el nombre
    # de una bebida de Licores, y una cerveza y un maní que su ficha recomienda para el asado y el picoteo.
    add_product(db, 99006, "Agua tónica limón 1,5 L (prueba)", LIQUOR, "Gaseosas")
    _price(db, LIQUOR, 99006, 1990)
    add_product(db, 99007, "Cerveza lager pack 6 latas (prueba)", LIQUOR, "Cervezas")
    _price(db, LIQUOR, 99007, 6990)
    add_product(db, 99008, "Maní salado 200 g (prueba)", EXPRESS, "Snacks salados")
    _price(db, EXPRESS, 99008, 1290)
    for pid, description in [(99007, "Ideal para el asado"), (99008, "Ideal para el picoteo")]:
        db.execute("UPDATE catalog_items SET description = %s WHERE master_product_id = %s", (description, pid))
    # «neumáticos aro 15» en Express, como en la base real: el vertical vende artículos para el auto, pero ninguno dice
    # «neumáticos» ni «15», y lo que calza el «15» son jugos en polvo de 15 g, más que el corte de lo que se mira. Los
    # neumáticos están en el mall.
    for pid, name in [
        (99030, "Cubreauto talla M (prueba)"),
        (99031, "Cera para auto en aerosol 360 cc (prueba)"),
        (99032, "Amarras elásticas para auto x 22 (prueba)"),
    ]:
        add_product(db, pid, name, EXPRESS, "Accesorios para exterior")
        _price(db, EXPRESS, pid, 3990)
    flavors = ["naranja", "piña", "frambuesa", "durazno", "manzana", "frutilla", "melón", "huesillo", "limón", "mango"]
    for i, flavor in enumerate(flavors + ["uva", "pera"]):
        add_product(db, 99010 + i, f"Jugo en polvo {flavor} 15 g (prueba)", EXPRESS, "Refrescos en polvo")
        _price(db, EXPRESS, 99010 + i, 290)
    for pid, name in [
        (99040, "Neumático aro 15 175/65 (prueba)"),
        (99041, "Neumático aro 15 185/60 (prueba)"),
        (99042, "Neumático aro 14 165/70 (prueba)"),
    ]:
        add_product(db, pid, name, MALL, "Accesorios para exterior")
        _price(db, MALL, pid, 49990)
    # Consultas que no nombran concepto ni ocasión, como en la base real: en Turbo, lo que calza «tres» o «colchón»
    # sin ser lo pedido (un pisco Tres Erres, un yogur «colchón de frutas», un ratchet «2»). De control, un nombre de
    # producto y una marca sin concepto que sí se venden, y un regalo en una chocolatería.
    for pid, name, store, category in [
        (99050, "Tres Erres Pisco Especial 35° 1 L (prueba)", TURBO, "Piscos"),
        (99051, "Pack 2 ratchet 1 pulgada (prueba)", TURBO, None),
        (99052, "Yogur griego colchón de frutas papaya (prueba)", TURBO, "Yogures"),
        (99053, "Cuchuflíes rellenos de manjar 6 unidades (prueba)", TURBO, "Galletas"),
        (99054, "Kinetic Sand arena mágica neón 227 g (prueba)", MALL, "Juguetes"),
        (99055, "Caja de regalo con bombones surtidos (prueba)", CHOCOLATE, "Bombones"),
    ]:
        add_product(db, pid, name, store, category)
        _price(db, store, pid, 3990)
    add_dish(db, 99101, "Panal de miel con crema (prueba)", PASTRY, "Postres")
    db.execute(
        """INSERT INTO menu_price_snapshots (run_id, item_id, price)
           SELECT max(run_id), 99101, 4990 FROM scrape_runs WHERE kind = 'restaurants'"""
    )
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    embedder = HashEmbedder()
    embed_search_documents(db, embedder)
    return db, embedder


def test_testimonial_items_of_the_named_concept_are_not_shown(catalog):
    """«televisor 55 pulgadas» en Turbo: «sin resultado» (un solo ítem del concepto, bajo MIN_CONCEPT_ITEMS), pero se
    mostraba el cable HDMI con la etiqueta del concepto."""
    db, embedder = catalog

    outcome = search_products(db, "turbo", "televisor 55 pulgadas", None, embedder)

    assert outcome.result.query_concepts == ["tv-video"] and not outcome.result.concept_in_vertical
    assert outcome.result.unmet and outcome.products == []


def test_word_matches_of_another_concept_are_not_shown_where_the_concept_is_not_sold(catalog):
    """«pañales» en restaurantes: el stemming junta «pañales» con «panal» y la coincidencia estricta impedía «sin
    resultado»; como nada era del concepto pedido, se mostraba el postre."""
    db, embedder = catalog

    outcome = search_products(db, "restaurantes", "pañales", None, embedder)

    assert outcome.result.query_concepts == ["panales"] and outcome.result.strict_lexical_matches > 0
    assert outcome.products == []


def test_a_number_alone_does_not_show_another_concept_where_the_concept_is_sold(catalog):
    """«neumáticos aro 15» en Express: el vertical vende el concepto (artículos para el auto), pero lo que calza el «15»
    en la léxica y en la vectorial son jugos en polvo de 15 g, que en la fusión dejan fuera los productos del concepto.
    Se mostraban los jugos; ahora, como donde no se vende el concepto, solo lo que dice lo pedido en su nombre."""
    db, embedder = catalog

    outcome = search_products(db, "conveniencia", "neumáticos aro 15", None, embedder)

    assert outcome.result.query_concepts == ["automotriz"] and outcome.result.concept_in_vertical
    assert outcome.result.hits and "automotriz" not in {h.concept_id for h in outcome.result.hits}  # lo que se mira
    assert not outcome.result.unmet and outcome.products == []


def test_grouped_search_shows_the_tyres_where_they_are_sold(catalog):
    db, embedder = catalog

    found = search_grouped(db, "neumáticos aro 15", embedder, current="conveniencia", limit=6)

    assert [g.vertical for g in found.groups] == ["mall"]
    # Los neumáticos empatan en el coseno del HashEmbedder: el orden entre ellos no está fijo.
    assert {"99040", "99041"} <= {p.entity_id for p in found.groups[0].products}


@pytest.mark.parametrize(
    ("vertical", "query", "product"),
    [
        ("licores", "cerveza pack 6", "99007"),
        ("supermercado", "pañales talla 3", "91007"),
        ("farmacia", "pañales talla 3", "91007"),
        ("mall", "neumáticos aro 15", "99040"),
    ],
)
def test_a_number_next_to_what_the_vertical_sells_still_finds_it(catalog, vertical, query, product):
    db, embedder = catalog

    outcome = search_products(db, vertical, query, None, embedder)

    assert product in [p.entity_id for p in outcome.products]


@pytest.mark.parametrize("query", ["sándwich", "sándwiches"])
def test_what_says_it_in_its_name_is_shown_even_with_another_concept(catalog, query):
    """Express no vende el concepto sándwiches, pero su sándwich (rotulado empanadas por su categoría) lo dice en el
    nombre, en singular o en plural: es lo pedido y se muestra. Lo demás que encuentra la búsqueda, no."""
    db, embedder = catalog

    outcome = search_products(db, "conveniencia", query, None, embedder)

    assert outcome.result.query_concepts == ["sandwiches"] and not outcome.result.concept_in_vertical
    assert [p.entity_id for p in outcome.products] == ["99005"]


def test_a_plural_query_finds_the_singular_name(catalog):
    """«limones» en Licores (sin frutas): la tónica dice «limón» en el nombre."""
    db, embedder = catalog

    outcome = search_products(db, "licores", "limones", None, embedder)

    assert outcome.result.query_concepts == ["frutas"] and not outcome.result.concept_in_vertical
    assert [p.entity_id for p in outcome.products] == ["99006"]


@pytest.mark.parametrize(
    ("query", "unrelated"),
    [
        ("sofá de tres cuerpos", "99050"),  # el pisco Tres Erres calza «tres»
        ("colchón 2 plazas", "99052"),  # el yogur «colchón de frutas» calza «colchón»
    ],
)
def test_without_concept_or_occasion_the_vertical_tau_is_not_enough(catalog, monkeypatch, query, unrelated):
    """En la base real, «sofá de tres cuerpos» en Turbo traía pisco Tres Erres (coseno 0,821, τ de Turbo 0,79) y
    «colchón 2 plazas» un ratchet y pilas «2 unidades» (0,824). Si la consulta no nombra concepto ni ocasión y nada
    calza todas sus palabras, el τ es el de la búsqueda agrupada (0,85), no el de la vertical."""
    db, embedder = catalog
    monkeypatch.setattr(hybrid, "thresholds", lambda: LOW_TAUS)

    outcome = search_products(db, "turbo", query, None, embedder)

    result = outcome.result
    assert result.query_concepts == [] and result.strict_lexical_matches == 0
    assert unrelated in {h.entity_id for h in result.hits}  # lo encontrado: lo que calza una palabra suelta
    assert LOW_TAUS["turbo"] <= result.max_cosine < 0.85  # el τ de la vertical lo dejaba pasar
    assert result.unmet and outcome.products == []


@pytest.mark.parametrize(
    ("vertical", "query", "product"),
    [
        ("turbo", "cuchuflíes", "99053"),  # un nombre de producto sin concepto: calza todas sus palabras
        ("mall", "kinetic sand", "99054"),  # una marca sin concepto
        ("chocolateria", "regalo para mi polola", "99055"),  # una ocasión sin concepto: decide el τ de la vertical
    ],
)
def test_a_query_without_concept_still_finds_what_the_vertical_sells(catalog, monkeypatch, vertical, query, product):
    db, embedder = catalog
    monkeypatch.setattr(hybrid, "thresholds", lambda: LOW_TAUS)

    outcome = search_products(db, vertical, query, None, embedder)

    assert outcome.result.query_concepts == [] and not outcome.result.unmet
    assert product in [p.entity_id for p in outcome.products]


@pytest.mark.parametrize(
    ("vertical", "query", "concept", "product"),
    [
        ("licores", "algo para el asado", "carnes", "99007"),  # nombra la ocasión asado
        ("conveniencia", "picoteo", "picoteo", "99008"),  # concepto amplio (`broad` en taxonomy.toml)
    ],
)
def test_an_occasion_or_a_broad_concept_keeps_what_was_found(catalog, vertical, query, concept, product):
    """Lo pedido son productos de varios tipos que su nombre no dice: no se exige que lo digan."""
    db, embedder = catalog

    outcome = search_products(db, vertical, query, None, embedder)

    assert outcome.result.query_concepts == [concept] and not outcome.result.concept_in_vertical
    assert not outcome.result.unmet and product in [p.entity_id for p in outcome.products]


def test_grouped_search_shows_it_where_it_is_sold_and_not_in_the_current_vertical(catalog):
    db, embedder = catalog

    tv = search_grouped(db, "televisor 55 pulgadas", embedder, current="turbo", limit=6)
    diapers = search_grouped(db, "pañales", embedder, current="restaurantes", limit=6)

    assert [g.vertical for g in tv.groups] == ["mall"] and not tv.unmet
    assert {p.concept for p in tv.groups[0].products} == {"tv-video"}
    assert "restaurantes" not in [g.vertical for g in diapers.groups]
    assert {"supermercado", "farmacia"} <= {g.vertical for g in diapers.groups}


def test_vertical_endpoint_says_there_is_nothing(catalog):
    from fastapi.testclient import TestClient

    from rappi_ia.agent.compose import TemplateComposer
    from rappi_ia.agent.rappi_agent import RappiAgent
    from rappi_ia.api import app as api
    from rappi_ia.api.services import Services

    db, embedder = catalog

    def conn_override():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    api.app.dependency_overrides[api.get_services] = lambda: Services(
        RappiAgent(embedder, TemplateComposer()), embedder
    )
    try:
        body = TestClient(api.app).get("/search", params={"q": "televisor 55 pulgadas", "vertical": "turbo"}).json()
    finally:
        api.app.dependency_overrides.clear()

    assert body["products"] == [] and body["unmet"] is True


@pytest.mark.parametrize(
    ("query", "verticals", "concept"),
    [
        ("papas fritas", {"supermercado", "conveniencia", "turbo"}, "snacks-salados"),
        ("helado", {"turbo", "chocolateria"}, "helados"),
        ("café", {"supermercado", "restaurantes"}, "cafe"),
        ("cerveza", {"licores", "supermercado", "conveniencia", "turbo"}, "cerveza"),
    ],
)
def test_legit_cross_matches_stay_in_every_vertical_that_sells_them(catalog, query, verticals, concept):
    """Lo que se vende en varias verticales sigue saliendo en cada una y, en el buscador, encabeza en la de la
    pantalla."""
    db, embedder = catalog

    for vertical in verticals:
        outcome = search_products(db, vertical, query, None, embedder)
        grouped = search_grouped(db, query, embedder, current=vertical, limit=6)
        assert outcome.products and {p.concept for p in outcome.products} == {concept}, (query, vertical)
        assert grouped.groups[0].vertical == vertical, (query, vertical)
