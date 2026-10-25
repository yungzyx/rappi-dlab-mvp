"""Pipeline completo contra `rappi_test`, con un cliente falso que sirve páginas reales guardadas."""

from argparse import Namespace

import pytest
from psycopg.pq import TransactionStatus

from conftest import FakeClient
from rappi_scraper import cli
from rappi_scraper.pipeline import discover, stores
from rappi_scraper.pipeline.queue import PossibleBlock
from rappi_scraper.pipeline.restaurants import process_restaurant_jobs
from rappi_scraper.pipeline.stores import process_store_jobs
from rappi_scraper.scraping.next_data import extract_next_data
from rappi_scraper.storage import repository
from rappi_scraper.storage.db import migrate
from rappi_scraper.storage.search import build_search_documents

LIDER = "/tiendas/900025946-lider"
LACTEOS = f"{LIDER}/lacteos-y-huevos"  # pasillo 14406; su primer sub-pasillo es yogurt (14521)


def _store_job(key, *paths, verticals=("supermercado",)):
    candidates = [
        {"store_id": i, "path": p, "city": "Santiago", "lat": -33.4, "lng": -70.6} for i, p in enumerate(paths)
    ]
    return {
        "job_key": key,
        "job_type": "store_group",
        "payload": {"verticals": list(verticals), "candidates": candidates},
    }


def _statuses(db):
    return dict(db.execute("SELECT job_key, status FROM scrape_jobs ORDER BY job_key").fetchall())


def test_store_job_falls_back_to_next_branch_and_skips_same_brand(db):
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(
        db,
        run,
        [
            _store_job("type:lider", "/tiendas/1-caida", "/tiendas/900025946-lider"),
            _store_job("type:otra", "/tiendas/900025946-lider"),  # misma marca (store_type 'lider')
        ],
    )
    client = FakeClient(unavailable={"/tiendas/1-caida"})

    process_store_jobs(db, client, run, max_aisles=1)

    assert _statuses(db) == {"type:lider": "done", "type:otra": "skipped"}
    assert db.execute("SELECT count(*) FROM store_products").fetchone()[0] > 0
    # la tienda repetida se detecta con la primera página, sin recorrer sus pasillos
    assert client.requested.count("/tiendas/900025946-lider") == 2
    assert db.execute("SELECT vertical FROM store_verticals WHERE store_id = 900025946").fetchone() == ("supermercado",)


def test_store_seen_only_in_filters_moves_to_turbo_once_its_page_says_so(db):
    """Sin store_type en el listado no se sabe si es Turbo: lo dice recién su página (store_type y sub_group)."""
    lider = "/tiendas/900025946-lider"

    class TurboPage(FakeClient):
        def get_next_data(self, path):
            data = super().get_next_data(path)
            if path == lider:
                data["props"]["pageProps"]["storeContext"].update(store_type="turbo_x", sub_group="Turbo")
            return data

    # Lo que deja el descubrimiento: la tienda sin formato, en el vertical del listado y con su filtro.
    repository.upsert_store(db, {"store_id": 900025946, "name": "Lider", "store_type": "", "path": lider})
    repository.upsert_store_vertical(db, 900025946, "supermercado", "", "", ["Té & Café"])
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [_store_job("id:900025946", lider)])

    process_store_jobs(db, TurboPage(), run, max_aisles=1)

    assert _statuses(db) == {"id:900025946": "done"}
    rows = db.execute("SELECT vertical, subvertical, filters FROM store_verticals WHERE store_id = 900025946")
    assert rows.fetchall() == [("turbo", "Turbo", ["Té & Café"])]


