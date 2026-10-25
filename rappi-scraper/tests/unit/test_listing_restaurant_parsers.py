import pytest

from conftest import restaurant_block, with_top_section
from rappi_scraper.scraping.listing_parser import parse_brand_chain, parse_vertical_listing
from rappi_scraper.scraping.next_data import ParseError
from rappi_scraper.scraping.restaurant_parser import parse_restaurant


def test_mall_listing_merges_groups_and_filter_only_stores(page):
    stores = parse_vertical_listing(page("listing_mall"))
    by_id = {s["store_id"]: s for s in stores}
    assert len(stores) == len(by_id) > 196  # sin duplicados, incluye tiendas solo de filtros

    casaideas = by_id[900101525]
    assert casaideas["store_type"] == "casaideas_multitiendas_enc"
    assert casaideas["subvertical"] == "Hogar"
    assert casaideas["path"] == "/tiendas/900101525-casaideas-multitiendas-enc"

    filter_only = [s for s in stores if not s["store_type"]]
    assert filter_only, "Moda/Vapes traen tiendas que no están en ningún grupo"
    assert all(s["filters"] and s["path"] == f"/tiendas/{s['store_id']}" for s in filter_only)


def test_market_listing_has_landing_classification(page):
    stores = parse_vertical_listing(page("listing_market"))
    classes = {s["landing_classification"] for s in stores if s["landing_classification"]}
    assert "supermercado" in classes
    assert any(s["subvertical"] == "Turbo" for s in stores)


def test_parse_brand_chain_lists_branches(page):
    chain = parse_brand_chain(page("brand_chain"))
    assert chain["brand_id"] == 1833
    assert chain["name"] == "Vapiano"
    assert len(chain["stores"]) == 2
    assert chain["stores"][0]["path"].startswith("/restaurantes/")


def test_parse_restaurant_menu_and_details(page):
    r = parse_restaurant(page("restaurant"))
    assert r["store"]["store_id"] == 384
    assert r["store"]["brand_id"] == 3607
    assert r["store"]["lat"] < -33 and r["store"]["lng"] < -70  # location viene como [lng, lat]
    assert r["cuisines"] == ["Internacional"]
    assert len(r["sections"]) == 9
    assert len(r["items"]) == 61
    section_ids = {s["section_id"] for s in r["sections"]}
    assert all(i["section_id"] in section_ids for i in r["items"])
    assert all(i["image_url"].startswith("https://images.rappi.cl/") for i in r["items"] if i["image_url"])


def test_a_dish_in_mas_vendidos_and_in_its_own_section_keeps_both(page):
    """Un plato en «Más vendidos» y en «Hamburguesas» es un solo ítem: queda en su sección (la última en el menú, como
    antes) y recuerda las otras en `extra_section_ids`. Antes venía dos veces y al guardarse ganaba la última."""
    data = page("restaurant")
    burgers = next(c for c in restaurant_block(data)["corridors"] if c["name"] == "Hamburguesas")
    data = with_top_section(data, burgers["products"][:2])

    r = parse_restaurant(data)

    assert [s["name"] for s in r["sections"]][:2] == ["Más vendidos", "Combos"]
    assert r["sections"][0]["section_id"] == 99999
    assert len(r["items"]) == 61  # sin repetidos
    by_id = {i["item_id"]: i for i in r["items"]}
    for product in burgers["products"][:2]:
        dish = by_id[product["id"]]
        assert dish["section_id"] == 13278
        assert dish["extra_section_ids"] == [99999]
    assert sum(1 for i in r["items"] if i["extra_section_ids"]) == 2


def test_a_dish_marked_popular_in_any_section_is_popular(page):
    data = page("restaurant")
    burgers = next(c for c in restaurant_block(data)["corridors"] if c["name"] == "Hamburguesas")
    data = with_top_section(data, [{**burgers["products"][0], "isPopular": True}])

    [dish] = [i for i in parse_restaurant(data)["items"] if i["item_id"] == burgers["products"][0]["id"]]

    assert dish["is_popular"] is True  # la última aparición (en «Hamburguesas») no lo marca


def test_a_menu_without_repeated_dishes_does_not_change(page):
    """Sin platos repetidos (el fixture tal cual): un ítem por plato, en el orden del menú y sin otras secciones."""
    data = page("restaurant")
    products = [p for c in restaurant_block(data)["corridors"] for p in c["products"]]

    r = parse_restaurant(data)

    assert [(i["item_id"], i["section_id"]) for i in r["items"]] == [(p["id"], p["corridorId"]) for p in products]
    assert all(i["extra_section_ids"] == [] for i in r["items"])


def test_restaurant_with_unexpected_shape_is_parse_error(page):
    """Un plato sin id (KeyError) o con un id raro (ValueError) es un error de página: se prueba otra sucursal."""
    data = page("restaurant")
    block = next(v for k, v in data["props"]["pageProps"]["fallback"].items() if k.startswith('@"restaurant/'))
    block["corridors"][0]["products"][0].pop("id")
    with pytest.raises(ParseError):
        parse_restaurant(data)
    block["corridors"][0]["products"][0]["id"] = "no-es-numero"
    with pytest.raises(ParseError):
        parse_restaurant(data)
