"""Impresiones, experimentos y catálogo fijado al registrar (migraciones 047 y 048): `list_view` con sus elementos en
`app_event_items`, las variantes de `experiments` (`modo_app` y el grupo de control de las ofertas, con su impresión
contrafactual `offer_withheld`), `payload.catalogo` en las vistas y el carro, y las vistas de `capa` que los leen."""

import uuid
from datetime import date

import pytest
from psycopg import errors
from test_query_budget import CountingConnection

from owner_client import OwnerClient
from rappi_ia import config
from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.rappi_agent import RappiAgent
from rappi_ia.api import app as api
from rappi_ia.api.services import Services
from rappi_ia.catalog.stores import product_detail
from rappi_ia.delivery import PERSON_TABLES, unknown_person_tables
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents
from rappi_ia.events import catalog_context, experiments
from rappi_ia.events import store as events
from rappi_ia.events.synth import generate

CHIPS = "91001"  # papas fritas del súper Centro (9101) del catálogo de prueba
SUPER = 9101


@pytest.fixture
def client(db):
    seed_demo(db)
    embedder = HashEmbedder()
    embed_search_documents(db, embedder)

    def conn_override():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    api.app.dependency_overrides[api.get_services] = lambda: Services(
        RappiAgent(embedder, TemplateComposer()), embedder
    )
    yield OwnerClient(api.app)
    api.app.dependency_overrides.clear()


def list_view(*items, mode=None, **extra):
    """Un `list_view` de los resultados de una búsqueda con estos elementos."""
    event = {
        "type": "list_view",
        "session_id": "s-imp",
        "client_event_id": str(uuid.uuid4()),
        "surface": "search",
        "origin": "resultados",
        "request_id": "req-imp",
        "position": max(i["position"] for i in items),
        "items": list(items),
        **extra,
    }
    if mode:
        event["payload"] = {"mode": mode}
    return event


def product(position, entity_id=CHIPS, concept="snacks-salados", vertical="grocery"):
    return {
        "position": position,
        "entity_type": "catalog_item",
        "entity_id": entity_id,
        "concept_id": concept,
        "vertical": vertical,
    }


def post(client, user_id, *batch):
    return client.post("/events", json={"user_id": user_id, "events": list(batch)})


def items_of(db, user_id):
    return db.execute(
        """SELECT i.position, i.entity_type, i.entity_id, i.concept_id, i.vertical
           FROM app_event_items i JOIN app_events e USING (event_id) WHERE e.user_id = %s ORDER BY i.position""",
        (user_id,),
    ).fetchall()


def user_in(variant: str, pct: int = 50) -> str:
    """Un id del prototipo que el sorteo estable deja en esa variante del grupo de control."""
    for n in range(1000):
        user_id = f"proto-{n:016x}"
        if (experiments.bucket(user_id, experiments.OFFERS_CONTROL) < pct) == (variant == experiments.CONTROL):
            return user_id
    raise AssertionError("sin id")


# ── Impresiones ──────────────────────────────────────────────────────────────
def test_a_list_view_saves_its_visible_items_with_their_place(client, db):
    batch = [list_view(product(0), product(2, "91003", "gaseosas"))]
    assert post(client, "u-imp", *batch).json() == {"guardados": 1}
    assert items_of(db, "u-imp") == [
        (0, "catalog_item", CHIPS, "snacks-salados", "supermercado"),  # la vertical, como código del catálogo
        (2, "catalog_item", "91003", "gaseosas", "supermercado"),
    ]
    row = db.execute("SELECT position, request_id, concept_id FROM app_events WHERE type = 'list_view'").fetchone()
    assert row == (2, "req-imp", None)  # la mayor posición vista; una lista no tiene un concepto
    # Un reintento del mismo lote no duplica ni el evento ni sus elementos.
    assert post(client, "u-imp", *batch).json() == {"guardados": 0}
    assert len(items_of(db, "u-imp")) == 2