def test_store_already_known_as_turbo_stays_in_turbo_when_rediscovered_only_in_filters(db, monkeypatch):
    """La corrida siguiente la vuelve a ver solo en los filtros de supermercado: no debe reaparecer ahí aunque su
    job falle y save_crawl no la corrija."""
    lider = "/tiendas/900025946-lider"
    repository.upsert_store(
        db, {"store_id": 900025946, "name": "Lider", "store_type": "turbo_x", "sub_group": "Turbo", "path": lider}
    )
    repository.upsert_store_vertical(db, 900025946, "turbo", "Turbo")
    only_in_filters = {
        "store_id": 900025946, "name": "", "store_type": "", "subvertical": "", "landing_classification": "",
        "path": "/tiendas/900025946", "filters": ["Té & Café"],
    }  # fmt: skip
    monkeypatch.setattr(discover, "parse_vertical_listing", lambda data: [only_in_filters])
    run = repository.start_run(db, "stores", {})
    city = {"city": "Santiago de Chile", "lat": -33.4, "lng": -70.6}

    discover.discover_stores(db, FakeClient(), run, ["supermercado"], [city])
    process_store_jobs(db, FakeClient(unavailable={"/tiendas/900025946"}), run, max_aisles=1)

    assert _statuses(db) == {"id:900025946": "failed"}
    rows = db.execute("SELECT vertical, filters FROM store_verticals WHERE store_id = 900025946").fetchall()
    assert rows == [("turbo", ["Té & Café"])]


def test_migration_moves_turbo_stores_left_in_the_listing_vertical(db):
    """900102097 y 900102111 (turbo_*, sub_group Turbo) quedaron en supermercado. Ya no se corrigen al bajarlas: el
    descubrimiento las pone en turbo y el job deja de nombrar supermercado."""
    repository.upsert_store(
        db, {"store_id": 900102097, "name": "Café y Té", "store_type": "turbo_cafeyte_nc", "sub_group": "Turbo"}
    )
    repository.upsert_store_vertical(db, 900102097, "supermercado", "Turbo", "", ["Té & Café"])
    repository.upsert_store(db, {"store_id": 1, "name": "Lider", "store_type": "lider"})
    repository.upsert_store_vertical(db, 1, "supermercado")
    db.execute("DELETE FROM schema_migrations WHERE name = '018_turbo_stores_from_filters.sql'")
    db.commit()

    migrate(db)

    rows = db.execute("SELECT store_id, vertical, filters FROM store_verticals ORDER BY 1").fetchall()
    assert rows == [(1, "supermercado", []), (900102097, "turbo", ["Té & Café"])]


def test_store_job_fails_when_no_branch_available(db):
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [_store_job("type:x", "/tiendas/1-a", "/tiendas/2-b")])

    process_store_jobs(db, FakeClient(unavailable={"/tiendas/1-a", "/tiendas/2-b"}), run)

    assert _statuses(db) == {"type:x": "failed"}


@pytest.mark.parametrize(
    ("bad_path", "next_path", "skipped_aisle"),
    [
        (LACTEOS, f"{LIDER}/snacks-y-dulces", 14406),
        (f"{LACTEOS}/yogurt", f"{LACTEOS}/leche", 14521),
    ],
    ids=["pasillo", "sub-pasillo"],
)
def test_page_without_storefront_skips_only_that_aisle(db, bad_path, next_path, skipped_aisle):
    # Rappi a veces entrega un pasillo o sub-pasillo sin fallback['storefront/...'] (27-09-2026): se omite esa
    # página y la tienda sigue, en vez de perder todo lo recorrido.
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [_store_job("type:lider", LIDER)])
    client = FakeClient({bad_path: "listing_market"})  # página real sin storefront

    process_store_jobs(db, client, run)

    # sigue con la página hermana siguiente, no corta el recorrido
    assert client.requested.index(next_path) > client.requested.index(bad_path)
    status, result = db.execute("SELECT status, result FROM scrape_jobs WHERE job_key = 'type:lider'").fetchone()
    assert (status, result["paginas_omitidas"], result["pasillos_omitidos"]) == ("done", 1, [skipped_aisle])
    assert result["paginas_intentadas"] == len(client.requested) - 1  # todas menos la portada
    assert db.execute("SELECT count(*) FROM store_products").fetchone()[0] > 0


