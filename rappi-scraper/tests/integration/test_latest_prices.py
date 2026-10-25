"""El último precio en su propia tabla (migración 032): `latest_prices` y `latest_menu_prices` siguen al historial, la
vigencia de las ofertas sale de una sola vista (`v_latest_offers`) y el reporte cuenta los cambios de precio sin
recorrer todo el historial. Las consultas viejas se copian aquí para comparar: con datos normales dan lo mismo."""

from datetime import UTC, datetime, timedelta

from psycopg.types.json import Jsonb

from rappi_scraper import reporting
from rappi_scraper.storage import repository
from rappi_scraper.storage.search import _DISH_PRICES, _OFFER_PRICES, build_search_documents

T0 = datetime(2026, 9, 1, 12, tzinfo=UTC)

# _OFFER_PRICES antes de la migración 032 (commit 042b6b8c): el último precio con DISTINCT ON sobre el historial.
OLD_OFFER_PRICES = """
WITH latest AS (
    SELECT DISTINCT ON (store_id, sku) store_id, sku, price, run_id
    FROM price_snapshots
    ORDER BY store_id, sku, scraped_at DESC, run_id DESC
),
skipped AS (
    SELECT j.run_id, (j.result->>'store_id')::bigint AS store_id, array_agg(a.aisle_id::bigint) AS aisles
    FROM scrape_jobs j
    CROSS JOIN LATERAL jsonb_array_elements_text(j.result->'pasillos_omitidos') a(aisle_id)
    WHERE j.job_type = 'store_group' AND j.status = 'done' AND jsonb_typeof(j.result->'pasillos_omitidos') = 'array'
    GROUP BY 1, 2
),
rescue AS (
    SELECT sk.run_id, sk.store_id, sk.aisles,
           (SELECT max(ps.run_id) FROM price_snapshots ps
            WHERE ps.store_id = sk.store_id AND ps.run_id < sk.run_id) AS previous_run
    FROM skipped sk
)
SELECT l.store_id, l.sku, l.price,
       l.run_id = f.format_run_id
       OR COALESCE(l.run_id = r.previous_run
                   AND (sp.aisle_id = ANY(r.aisles) OR sp.sub_aisle_id = ANY(r.aisles)), false) AS current
FROM latest l
JOIN v_store_format_runs f USING (store_id)
LEFT JOIN rescue r ON r.run_id = f.format_run_id AND r.store_id = l.store_id
LEFT JOIN store_products sp ON sp.store_id = l.store_id AND sp.sku = l.sku
"""

# _DISH_PRICES antes de la migración 032.
OLD_DISH_PRICES = """
WITH latest AS (
    SELECT DISTINCT ON (mps.item_id) mps.item_id, mps.price, mps.real_price, mps.run_id, mps.scraped_at,
           mi.store_id, s.brand_id, COALESCE(s.brand_id::text, 'id:' || s.store_id) AS chain
    FROM menu_price_snapshots mps
    JOIN menu_items mi ON mi.item_id = mps.item_id
    JOIN stores s ON s.store_id = mi.store_id
    ORDER BY mps.item_id, mps.scraped_at DESC
),
chain_run AS (
    SELECT DISTINCT ON (chain) chain, run_id FROM latest ORDER BY chain, scraped_at DESC, run_id DESC
),
gone AS (
    SELECT job_key, max(run_id) AS run_id
    FROM scrape_jobs
    WHERE job_type = 'restaurant' AND status = 'skipped' AND result->>'reason' = 'ya no existe en Rappi'
    GROUP BY job_key
)
SELECT l.item_id, l.price, l.real_price,
       l.run_id = c.run_id AND l.run_id >= GREATEST(gc.run_id, gr.run_id, 0) AS current
FROM latest l
JOIN chain_run c USING (chain)
LEFT JOIN gone gc ON gc.job_key = 'chain:' || l.brand_id
LEFT JOIN gone gr ON gr.job_key = 'rest:' || l.store_id
"""


def _select(create_temp_table: str) -> str:
    """La consulta de un `CREATE TEMP TABLE … AS` de search.py."""
    return create_temp_table.split(" AS\n", 1)[1]