def test_two_items_in_the_same_place_keep_the_first_and_the_batch_is_saved(client, db):
    cart = {
        "type": "cart_add",
        "session_id": "s-imp",
        "cart_id": "c",
        "entity_type": "catalog_item",
        "entity_id": CHIPS,
    }
    assert post(client, "u-doble", list_view(product(0), product(0, "91003", "gaseosas")), cart).json() == {
        "guardados": 2
    }
    assert [row[2] for row in items_of(db, "u-doble")] == [CHIPS]


def test_in_rappi_hoy_the_items_go_without_concept(client, db):
    post(client, "u-hoy", list_view(product(0), mode="actual"))
    assert items_of(db, "u-hoy") == [(0, "catalog_item", CHIPS, None, "supermercado")]


@pytest.mark.parametrize(
    "event",
    [
        {"type": "view_item", "session_id": "s", "items": [product(0)]},  # solo list_view trae elementos
        list_view(*[product(i) for i in range(events.MAX_EVENT_ITEMS + 1)]),
        list_view({"position": 0, "entity_type": "concepto", "entity_id": "x"}),
        {"type": "offer_withheld", "session_id": "s"},  # la retención la decide solo /agent/offer
    ],
)
def test_bad_impressions_are_rejected(client, event):
    assert post(client, "u-mal", event).status_code in (400, 422)


def test_forget_takes_the_impressions_with_the_person_or_the_concept(client, db):
    post(client, "proto-0000000000000a01", list_view(product(0), product(1, "91003", "gaseosas")))
    events.forget(db, "proto-0000000000000a01", "gaseosas")
    assert [row[3] for row in items_of(db, "proto-0000000000000a01")] == ["snacks-salados"]
    events.forget(db, "proto-0000000000000a01")
    assert db.execute("SELECT count(*) FROM app_event_items").fetchone()[0] == 0


def test_old_impressions_are_purged_and_the_event_stays(client, db):
    post(client, "u-viejo", list_view(product(0)))
    db.execute("UPDATE app_events SET ts = now() - interval '100 days' WHERE user_id = 'u-viejo'")
    assert events.purge_old_impressions(db) == 1
    assert items_of(db, "u-viejo") == []
    assert db.execute("SELECT count(*) FROM app_events WHERE type = 'list_view'").fetchone()[0] == 1


def test_the_new_person_tables_are_known_to_the_delivery(db):
    assert {"app_event_items", "experiment_assignments"} <= set(PERSON_TABLES)
    assert unknown_person_tables(db) == []


# ── Catálogo fijado al registrar ─────────────────────────────────────────────
def test_views_and_cart_pin_the_price_and_open_state_they_saw(client, db):
    price = db.execute(
        """SELECT min(l.price) FROM v_latest_offers l JOIN store_products sp ON sp.store_id = l.store_id
           AND sp.sku = l.sku WHERE sp.master_product_id = %s AND l.store_id = %s AND l.current""",
        (int(CHIPS), SUPER),
    ).fetchone()[0]
    db.execute("UPDATE stores SET raw = jsonb_build_object('is_open', false) WHERE store_id = %s", (SUPER,))
    batch = [
        {
            "type": "cart_add",
            "session_id": "s",
            "cart_id": "c",
            "entity_type": "catalog_item",
            "entity_id": CHIPS,
            "payload": {"store_id": SUPER, "catalogo": {"precio": 1}},  # lo que mande la app se reemplaza
        },
        {"type": "view_store", "session_id": "s", "entity_type": "store", "entity_id": str(SUPER)},
        {"type": "search", "session_id": "s", "payload": {"catalogo": {"precio": 1}}},  # otros tipos no se tocan
    ]
    post(client, "u-precio", *batch)
    rows = dict(db.execute("SELECT type, payload -> 'catalogo' FROM app_events WHERE user_id = 'u-precio'").fetchall())
    assert rows["cart_add"] == {"precio": round(float(price)), "abierta": False, "horario": "descarga"}
    assert rows["view_store"] == {"abierta": False, "horario": "descarga"}
    assert rows["search"] == {"precio": 1}