def test_one_broken_aisle_page_is_skipped_not_fatal(db):
    """Un pasillo con el JSON cortado (json.loads → ValueError) tumbaba toda la tienda tras recorrerla."""

    class BrokenAisle(FakeClient):
        def get_next_data(self, path):
            if path == LACTEOS:
                self.requested.append(path)
                return extract_next_data('<script id="__NEXT_DATA__" type="application/json">{"props":</script>')
            return super().get_next_data(path)

    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [_store_job("type:lider", LIDER)])

    process_store_jobs(db, BrokenAisle(), run)

    status, result = db.execute("SELECT status, result FROM scrape_jobs WHERE job_key = 'type:lider'").fetchone()
    assert (status, result["paginas_omitidas"]) == ("done", 1)


def _seed_previous_run(db) -> tuple[int, list[str]]:
    """Corrida 1 de Lider con dos productos que no están en las páginas guardadas: uno del pasillo Lácteos (14406) y
    otro de Snacks (14411). Devuelve la corrida y sus master_product_id."""
    run = repository.start_run(db, "stores", {})
    repository.upsert_store(db, {"store_id": 900025946, "name": "Lider", "store_type": "lider", "path": LIDER})
    repository.upsert_store_vertical(db, 900025946, "supermercado")
    products = [
        {"product_id": f"x{aisle}", "master_product_id": aisle * 100, "name": f"Producto {aisle}", "price": 990,
         "in_stock": True, "_aisle_id": aisle}
        for aisle in (14406, 14411)
    ]  # fmt: skip
    repository.save_products(db, run, 900025946, products)
    _finish_store_job(db, run)
    repository.finish_run(db, run)
    return run, ["1440600", "1441100"]


def _finish_store_job(db, run: int) -> None:
    """El job terminado que deja el scraper al bajar Lider: la bajada anterior del formato para un pasillo omitido."""
    repository.add_jobs(db, run, [_store_job("type:lider", LIDER)])
    repository.mark_job(db, run, "type:lider", "done", {"store_id": 900025946, "store_type": "lider"}, None)


def test_skipped_aisle_keeps_its_offers_current(db):
    """La corrida 2 no pudo leer Lácteos: sus productos siguen en la búsqueda (con su último precio) hasta la próxima
    corrida, en vez de desaparecer una semana. Lo que no salió en un pasillo que sí se leyó deja de estar vigente."""
    _, (in_skipped, in_read) = _seed_previous_run(db)
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [_store_job("type:lider", LIDER)])

    process_store_jobs(db, FakeClient(failing={LACTEOS}), run)
    build_search_documents(db)

    status, result = db.execute("SELECT status, result FROM scrape_jobs WHERE run_id = %s", (run,)).fetchone()
    assert (status, result["pasillos_omitidos"]) == ("done", [14406])
    ids = {r[0] for r in db.execute("SELECT entity_id FROM search_documents WHERE entity_type = 'catalog_item'")}
    assert in_skipped in ids
    assert in_read not in ids


def _seed_run(db, products: dict[str, int]) -> None:
    """Una corrida terminada de Lider con esos productos {sku: pasillo}, ninguno en las páginas guardadas."""
    run = repository.start_run(db, "stores", {})
    repository.upsert_store(db, {"store_id": 900025946, "name": "Lider", "store_type": "lider", "path": LIDER})
    repository.upsert_store_vertical(db, 900025946, "supermercado")
    rows = [
        {"product_id": sku, "master_product_id": int(sku[1:]), "name": sku, "price": 990, "in_stock": True,
         "_aisle_id": aisle}
        for sku, aisle in products.items()
    ]  # fmt: skip
    repository.save_products(db, run, 900025946, rows)
    _finish_store_job(db, run)
    repository.finish_run(db, run)


def test_skipped_aisle_only_rescues_offers_from_the_previous_run(db):
    """Un producto que la corrida 2 ya no encontró (con su pasillo leído sin problemas) no vuelve con el precio de hace
    meses porque la corrida 3 se saltó ese pasillo; uno que sí estaba en la corrida 2 se mantiene."""
    _seed_run(db, {"x7001": 14406, "x7003": 14411})  # corrida 1: x7001 en Lácteos
    _seed_run(db, {"x7002": 14406, "x7003": 14411})  # corrida 2: x7001 ya no está; x7002 sí
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [_store_job("type:lider", LIDER)])

    process_store_jobs(db, FakeClient(failing={LACTEOS}), run)  # corrida 3: Lácteos omitido
    build_search_documents(db)

    ids = {r[0] for r in db.execute("SELECT entity_id FROM search_documents WHERE entity_type = 'catalog_item'")}
    assert "7002" in ids
    assert "7001" not in ids


