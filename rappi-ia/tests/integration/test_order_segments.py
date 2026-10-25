"""Después de cada pedido (`POST /orders`), los segmentos de esa persona se recalculan en segundo plano, con su propia
conexión: dos pedidos seguidos no chocan, un usuario olvidado no revive y un error no rompe el pedido."""

import logging
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from conftest import add_price, add_product, add_store
from owner_client import OwnerClient
from rappi_ia.api import app as api
from rappi_ia.concepts.store import seed_taxonomy
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.db import connect
from rappi_ia.events import store as events
from rappi_ia.layers import segments
from rappi_ia.layers.segments import load_segment_rules, recalculate_user_segments


def _shared(db):
    """El connector de los tests: la conexión del test, sin cerrarla al terminar."""

    @contextmanager
    def connector():
        yield db

    return connector


def _catalog(db):
    """La taxonomía y el producto de `_line`: /orders toma el precio del catálogo."""
    seed_taxonomy(db, load_taxonomy())
    add_store(db, 1, "supermercado", "Súper")
    add_product(db, 91001, "Papas fritas clásicas 180 g", 1, "Snacks salados")
    add_price(db, 1, 91001, 1990)
    db.commit()


@pytest.fixture
def client(db):
    _catalog(db)

    def conn_override():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    api.app.dependency_overrides[api.get_connector] = lambda: _shared(db)
    yield OwnerClient(api.app)
    api.app.dependency_overrides.clear()


def _line(product="91001", concept="snacks-salados"):
    return {"entity_type": "catalog_item", "entity_id": product, "concept_id": concept, "unit_price": 1990}


def _order_direct(db, user, n):
    """Pedidos guardados sin pasar por la API (sin recálculo), cada uno en su sesión: un segmento cuenta ocasiones."""
    for i in range(n):
        events.record_order(db, user, f"s-{i}", f"c-{user}-direct-{i}", "supermercado", [_line()])
    db.commit()


def post_order(client, user, cart):
    body = {"user_id": user, "session_id": f"s-{cart}", "cart_id": cart, "vertical": "supermercado", "lines": [_line()]}
    reply = client.post("/orders", json=body)
    assert reply.status_code == 200, reply.text
    return reply.json()["order_id"]


def _segments(db, user):
    return dict(db.execute("SELECT segment_id, signals FROM user_segments WHERE user_id = %s", (user,)).fetchall())


def _segment_runs(db):
    return db.execute("SELECT count(*) FROM layer_runs WHERE layer = 'segments'").fetchone()[0]


def test_order_recalculates_that_users_segments(client, db):
    _order_direct(db, "u1", 2)
    _order_direct(db, "u2", 2)
    assert _segments(db, "u1") == {}

    post_order(client, "u1", "c-api-1")

    assert _segments(db, "u1")["snacks-salados"] == 3  # los dos de antes y el de la API
    assert _segments(db, "u2") == {}  # solo se recalcula quien pidió


def test_two_orders_in_a_row_do_not_collide(client, db, test_url, caplog):
    _order_direct(db, "u1", 2)
    post_order(client, "u1", "c-api-1")
    post_order(client, "u1", "c-api-2")
    assert _segments(db, "u1")["snacks-salados"] == 4  # la segunda corrida ve los dos pedidos

    # Dos recálculos a la vez, cada uno con su conexión (como dos tareas en segundo plano del servidor).
    events.record_order(db, "u1", "s-5", "c-direct-5", "supermercado", [_line()])
    db.commit()

    @contextmanager
    def own_connection():
        with connect(test_url) as conn:
            yield conn

    start = threading.Barrier(2)

    def run():
        start.wait()
        recalculate_user_segments(own_connection, "u1")

    with caplog.at_level(logging.INFO, logger=segments.__name__):
        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len([r for r in caplog.records if "Segmentos recalculados" in r.getMessage()]) == 2
    assert not [r for r in caplog.records if "u1" in r.getMessage()]  # sin el id de la persona en el registro
    db.rollback()  # una foto nueva: lo que guardaron las otras conexiones
    assert _segments(db, "u1")["snacks-salados"] == 5


def test_a_recalculation_waits_for_the_one_in_flight(db, test_url):
    """El candado por persona: un recálculo que llega mientras otro sigue abierto espera y ve lo último."""
    seed_taxonomy(db, load_taxonomy())
    _order_direct(db, "u1", 2)

    @contextmanager
    def own_connection():
        with connect(test_url) as conn:
            yield conn

    with connect(test_url) as in_flight:
        in_flight.execute("SELECT pg_advisory_xact_lock(hashtext('segments:' || %s))", ("u1",))
        waiting = threading.Thread(target=recalculate_user_segments, args=(own_connection, "u1"))
        waiting.start()
        waiting.join(timeout=0.5)
        assert waiting.is_alive()  # espera el candado
        events.record_order(in_flight, "u1", "s-in-flight", "c-in-flight", "supermercado", [_line()])
        in_flight.commit()  # suelta el candado con el tercer pedido guardado
        waiting.join()

    db.rollback()
    assert _segments(db, "u1")["snacks-salados"] == 3