def test_products_without_store_are_pinned_like_their_card_in_one_query(db):
    """Sin `payload.store_id`, el precio y la tienda son los de la ficha (`product_detail`), y todo el lote se resuelve
    en una consulta, no en una por evento."""
    seed_demo(db)
    ids = [CHIPS, "91002", "91003", "91004", "92002"]
    batch = [events.Event("u-lote", "s", "view_item", entity_type="catalog_item", entity_id=i) for i in ids * 4]
    counting = CountingConnection(db)

    catalog_context.pin(counting, batch)

    assert len(counting.statements) <= 2  # los precios y el estado de las tiendas
    for e in batch[: len(ids)]:
        card = product_detail(db, "catalog_item", e.entity_id)
        assert e.payload["catalogo"]["precio"] == round(card["price_value"])
        if card["store_id"] is None:
            assert "abierta" not in e.payload["catalogo"]


# ── Experimentos ─────────────────────────────────────────────────────────────
def test_the_draw_is_stable_and_off_by_default(db, monkeypatch):
    assert experiments.bucket("proto-1", "ofertas_control") == experiments.bucket("proto-1", "ofertas_control")
    events.ensure_user(db, "proto-0000000000000b01")
    assert config.OFFERS_CONTROL_PCT == 0
    assert experiments.offers_variant(db, "proto-0000000000000b01") is None  # apagado: nadie entra
    assert experiments.variants(db, "proto-0000000000000b01") == {}
    control = user_in(experiments.CONTROL)
    events.ensure_user(db, control)
    assert experiments.offers_variant(db, control, pct=50) == experiments.CONTROL
    # Ya asignada, la variante no cambia aunque cambie el porcentaje.
    assert experiments.offers_variant(db, control, pct=1) == experiments.CONTROL


def test_assignments_check_the_variant_and_the_population(db):
    events.ensure_user(db, "syn-x", source="synthetic")
    with pytest.raises(errors.RaiseException), db.transaction():
        db.execute(
            "INSERT INTO experiment_assignments (user_id, experiment_id, variant, source)"
            " VALUES ('syn-x', 'modo_app', 'otra', 'synthetic')"
        )
    with pytest.raises(errors.RaiseException), db.transaction():
        db.execute(
            "INSERT INTO experiment_assignments (user_id, experiment_id, variant, source)"
            " VALUES ('syn-x', 'modo_app', 'propuesta', 'prototype')"
        )


def test_the_session_mode_is_the_first_mode_and_sessions_echo_the_variants(client, db):
    first = {"user_id": "u-modo", "events": [{"type": "app_open", "session_id": "s1"}], "session": {"mode": "actual"}}
    client.post("/events", json=first)
    second = {**first, "events": [{"type": "app_open", "session_id": "s2"}], "session": {"mode": "propuesta"}}
    client.post("/events", json=second)
    assert experiments.variants(db, "u-modo") == {"modo_app": "actual"}
    sessions = db.execute("SELECT session_id, mode, variants FROM app_sessions ORDER BY session_id").fetchall()
    assert sessions == [("s1", "actual", {"modo_app": "actual"}), ("s2", "propuesta", {"modo_app": "actual"})]


def test_a_new_session_gets_its_offers_variant_when_the_experiment_is_on(client, db, monkeypatch):
    monkeypatch.setattr(config, "OFFERS_CONTROL_PCT", 50)
    user_id = client.post("/session", json={}).json()["user_id"]
    assert set(experiments.variants(db, user_id)) == {"ofertas_control"}


def test_the_control_group_does_not_see_mochis_offer_and_it_is_recorded_as_counterfactual(client, db, monkeypatch):
    monkeypatch.setattr(config, "OFFERS_CONTROL_PCT", 50)
    cart = {"product": {"entity_type": "catalog_item", "entity_id": CHIPS}}
    control, treated = user_in(experiments.CONTROL), user_in(experiments.TREATMENT)

    def ask(user_id, moment="carrito", context=cart, session="s-of"):
        body = {"moment": moment, "user_id": user_id, "context": context}
        return client.post("/agent/offer", json={**body, **({"session_id": session} if session else {})})

    shown = ask(treated)
    assert shown.status_code == 200 and shown.json()["products"]
    assert ask(control).status_code == 204
    [(event_id, payload, origin, request_id, concept)] = db.execute(
        "SELECT event_id, payload, origin, request_id, concept_id FROM app_events WHERE type = 'offer_withheld'"
    ).fetchall()
    assert payload == {"moment": "carrito", "experiment": "ofertas_control", "variant": "control"}
    assert origin == "agent-carrito" and request_id and concept == shown.json()["reason"]["concept"]
    withheld = db.execute("SELECT entity_id FROM app_event_items WHERE event_id = %s ORDER BY position", (event_id,))
    assert [row[0] for row in withheld] == [p["entity_id"] for p in shown.json()["products"]]
    # Lo que la persona pide (un plan) se muestra siempre, y sin sesión no se retiene nada.
    assert ask(control, "plan", {"occasion": "carrete"}).status_code == 200
    assert ask(control, session=None).status_code == 200
    assert experiments.variants(db, treated) == {"ofertas_control": "tratamiento"}


