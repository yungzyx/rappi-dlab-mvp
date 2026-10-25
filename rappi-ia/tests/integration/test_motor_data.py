from datetime import UTC, datetime

import pytest

from rappi_ia.motor.data import Line, load_orders, load_signals, sensitive_concepts

T1 = datetime(2026, 9, 1, 15, tzinfo=UTC)
T2 = datetime(2026, 9, 5, 15, tzinfo=UTC)
T3 = datetime(2026, 9, 9, 15, tzinfo=UTC)


@pytest.fixture
def people(db):
    """Una persona del prototipo y una simulada; pedidos en los dos modos y eventos con y sin vertical."""
    db.execute("INSERT INTO app_users (user_id, source) VALUES ('p1', 'prototype'), ('s1', 'synthetic')")
    db.execute(
        """INSERT INTO concepts (concept_id, name, sensitive, taxonomy_version)
           VALUES ('cafe', 'Café', false, 'v1'), ('preservativos', 'Preservativos', true, 'v1')"""
    )
    orders = [
        ("o1", "p1", "c1", T1, "turbo", 5000, "propuesta", "prototype"),
        ("o2", "p1", "c2", T2, "supermercado", 8000, "actual", "prototype"),  # «Rappi hoy»: no enseña
        ("o3", "p1", None, T3, "farmacia", 3000, "propuesta", "prototype"),
        ("o4", "s1", None, T1, "mall", 9000, "propuesta", "synthetic"),
    ]
    for row in orders:
        db.execute(
            """INSERT INTO app_orders (order_id, user_id, cart_id, ts, vertical, total, mode, source)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            row,
        )
    lines = [
        ("o1", 1, "catalog_item", "101", "cafe", False),
        ("o1", 2, "menu_item", "202", None, True),
        ("o3", 1, "catalog_item", "303", "preservativos", False),
    ]
    for row in lines:
        db.execute(
            """INSERT INTO app_order_lines (order_id, line_no, entity_type, entity_id, concept_id, from_suggestion)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            row,
        )
    events = [
        ("p1", T1, "vertical_open", "restaurantes", "{}", "prototype"),
        ("p1", T1, "view_store", "mall", '{"mode": "actual"}', "prototype"),  # en «Rappi hoy»: no cuenta
        ("p1", T2, "search", None, "{}", "prototype"),  # sin vertical
        ("p1", T2, "app_open", "turbo", "{}", "prototype"),  # no es señal de afinidad
        ("p1", T3, "cart_add", "turbo", '{"mode": "propuesta"}', "prototype"),
        ("s1", T2, "view_item", "mall", "{}", "synthetic"),
    ]
    for row in events:
        db.execute(
            """INSERT INTO app_events (user_id, session_id, ts, type, vertical, payload, source)
               VALUES (%s, 's', %s, %s, %s, %s::jsonb, %s)""",
            row,
        )
    return db


def test_load_orders_only_proposal_mode_and_one_source(people):
    orders = load_orders(people, "prototype")
    assert [o.order_id for o in orders] == ["o1", "o3"]
    first = orders[0]
    assert (first.user_id, first.cart_id, first.ts, first.vertical, first.total) == ("p1", "c1", T1, "turbo", 5000.0)
    assert first.lines == (Line("cafe", "catalog_item", "101", False), Line(None, "menu_item", "202", True))
    [synthetic] = load_orders(people, "synthetic")
    assert synthetic.order_id == "o4"
    assert synthetic.lines == ()  # un pedido sin líneas
    assert [o.order_id for o in load_orders(people, "prototype", before=T3)] == ["o1"]
    assert [o.order_id for o in load_orders(people, "prototype", since=T1)] == ["o3"]  # estrictamente después
    assert [o.order_id for o in load_orders(people, "prototype", since=T1, before=T3)] == []
    assert load_orders(people, "prototype", user_id="s1") == []


def test_load_signals_skip_actual_mode_and_bring_vertical_open(people):
    signals = load_signals(people, "prototype")
    assert [(s.user_id, s.ts, s.kind, s.vertical) for s in signals] == [
        ("p1", T1, "order", "turbo"),
        ("p1", T1, "vertical_open", "restaurantes"),
        ("p1", T3, "order", "farmacia"),
        ("p1", T3, "cart_add", "turbo"),
    ]
    assert [(s.kind, s.vertical) for s in load_signals(people, "synthetic")] == [
        ("order", "mall"),
        ("view_item", "mall"),
    ]
    assert [s.kind for s in load_signals(people, "prototype", user_id="p1", before=T2)] == ["order", "vertical_open"]


def test_load_signals_with_the_orders_already_read_gives_the_same_signals(people):
    """El motor pasa los pedidos que ya leyó (`orders`) para no leerlos dos veces: las señales son las mismas."""
    for source in ("prototype", "synthetic"):
        assert load_signals(people, source, orders=load_orders(people, source)) == load_signals(people, source)
    p1 = load_orders(people, "prototype", user_id=["p1"])
    assert load_signals(people, "prototype", ["p1"], orders=p1) == load_signals(people, "prototype", ["p1"])
    assert [s.kind for s in load_signals(people, "prototype", orders=[])] == ["vertical_open", "cart_add"]


def test_sensitive_concepts(people):
    assert sensitive_concepts(people) == frozenset({"preservativos"})
