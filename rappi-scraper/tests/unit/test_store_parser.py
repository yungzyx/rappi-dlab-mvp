import pytest

from conftest import astro_island
from rappi_scraper.pricing import discount_pct
from rappi_scraper.scraping.astro import Page, ParseError, components, content_islands, island_error
from rappi_scraper.scraping.store_parser import (
    parse_aisles,
    parse_products,
    parse_store,
    parse_sub_aisles,
    slugify,
)


def test_props_are_revived_from_astro_serialization():
    """Astro manda cada valor como [tipo, valor]: 0 un valor (y los de un objeto, serializados igual), 1 una lista."""
    props = '{"a":[0,{"b":[1,[[0,1],[0,{"c":[0,null]}]]]}],"n":[0]}'.replace('"', "&quot;")
    page = Page("", f'<astro-island uid="1" component-url="/_astro/X.Ab1.js" props="{props}"></astro-island>')
    assert components(page, "X") == [{"a": {"b": [1, {"c": None}]}, "n": None}]  # [0] es undefined
    nested = {"a": {"b": [1, {"c": None}]}}
    assert components(Page("", astro_island("X", nested)), "X") == [nested]
    assert components(page, "Y") == []


def test_content_islands_skip_the_header_ones_and_unescape_the_path():
    html = (
        "fetch('/_server-islands/UserAvatarContent?e=default&p=a&s=')"
        "fetch('/_server-islands/StoreContent?e=default&amp;p=b%2F&s=')"
        "fetch('/_server-islands/StoreContent?e=default&amp;p=b%2F&s=')"  # el mismo, otra vez (precarga)
    )
    assert content_islands(html) == [("StoreContent", "/_server-islands/StoreContent?e=default&p=b%2F&s=")]


def test_island_error_page_gives_code_and_message():
    error = '<div data-analytics="{&quot;event_name&quot;:&quot;VIEW_ERROR_PAGE&quot;,&quot;event_properties&quot;:{&quot;ERROR_CODE&quot;:&quot;404&quot;,&quot;ERROR_MESSAGE&quot;:&quot;Location not found&quot;}}"></div>'  # noqa: E501
    assert island_error(error) == ("404", "Location not found")
    assert island_error("<astro-island></astro-island>") is None


def test_parse_store_returns_store_info_and_canonical_path(page):
    store = parse_store(page("store"))
    assert store["store_id"] == 900025946
    assert store["name"] == "Lider"
    assert store["path"] == "/tiendas/900025946-lider"
    assert (store["brand_id"], store["brand_name"]) == (12216, "Lider")
    assert (store["store_type"], store["sub_group"]) == ("lider", "Super")
    assert store["lat"] < -33 and store["lng"] < -70
    assert store["city"] == store["address"] == ""  # no vienen: no pisan lo guardado


def test_a_page_without_store_data_is_parse_error(page):
    with pytest.raises(ParseError, match="sin datos de la tienda"):
        parse_store(page("listing_market"))


def test_parse_aisles_lists_the_linked_aisles_with_their_pages(page):
    aisles = parse_aisles(page("store"))
    assert len(aisles) == 10
    lacteos = aisles[0]
    assert lacteos == {
        "aisle_id": 14406,
        "name": "Lácteos y Huevos",
        "friendly_url": "lacteos-y-huevos",
        "product_count": None,
        "path": "/tiendas/market/lider/900025946-lider/sub_aisles?aisle_id=14406",
    }


def test_a_store_without_aisle_links_has_no_aisles(page):
    assert parse_aisles(page("store_small")) == []
    assert len(parse_products(page("store_small"))) == 2


def test_parse_sub_aisles_comes_with_their_products(page):
    subs = parse_sub_aisles(page("aisle"))
    assert [(s["aisle_id"], s["friendly_url"]) for s in subs] == [
        (14521, "yogurt"),
        (14516, "leche"),
        (14512, "cremas"),
    ]
    assert all(len(s["products"]) == 2 for s in subs)


def test_products_keep_the_keys_of_the_previous_page(page):
    """`save_products` y `store_products.raw` leen las claves de antes: snake_case, precio normal en `real_price`."""
    products = parse_products(page("store"))
    assert len(products) == 4
    assert all(p["product_id"] and p["store_id"] == 900025946 for p in products)
    milk = next(p for p in products if p["name"] == "Colun Leche Entera Natural")
    assert (milk["price"], milk["real_price"], milk["in_stock"]) == (930, 1100, True)
    assert milk["master_product_id"] == 196743 and milk["category_id"] == 110
    assert milk["image_url"] == milk["image_url"].split("?")[0]  # sin los parámetros de tamaño
    assert milk["id"] == f"900025946_{milk['product_id']}"
    promo = next(p for p in products if p["have_complex_discounts"])
    assert promo["complex_discounts"][0]["label"].startswith("-")


def test_unexpected_shapes_are_parse_errors():
    item = {"type": "cpg_product_item", "id": 1}  # sin storeId
    page = Page("", astro_island("DynamicListAisle", {"component": {"id": 1, "title": "X", "items": [item]}}))
    with pytest.raises(ParseError):
        parse_products(page)
    page = Page("", astro_island("DynamicListAisle", {"component": {"id": 1, "items": []}}))  # sin título
    with pytest.raises(ParseError):
        parse_sub_aisles(page)


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