def test_recalculation_after_forget_restores_nothing(client, db):
    _order_direct(db, "u1", 3)
    post_order(client, "u1", "c-api-1")
    assert _segments(db, "u1")
    events.forget(db, "u1")
    db.commit()
    runs = _segment_runs(db)

    recalculate_user_segments(_shared(db), "u1")

    assert _segments(db, "u1") == {}
    assert db.execute("SELECT count(*) FROM app_users WHERE user_id = 'u1'").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM user_segment_history WHERE user_id = 'u1'").fetchone()[0] == 0
    assert _segment_runs(db) == runs  # ni siquiera empezó una corrida


def test_recalculation_error_does_not_break_the_order(client, db, caplog):
    @contextmanager
    def broken():
        raise RuntimeError("sin base")
        yield

    api.app.dependency_overrides[api.get_connector] = lambda: broken

    with caplog.at_level(logging.WARNING, logger=segments.__name__):
        order_id = post_order(client, "u1", "c-api-1")

    assert db.execute("SELECT count(*) FROM app_orders WHERE order_id = %s", (order_id,)).fetchone()[0] == 1
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert [r.name for r in warnings] == [segments.__name__, "rappi_ia.motor.build"]  # segmentos y motor
    assert all("u1" not in r.getMessage() for r in warnings)  # sin el id de la persona