def _runs(db, n: int) -> list[int]:
    return [repository.start_run(db, "stores", {}) for _ in range(n)]


def _store(db, store_id: int, store_type: str | None, brand_id: int | None = None) -> None:
    if brand_id is not None:
        db.execute("INSERT INTO brands (brand_id, name) VALUES (%s, 'Cadena') ON CONFLICT DO NOTHING", (brand_id,))
    db.execute(
        "INSERT INTO stores (store_id, name, store_type, brand_id) VALUES (%s, %s, %s, %s)",
        (store_id, f"Tienda {store_id}", store_type, brand_id),
    )


def _product(db, store_id: int, sku: str, aisle: int | None = None, sub_aisle: int | None = None) -> None:
    db.execute(
        "INSERT INTO store_products (store_id, sku, aisle_id, sub_aisle_id) VALUES (%s, %s, %s, %s)",
        (store_id, sku, aisle, sub_aisle),
    )


def _snap(db, run: int, store_id: int, sku: str, price, day: float, in_stock: bool | None = True) -> None:
    db.execute(
        "INSERT INTO price_snapshots (run_id, store_id, sku, price, real_price, in_stock, scraped_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (run, store_id, sku, price, price, in_stock, T0 + timedelta(days=day)),
    )


def _latest(db, store_id: int, sku: str):
    return db.execute(
        "SELECT run_id, price FROM latest_prices WHERE store_id = %s AND sku = %s", (store_id, sku)
    ).fetchone()


def _history_latest(db) -> set[tuple]:
    return set(
        db.execute(
            """SELECT DISTINCT ON (store_id, sku) store_id, sku, price, real_price, discount_pct, pum, in_stock, run_id,
                      scraped_at
               FROM price_snapshots ORDER BY store_id, sku, scraped_at DESC, run_id DESC"""
        ).fetchall()
    )


def test_latest_prices_follows_newest_snapshot(db):
    """Cada escritura del historial (snapshot nuevo, uno atrasado, corrección, borrado y borrado en cascada) deja en
    latest_prices la fila más nueva de cada SKU, igual que recorrer el historial."""
    r1, r2, r3 = _runs(db, 3)
    _store(db, 1, "lider")
    _product(db, 1, "a")
    _product(db, 1, "b")

    _snap(db, r1, 1, "a", 1000, 0)
    assert _latest(db, 1, "a") == (r1, 1000)
    _snap(db, r2, 1, "a", 900, 7)
    assert _latest(db, 1, "a") == (r2, 900)
    _snap(db, r3, 1, "a", 500, -3)  # llega después, pero es más viejo: no reemplaza al último
    assert _latest(db, 1, "a") == (r2, 900)

    db.execute("UPDATE price_snapshots SET price = 950 WHERE run_id = %s AND sku = 'a'", (r2,))
    assert _latest(db, 1, "a") == (r2, 950)
    db.execute("DELETE FROM price_snapshots WHERE run_id = %s AND sku = 'a'", (r2,))
    assert _latest(db, 1, "a") == (r1, 1000)

    # El reintento de un job vuelve a guardar la misma corrida (ON CONFLICT … DO UPDATE de save_products).
    repository.save_products(db, r1, 1, [{"product_id": "b", "name": "B", "price": 700, "in_stock": True}])
    repository.save_products(db, r1, 1, [{"product_id": "b", "name": "B", "price": 650, "in_stock": True}])
    assert _latest(db, 1, "b") == (r1, 650)
    assert set(db.execute("SELECT * FROM latest_prices").fetchall()) == _history_latest(db)

    db.execute("DELETE FROM scrape_runs WHERE run_id = %s", (r1,))  # en cascada: a queda con su snapshot de r3
    assert _latest(db, 1, "a") == (r3, 500)
    assert _latest(db, 1, "b") is None
    db.execute("DELETE FROM store_products WHERE sku = 'a'")
    assert _latest(db, 1, "a") is None

    _snap(db, r2, 1, "b", 800, 1)
    db.execute("TRUNCATE price_snapshots")
    assert db.execute("SELECT count(*) FROM latest_prices").fetchone()[0] == 0


