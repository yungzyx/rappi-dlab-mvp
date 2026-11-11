import logging
import os
import zlib
from datetime import datetime
from zoneinfo import ZoneInfo

# La suite hace miles de requests desde la misma IP ("testclient"): sin tope por IP (se lee al importar la config).
# test_api_env y test_limits prueban el límite con sus propios valores.
os.environ["API_RATE_PER_MIN"] = "0"
os.environ["API_RATE_WRITE_PER_MIN"] = "0"
# Las sesiones de la suite: un secreto fijo de prueba (no se crea data/api-secret) y sin tope de personas nuevas por IP
# (test_ownership lo prueba con el suyo).
os.environ["API_SECRET"] = "secreto-de-los-tests-no-sirve-fuera-de-ellos"
os.environ["API_NEW_USERS_PER_IP_DAY"] = "0"
# Sin precarga de los índices al arrancar la API: abriría su propia conexión a DATABASE_URL (la base real) y alargaría
# la suite. test_api_startup y test_prewarm la prueban por su cuenta.
os.environ["API_PREWARM"] = "0"

import pytest  # noqa: E402

from rappi_ia.catalog import cache  # noqa: E402
from rappi_ia.db import connect, database_url  # noqa: E402
from rappi_ia.demo.seed import reset_test_database  # noqa: E402
from rappi_ia.layers.segments import forget_source_spend  # noqa: E402

# El CI corre la suite en partes paralelas, cada una con su Postgres: `RAPPI_IA_TEST_SHARD=2/3` deja la segunda de
# tres. Reparte archivos enteros (sus fixtures de módulo no se repiten), de más a menos pesado y siempre a la parte más
# liviana: un test de integración pesa 1 (resetea la base) y uno unitario casi nada. Sin la variable, corre todo.
SHARD_ENV = "RAPPI_IA_TEST_SHARD"
UNIT_TEST_WEIGHT = 0.02


def shard_files(weights: dict[str, float], parts: int) -> list[set[str]]:
    """Los archivos de cada parte: el reparto es estable (mismos archivos, mismas partes) y parejo en peso."""
    loads = [0.0] * parts
    shards: list[set[str]] = [set() for _ in range(parts)]
    for path, weight in sorted(weights.items(), key=lambda kv: (-kv[1], kv[0])):
        lightest = min(range(parts), key=lambda i: (loads[i], i))
        loads[lightest] += weight
        shards[lightest].add(path)
    return shards


def pytest_collection_modifyitems(config, items):
    spec = os.environ.get(SHARD_ENV)
    if not spec:
        return
    part, parts = (int(n) for n in spec.split("/"))
    if not 1 <= part <= parts:
        raise pytest.UsageError(f"{SHARD_ENV}={spec}: la parte va de 1 a {parts}")
    weights: dict[str, float] = {}
    for item in items:
        path = item.nodeid.split("::")[0]
        weights[path] = weights.get(path, 0.0) + (1.0 if "/integration/" in f"/{path}" else UNIT_TEST_WEIGHT)
    keep = shard_files(weights, parts)[part - 1]
    selected = [item for item in items if item.nodeid.split("::")[0] in keep]
    config.hook.pytest_deselected(items=[item for item in items if item.nodeid.split("::")[0] not in keep])
    items[:] = selected


@pytest.fixture(autouse=True)
def real_db_guard(monkeypatch):
    """Ningún test abre la base real por el connector de la API (el recálculo de segmentos después de un pedido):
    sin un `get_connector` propio, la tarea falla con este error (queda en el log) y la lista anota cada intento.
    Tampoco abre el pool de la API, que se conecta a DATABASE_URL: el `lifespan` de un `with TestClient(app)` lo
    intenta y aquí no hace nada (test_pool instala uno propio sobre rappi_ia_test). Sin pool, `get_conn` se niega. Ni
    revisa la ciudad de la demo (`prewarm.check_demo_city`, con su propia conexión): queda anotado en la lista.
    Va en el módulo, no en `dependency_overrides`, que los fixtures vacían con `clear()`."""
    from rappi_ia.api import deps, prewarm

    attempts: list[str] = []

    def refuse():
        attempts.append("connector")
        raise RuntimeError("Los tests no abren la base real: reemplaza get_connector con la conexión del test")

    monkeypatch.setattr(deps, "_own_connection", refuse)
    monkeypatch.setattr(deps, "open_pool", lambda: attempts.append("pool"))
    monkeypatch.setattr(prewarm, "check_demo_city", lambda: attempts.append("ciudad"))
    return attempts