def test_too_many_skipped_pages_fails_job(db):
    """Con más del 5 % de las páginas omitidas el job falla (y pasa por el reintento): no se guarda un catálogo a
    medias, y la corrida anterior sigue siendo la que vale para el formato."""
    previous, (in_skipped, in_read) = _seed_previous_run(db)
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [_store_job("type:lider", LIDER)])

    process_store_jobs(db, FakeClient(failing={LACTEOS}), run, max_aisles=2)  # 1 de 12 páginas: 8 %
    build_search_documents(db)

    status, error, attempts, result = db.execute(
        "SELECT status, error, attempts, result FROM scrape_jobs WHERE run_id = %s", (run,)
    ).fetchone()
    assert (status, error, attempts) == ("failed", "demasiadas páginas omitidas", 2)
    assert (result["paginas_omitidas"], result["paginas_intentadas"]) == (1, 12)
    assert db.execute("SELECT count(*) FROM price_snapshots WHERE run_id = %s", (run,)).fetchone()[0] == 0
    ids = {r[0] for r in db.execute("SELECT entity_id FROM search_documents WHERE entity_type = 'catalog_item'")}
    assert {in_skipped, in_read} <= ids  # la corrida 1 sigue vigente


def test_possible_block_from_the_client_stops_the_store_job(db):
    """El cliente detecta el bloqueo por request: ni el pasillo ni la tienda lo atrapan, y el job sigue pendiente."""

    class Blocking(FakeClient):
        def get_next_data(self, path):
            if path == LACTEOS:
                raise PossibleBlock("posible bloqueo: 20 respuestas seguidas de rechazo")
            return super().get_next_data(path)

    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [_store_job("type:lider", LIDER)])

    with pytest.raises(PossibleBlock):
        process_store_jobs(db, Blocking(), run)

    assert _statuses(db) == {"type:lider": "pending"}


def test_first_handler_runs_outside_transaction(db, monkeypatch):
    """Leer la cola abría una transacción que quedaba «idle in transaction» durante todo el primer job (decenas de
    minutos): retenía vacuum y cualquier migración."""
    seen = []

    def handler(conn, client, run_id, payload, done_types, max_aisles):
        seen.append(conn.info.transaction_status)
        return "done", {}, None

    monkeypatch.setattr(stores, "_run_store_job", handler)
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [_store_job("type:lider", LIDER)])

    process_store_jobs(db, FakeClient(), run)

    assert seen == [TransactionStatus.IDLE]


def test_branch_that_redirects_mid_crawl_falls_back_to_next_branch(db):
    # Un pasillo que redirige al listado (/tiendas/tipo/...) dice que la sucursal dejó de despachar a esa ubicación:
    # no se guarda su catálogo a medias, se prueba la siguiente sucursal.
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [_store_job("type:x", "/tiendas/900025946-lider", "/tiendas/2-otra")])
    client = FakeClient({"/tiendas/2-otra": "store_mall"}, unavailable={"/tiendas/900025946-lider/lacteos-y-huevos"})

    process_store_jobs(db, client, run, max_aisles=1)

    status, result = db.execute("SELECT status, result FROM scrape_jobs WHERE job_key = 'type:x'").fetchone()
    assert (status, result["store_id"]) == ("done", 900099813)
    assert db.execute("SELECT count(*) FROM store_products WHERE store_id = 900025946").fetchone()[0] == 0


def test_branch_that_redirects_mid_crawl_fails_when_no_other_branch(db):
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [_store_job("type:lider", "/tiendas/900025946-lider")])
    client = FakeClient(unavailable={"/tiendas/900025946-lider/lacteos-y-huevos"})

    process_store_jobs(db, client, run, max_aisles=1)

    status, error = db.execute("SELECT status, error FROM scrape_jobs WHERE job_key = 'type:lider'").fetchone()
    assert (status, error) == ("failed", "sucursal no disponible a mitad del recorrido")
    assert db.execute("SELECT count(*) FROM store_products").fetchone()[0] == 0