def test_same_scraped_at_prefers_newer_run(db):
    """Con la misma fecha (un CSV antiguo importado dos veces), el último precio es el de la corrida más nueva, llegue
    en el orden que llegue: el desempate de v_store_format_runs."""
    r1, r2 = _runs(db, 2)
    _store(db, 1, "lider")
    _product(db, 1, "a")
    _product(db, 1, "b")
    _snap(db, r1, 1, "a", 1000, 0)
    _snap(db, r2, 1, "a", 900, 0)
    _snap(db, r2, 1, "b", 800, 0)
    _snap(db, r1, 1, "b", 700, 0)

    rows = db.execute("SELECT sku, run_id, price FROM v_latest_prices ORDER BY sku").fetchall()
    assert rows == [("a", r2, 900), ("b", r2, 800)]


def test_latest_menu_prices_follows_newest_snapshot(db):
    r1, r2 = _runs(db, 2)
    _store(db, 7, None)
    db.execute("INSERT INTO menu_items (item_id, rappi_item_id, store_id, name) VALUES (70, 70, 7, 'Pizza')")

    def snap(run, price, day):
        db.execute(
            "INSERT INTO menu_price_snapshots (run_id, item_id, price, scraped_at) VALUES (%s, 70, %s, %s)",
            (run, price, T0 + timedelta(days=day)),
        )

    def latest():
        return db.execute("SELECT run_id, price FROM latest_menu_prices WHERE item_id = 70").fetchone()

    snap(r1, 9990, 0)
    snap(r2, 8990, 0)  # misma fecha: gana la corrida más nueva
    assert latest() == (r2, 8990)
    db.execute("UPDATE menu_price_snapshots SET price = 7990 WHERE run_id = %s", (r2,))
    assert latest() == (r2, 7990)
    db.execute("DELETE FROM menu_price_snapshots WHERE run_id = %s", (r2,))
    assert latest() == (r1, 9990)
    db.execute("DELETE FROM menu_items WHERE item_id = 70")
    assert latest() is None


def _three_run_catalog(db) -> tuple[int, int, int]:
    """Tres corridas: el formato lider (tiendas 1 y 2) se baja en las tres desde la tienda 1, jumbo (3) hasta la 2 y
    la tienda 4 (sin formato) solo en la 1. La corrida 3 no pudo leer el pasillo 11 ni el sub-pasillo 120 de la 1."""
    r1, r2, r3 = _runs(db, 3)
    _store(db, 1, "lider")
    _store(db, 2, "lider")
    _store(db, 3, "jumbo")
    _store(db, 4, None)
    for sku, aisle, sub in [("a", 10, 100), ("b", 11, 110), ("c", 10, 101), ("d", 12, 120), ("e", 11, 111)]:
        _product(db, 1, sku, aisle, sub)
    _product(db, 2, "a", 10)
    _product(db, 3, "a", 30)
    _product(db, 3, "b", 31)
    _product(db, 4, "z")

    for sku in "abcde":
        _snap(db, r1, 1, sku, 1000, 0)
    _snap(db, r1, 2, "a", 990, 0)
    _snap(db, r1, 3, "a", 1100, 0)
    _snap(db, r1, 3, "b", 1200, 7)  # misma fecha que su snapshot de la corrida 2: gana la 2
    _snap(db, r1, 4, "z", 500, 0)
    for sku in "abd":
        _snap(db, r2, 1, sku, 950, 7)
    _snap(db, r2, 3, "a", 1050, 7, in_stock=False)
    _snap(db, r2, 3, "b", None, 7)
    _snap(db, r3, 1, "a", 900, 14)

    def job(run, store_id, skipped):
        db.execute(
            "INSERT INTO scrape_jobs (run_id, job_key, job_type, payload, status, result)"
            " VALUES (%s, %s, 'store_group', '{}', 'done', %s)",
            (run, f"type:{store_id}", Jsonb({"store_id": store_id, "products": 1, "pasillos_omitidos": skipped})),
        )

    # Cada corrida que bajó una tienda deja su job (la 1 y la 4 en las tres o en la 1, la 3 en la 1 y la 2).
    job(r1, 1, [])
    job(r2, 1, [])
    job(r3, 1, [11, 120])
    job(r1, 3, [])
    job(r2, 3, [99])
    job(r1, 4, [])
    return r1, r2, r3