@pytest.fixture(autouse=True)
def keep_logging_config():
    """El `lifespan` de la API configura el logging de todo el proceso (handler y nivel de la raíz): ningún test se lo
    deja al siguiente."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    factory = logging.getLogRecordFactory()
    quiet = {name: logging.getLogger(name).level for name in ("httpx", "httpx2", "httpcore")}
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
    logging.setLogRecordFactory(factory)
    for name, previous in quiet.items():
        logging.getLogger(name).setLevel(previous)


# La hora local con que se compara el horario publicado de los restaurantes (catalog/hours.py): un jueves a las 13:00 en
# Santiago, cuando todos los del catálogo de prueba que publican horario están abiertos. Sin ella, el orden de una lista
# (los cerrados al final) dependería de la hora en que corre la suite. Los tests del horario pasan su propia hora.
FIXED_LOCAL_TIME = datetime(2026, 10, 22, 13, 0, tzinfo=ZoneInfo("America/Santiago"))


@pytest.fixture(autouse=True)
def fixed_local_time(monkeypatch):
    from rappi_ia.catalog import hours

    monkeypatch.setattr(hours, "now_local", lambda: FIXED_LOCAL_TIME)
    return FIXED_LOCAL_TIME


@pytest.fixture(autouse=True)
def fresh_caches():
    """Cada test recrea la base (y su corrida 1): nada de la caché del catálogo ni del gasto por fuente de los segmentos
    pasa de un test a otro."""
    cache.clear()
    forget_source_spend()
    yield
    cache.clear()
    forget_source_spend()


@pytest.fixture
def test_url():
    """URL de `rappi_ia_test`, la única base que los tests pueden borrar."""
    try:
        url = database_url("DATABASE_URL_TEST")
    except RuntimeError:
        pytest.skip("DATABASE_URL_TEST no configurada")
    if not url.rstrip("/").endswith("rappi_ia_test"):
        pytest.fail(f"Por seguridad los tests solo borran la base rappi_ia_test, no {url}")
    return url


@pytest.fixture
def db(test_url):
    """Conexión a `rappi_ia_test` con el esquema recreado desde cero para cada test.

    Base propia (no `rappi_test`) para que los tests de rappi-ia y del scraper no se pisen.
    """
    with connect(test_url) as conn:
        reset_test_database(conn)
        yield conn
        conn.rollback()


def add_store(conn, store_id: int, vertical: str, name: str = "Tienda") -> None:
    conn.execute(
        "INSERT INTO stores (store_id, name, store_type, path) VALUES (%s, %s, %s, %s)",
        (store_id, name, f"tipo_{store_id}", f"/tiendas/{store_id}"),
    )
    conn.execute("INSERT INTO store_verticals (store_id, vertical) VALUES (%s, %s)", (store_id, vertical))


def add_product(conn, product_id: int, name: str, store_id: int, category: str | None = None) -> None:
    category_id = None
    if category:
        category_id = conn.execute(
            """INSERT INTO categories (category_id, name)
               VALUES ((SELECT coalesce(max(category_id), 0) + 1 FROM categories), %s)
               RETURNING category_id""",
            (category,),
        ).fetchone()[0]
    conn.execute(
        "INSERT INTO catalog_items (master_product_id, name, category_id) VALUES (%s, %s, %s)",
        (product_id, name, category_id),
    )
    conn.execute(
        "INSERT INTO store_products (store_id, sku, master_product_id) VALUES (%s, %s, %s)",
        (store_id, f"sku-{product_id}", product_id),
    )


def add_dish(conn, item_id: int, name: str, store_id: int, section: str, cuisines=()) -> None:
    section_id = zlib.crc32(section.encode()) % 100_000
    conn.execute(
        """INSERT INTO menu_sections (store_id, section_id, name, position)
           VALUES (%s, %s, %s, 0) ON CONFLICT DO NOTHING""",
        (store_id, section_id, section),
    )
    conn.execute(
        "INSERT INTO menu_items (item_id, rappi_item_id, store_id, section_id, name) VALUES (%s, %s, %s, %s, %s)",
        (item_id, item_id, store_id, section_id, name),
    )
    for cuisine in cuisines:
        conn.execute("INSERT INTO cuisines (name) VALUES (%s) ON CONFLICT DO NOTHING", (cuisine,))
        conn.execute(
            "INSERT INTO restaurant_cuisines (store_id, cuisine) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (store_id, cuisine),
        )


def add_price(conn, store_id: int, product_id: int, price: float) -> None:
    # Todos en una misma corrida, como una descarga real: con una corrida por precio, la búsqueda tomaría los
    # productos con precio anterior como algo que la tienda ya no vende.
    run_id = conn.execute("SELECT min(run_id) FROM scrape_runs WHERE kind = 'stores' AND status = 'done'").fetchone()[0]
    if run_id is None:
        run_id = conn.execute(
            "INSERT INTO scrape_runs (kind, status) VALUES ('stores', 'done') RETURNING run_id"
        ).fetchone()[0]
    conn.execute(
        "INSERT INTO price_snapshots (run_id, store_id, sku, price, in_stock) VALUES (%s, %s, %s, %s, true)",
        (run_id, store_id, f"sku-{product_id}", price),
    )
