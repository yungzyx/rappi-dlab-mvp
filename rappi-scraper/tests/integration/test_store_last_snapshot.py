"""El último snapshot de cada tienda (migración 038), con su formato y la última corrida del formato (039), en su propia
tabla: store_last_snapshot sigue al historial y a stores, y v_store_format_runs, que ahora es esa tabla, da lo mismo que
antes; v_latest_offers, la única definición de oferta vigente, también. Las definiciones viejas (019 y 032) se copian
aquí para comparar fila por fila."""

from datetime import UTC, datetime, timedelta

from psycopg.types.json import Jsonb

from rappi_scraper.storage import repository

T0 = datetime(2026, 9, 1, 12, tzinfo=UTC)

# v_store_format_runs de la migración 019: el último snapshot de cada tienda, buscado en price_snapshots.
OLD_STORE_FORMAT_RUNS = """
WITH last AS (
    SELECT s.store_id, COALESCE(s.store_type, 'id:' || s.store_id) AS format, l.run_id, l.scraped_at
    FROM stores s
    CROSS JOIN LATERAL (SELECT ps.run_id, ps.scraped_at FROM price_snapshots ps WHERE ps.store_id = s.store_id
                        ORDER BY ps.scraped_at DESC, ps.run_id DESC LIMIT 1) l
)
SELECT store_id, format,
       first_value(run_id) OVER (PARTITION BY format ORDER BY scraped_at DESC, run_id DESC) AS format_run_id
FROM last"""

# v_latest_offers de la migración 032, con la v_store_format_runs de la 019.
OLD_LATEST_OFFERS = f"""
SELECT lp.store_id, lp.sku, lp.price, lp.real_price, lp.discount_pct, lp.in_stock, lp.run_id, lp.scraped_at,
       f.format_run_id,
       CASE WHEN lp.run_id = f.format_run_id THEN true
            WHEN r.run_id IS NULL OR lp.run_id >= r.run_id THEN false
            WHEN NOT EXISTS (SELECT 1 FROM store_products sp
                             WHERE sp.store_id = lp.store_id AND sp.sku = lp.sku
                               AND (sp.aisle_id = ANY(r.aisles) OR sp.sub_aisle_id = ANY(r.aisles))) THEN false
            ELSE COALESCE(lp.run_id = (SELECT max(j.run_id) FROM scrape_jobs j
                                       JOIN stores js ON js.store_id = (j.result->>'store_id')::bigint
                                       WHERE j.job_type = 'store_group' AND j.status = 'done' AND j.run_id < r.run_id
                                         AND COALESCE(js.store_type, 'id:' || js.store_id) = f.format), false)
       END AS current
FROM latest_prices lp
JOIN ({OLD_STORE_FORMAT_RUNS}) f ON f.store_id = lp.store_id
LEFT JOIN (
    SELECT j.run_id, (j.result->>'store_id')::bigint AS store_id, array_agg(a.aisle_id::bigint) AS aisles
    FROM scrape_jobs j
    CROSS JOIN LATERAL jsonb_array_elements_text(j.result->'pasillos_omitidos') a(aisle_id)
    WHERE j.job_type = 'store_group' AND j.status = 'done'
      AND jsonb_typeof(j.result->'pasillos_omitidos') = 'array' AND j.result->'pasillos_omitidos' <> '[]'
    GROUP BY 1, 2
) r ON r.run_id = f.format_run_id AND r.store_id = lp.store_id"""

NEW_LATEST_OFFERS = """
SELECT store_id, sku, price, real_price, discount_pct, in_stock, run_id, scraped_at, format_run_id, current
FROM v_latest_offers"""

STORE_LAST = "SELECT store_id, run_id, scraped_at FROM store_last_snapshot"
HISTORY_STORE = """
SELECT DISTINCT ON (store_id) store_id, run_id, scraped_at
FROM price_snapshots ORDER BY store_id, scraped_at DESC, run_id DESC"""


def _store(db, store_id: int, store_type: str | None) -> None:
    db.execute(
        "INSERT INTO stores (store_id, name, store_type) VALUES (%s, %s, %s)",
        (store_id, f"Tienda {store_id}", store_type),
    )


def _product(db, store_id: int, sku: str, aisle: int | None = None, sub_aisle: int | None = None) -> None:
    db.execute(
        "INSERT INTO store_products (store_id, sku, aisle_id, sub_aisle_id) VALUES (%s, %s, %s, %s)",
        (store_id, sku, aisle, sub_aisle),
    )


def _download(db, run: int, store_id: int, skus: str, day: float, skipped=(), price: int = 1000) -> None:
    """Una bajada de una tienda: un snapshot por SKU y el job store_group terminado, con sus pasillos omitidos."""
    for sku in skus:
        db.execute(
            "INSERT INTO price_snapshots (run_id, store_id, sku, price, real_price, in_stock, scraped_at)"
            " VALUES (%s, %s, %s, %s, %s, true, %s)",
            (run, store_id, sku, price + day, price + day, T0 + timedelta(days=day)),
        )
    db.execute(
        "INSERT INTO scrape_jobs (run_id, job_key, job_type, payload, status, result)"
        " VALUES (%s, %s, 'store_group', '{}', 'done', %s)",
        (run, f"type:{store_id}", Jsonb({"store_id": store_id, "products": len(skus), "pasillos_omitidos": skipped})),
    )