def test_offer_prices_match_old_query(db):
    """La vigencia sale de v_latest_offers con el mismo resultado que la consulta vieja sobre el historial."""
    _three_run_catalog(db)

    old = set(db.execute(OLD_OFFER_PRICES).fetchall())
    new = set(db.execute(_select(_OFFER_PRICES)).fetchall())
    assert new == old
    current = {(store_id, sku): is_current for store_id, sku, _, is_current in new}
    assert current == {
        (1, "a"): True,  # de la corrida 3
        (1, "b"): True,  # pasillo 11 omitido en la 3: vale su precio de la 2
        (1, "c"): False,  # la 2 ya no lo encontró y su pasillo se leyó
        (1, "d"): True,  # sub-pasillo 120 omitido
        (1, "e"): False,  # pasillo omitido, pero la 2 ya no lo encontró: no revive el precio de la 1
        (2, "a"): False,  # sucursal que su formato ya no baja
        (3, "a"): True,
        (3, "b"): True,
        (4, "z"): True,
    }


def test_skipped_aisle_rescue_needs_the_formats_previous_download(db):
    """Cada corrida baja una sucursal por formato, no siempre la misma: con B → A → B, si la segunda bajada de B no lee
    un pasillo, el rescate no puede revivir los precios de B de hace dos corridas (la anterior del formato fue A).
    Con B → B, sí. Sin una bajada anterior del formato (un CSV importado no deja jobs), no rescata: vigente es false,
    no NULL (la búsqueda toma NULL como vigente)."""
    runs = _runs(db, 4)
    _store(db, 1, "lider")  # sucursal B
    _store(db, 2, "lider")  # sucursal A, mismo formato
    _product(db, 1, "x", 11)
    _product(db, 1, "y", 10)
    _product(db, 2, "x", 11)
    _store(db, 3, "jumbo")
    _product(db, 3, "v", 10)
    _product(db, 3, "w", 11)

    def download(run, store_id, skus, day, skipped=()):
        for sku in skus:
            _snap(db, run, store_id, sku, 1000 + day, day)
        db.execute(
            "INSERT INTO scrape_jobs (run_id, job_key, job_type, payload, status, result)"
            " VALUES (%s, %s, 'store_group', '{}', 'done', %s)",
            (run, f"type:{store_id}", Jsonb({"store_id": store_id, "products": 1, "pasillos_omitidos": list(skipped)})),
        )

    def current():
        return dict(
            ((store_id, sku), is_current)
            for store_id, sku, is_current in db.execute("SELECT store_id, sku, current FROM v_latest_offers").fetchall()
        )

    _snap(db, runs[0], 3, "w", 500, 0)  # jumbo importado de un CSV: sin job
    download(runs[0], 1, "xy", 0)  # B
    download(runs[1], 2, "x", 7)  # A
    download(runs[1], 3, "v", 7, skipped=[11])
    download(runs[2], 1, "y", 14, skipped=[11])  # B otra vez, sin leer el pasillo 11
    jumbo = {(3, "v"): True, (3, "w"): False}
    assert current() == {(1, "x"): False, (1, "y"): True, (2, "x"): False, **jumbo}

    download(runs[3], 1, "x", 21, skipped=[10])  # B → B: el pasillo 10 vale el precio de la corrida anterior
    assert current() == {(1, "x"): True, (1, "y"): True, (2, "x"): False, **jumbo}