def test_segment_rules_are_cached(tmp_path):
    assert load_segment_rules() is load_segment_rules()

    path = tmp_path / "segments.toml"
    path.write_text(segments.RULES_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    first = load_segment_rules(path)
    assert load_segment_rules(path) is first

    path.write_text(path.read_text(encoding="utf-8").replace('version = "', 'version = "x', 1), encoding="utf-8")
    assert load_segment_rules(path)[0] == "x" + first[0]  # el archivo cambió: se vuelve a leer


def test_one_users_metrics_match_the_whole_source(db):
    """Filtrar por persona en SQL da lo mismo que calcular toda la fuente y quedarse con ella (también el percentil
    de gasto, que se mide contra todos, y dos pedidos a la misma hora)."""
    seed_taxonomy(db, load_taxonomy())
    now = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
    same = now - timedelta(days=5)
    for user, days, total in (("u1", (100, 5, 5), 1000), ("u2", (80, 20), 5000), ("u3", (2,), 300)):
        for i, ago in enumerate(days):
            ts = same if ago == 5 else now - timedelta(days=ago)
            line = {**_line(), "unit_price": total}
            events.record_order(db, user, f"s-{user}-{i}", f"c-{user}-{i}", "supermercado", [line], ts=ts)
    db.commit()

    whole = segments.user_metrics(db, "prototype", now=now)

    assert set(whole) == {"u1", "u2", "u3"} and "gasto_90d_percentil" in whole["u2"]
    for user in whole:
        assert segments.user_metrics(db, "prototype", user, now=now) == {user: whole[user]}


class SpyConnection:
    """Anota el SQL de cada consulta."""

    def __init__(self, conn):
        self._conn = conn
        self.statements: list[str] = []

    def execute(self, query, *args, **kwargs):
        self.statements.append(str(query))
        return self._conn.execute(query, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _orders_for_metrics(db, now):
    seed_taxonomy(db, load_taxonomy())
    for n in range(12):  # 12 personas con gastos distintos: el percentil tiene dónde caer
        user = f"u{n}"
        for i in range(n % 3 + 1):
            line = {**_line(), "unit_price": 500 * (n + 1)}
            ts = now - timedelta(days=5 + 20 * i)
            events.record_order(db, user, f"s-{user}-{i}", f"c-{user}-{i}", "supermercado", [line], ts=ts)
    db.commit()


def test_user_metrics_filters_inside_subqueries(db):
    """Con una persona, cada métrica filtra por ella dentro de su consulta (antes se calculaba para toda la fuente y se
    filtraba por fuera): da lo mismo que calcular toda la fuente y quedarse con ella."""
    now = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
    _orders_for_metrics(db, now)
    whole = segments.user_metrics(db, "prototype", now=now)
    spy = SpyConnection(db)

    for user in whole:
        assert segments.user_metrics(spy, "prototype", user, now=now) == {user: whole[user]}

    assert spy.statements and not [s for s in spy.statements if "m.user_id" in s]
    unfiltered = [s for s in spy.statements if "%(user)s" not in s]
    assert len(unfiltered) == 1  # solo el gasto de toda la fuente, para el percentil (una vez: queda del día)


def test_spend_percentile_reads_the_whole_source_once_a_day(db):
    now = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
    _orders_for_metrics(db, now)
    spy = SpyConnection(db)

    def whole_source_reads():
        return len([s for s in spy.statements if "%(user)s" not in s])

    before = segments.user_metrics(spy, "prototype", "u1", now=now)["u1"]["gasto_90d_percentil"]
    line = {**_line(), "unit_price": 99_000}
    events.record_order(db, "u1", "s-big", "c-big", "supermercado", [line], ts=now - timedelta(days=1))
    after = segments.user_metrics(spy, "prototype", "u1", now=now)["u1"]["gasto_90d_percentil"]

    assert (before, after) == (pytest.approx(1 / 11), 1.0)  # su gasto se lee siempre: ahora es quien más gasta
    assert whole_source_reads() == 1
    segments.user_metrics(spy, "prototype", "u2", now=now + timedelta(days=1))
    assert whole_source_reads() == 2  # otro día: se vuelve a leer


def test_three_orders_add_no_layer_runs(client, db):
    """El recálculo de una persona después de un pedido no deja una corrida en `layer_runs` (sumaba una por pedido);
    la corrida de toda la fuente sí."""
    _order_direct(db, "u1", 2)
    runs = _segment_runs(db)

    for cart in ("c-api-1", "c-api-2", "c-api-3"):
        post_order(client, "u1", cart)

    assert _segment_runs(db) == runs
    assert _segments(db, "u1")["snacks-salados"] == 5
    segments.build_segments(db, "prototype")
    assert _segment_runs(db) == runs + 1


def test_a_client_without_its_own_connector_never_opens_the_real_db(db, real_db_guard, caplog):
    """Un cliente de test que solo reemplaza `get_conn`: el recálculo choca con la guarda de `conftest.py` (nunca
    con la base real), queda un aviso y el pedido sale igual."""
    _catalog(db)

    def conn_override():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    try:
        with caplog.at_level(logging.WARNING, logger=segments.__name__):
            order_id = post_order(OwnerClient(api.app), "u1", "c-api-1")
    finally:
        api.app.dependency_overrides.clear()

    assert real_db_guard == ["connector", "connector"]  # el recálculo de segmentos y el del motor
    assert db.execute("SELECT count(*) FROM app_orders WHERE order_id = %s", (order_id,)).fetchone()[0] == 1
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2 and all("base real" in str(r.exc_info[1]) for r in warnings)


def test_a_concept_forget_waits_for_the_recalculation_in_flight(db, test_url):
    """«Olvidar» toma el mismo candado por persona: no recalcula a la vez que un recálculo de un pedido."""
    seed_taxonomy(db, load_taxonomy())
    _order_direct(db, "u1", 3)

    def forget():
        with connect(test_url) as conn:
            events.forget(conn, "u1", "snacks-salados")

    with connect(test_url) as in_flight:
        in_flight.execute("SELECT pg_advisory_xact_lock(hashtext('segments:' || %s))", ("u1",))
        waiting = threading.Thread(target=forget)
        waiting.start()
        waiting.join(timeout=0.5)
        assert waiting.is_alive()  # espera el candado
        in_flight.commit()
        waiting.join()

    db.rollback()
    assert "snacks-salados" not in _segments(db, "u1")


def test_a_whole_user_forget_also_waits_for_the_recalculation_in_flight(db, test_url):
    seed_taxonomy(db, load_taxonomy())
    _order_direct(db, "u1", 3)

    def forget():
        with connect(test_url) as conn:
            events.forget(conn, "u1")

    with connect(test_url) as in_flight:
        in_flight.execute("SELECT pg_advisory_xact_lock(hashtext('segments:' || %s))", ("u1",))
        waiting = threading.Thread(target=forget)
        waiting.start()
        waiting.join(timeout=0.5)
        assert waiting.is_alive()
        in_flight.commit()
        waiting.join()

    db.rollback()
    assert db.execute("SELECT count(*) FROM app_users WHERE user_id = 'u1'").fetchone()[0] == 0


def test_a_single_user_recalculation_does_not_reseed_current_definitions(db):
    seed_taxonomy(db, load_taxonomy())
    _order_direct(db, "u1", 3)
    rules = load_segment_rules()[1]

    segments.build_segments(db, "prototype", "u1")  # base nueva: siembra aunque sea de una persona
    assert db.execute("SELECT count(*) FROM segment_defs").fetchone()[0] == len(rules)
    db.execute("UPDATE segment_defs SET name = 'marca de prueba' WHERE segment_id = 'snacks-salados'")

    segments.build_segments(db, "prototype", "u1")  # reglas al día: no las vuelve a escribir
    name = "SELECT name FROM segment_defs WHERE segment_id = 'snacks-salados'"
    assert db.execute(name).fetchone()[0] == "marca de prueba"
    assert "snacks-salados" in _segments(db, "u1")

    db.execute("UPDATE segment_defs SET rules_version = 'vieja' WHERE segment_id = 'gaseosas'")
    segments.build_segments(db, "prototype", "u1")  # una definición de otras reglas: siembra de nuevo
    assert db.execute(name).fetchone()[0] != "marca de prueba"

    db.execute("UPDATE segment_defs SET name = 'marca de prueba' WHERE segment_id = 'snacks-salados'")
    segments.build_segments(db, "prototype")  # la corrida de toda la fuente siempre siembra
    assert db.execute(name).fetchone()[0] != "marca de prueba"
