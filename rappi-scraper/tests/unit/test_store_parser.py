import pytest

from rappi_scraper.pricing import discount_pct
from rappi_scraper.scraping.next_data import ParseError, extract_next_data
from rappi_scraper.scraping.store_parser import (
    parse_aisles,
    parse_products,
    parse_store,
    parse_sub_aisles,
    slugify,
)


def test_extract_next_data_raises_when_script_missing():
    with pytest.raises(ParseError):
        extract_next_data("<html><body>sin datos</body></html>")


def test_broken_next_data_is_parse_error():
    """Una página cortada es un error de esa página (se omite), no uno que tumba la tienda entera."""
    with pytest.raises(ParseError):
        extract_next_data('<script id="__NEXT_DATA__" type="application/json">{"a":</script>')


def test_next_data_any_attribute_order():
    html = '<script type="application/json" nonce="x1" id="__NEXT_DATA__">{"a": 1}</script>'
    assert extract_next_data(html) == {"a": 1}


def test_unexpected_shapes_are_parse_errors(page):
    store = page("store")
    tree = store["props"]["pageProps"]["fallback"]
    storefront = next(v for k, v in tree.items() if k.startswith("storefront/"))
    storefront["aisles_tree_response"]["data"]["components"][0]["resource"].pop("name")
    with pytest.raises(ParseError):
        parse_aisles(store)
    storefront["aisles_tree_response"]["data"]["components"] = 7  # un tipo inesperado
    with pytest.raises(ParseError):
        parse_aisles(store)


def test_parse_store_returns_store_info_and_canonical_path(page):
    store = parse_store(page("store"))
    assert store["store_id"] == 900025946
    assert store["name"] == "Lider"
    assert store["path"] == "/tiendas/900025946-lider"
    assert store["address"]


def test_parse_store_includes_brand_and_subvertical(page):
    store = parse_store(page("store_mall"))
    assert store["brand_id"] == 64116
    assert store["store_type"] == "accesoriosnyr_mt_enc"
    assert store["sub_group"] == "Tecnologia"


def test_parse_aisles_lists_aisles_with_ids_urls_and_counts(page):
    aisles = parse_aisles(page("store"))
    assert len(aisles) == 19
    assert all(a["aisle_id"] for a in aisles)
    lacteos = next(a for a in aisles if a["friendly_url"] == "lacteos-y-huevos")
    assert lacteos["name"] == "Lácteos y Huevos"
    assert lacteos["product_count"] > 0


def test_parse_sub_aisles_includes_non_rendered_ones_with_generated_slug(page):
    subs = parse_sub_aisles(page("aisle"))
    urls = {s["friendly_url"] for s in subs}
    assert len(subs) == 10
    assert {"yogurt", "leche", "leche-saborizada"} <= urls  # renderizados
    assert "mantequillas-y-margarinas" in urls  # generado desde el nombre
    assert next(s for s in subs if s["name"] == "Yogurt")["product_count"] == 313


def test_parse_products_on_sub_aisle_page(page):
    products = parse_products(page("subaisle"))
    assert len(products) == 24
    assert all(p["product_id"] and p["store_id"] == 900025946 for p in products)


def test_parse_products_on_aisle_page(page):
    assert len(parse_products(page("aisle"))) == 45


def test_missing_storefront_error_names_the_page_received(page):
    # listing_market: Rappi devolvió el listado del vertical en vez del pasillo (como en farmacia/primeros-auxilios)
    with pytest.raises(ParseError) as exc:
        parse_aisles(page("listing_market"))
    assert str(exc.value) == "No se encontró fallback['storefront/...'] (claves: cpgs-catalog)"


def test_missing_storefront_error_lists_key_prefixes_without_ids():
    # sin ids ni repetidos: el reporte agrupa los errores por texto
    fallback = {"store_information/900025946": {}, "store_information/1": {}, '@"cpgs-catalog","market",0,': {}}
    with pytest.raises(ParseError) as exc:
        parse_products({"props": {"pageProps": {"fallback": fallback}}})
    assert str(exc.value).endswith("(claves: cpgs-catalog, store_information)")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Lácteos y Huevos", "lacteos-y-huevos"),
        ("Mantequillas y margarinas", "mantequillas-y-margarinas"),
        ("Arroz, granos y pastas", "arroz-granos-y-pastas"),
        ("Santiago de Chile", "santiago-de-chile"),
    ],
)
def test_slugify(text, expected):
    assert slugify(text) == expected


@pytest.mark.parametrize(
    ("price", "real_price", "expected"),
    [(1030, 1280, 19.5), (500, 500, 0.0), (None, 500, 0.0), (500, None, 0.0), (600, 500, 0.0)],
)
def test_discount_pct(price, real_price, expected):
    assert discount_pct(price, real_price) == expected