# ── Vistas de capa y panel ───────────────────────────────────────────────────
def test_ctr_by_position_counts_a_click_from_the_same_place(client, db):
    seen = list_view(product(0), product(1, "91003", "gaseosas"))
    click = {
        "type": "cart_add",
        "session_id": "s-imp",
        "cart_id": "c-imp",
        "entity_type": "catalog_item",
        "entity_id": "91003",
        "surface": "search",
        "origin": "resultados",
        "position": 1,
        "request_id": "req-imp",
    }
    post(client, "u-ctr", seen, click)
    rows = db.execute(
        "SELECT position, impresiones, clics, ctr, al_carro FROM capa.v_ctr_posicion WHERE source = 'prototype'"
        " ORDER BY position"
    ).fetchall()
    assert [tuple(map(float, r)) for r in rows] == [(0, 1, 0, 0, 0), (1, 1, 1, 1, 1)]
    data = client.get("/analytics/ctr-posicion?source=prototype").json()["data"]
    assert [p["clics"] for p in data["posiciones"]] == [0, 1]
    assert data["listas"] == [{"pantalla": "search", "lista": "resultados", "impresiones": 2, "clics": 1, "ctr": 0.5}]


def test_session_funnel_and_abandoned_carts(client, db):
    post(
        client,
        "u-emb",
        list_view(product(0)),
        {
            "type": "cart_add",
            "session_id": "s-imp",
            "cart_id": "c-emb",
            "entity_type": "catalog_item",
            "entity_id": CHIPS,
            "value": 1990,
        },
    )
    db.execute("UPDATE app_events SET ts = now() - interval '2 hours' WHERE user_id = 'u-emb'")
    [funnel] = client.get("/analytics/embudo-sesion?source=prototype").json()["data"]
    assert funnel == {"modo": "propuesta", "sesiones": 1, "vieron": 1, "tocaron": 1, "agregaron": 1, "pidieron": 0}
    [cart] = db.execute(
        "SELECT cart_id, unidades, monto, llego_a_pagar FROM capa.v_carros_abandonados WHERE user_id = 'u-emb'"
    ).fetchall()
    assert cart == ("c-emb", 1, 1990, False)
    # Con su pedido dentro de la hora ya no está abandonado.
    events.record_order(
        db,
        "u-emb",
        "s-imp",
        "c-emb",
        "supermercado",
        [{"entity_type": "catalog_item", "entity_id": CHIPS, "unit_price": 1990}],
        ts=None,
    )
    db.execute("UPDATE app_orders SET ts = now() - interval '110 minutes' WHERE user_id = 'u-emb'")
    assert db.execute("SELECT count(*) FROM capa.v_carros_abandonados WHERE user_id = 'u-emb'").fetchone()[0] == 0


