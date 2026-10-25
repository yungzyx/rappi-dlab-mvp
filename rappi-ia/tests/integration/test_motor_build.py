"""`rappi-ia motor` (motor/build.py): arma las tablas del motor por fuente y recalcula a cada persona después de su
pedido y de «Olvidar».

Sobre el catálogo inventado de la demo y personas simuladas: prueba la mecánica, no un efecto.
"""

import threading
import time
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta

import pytest

from conftest import add_price, add_product, add_store
from owner_client import OwnerClient
from rappi_ia.api import app as api
from rappi_ia.concepts.store import seed_taxonomy
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.db import connect
from rappi_ia.demo.seed import seed_demo
from rappi_ia.events import store as events
from rappi_ia.events.synth import generate
from rappi_ia.layers.runs import finish_layer_run, start_layer_run
from rappi_ia.motor.build import build_motor, refresh_user, refresh_user_conn
from rappi_ia.motor.evaluate import GRID_B, GRID_C, GRID_LAMBDA, METHODS, report
from rappi_ia.motor.model import DEFAULT_WEIGHTS
from rappi_ia.motor.predict import latest_weights
from rappi_ia.motor.recommend import latest_lambda

POPULATION_TABLES = ("vertical_transitions", "combo_stats", "combo_steps", "cross_sell_rules", "trends")
COUNT_OF_TABLE = {
    "vertical_transitions": "transiciones",
    "combo_stats": "combinaciones",
    "combo_steps": "pasos",
    "cross_sell_rules": "reglas",
    "trends": "tendencias",
}
FINE_COUNT_OF_TABLE = {"combo_stats": "combinaciones_finas", "combo_steps": "pasos_finos"}  # la misma tabla, otro nivel


@pytest.fixture
def simulated(db):
    seed_demo(db)
    generate(db, users=300, weeks=26, seed=5, until=date(2026, 10, 4))
    db.commit()
    return db


def _rows(db, table, source="synthetic"):
    return db.execute(f"SELECT count(*) FROM {table} WHERE data_source = %s", (source,)).fetchone()[0]


def _personal(db, table, source="synthetic"):
    return db.execute(
        f"SELECT count(*) FROM {table} t JOIN app_users u USING (user_id) WHERE u.source = %s", (source,)
    ).fetchone()[0]


def _line(product="91001", concept="snacks-salados"):
    return {"entity_type": "catalog_item", "entity_id": product, "concept_id": concept, "unit_price": 1990}