def _assert_same_as_before(db) -> dict:
    """La tabla es el último snapshot del historial y las dos vistas dan exactamente las filas de antes. Devuelve la
    vigencia de cada oferta, para comprobar que el caso no es trivial."""
    assert set(db.execute(STORE_LAST).fetchall()) == set(db.execute(HISTORY_STORE).fetchall())
    old_runs = db.execute(OLD_STORE_FORMAT_RUNS).fetchall()
    assert sorted(db.execute("SELECT * FROM v_store_format_runs").fetchall()) == sorted(old_runs)
    old_offers = db.execute(OLD_LATEST_OFFERS).fetchall()
    assert sorted(db.execute(NEW_LATEST_OFFERS).fetchall()) == sorted(old_offers)
    return {(row[0], row[1]): row[-1] for row in old_offers}


def test_format_runs_and_offers_match_the_old_views(db):
    """Varias corridas por tienda, sucursales que se turnan dentro de un formato, pasillos omitidos (con y sin rescate),
    tiendas nuevas, snapshots y corridas borrados, fechas corregidas y una tienda que cambia de formato: en cada paso,
    las vistas sobre store_last_snapshot dan las mismas filas que las de antes."""
    r1, r2, r3, r4, r5 = (repository.start_run(db, "stores", {}) for _ in range(5))
    _store(db, 1, "lider")  # sucursal B
    _store(db, 2, "lider")  # sucursal A, mismo formato
    _store(db, 3, "jumbo")
    _store(db, 4, None)  # sin formato: es su propio formato
    _store(db, 5, "Lider")  # otro formato: solo cambia una mayúscula
    _store(db, 6, "jumbo")
    _store(db, 7, "tottus")  # sin precios: no sale
    for sku, aisle, sub in [("a", 10, 100), ("b", 11, 110), ("c", 10, 101), ("d", 12, 120), ("e", 11, 111)]:
        _product(db, 1, sku, aisle, sub)
    _product(db, 2, "a", 10)
    _product(db, 2, "b", 11)
    _product(db, 3, "a", 30)
    _product(db, 3, "b", 31)
    _product(db, 4, "z")
    _product(db, 5, "a", 10)
    _product(db, 6, "a", 30)

    _download(db, r1, 1, "abcde", 0)
    _download(db, r1, 3, "ab", 0)
    _download(db, r1, 4, "z", 0)
    _download(db, r2, 2, "ab", 7)  # lider: B → A
    _download(db, r2, 3, "a", 7, skipped=[31])  # jumbo sin el pasillo 31: b vale su precio de la corrida 1
    _download(db, r3, 1, "ac", 14, skipped=[11, 120])  # B otra vez: la bajada anterior del formato fue A, sin rescate
    current = _assert_same_as_before(db)
    assert current[(3, "b")] is True and current[(1, "b")] is False and current[(2, "a")] is False
    assert current[(1, "a")] is True and current[(4, "z")] is True

    _download(db, r4, 5, "a", 21)  # tienda nueva con un formato nuevo
    _download(db, r4, 6, "a", 21)  # tienda nueva de jumbo: la 3 deja de ser la vigente
    current = _assert_same_as_before(db)
    assert current[(3, "a")] is False and current[(6, "a")] is True and current[(5, "a")] is True

    _download(db, r5, 1, "e", 28, skipped=[10])  # B → B: el pasillo 10 vale el precio de la corrida anterior
    current = _assert_same_as_before(db)
    assert current[(1, "e")] is True and current[(1, "c")] is True and current[(1, "b")] is False

    # Borrar snapshots: los de la última bajada de B (vuelve a mandar la de A) y un SKU suelto.
    db.execute("DELETE FROM price_snapshots WHERE run_id = %s AND store_id = 1", (r5,))
    db.execute("DELETE FROM price_snapshots WHERE run_id = %s AND store_id = 2 AND sku = 'b'", (r2,))
    _assert_same_as_before(db)

    # Una corrida entera en cascada: las tiendas 5 y 6 se quedan sin precios y salen de la vista.
    db.execute("DELETE FROM scrape_runs WHERE run_id = %s", (r4,))
    assert db.execute("SELECT count(*) FROM store_last_snapshot WHERE store_id IN (5, 6)").fetchone()[0] == 0
    _assert_same_as_before(db)

    # Corregir fechas hacia atrás (la bajada de A queda antes que la primera de B) y hacia adelante.
    db.execute("UPDATE price_snapshots SET scraped_at = scraped_at - interval '30 days' WHERE run_id = %s", (r2,))
    _assert_same_as_before(db)
    db.execute("UPDATE price_snapshots SET scraped_at = scraped_at + interval '60 days' WHERE store_id = 4")
    _assert_same_as_before(db)

    # Una tienda cambia de formato (se lee de stores, al tiro) y se borra un producto (en cascada).
    db.execute("UPDATE stores SET store_type = 'jumbo' WHERE store_id = 4")
    _assert_same_as_before(db)
    db.execute("DELETE FROM store_products WHERE store_id = 1 AND sku = 'a'")
    _assert_same_as_before(db)
    db.execute("UPDATE stores SET store_type = store_type, name = 'Otra' WHERE store_id = 3")  # como al redescubrirla
    _assert_same_as_before(db)
    db.execute("UPDATE stores SET store_type = NULL WHERE store_id = 3")  # jumbo pierde a su tienda más nueva
    _assert_same_as_before(db)

    # Borrar la tienda que tiene la última corrida de su formato (en cascada hasta sus snapshots).
    lider = "SELECT DISTINCT format_run_id FROM v_store_format_runs WHERE format = 'lider'"
    before = db.execute(lider).fetchone()[0]
    holder = db.execute(
        "SELECT store_id FROM store_last_snapshot WHERE format = 'lider' AND run_id = %s", (before,)
    ).fetchone()[0]
    db.execute("DELETE FROM stores WHERE store_id = %s", (holder,))
    assert db.execute(lider).fetchone()[0] != before
    _assert_same_as_before(db)

    db.execute("TRUNCATE price_snapshots")
    assert db.execute("SELECT count(*) FROM store_last_snapshot").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM v_store_format_runs").fetchone()[0] == 0