def test_the_amplitude_bridge_uses_rappis_names_and_envelope(client, db):
    post(
        client,
        "u-amp",
        list_view(product(0), product(1, "91003", "gaseosas")),
        {"type": "search", "session_id": "s-imp", "unmet": True, "results": 0, "client_event_id": str(uuid.uuid4())},
        {"type": "cart_remove", "session_id": "s-imp", "cart_id": "c"},
    )
    rows = {
        r[0]: r[1:]
        for r in db.execute(
            """SELECT evento_mvp, event_type, equivalente, event_properties, uuid IS NOT NULL
               FROM capa.v_eventos_amplitude WHERE user_id = 'u-amp'"""
        )
    }
    assert rows["list_view"][:2] == ("VIEW_COMPONENT", True)
    assert rows["list_view"][2] == {
        "CONTEXT": "search",
        "SOURCE": "resultados",
        "COMPONENT_NAME": "resultados",
        "COMPONENT_INDEX": 1,
        "REQUEST_ID": "req-imp",
        "PRODUCT_ID_LIST": [CHIPS, "91003"],
        "LAST_POSITION_VIEWED": 1,
    }
    assert rows["search"][:2] == ("LOCAL_SEARCH_NULL_RESULTS", True)
    assert rows["cart_remove"][:2] == ("MVP_CART_REMOVE", False)
    assert all(r[3] for r in rows.values())  # todos con uuid, también los que no lo trajeron


def test_every_event_type_says_if_rappi_has_it(db):
    """Cada tipo de EVENT_TYPES sale en el puente con un nombre, y `equivalente` es false solo en los MVP_ (migración
    051: antes `order_cancelled` salía MVP_ y equivalente). Un tipo nuevo sin traducción obliga a decidirlo aquí."""
    events.ensure_user(db, "u-tipos", "prototype")
    db.execute(
        """INSERT INTO app_events (user_id, session_id, type, source)
           SELECT 'u-tipos', 's-tipos', t, 'prototype' FROM unnest(%s::text[]) t""",
        (sorted(events.EVENT_TYPES),),
    )
    rows = {
        kind: (name, equivalent)
        for kind, name, equivalent in db.execute(
            "SELECT evento_mvp, event_type, equivalente FROM capa.v_eventos_amplitude WHERE user_id = 'u-tipos'"
        )
    }

    assert set(rows) == events.EVENT_TYPES
    assert all(equivalent == (not name.startswith("MVP_")) for name, equivalent in rows.values())
    assert {kind for kind, (_, equivalent) in rows.items() if not equivalent} == {
        "cart_remove",
        "suggestion_dismissed",
        "reorder",
        "offer_withheld",
        "order_cancelled",
        "vertical_reorder_shown",
        "agent_visibility",
        "offer_why_open",
    }
    assert rows["order_cancelled"] == ("MVP_ORDER_CANCELLED", False)
    assert rows["vertical_reorder_shown"] == ("MVP_VERTICAL_REORDER_SHOWN", False)
    assert rows["agent_visibility"] == ("MVP_AGENT_VISIBILITY", False)
    assert rows["offer_why_open"] == ("MVP_OFFER_WHY_OPEN", False)


def test_the_synthetic_population_has_impressions_positions_and_its_mode(db):
    seed_demo(db)
    generate(db, users=12, weeks=4, seed=11, until=date(2026, 10, 4))
    views, with_items = db.execute(
        """SELECT count(*),
                  count(*) FILTER (WHERE EXISTS (SELECT 1 FROM app_event_items i WHERE i.event_id = e.event_id))
           FROM app_events e WHERE source = 'synthetic' AND type = 'list_view'"""
    ).fetchone()
    assert views > 0 and with_items == views
    # Lo que se mira y se agrega sale de los resultados, con su lugar: todo clic tiene su impresión.
    orphans = db.execute(
        """SELECT count(*) FROM app_events k WHERE k.source = 'synthetic' AND k.type IN ('view_item', 'cart_add')
             AND k.position IS NOT NULL AND NOT EXISTS (
               SELECT 1 FROM app_events e JOIN app_event_items i USING (event_id)
               WHERE e.type = 'list_view' AND e.session_id = k.session_id AND e.request_id = k.request_id
                 AND i.position = k.position AND i.entity_id = k.entity_id)"""
    ).fetchone()[0]
    assert orphans == 0
    assert db.execute("SELECT DISTINCT variant FROM experiment_assignments WHERE source = 'synthetic'").fetchall() == [
        ("propuesta",)
    ]
    assert db.execute("SELECT count(*) FROM capa.v_ctr_posicion WHERE source = 'synthetic'").fetchone()[0] > 0
