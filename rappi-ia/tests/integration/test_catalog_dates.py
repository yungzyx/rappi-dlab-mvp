"""De qué fecha son los precios del catálogo (catalog/dates.py): el `catalogo` de /catalog/home, que la app y el panel
muestran junto a los precios.

Sobre el catálogo de `seed_demo`, movido para que su descarga más nueva sea del 18-10-2026 a las 02:30 UTC: en Chile
(UTC-3 en octubre) todavía es el 17-10.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from rappi_ia.api import app as api
from rappi_ia.catalog.dates import catalog_dates
from rappi_ia.catalog.home import home
from rappi_ia.demo.seed import seed_demo

NEWEST = datetime(2026, 10, 18, 2, 30, tzinfo=UTC)
DAY = "2026-10-17"  # NEWEST en hora de Chile
NEXT_DAY = "2026-10-18"
VERTICALS = {"supermercado", "conveniencia", "turbo", "licores", "farmacia", "mall", "chocolateria", "restaurantes"}
TURBO_STORES = (9301, 9302)


@pytest.fixture
def seeded(db):
    seed_demo(db)
    # Corre los precios de productos y de platos para que el más nuevo de cada historial sea NEWEST; las distancias
    # entre ellos (la corrida anterior, 7 días antes) no cambian.
    for table in ("price_snapshots", "menu_price_snapshots"):
        db.execute(
            f"UPDATE {table} SET scraped_at = scraped_at + (%s - (SELECT max(scraped_at) FROM {table}))", (NEWEST,)
        )
    return db


def one_day(day: str) -> dict:
    return {"desde": day, "hasta": day}


def new_run(conn, kind: str, status: str) -> int:
    return conn.execute(
        "INSERT INTO scrape_runs (kind, status) VALUES (%s, %s) RETURNING run_id", (kind, status)
    ).fetchone()[0]


def test_each_vertical_dates_its_current_prices_in_chile_time(seeded):
    dates = catalog_dates(seeded)

    assert set(dates["verticales"]) == VERTICALS
    assert all(day == one_day(DAY) for day in dates["verticales"].values())
    assert (dates["desde"], dates["hasta"]) == (DAY, DAY)


def test_a_vertical_downloaded_earlier_keeps_its_own_date(seeded):
    # Turbo se bajó 20 días antes que lo demás (sus dos tiendas, con su corrida anterior): el catálogo va del 27-09 al
    # 17-10 y Turbo dice el 27-09.
    seeded.execute(
        "UPDATE price_snapshots SET scraped_at = scraped_at - interval '20 days' WHERE store_id = ANY(%s)",
        (list(TURBO_STORES),),
    )

    dates = catalog_dates(seeded)

    assert dates["verticales"]["turbo"] == one_day("2026-09-27")
    assert dates["verticales"]["supermercado"] == one_day(DAY)
    assert (dates["desde"], dates["hasta"]) == ("2026-09-27", DAY)


def test_an_offer_no_longer_current_does_not_date_the_catalog(seeded):
    # La corrida anterior (7 días antes) dejó precios en el historial, pero ninguno sigue vigente.
    old = seeded.execute("SELECT count(*) FROM price_snapshots WHERE scraped_at < %s - interval '1 day'", (NEWEST,))
    assert old.fetchone()[0] > 0

    assert catalog_dates(seeded)["desde"] == DAY


@pytest.mark.parametrize("status", ["failed", "running"])
def test_prices_of_a_run_that_failed_or_is_still_running_never_date_the_catalog(seeded, status):
    later = NEWEST + timedelta(days=1)
    # Una corrida de tiendas que alcanzó a bajar un precio del súper Centro: ese precio queda vigente (es la última
    # corrida de su formato), y una de restaurantes que bajó un plato.
    stores_run = new_run(seeded, "stores", status)
    seeded.execute(
        "INSERT INTO price_snapshots (run_id, store_id, sku, price, in_stock, scraped_at)"
        " VALUES (%s, 9101, 'sku-91001', 1990, true, %s)",
        (stores_run, later),
    )
    dishes_run = new_run(seeded, "restaurants", status)
    seeded.execute(
        "INSERT INTO menu_price_snapshots (run_id, item_id, price, real_price, scraped_at)"
        " VALUES (%s, 98001, 9990, 9990, %s)",
        (dishes_run, later),
    )
    current = seeded.execute(
        "SELECT run_id FROM v_latest_offers WHERE store_id = 9101 AND sku = 'sku-91001' AND current"
    ).fetchone()
    assert current == (stores_run,)

    dates = catalog_dates(seeded)

    assert dates["verticales"]["supermercado"] == one_day(DAY)
    assert dates["verticales"]["restaurantes"] == one_day(DAY)
    assert dates["hasta"] == DAY

    # La misma corrida, ya terminada, sí cuenta.
    seeded.execute("UPDATE scrape_runs SET status = 'done' WHERE run_id IN (%s, %s)", (stores_run, dishes_run))

    dates = catalog_dates(seeded)

    assert dates["verticales"]["supermercado"]["hasta"] == NEXT_DAY
    assert dates["verticales"]["restaurantes"] == {"desde": DAY, "hasta": NEXT_DAY}
    assert dates["hasta"] == NEXT_DAY


def test_an_empty_catalog_has_no_dates(db):
    assert catalog_dates(db) == {"desde": None, "hasta": None, "verticales": {}}


def test_home_says_the_date_of_its_prices(seeded):
    assert home(seeded)["catalogo"] == catalog_dates(seeded)

    def conn_override():
        yield seeded

    api.app.dependency_overrides[api.get_conn] = conn_override
    try:
        body = TestClient(api.app).get("/catalog/home").json()
    finally:
        api.app.dependency_overrides.clear()

    assert (body["catalogo"]["desde"], body["catalogo"]["hasta"]) == (DAY, DAY)
    assert body["catalogo"]["verticales"]["turbo"] == one_day(DAY)