def test_store_fails_when_no_aisle_can_be_read(db):
    # Con solo la portada la tienda quedaría "done" y casi vacía: mejor 'failed', visible en el reporte. El mensaje
    # no lleva números para que el reporte agrupe todas las tiendas con este error.
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [_store_job("type:lider", "/tiendas/900025946-lider")])
    lider = "/tiendas/900025946-lider"
    client = FakeClient({f"{lider}/lacteos-y-huevos": "listing_market", f"{lider}/snacks-y-dulces": "listing_market"})

    process_store_jobs(db, client, run, max_aisles=2)

    status, error = db.execute("SELECT status, error FROM scrape_jobs WHERE job_key = 'type:lider'").fetchone()
    assert (status, error) == ("failed", "ParseError: ningún pasillo se pudo leer")
    assert db.execute("SELECT count(*) FROM store_products").fetchone()[0] == 0


def test_restaurant_branches_of_same_brand_are_scraped_once(db):
    run = repository.start_run(db, "restaurants", {})
    repository.add_jobs(
        db,
        run,
        [
            {
                "job_key": f"rest:{i}",
                "job_type": "restaurant",
                "payload": {
                    "verticals": ["restaurantes"],
                    "candidates": [{"store_id": i, "path": f"/restaurantes/{i}"}],
                },
            }
            for i in (1, 2)
        ],
    )
    pages = {"/restaurantes/1": "restaurant", "/restaurantes/2": "restaurant"}  # misma marca (3607)

    process_restaurant_jobs(db, FakeClient(pages), run)

    assert _statuses(db) == {"rest:1": "done", "rest:2": "skipped"}
    assert repository.brands_done(db, run) == {3607}
    assert db.execute("SELECT count(*) FROM menu_price_snapshots").fetchone()[0] == 61


def test_restaurant_that_no_longer_exists_is_skipped_not_failed(db):
    """Un restaurante dado de baja no es una falla del scraper (no debe inflar "Jobs fallidos" del reporte)."""
    run = repository.start_run(db, "restaurants", {})
    job = {"verticals": ["restaurantes"], "candidates": [{"store_id": 7, "path": "/restaurantes/7-cerrado"}]}
    repository.add_jobs(db, run, [{"job_key": "rest:7", "job_type": "restaurant", "payload": job}])
    db.commit()

    process_restaurant_jobs(db, FakeClient(gone={"/restaurantes/7-cerrado"}), run)

    status, result = db.execute("SELECT status, result FROM scrape_jobs WHERE job_key = 'rest:7'").fetchone()
    assert (status, result["reason"]) == ("skipped", "ya no existe en Rappi")


def test_discover_restaurants_retries_failed_chains_and_skips_their_branches(db, monkeypatch):
    chain_url = "https://www.rappi.cl/restaurantes/delivery/1833-vapiano"
    sitemaps = {
        discover.CHAIN_SITEMAP: [chain_url],
        discover.PARTNER_SITEMAP: [
            "https://www.rappi.cl/restaurantes/900021447-vapiano",  # sucursal de la cadena
            "https://www.rappi.cl/restaurantes/555-independiente",
        ],
    }
    monkeypatch.setattr(discover, "_sitemap_urls", lambda client, url: sitemaps[url])
    client = FakeClient(
        {"/restaurantes/delivery/1833-vapiano": "brand_chain"}, failing_once={"/restaurantes/delivery/1833-vapiano"}
    )
    run = repository.start_run(db, "restaurants", {})

    n_jobs = discover.discover_restaurants(db, client, run)

    assert n_jobs == 2
    assert set(_statuses(db)) == {"chain:1833", "rest:555"}