def test_new_snapshot_updates_the_store_row(db):
    """Un snapshot nuevo pone su corrida y su fecha en la fila de su tienda; uno atrasado no la cambia; con la misma
    fecha gana la corrida más nueva (el desempate de v_store_format_runs); el reintento de un job (ON CONFLICT … DO
    UPDATE de save_products) también la sigue."""
    r1, r2, r3 = (repository.start_run(db, "stores", {}) for _ in range(3))
    _store(db, 1, "lider")
    _product(db, 1, "a")

    def last():
        return db.execute("SELECT run_id, scraped_at FROM store_last_snapshot WHERE store_id = 1").fetchone()

    def snap(run, day):
        db.execute(
            "INSERT INTO price_snapshots (run_id, store_id, sku, price, scraped_at) VALUES (%s, 1, 'a', 1000, %s)"
            " ON CONFLICT (run_id, store_id, sku) DO UPDATE SET scraped_at = EXCLUDED.scraped_at",
            (run, T0 + timedelta(days=day)),
        )

    assert last() is None
    snap(r2, 7)
    assert last() == (r2, T0 + timedelta(days=7))
    snap(r1, 0)  # llega después, pero es más viejo
    assert last() == (r2, T0 + timedelta(days=7))
    snap(r3, 7)  # misma fecha, corrida más nueva
    assert last() == (r3, T0 + timedelta(days=7))
    snap(r1, 10)  # el reintento de la corrida 1 la deja como la más nueva
    assert last() == (r1, T0 + timedelta(days=10))
    snap(r1, 3)  # y si su fecha retrocede, el último vuelve a leerse del historial
    assert last() == (r3, T0 + timedelta(days=7))

    repository.save_products(db, r2, 1, [{"product_id": "b", "name": "B", "price": 700, "in_stock": True}])
    run_id, scraped_at = last()
    assert run_id == r2 and scraped_at > T0 + timedelta(days=7)  # sin fecha, el snapshot queda con la hora actual
    assert db.execute("SELECT format_run_id FROM v_store_format_runs WHERE store_id = 1").fetchone()[0] == r2


def test_moving_a_snapshot_to_another_store_updates_both_rows(db):
    """Un UPDATE que cambia la tienda de un snapshot vuelve a leer la tienda que lo pierde y pone el snapshot en la que
    lo gana."""
    r1, r2 = (repository.start_run(db, "stores", {}) for _ in range(2))
    for store_id in (1, 2):
        _store(db, store_id, "lider")
        _product(db, store_id, "a")
    _download(db, r1, 1, "a", 0)
    _download(db, r2, 1, "a", 7)
    _download(db, r1, 2, "a", 3)
    assert set(db.execute(STORE_LAST).fetchall()) == set(db.execute(HISTORY_STORE).fetchall())

    db.execute("DELETE FROM price_snapshots WHERE run_id = %s AND store_id = 2", (r1,))
    db.execute("UPDATE price_snapshots SET store_id = 2 WHERE run_id = %s AND store_id = 1", (r2,))
    rows = dict((s, (r, t)) for s, r, t in db.execute(STORE_LAST).fetchall())
    assert rows == {1: (r1, T0), 2: (r2, T0 + timedelta(days=7))}
    _assert_same_as_before(db)
