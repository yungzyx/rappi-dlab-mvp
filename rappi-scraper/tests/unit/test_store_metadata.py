from rappi_scraper.scraping.store_metadata import normalize_stores


def _raw(store_id, brand, city, reviews=0):
    return {
        "storeId": store_id,
        "brandName": brand,
        "storeName": f"{brand} {store_id}",
        "city": city,
        "address": "Calle 1",
        "lat": -33.4,
        "lng": -70.6,
        "url": f"https://www.rappi.cl/tiendas/{store_id}-x",
        "review": {"total": reviews},
    }


def test_normalize_stores_strips_city_and_skips_incomplete():
    metadata = {
        "storesById": {
            "1": _raw(1, "Lider", "Santiago de Chile", reviews=10),
            "3": _raw(3, "Lider Express", " Iquique"),
            "5": {**_raw(5, "Jumbo", "Talca"), "url": None},
            "6": {**_raw(6, "Jumbo", "Talca"), "lat": None},
        }
    }
    stores = normalize_stores(metadata)
    assert {s["store_id"] for s in stores} == {1, 3}
    assert next(s for s in stores if s["store_id"] == 3)["city"] == "Iquique"
    assert stores[0]["path"] == "/tiendas/1-x"
    assert stores[0]["reviews"] == 10
