import pytest

from conftest import menu_sections, with_section
from rappi_scraper.scraping.astro import Page, ParseError
from rappi_scraper.scraping.listing_parser import parse_vertical_listing
from rappi_scraper.scraping.restaurant_parser import parse_restaurant


def test_listing_lists_each_store_once_with_its_group(page):
    stores = parse_vertical_listing(page("listing_market"))
    by_id = {s["store_id"]: s for s in stores}
    assert len(stores) == len(by_id) == 5  # Lider sale en los dos grupos
    lider = by_id[900025946]
    assert (lider["store_type"], lider["landing_classification"]) == ("lider", "Mercados")
    assert lider["path"] == "/tiendas/900025946-lider"
    assert any(s["store_type"].startswith("turbo") for s in stores)


def test_a_page_without_listing_has_no_stores(page):
    assert parse_vertical_listing(page("store")) == []


def test_parse_restaurant_menu_and_details(page):
    r = parse_restaurant(page("restaurant"))
    assert r["store"]["store_id"] == 384
    assert (r["store"]["brand_id"], r["store"]["brand_name"]) == (3607, "Rincón Venezolano")
    assert r["store"]["path"] == "/restaurantes/384-rincon-venezolano"
    assert r["store"]["lat"] is None and r["store"]["address"] == ""  # no vienen: no pisan lo guardado
    assert r["details"]["rating"] == 4.4 and r["details"]["review_count"] == 168
    assert r["details"]["schedules"] is None and r["cuisines"] == []
    assert [s["name"] for s in r["sections"]] == ["Hamburguesas", "Combos", "Promociones"]  # sin Populares ni Para Ti
    assert len(r["items"]) == 7
    section_ids = {s["section_id"] for s in r["sections"]}
    assert all(i["section_id"] in section_ids for i in r["items"])
    assert all(i["image_url"].startswith("https://images.rappi.cl/") and "?" not in i["image_url"] for i in r["items"])
    assert all(i["real_price"] == i["price"] and i["discount_pct"] == 0 for i in r["items"])


def test_a_dish_in_populares_is_popular(page):
    data = page("restaurant")
    [popular] = next(s for s in menu_sections(data) if s["title"] == "Populares")["items"]

    by_id = {i["item_id"]: i for i in parse_restaurant(data)["items"]}

    assert by_id[popular["product"]["id"]]["is_popular"] is True
    assert sum(i["is_popular"] for i in by_id.values()) == 1


def test_a_dish_in_two_sections_keeps_both(page):
    """Un plato en dos secciones es un solo ítem: queda en la última del menú y recuerda las otras en
    `extra_section_ids` (migración 040)."""
    data = page("restaurant")
    burgers = next(s for s in menu_sections(data) if s["title"] == "Hamburguesas")["items"]
    data = with_section(data, 99999, "Lo más pedido", burgers[:2], first=True)

    r = parse_restaurant(data)

    assert [s["name"] for s in r["sections"]][:2] == ["Lo más pedido", "Hamburguesas"]
    assert len(r["items"]) == 7  # sin repetidos
    by_id = {i["item_id"]: i for i in r["items"]}
    for entry in burgers[:2]:
        dish = by_id[entry["product"]["id"]]
        assert (dish["section_id"], dish["extra_section_ids"]) == (13278, [99999])
    assert sum(1 for i in r["items"] if i["extra_section_ids"]) == 2


def test_a_discounted_dish_keeps_its_normal_price(page):
    data = page("restaurant")
    [entry, *_] = next(s for s in menu_sections(data) if s["title"] == "Combos")["items"]
    product = {**entry["product"], "id": 1, "pricing": {"currentPrice": 7500, "originalPrice": 10000}}
    data = with_section(data, 77, "Ofertas", [{"product": product}])

    [dish] = [i for i in parse_restaurant(data)["items"] if i["item_id"] == 1]

    assert (dish["price"], dish["real_price"], dish["discount_pct"]) == (7500, 10000, 25.0)


def test_a_menu_out_of_coverage_has_no_dishes(page):
    """Con la ubicación fuera de la zona del local, la página trae todo el menú en "No disponible" (-404), sin
    secciones: no se toma (el pipeline prueba otra sucursal), pero el local se lee igual."""
    data = page("restaurant")
    entries = [e for s in menu_sections(data) for e in s["items"]]
    view = next(line for line in data.html.splitlines() if line.startswith("<div data-analytics"))
    out_of_coverage = with_section(Page(data.path, view), -404, "No disponible", entries)

    r = parse_restaurant(out_of_coverage)

    assert r["store"]["store_id"] == 384
    assert r["items"] == [] and r["sections"] == []


def test_restaurant_with_unexpected_shape_is_parse_error(page):
    """Un plato sin id (KeyError) o con un id raro (ValueError) es un error de página: se prueba otra sucursal."""
    with pytest.raises(ParseError):
        parse_restaurant(with_section(page("restaurant"), 5, "X", [{"product": {"title": "sin id"}}]))
    with pytest.raises(ParseError):
        parse_restaurant(with_section(page("restaurant"), 5, "X", [{"product": {"id": "no-es-numero"}}]))


def test_a_page_without_the_restaurant_data_is_parse_error(page):
    with pytest.raises(ParseError, match="VIEW_STORE"):
        parse_restaurant(page("store"))