def test_build_motor_fills_every_table_and_records_the_run(simulated):
    db = simulated
    counts = build_motor(db, "synthetic")

    for table in POPULATION_TABLES:
        if table == "cross_sell_rules":  # con 300 personas inventadas puede no haber reglas sobre el umbral
            assert _rows(db, table) == counts["reglas"]
            continue
        assert _rows(db, table) > 0, table
        assert _rows(db, table) == counts[COUNT_OF_TABLE[table]] + counts.get(FINE_COUNT_OF_TABLE.get(table), 0), table
    assert counts["afinidad"] == _personal(db, "user_vertical_affinity") > 0
    assert counts["recompra"] == _personal(db, "replenishment") > 0
    assert set(counts["pesos"]) == set(DEFAULT_WEIGHTS)

    status, stored, version = db.execute(
        "SELECT status, counts, rules_version FROM layer_runs WHERE layer = 'motor' ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    assert status == "done"
    assert stored["fuente"] == "synthetic"
    assert stored["transiciones"] == counts["transiciones"]
    assert version.startswith("2026-10-16+")

    # La ventana de tendencias termina el último día con pedidos (hora de Santiago), no hoy.
    [window_end] = db.execute("SELECT DISTINCT window_end FROM trends WHERE data_source = 'synthetic'").fetchone()
    assert window_end <= date(2026, 10, 4)
    # Las filas de cada persona: puntajes positivos, con pedidos y señales contadas.
    bad = db.execute(
        "SELECT count(*) FROM user_vertical_affinity WHERE score <= 0 OR signals < orders OR last_ts IS NULL"
    ).fetchone()[0]
    assert bad == 0
    # Las transiciones de un vertical suman 1.
    sums = db.execute(
        """SELECT from_vertical, sum(prob) FROM vertical_transitions WHERE data_source = 'synthetic'
           GROUP BY from_vertical"""
    ).fetchall()
    assert all(abs(total - 1) < 1e-4 for _v, total in sums)


def test_build_motor_writes_both_combo_levels(simulated):
    db = simulated
    counts = build_motor(db, "synthetic")

    for table, key in (("combo_stats", "combinaciones"), ("combo_steps", "pasos")):
        for nivel, name in (("grueso", key), ("fino", f"{key}_finas" if key == "combinaciones" else "pasos_finos")):
            n = db.execute(
                f"SELECT count(*) FROM {table} WHERE data_source = 'synthetic' AND nivel = %s", (nivel,)
            ).fetchone()[0]
            assert n == counts[name] > 0, (table, nivel)
    coarse = {c for (c,) in db.execute("SELECT combo FROM combo_stats WHERE nivel = 'grueso'")}
    fine = {c for (c,) in db.execute("SELECT combo FROM combo_stats WHERE nivel = 'fino'")}
    assert coarse <= {"rest", "turbo", "retail", "rest+turbo", "rest+retail", "turbo+retail", "rest+turbo+retail"}
    assert fine and all(not set(c.split("+")) & {"rest", "retail"} for c in fine)  # verticales, no grupos
    assert not {"favor", "travel"} & {m for c in fine for m in c.split("+")}  # los servicios no tienen pedidos
    assert coarse.isdisjoint(fine - {"turbo"}) and "ninguna" not in fine


def test_build_motor_twice_replaces_rows(simulated):
    db = simulated
    first = build_motor(db, "synthetic")
    second = build_motor(db, "synthetic")

    assert first == second
    for table in POPULATION_TABLES:
        assert _rows(db, table) == second[COUNT_OF_TABLE[table]] + second.get(FINE_COUNT_OF_TABLE.get(table), 0), table
    assert _personal(db, "user_vertical_affinity") == second["afinidad"]
    assert _personal(db, "replenishment") == second["recompra"]
    last_run = db.execute("SELECT max(run_id) FROM layer_runs WHERE layer = 'motor'").fetchone()[0]
    stale = db.execute(
        "SELECT count(*) FROM vertical_transitions WHERE data_source = 'synthetic' AND run_id <> %s", (last_run,)
    ).fetchone()[0]
    assert stale == 0


def test_build_synthetic_keeps_prototype_rows(simulated):
    db = simulated
    # El prototipo cuenta hasta hoy (tendencias de 28 días, afinidad de 180): los pedidos, en las últimas 4 semanas.
    start = datetime.now(UTC) - timedelta(days=22)
    for day in range(4):  # una persona del prototipo con un pedido por semana
        events.record_order(
            db, "p-1", f"s-{day}", f"c-{day}", "supermercado", [_line("1", None)], ts=start + timedelta(days=7 * day)
        )
    db.commit()
    prototype = build_motor(db, "prototype")
    assert prototype["tendencias"] > 0 and prototype["afinidad"] == 1

    build_motor(db, "synthetic")

    assert _rows(db, "trends", "prototype") == prototype["tendencias"]
    assert _rows(db, "vertical_transitions", "prototype") == prototype["transiciones"]
    assert _personal(db, "user_vertical_affinity", "prototype") == 1


def test_build_motor_chooses_weights_and_stores_the_evaluation(simulated):
    db = simulated
    counts = build_motor(db, "synthetic")

    evaluation = counts["evaluacion"]
    assert counts["pesos"] == evaluation["pesos"]
    assert counts["pesos"]["afinidad"] == 1
    assert counts["pesos"]["transicion"] in GRID_B and counts["pesos"]["popularidad"] in GRID_C
    assert set(evaluation["proximo_vertical"]) == set(METHODS)
    assert evaluation["proximo_vertical"]["combinado"]["personas"] > 0
    assert {"precision3", "cobertura", "lo_mas_pedido"} <= set(evaluation["compra_cruzada"])
    assert {"n", "error_mediano_dias", "acierto_7_dias"} <= set(evaluation["recompra"])
    stored = db.execute("SELECT counts FROM layer_runs WHERE layer = 'motor' ORDER BY run_id DESC LIMIT 1").fetchone()[
        0
    ]
    assert stored["evaluacion"] == evaluation
    assert latest_weights(db, "synthetic") == counts["pesos"]
    assert counts["lambda_cruzada"] == evaluation["lambda_cruzada"] in GRID_LAMBDA
    assert latest_lambda(db, "synthetic") == counts["lambda_cruzada"]
    assert {"precision3", "precision3_mismas_personas"} <= set(evaluation["compra_cruzada"]["mezcla"])
    assert "Datos simulados" in report(evaluation, "synthetic")


def test_build_motor_without_evaluating_keeps_the_last_weights(simulated):
    db = simulated
    tuned = build_motor(db, "synthetic")["pesos"]
    db.execute(
        "UPDATE layer_runs SET counts = jsonb_set(jsonb_set(counts, '{pesos,transicion}', '7'), '{lambda_cruzada}', "
        "'3') WHERE layer = 'motor'"
    )  # pesos que no salen de la grilla: se ve que vienen de la corrida anterior
    db.commit()

    counts = build_motor(db, "synthetic", evaluate=False)
    assert counts["evaluacion"] is None
    assert counts["pesos"] == {**tuned, "transicion": 7.0}
    assert counts["lambda_cruzada"] == 3.0


def test_build_motor_without_people_to_validate_keeps_the_last_weights(db):
    # Pedidos al principio y al final (90 días): nadie pide antes y durante la validación.
    start = datetime(2026, 6, 1, 15, tzinfo=UTC)
    for person in range(3):
        for day in (0, 2, 88, 90):
            events.record_order(
                db, f"p-{person}", f"s-{person}-{day}", f"c-{person}-{day}", "supermercado", [_line("1", None)],
                ts=start + timedelta(days=day),
            )  # fmt: skip
    previous = {"afinidad": 1.0, "transicion": 2.0, "popularidad": 0.5}
    run = start_layer_run(db, "motor", "v")
    finish_layer_run(db, run, {"fuente": "prototype", "pesos": previous})
    db.commit()

    counts = build_motor(db, "prototype")
    assert counts["pesos"] == previous
    assert counts["evaluacion"]["validacion"]["personas"] == 0
    assert counts["evaluacion"]["validacion"]["aviso"]
    assert latest_weights(db, "prototype") == previous


def test_build_motor_without_84_days_keeps_the_last_weights_and_lambda(db):
    """Sin datos para evaluar, la corrida no vuelve a los pesos por defecto: conserva los elegidos antes."""
    start = datetime(2026, 9, 1, 15, tzinfo=UTC)
    for day in range(4):
        events.record_order(
            db, "p-1", f"s-{day}", f"c-{day}", "supermercado", [_line("1", None)], ts=start + timedelta(days=7 * day)
        )
    previous = {"afinidad": 1.0, "transicion": 7.0, "popularidad": 0.25}
    run = start_layer_run(db, "motor", "v")
    finish_layer_run(db, run, {"fuente": "prototype", "pesos": previous, "lambda_cruzada": 3.0})
    db.commit()

    counts = build_motor(db, "prototype")
    assert counts["evaluacion"] is None
    assert counts["pesos"] == previous
    assert counts["lambda_cruzada"] == 3.0
    assert latest_weights(db, "prototype") == previous and latest_lambda(db, "prototype") == 3.0


def test_cli_writes_one_report_per_source_and_a_notice_when_not_evaluated(simulated, tmp_path, monkeypatch):
    from rappi_ia import cli, config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    cli.cmd_motor(simulated, cli.build_parser().parse_args(["motor"]))
    synthetic = (tmp_path / "eval" / "motor-synthetic.md").read_text(encoding="utf-8")
    assert "Combinado" in synthetic and "Datos simulados" in synthetic
    prototype = (tmp_path / "eval" / "motor-prototype.md").read_text(encoding="utf-8")
    assert "no se evaluó: sin pedidos" in prototype

    cli.cmd_motor(simulated, cli.build_parser().parse_args(["motor", "--source", "synthetic", "--sin-evaluar"]))
    stub = (tmp_path / "eval" / "motor-synthetic.md").read_text(encoding="utf-8")
    assert "no se evaluó" in stub and "Combinado" not in stub


def test_build_without_orders_writes_nothing_and_finishes(db):
    counts = build_motor(db, "prototype")
    assert counts["transiciones"] == counts["afinidad"] == counts["tendencias"] == 0
    assert counts["pesos"] == DEFAULT_WEIGHTS and counts["evaluacion"] is None
    assert counts["lambda_cruzada"] == 1.0
    status = db.execute("SELECT status FROM layer_runs WHERE layer = 'motor'").fetchone()[0]
    assert status == "done"


def test_build_failure_marks_the_run_failed(simulated, monkeypatch):
    from rappi_ia.motor import build

    def broken(*_args, **_kwargs):
        raise RuntimeError("roto")

    monkeypatch.setattr(build, "trends", broken)
    with pytest.raises(RuntimeError):
        build_motor(simulated, "synthetic")
    status, counts = simulated.execute(
        "SELECT status, counts FROM layer_runs WHERE layer = 'motor' ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    assert status == "failed" and counts["fuente"] == "synthetic"
    assert _rows(simulated, "vertical_transitions") == 0  # nada a medias


# Después de un pedido y de «Olvidar»


@pytest.fixture
def client(db):
    seed_taxonomy(db, load_taxonomy())
    add_store(db, 1, "supermercado", "Súper")
    add_product(db, 91001, "Papas fritas clásicas 180 g", 1, "Snacks salados")
    add_price(db, 1, 91001, 1990)
    db.commit()

    @contextmanager
    def connector():  # el recálculo después del pedido usa la conexión del test, sin cerrarla
        yield db

    def conn_override():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    api.app.dependency_overrides[api.get_connector] = lambda: connector
    yield OwnerClient(api.app)
    api.app.dependency_overrides.clear()


def _affinity(db, user):
    return {
        v: (orders, signals)
        for v, orders, signals in db.execute(
            "SELECT vertical, orders, signals FROM user_vertical_affinity WHERE user_id = %s", (user,)
        )
    }


def _replenishment(db, user):
    return {r[0] for r in db.execute("SELECT concept_id FROM replenishment WHERE user_id = %s", (user,))}


def test_refresh_user_updates_affinity_after_an_order(client, db):
    assert _affinity(db, "u1") == {}
    body = {"user_id": "u1", "session_id": "s-1", "cart_id": "c-1", "vertical": "supermercado", "lines": [_line()]}
    reply = client.post("/orders", json=body)
    assert reply.status_code == 200, reply.text

    assert _affinity(db, "u1") == {"supermercado": (1, 1)}


def test_refresh_user_never_raises(db, caplog):
    @contextmanager
    def broken():
        raise RuntimeError("sin base")
        yield

    refresh_user(broken, "u1")  # registra y sigue
    assert any("motor" in r.getMessage().lower() for r in caplog.records)


def test_forget_clears_affinity_and_replenishment(client, db):
    start = datetime.now(UTC) - timedelta(days=30)
    for day in range(4):  # cada 7 días: recompra regular de snacks
        events.record_order(
            db, "u1", f"s-{day}", f"c-{day}", "supermercado", [_line()], ts=start + timedelta(days=7 * day)
        )
    db.commit()
    refresh_user(lambda: _same(db), "u1")
    assert _replenishment(db, "u1") == {"snacks-salados"}
    assert _affinity(db, "u1") == {"supermercado": (4, 4)}

    # Olvidar un concepto: los pedidos quedan (afinidad), la recompra de ese concepto no.
    reply = client.delete("/profile/u1", params={"concept": "snacks-salados"})
    assert reply.status_code == 200, reply.text
    assert _replenishment(db, "u1") == set()
    assert _affinity(db, "u1") == {"supermercado": (4, 4)}

    # Olvidar todo: nada de la persona.
    reply = client.delete("/profile/u1")
    assert reply.status_code == 200, reply.text
    assert _affinity(db, "u1") == {}
    assert _replenishment(db, "u1") == set()


@contextmanager
def _same(db):
    yield db


# «Olvidar» mientras corre `build_motor`: con dos conexiones


@pytest.fixture
def two_people(client, db):
    """u1 y u2, del prototipo, con cuatro pedidos de snacks cada 7 días: afinidad y recompra."""
    start = datetime.now(UTC) - timedelta(days=30)
    for user in ("u1", "u2"):
        for day in range(4):
            events.record_order(
                db, user, f"s-{user}-{day}", f"c-{user}-{day}", "supermercado", [_line()],
                ts=start + timedelta(days=7 * day),
            )  # fmt: skip
    db.commit()
    return db


def _forget_after_the_build_read_the_orders(monkeypatch, test_url, user, concept=None):
    """«Olvidar» (como `DELETE /profile`) en otra conexión, confirmado justo después de que `build_motor` leyó los
    pedidos de la fuente: lo que leyó ya no está al día."""
    from rappi_ia.motor import build

    read = build.transitions

    def forget_then_continue(orders):
        with connect(test_url) as other:
            other.execute("SET lock_timeout = '3s'")  # si el build tuviera tomadas las filas, falla en vez de colgar
            events.forget(other, user, concept)
            refresh_user_conn(other, user)
            other.commit()
        return read(orders)

    monkeypatch.setattr(build, "transitions", forget_then_continue)


def _last_motor_status(db):
    return db.execute("SELECT status FROM layer_runs WHERE layer = 'motor' ORDER BY run_id DESC LIMIT 1").fetchone()[0]


def test_a_person_forgotten_during_the_build_does_not_fail_it(two_people, monkeypatch, test_url):
    db = two_people
    _forget_after_the_build_read_the_orders(monkeypatch, test_url, "u2")

    counts = build_motor(db, "prototype", evaluate=False)

    assert _last_motor_status(db) == "done"
    assert counts["afinidad"] == 1
    assert _affinity(db, "u2") == {} and _replenishment(db, "u2") == set()
    assert _affinity(db, "u1") == {"supermercado": (4, 4)} and _replenishment(db, "u1") == {"snacks-salados"}


def test_a_concept_forgotten_during_the_build_stays_forgotten(two_people, monkeypatch, test_url):
    db = two_people
    _forget_after_the_build_read_the_orders(monkeypatch, test_url, "u1", "snacks-salados")

    build_motor(db, "prototype", evaluate=False)

    assert _last_motor_status(db) == "done"
    assert _replenishment(db, "u1") == set()  # el build no la reescribe con lo que leyó antes
    assert _affinity(db, "u1") == {"supermercado": (4, 4)}
    assert _replenishment(db, "u2") == {"snacks-salados"}


def test_the_build_waits_for_a_forget_in_flight_and_skips_the_person(two_people, test_url):
    """«Olvidar» tiene el candado de u2 y no confirma: el build lo espera y después salta a u2, que ya no está."""
    db = two_people
    with connect(test_url) as in_flight:
        events.forget(in_flight, "u2")
        refresh_user_conn(in_flight, "u2")
        result: dict = {}
        building = threading.Thread(target=lambda: result.update(build_motor(db, "prototype", evaluate=False)))
        building.start()
        deadline = time.monotonic() + 10
        waiting = """SELECT count(*) FROM pg_locks
                     WHERE NOT granted AND locktype = 'advisory'
                       AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"""
        while not in_flight.execute(waiting).fetchone()[0]:
            assert time.monotonic() < deadline, "el build no llegó a esperar el candado de u2"
            time.sleep(0.05)
        assert building.is_alive()
        in_flight.commit()
        building.join(timeout=30)

    assert result["afinidad"] == 1
    assert _last_motor_status(db) == "done"
    assert _affinity(db, "u2") == {}
    assert _affinity(db, "u1") == {"supermercado": (4, 4)}


def test_the_build_skips_a_person_the_purge_is_deleting_instead_of_waiting(two_people, test_url):
    """La purga borra sin el candado por persona: el build salta a quien está borrando y no toca sus filas."""
    db = two_people
    build_motor(db, "prototype", evaluate=False)
    db.execute("SET lock_timeout = '3s'")  # si el build esperara a la purga, falla en vez de colgar
    db.commit()
    with connect(test_url) as purging:
        purging.execute("DELETE FROM app_users WHERE user_id = 'u2'")  # sin confirmar: tiene la fila tomada
        counts = build_motor(db, "prototype", evaluate=False)
        purging.rollback()

    assert counts["afinidad"] == 1
    assert _last_motor_status(db) == "done"
    assert _affinity(db, "u2") == {"supermercado": (4, 4)}  # la purga no confirmó: lo suyo sigue como estaba


def test_a_run_shows_its_source_from_the_start(simulated, monkeypatch, test_url):
    """Una corrida que se corta a medias (sin llegar a `failed`) igual dice de qué fuente era."""
    from rappi_ia.motor import build

    seen = {}

    def peek(_conn, _source, run, _evaluate):
        with connect(test_url) as other:
            seen["counts"] = other.execute("SELECT counts FROM layer_runs WHERE run_id = %s", (run,)).fetchone()[0]
        return {"fuente": "synthetic"}

    monkeypatch.setattr(build, "_build", peek)
    build_motor(simulated, "synthetic")
    assert seen["counts"] == {"fuente": "synthetic"}


def test_without_orders_the_personal_phase_still_leaves_out_sensitive_concepts(db, monkeypatch):
    """Sin pedidos al leer la población, uno que llega antes de la fase por persona igual pasa por las guardias."""
    from rappi_ia.motor import build

    seed_taxonomy(db, load_taxonomy())
    db.execute("UPDATE concepts SET sensitive = true WHERE concept_id = 'snacks-salados'")
    db.commit()
    seen = {}
    personal = build._build_personal

    def spy(conn, source, now, sensitive):
        seen["sensitive"] = sensitive
        return personal(conn, source, now, sensitive)

    monkeypatch.setattr(build, "_build_personal", spy)
    build_motor(db, "prototype")
    assert "snacks-salados" in seen["sensitive"]


def test_refresh_user_leaves_synthetic_people_alone(simulated):
    """Sus filas las arma `build_motor` con el `now` de su fuente: el recálculo de una persona no las pisa."""
    db = simulated
    build_motor(db, "synthetic")
    user, before = db.execute(
        "SELECT user_id, count(*) FROM user_vertical_affinity GROUP BY user_id ORDER BY user_id LIMIT 1"
    ).fetchone()

    refresh_user(lambda: _same(db), user)

    assert db.execute("SELECT count(*) FROM user_vertical_affinity WHERE user_id = %s", (user,)).fetchone()[0] == before


# La fuente prototype: presente y pocas personas


def _recent_orders(days_ago: int, users: int):
    from rappi_ia.motor.data import Line, Order

    ts = datetime.now(UTC) - timedelta(days=days_ago)
    line = Line(None, "catalog_item", "91001", False)
    return [Order(f"u{i}", f"o{i}", None, ts, "turbo", 1000.0, (line,)) for i in range(users)]


@pytest.mark.parametrize("source", ["prototype", "synthetic"])
def test_build_uses_the_present_only_for_the_prototype(db, monkeypatch, source):
    """El prototipo mide sus ventanas desde hoy (como el recálculo de cada pedido); los simulados, desde su último
    pedido."""
    from rappi_ia.motor import build
    from rappi_ia.motor.model import TZ

    orders = _recent_orders(days_ago=10, users=2)
    monkeypatch.setattr(build, "load_orders", lambda *_args: orders)
    monkeypatch.setattr(build, "load_signals", lambda *_args, **_kwargs: [])
    build_motor(db, source, evaluate=False)

    window_end = db.execute("SELECT DISTINCT window_end FROM trends WHERE data_source = %s", (source,)).fetchone()[0]
    expected = datetime.now(TZ) if source == "prototype" else orders[0].ts.astimezone(TZ)
    assert window_end == expected.date()


def test_prototype_trends_hide_what_one_or_two_people_ordered(db, monkeypatch):
    from rappi_ia.motor import build
    from rappi_ia.motor.model import PROTOTYPE_MIN_USERS

    few, many = _recent_orders(2, users=2), _recent_orders(2, users=PROTOTYPE_MIN_USERS)
    for source, orders, products in (("prototype", few, 0), ("synthetic", few, 1)):
        monkeypatch.setattr(build, "load_orders", lambda *_args, orders=orders: orders)
        monkeypatch.setattr(build, "load_signals", lambda *_args, **_kwargs: [])
        build_motor(db, source, evaluate=False)
        assert (
            db.execute(
                "SELECT count(*) FROM trends WHERE data_source = %s AND scope = 'producto'", (source,)
            ).fetchone()[0]
            == products
        )
        assert (
            db.execute(
                "SELECT users_now FROM trends WHERE data_source = %s AND scope = 'vertical'", (source,)
            ).fetchone()[0]
            == 2
        )  # el vertical es un agregado: sale siempre

    monkeypatch.setattr(build, "load_orders", lambda *_args: many)
    build_motor(db, "prototype", evaluate=False)
    products = db.execute("SELECT count(*) FROM trends WHERE data_source = 'prototype' AND scope = 'producto'")
    assert products.fetchone()[0] == 1