@pytest.mark.parametrize("vertical", ["mall", "supermercado"])
def test_pending_jobs_filter_by_vertical(db, vertical):
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(
        db,
        run,
        [
            _store_job("type:a", "/tiendas/1", verticals=("mall",)),
            _store_job("type:b", "/tiendas/2", verticals=("mall", "supermercado")),
        ],
    )

    keys = [j["job_key"] for j in repository.pending_jobs(db, run, "store_group", vertical)]

    assert keys == (["type:a", "type:b"] if vertical == "mall" else ["type:b"])


def test_a_listing_that_failed_is_reported_and_can_be_retried_alone(db, monkeypatch):
    """A las 03:00 las botillerías están cerradas y el listado de licores llega sin tiendas (13 ciudades el 04-10):
    el descubrimiento anota qué listados fallaron para volver a pedirlos, y solo esos, más tarde."""
    store = {
        "store_id": 900030001, "name": "Botillería", "store_type": "boti", "subvertical": "",
        "landing_classification": "", "path": "/tiendas/900030001-boti", "filters": [],
    }  # fmt: skip
    monkeypatch.setattr(discover, "parse_vertical_listing", lambda data: [store])
    run = repository.start_run(db, "stores", {})
    city = {"city": "Viña del Mar", "lat": -33.0, "lng": -71.5}
    licores = discover.VERTICAL_LISTINGS["licores"]
    client = FakeClient(failing_once={licores})

    discover.discover_stores(db, client, run, ["supermercado", "licores"], [city])

    # queda guardado en la corrida: el reintento sobrevive a un corte y el reporte de calidad lo avisa
    failed = discover.failed_listings(db, run)
    assert failed == {("Viña del Mar", "licores")}
    assert db.execute("SELECT vertical FROM store_verticals").fetchall() == [("supermercado",)]
    client.requested.clear()

    discover.discover_stores(db, client, run, ["supermercado", "licores"], [city], only=failed)

    assert client.requested == [licores]  # solo el que falló
    verticals = db.execute("SELECT vertical FROM store_verticals ORDER BY 1").fetchall()
    assert verticals == [("licores",), ("supermercado",)]
    payload = db.execute("SELECT payload FROM scrape_jobs WHERE job_key = 'type:boti'").fetchone()[0]
    assert payload["verticals"] == ["supermercado", "licores"]
    assert discover.failed_listings(db, run) == set()  # ya no falla ninguno


def test_empty_listing_is_retried(db, monkeypatch):
    """A las 03:00 el listado de licores llega con 0 tiendas, sin error: también se anota para reintentarlo."""
    monkeypatch.setattr(discover, "parse_vertical_listing", lambda data: [])
    run = repository.start_run(db, "stores", {})
    city = {"city": "Viña del Mar", "lat": -33.0, "lng": -71.5}

    discover.discover_stores(db, FakeClient(), run, ["licores"], [city])

    assert discover.failed_listings(db, run) == {("Viña del Mar", "licores")}


def test_city_not_overwritten_by_listing(db, monkeypatch):
    """Una tienda nacional sale en el listado de varias ciudades: su ciudad no cambia según el último listado."""
    store = {
        "store_id": 900030001, "name": "Mall", "store_type": "mall_x", "subvertical": "", "landing_classification": "",
        "path": "/tiendas/900030001-mall", "filters": [],
    }  # fmt: skip
    monkeypatch.setattr(discover, "parse_vertical_listing", lambda data: [store])
    run = repository.start_run(db, "stores", {})
    cities = [{"city": c, "lat": -33.0, "lng": -71.0} for c in ("Santiago de Chile", "Temuco")]

    discover.discover_stores(db, FakeClient(), run, ["mall"], cities)

    assert db.execute("SELECT city FROM stores WHERE store_id = 900030001").fetchone() == ("Santiago de Chile",)


def test_new_run_closes_previous(db):
    """`discover --new-run` dejaba la corrida anterior «en curso» para siempre (y rappi-ia no embebía)."""
    first = cli._run_id(db, "stores", Namespace(new_run=False))
    second = cli._run_id(db, "stores", Namespace(new_run=True))

    runs = db.execute("SELECT run_id, status FROM scrape_runs ORDER BY run_id").fetchall()
    assert runs == [(first, "failed"), (second, "running")]