def test_dish_prices_match_old_query(db):
    r1, r2 = _runs(db, 2)
    _store(db, 7, None, brand_id=70)
    _store(db, 8, None, brand_id=70)
    _store(db, 9, None)
    for item_id, store_id in [(71, 7), (72, 7), (81, 8), (91, 9)]:
        db.execute(
            "INSERT INTO menu_items (item_id, rappi_item_id, store_id, name) VALUES (%s, %s, %s, 'Plato')",
            (item_id, item_id, store_id),
        )
    for run, item_id, price, day in [(r1, 71, 5000, 0), (r1, 72, 6000, 0), (r1, 81, 5100, 0), (r1, 91, 3000, 0),
                                     (r2, 71, 5500, 7), (r2, 72, None, 7)]:  # fmt: skip
        db.execute(
            "INSERT INTO menu_price_snapshots (run_id, item_id, price, scraped_at) VALUES (%s, %s, %s, %s)",
            (run, item_id, price, T0 + timedelta(days=day)),
        )
    db.execute(
        "INSERT INTO scrape_jobs (run_id, job_key, job_type, payload, status, result)"
        " VALUES (%s, 'rest:9', 'restaurant', '{}', 'skipped', '{\"reason\": \"ya no existe en Rappi\"}')",
        (r2,),
    )

    old = set(db.execute(OLD_DISH_PRICES).fetchall())
    assert set(db.execute(_select(_DISH_PRICES)).fetchall()) == old
    assert {(item_id, current) for item_id, _, _, current in old} == {(71, True), (72, True), (81, False), (91, False)}


def test_build_search_uses_current_offers(db):
    """La búsqueda publica las ofertas vigentes de v_latest_offers (el precio mínimo sale de ellas)."""
    _three_run_catalog(db)
    db.execute("INSERT INTO catalog_items (master_product_id, name) VALUES (500, 'Leche'), (600, 'Arroz')")
    db.execute("UPDATE store_products SET master_product_id = 500 WHERE sku IN ('a', 'b')")
    db.execute("UPDATE store_products SET master_product_id = 600 WHERE sku IN ('c', 'e')")
    db.execute("INSERT INTO store_verticals (store_id, vertical) VALUES (1, 'supermercado'), (3, 'supermercado')")

    build_search_documents(db)

    rows = dict(
        db.execute(
            "SELECT entity_id, (metadata->>'precio_min')::int FROM search_documents WHERE entity_type = 'catalog_item'"
        ).fetchall()
    )
    assert rows == {"500": 900}  # 600 solo tiene ofertas que ya no son vigentes


def test_report_price_changes_match_window_version(db):
    """El conteo del reporte (cada fila de la corrida contra la anterior de su SKU, por índice) da lo mismo que la
    ventana de v_price_changes sobre todo el historial."""
    r1, r2, r3 = _runs(db, 3)
    _store(db, 1, "lider")
    _store(db, 2, "jumbo")
    for store_id in (1, 2):
        for sku in "abcdef":
            _product(db, store_id, sku)
    rows = [
        (r1, 1, "a", 1000), (r2, 1, "a", 900), (r3, 1, "a", 950),  # baja y sube
        (r1, 1, "b", 1000), (r2, 1, "b", 1000), (r3, 1, "b", 1000),  # no cambia
        (r1, 1, "c", None), (r2, 1, "c", 800), (r3, 1, "c", None),  # sin precio antes o ahora
        (r1, 1, "d", 700), (r3, 1, "d", 600),  # falta en la corrida 2: compara con la 1
        (r2, 1, "e", 500), (r3, 1, "e", 500),
        (r1, 2, "a", 1000), (r2, 2, "a", 1100),  # otra tienda, mismo SKU
        (r3, 2, "f", 300),  # nuevo
    ]  # fmt: skip
    for run, store_id, sku, price in rows:
        _snap(db, run, store_id, sku, price, 7 * (run - r1))

    for run in (r1, r2, r3):
        window = db.execute("SELECT count(*) FROM v_price_changes WHERE run_id = %s", (run,)).fetchone()[0]
        assert db.execute(reporting.PRICE_CHANGES_SQL, {"run": run}).fetchone()[0] == window
    assert [db.execute(reporting.PRICE_CHANGES_SQL, {"run": r}).fetchone()[0] for r in (r1, r2, r3)] == [0, 2, 2]
