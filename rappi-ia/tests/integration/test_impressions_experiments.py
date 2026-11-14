"""Impresiones, experimentos y catálogo fijado al registrar (migraciones 047 y 048): `list_view` con sus elementos en
`app_event_items`, las variantes de `experiments` (`modo_app` y el grupo de control de las ofertas, con su impresión
contrafactual `offer_withheld`), `payload.catalogo` en las vistas y el carro, y las vistas de `capa` que los leen."""

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from psycopg import errors
from test_query_budget import CountingConnection

from owner_client import OwnerClient
from rappi_ia import config
from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.rappi_agent import RappiAgent
from rappi_ia.analytics import queries
from rappi_ia.api import agent as api_agent
from rappi_ia.api import app as api
from rappi_ia.api import identity
from rappi_ia.api.services import Services
from rappi_ia.catalog.stores import product_detail
from rappi_ia.delivery import PERSON_TABLES, unknown_person_tables
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents
from rappi_ia.events import catalog_context, experiments, synth
from rappi_ia.events import store as events
from rappi_ia.events.synth import generate
from rappi_ia.motor.build import refresh_user_conn
from rappi_ia.motor.model import TZ

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
        {"type": "offer_eligible", "session_id": "s"},  # y la oferta entregada en tratamiento, también
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
    session = client.post("/session", json={}).json()
    variant = experiments.variants(db, session["user_id"])[experiments.OFFERS_CONTROL]
    assert session["agent_enabled"] is (variant != experiments.CONTROL)


def mine(user_id):
    """La cabecera con el token de esa persona: lo que manda la app al recargar (`GET /session`)."""
    return {identity.TOKEN_HEADER: identity.sign(user_id)}


def test_the_session_says_whether_mochi_is_on_also_after_reloading(client, db, monkeypatch):
    """La app pide `GET /session` cada vez que abre con un token ya guardado: así sabe al recargar si la persona está
    en el grupo de control ("Mochi apagado"), y quien ya tenía token antes de encender el experimento recibe ahí su
    variante, estable aunque cambie el porcentaje. Sin token (o con uno ajeno a la API) es un 401: la app pide otra."""
    monkeypatch.setattr(config, "OFFERS_CONTROL_PCT", 50)
    assert client.get("/session").status_code == 401
    assert client.get("/session", headers={identity.TOKEN_HEADER: "proto-0000000000000001.firma"}).status_code == 401
    control, treated = user_in(experiments.CONTROL), user_in(experiments.TREATMENT)
    assert client.get("/session", headers=mine(control)).json() == {"user_id": control, "agent_enabled": False}
    assert client.get("/session", headers=mine(treated)).json() == {"user_id": treated, "agent_enabled": True}
    assert experiments.variants(db, control) == {experiments.OFFERS_CONTROL: experiments.CONTROL}
    monkeypatch.setattr(config, "OFFERS_CONTROL_PCT", 1)  # ya asignada, la variante no cambia
    assert client.get("/session", headers=mine(control)).json()["agent_enabled"] is False
    monkeypatch.setattr(config, "OFFERS_CONTROL_PCT", 0)  # apagado, Mochi vuelve para todos
    assert client.get("/session", headers=mine(control)).json()["agent_enabled"] is True


def test_with_the_control_at_zero_nothing_changes_for_anybody(client, db):
    """Con OFFERS_CONTROL_PCT en 0 (producción y la prueba con usuarios): Mochi para todos, sus respuestas y ofertas de
    siempre, sin asignar a nadie ni anotar nada del experimento, también para quien quedaría en control encendido."""
    assert config.OFFERS_CONTROL_PCT == 0
    would_be_control = user_in(experiments.CONTROL)
    assert client.post("/session", json={}).json()["agent_enabled"] is True
    assert client.get("/session", headers=mine(would_be_control)).json()["agent_enabled"] is True
    answer = client.post("/agent/ask", json={"message": "cerveza", "user_id": would_be_control, "session_id": "s-0"})
    assert answer.status_code == 200 and "x-agent-withheld" not in answer.headers and answer.json()["suggestion"]
    cart = {"product": {"entity_type": "catalog_item", "entity_id": CHIPS}}
    for moment, context, surface in (("carrito", cart, "home"), ("plan", {"occasion": "carrete"}, "home")):
        body = {"moment": moment, "user_id": would_be_control, "session_id": "s-0", "surface": surface}
        reply = client.post("/agent/offer", json={**body, "context": context})
        assert reply.status_code == 200 and "x-offer-withheld" not in reply.headers
    assert db.execute("SELECT count(*) FROM experiment_assignments").fetchone() == (0,)
    types = db.execute("SELECT array_agg(DISTINCT type) FROM app_events").fetchone()[0]
    assert types == ["ask"]


def test_mochi_off_answers_the_usual_search_and_records_what_mochi_would_have_said(client, db, monkeypatch):
    """`/agent/ask` para el grupo de control (una app vieja: la de hoy no le muestra ese buscador): la búsqueda de
    siempre, sin texto de Mochi, plan, sugerencia cruzada ni acciones, con `X-Agent-Withheld: 1`. Lo que Mochi habría
    dicho queda como `offer_withheld` en el buscador, que no cuenta en la parte expuesta, y la consulta como una
    búsqueda: la adopción del control sigue en 0. "Para ti" (/recommendations) sí lo conserva."""
    monkeypatch.setattr(config, "OFFERS_CONTROL_PCT", 50)
    control, treated = user_in(experiments.CONTROL), user_in(experiments.TREATMENT)

    def ask(user_id):
        return client.post("/agent/ask", json={"message": "cerveza", "user_id": user_id, "session_id": "s-ask"})

    mochi = ask(treated)
    assert mochi.status_code == 200 and "x-agent-withheld" not in mochi.headers
    suggestion = mochi.json()["suggestion"]
    off = ask(control)
    assert off.status_code == 200 and off.headers["x-agent-withheld"] == "1"
    body = off.json()
    assert set(body) == {"text", "products", "unmet", "corrected_query", "intent", "request_id"}
    assert "Mochi" not in body["text"] and body["intent"]["kind"] == "buscar"
    usual = client.get("/search", params={"q": "cerveza"}).json()
    assert [p["entity_id"] for p in body["products"]] == [
        p["entity_id"] for group in usual["groups"] for p in group["products"]
    ]
    rows = db.execute(
        """SELECT e.user_id, e.type, e.surface, e.origin, e.payload, e.concept_id,
                  array_remove(array_agg(i.entity_id ORDER BY i.position), NULL)
           FROM app_events e LEFT JOIN app_event_items i USING (event_id)
           WHERE e.type <> 'list_view' GROUP BY e.event_id ORDER BY e.user_id = %s, e.type""",
        (control,),
    ).fetchall()
    assert [row[:2] for row in rows] == [(treated, "ask"), (control, "offer_withheld"), (control, "search")]
    _, _, surface, origin, payload, concept, items = rows[1]
    assert (surface, origin, concept) == ("agent", "agent-ask", suggestion["concept"])
    assert payload["moment"] == "ask" and payload["variant"] == "control"
    assert payload["retenido"][0] == "respuesta" and "sugerencia" in payload["retenido"]
    assert items == [p["entity_id"] for p in suggestion["products"]]

    groups = {v["variante"]: v for v in experiments_of(client, "prototype")[experiments.OFFERS_CONTROL]["variantes"]}
    assert groups["control"]["ofertas"]["retenidas"] == 0 and groups["control"]["ofertas"]["personas_con_oferta"] == 0
    adoption = experiments_of(client, "prototype")[experiments.OFFERS_CONTROL]["adopcion"]["variantes"]
    assert {row["variante"]: row["usaron"] for row in adoption} == {"tratamiento": 1, "control": 0}
    assert client.get("/recommendations", params={"user_id": control}).status_code == 200
    blank = client.post("/agent/ask", json={"message": "   ", "user_id": control})
    assert blank.status_code == 200 and blank.json()["products"] == [] and blank.json()["unmet"] is True


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
    # Mochi apagado: tampoco un plan, y sin sesión también se retiene; ninguno de los dos se anota.
    for reply in (ask(control, "plan", {"occasion": "carrete"}), ask(control, session=None)):
        assert reply.status_code == 204 and reply.headers["x-offer-withheld"] == "1"
    assert db.execute("SELECT count(*) FROM app_events WHERE type = 'offer_withheld'").fetchone() == (1,)
    assert experiments.variants(db, treated) == {"ofertas_control": "tratamiento"}


def test_the_control_group_never_gets_an_offer_and_only_what_both_groups_ask_for_is_recorded(client, db, monkeypatch):
    """Mochi apagado: a control la API no le entrega ninguna oferta, ni pedida desde el buscador ni "¿Me falta algo?"
    del checkout. Solo se anota la que la app pide igual en los dos grupos (la Home, fuera del buscador), con su
    pantalla y la cabecera que lo dice; lo demás solo lo puede pedir tratamiento y no se anota en ninguno."""
    monkeypatch.setattr(config, "OFFERS_CONTROL_PCT", 50)
    control = user_in(experiments.CONTROL)
    body = {"moment": "carrito", "user_id": control, "session_id": "s-of", "context": {"product": {
        "entity_type": "catalog_item", "entity_id": CHIPS}}}  # fmt: skip

    asked = client.post("/agent/offer", json={**body, "surface": "agent"})
    assert asked.status_code == 204 and asked.headers["x-offer-withheld"] == "1"
    assert db.execute("SELECT count(*) FROM app_events WHERE type = 'offer_withheld'").fetchone() == (0,)

    alone = client.post("/agent/offer", json={**body, "surface": "home"})
    assert alone.status_code == 204 and alone.headers["x-offer-withheld"] == "1"
    rows = db.execute("SELECT surface, origin FROM app_events WHERE type = 'offer_withheld'").fetchall()
    assert rows == [("home", "agent-carrito")]
    checkout = {**body, "moment": "checkout", "surface": "checkout", "context": {"cart": [
        {"entity_type": "catalog_item", "entity_id": CHIPS}]}}  # fmt: skip
    new = {**body, "moment": "vertical_por_probar", "surface": "home", "context": {}}
    for reply in (client.post("/agent/offer", json=checkout), client.post("/agent/offer", json=new)):
        assert reply.status_code == 204 and reply.headers["x-offer-withheld"] == "1"
    assert db.execute("SELECT count(*) FROM app_events WHERE type = 'offer_withheld'").fetchone() == (1,)
    # Una pantalla que no existe es un 422 (como en /events), no una retenida.
    assert client.post("/agent/offer", json={**body, "surface": "otra"}).status_code == 422


def test_show_me_something_new_is_not_recorded_in_either_group(client, db, monkeypatch):
    """La vertical por probar ("Muéstrame algo nuevo") se pide en el menú de la mascota, que el control no tiene: en
    tratamiento se muestra, pero no se anota como `offer_eligible`, así la parte expuesta solo cuenta lo que los dos
    grupos pueden recibir."""
    monkeypatch.setattr(config, "OFFERS_CONTROL_PCT", 50)
    body = {"moment": "vertical_por_probar", "user_id": user_in(experiments.TREATMENT), "session_id": "s-nuevo",
            "surface": "home", "context": {}}  # fmt: skip
    shown = client.post("/agent/offer", json=body)
    assert shown.status_code == 200 and shown.json()["products"]
    assert db.execute("SELECT count(*) FROM app_events WHERE type = 'offer_eligible'").fetchone() == (0,)
    assert "vertical_por_probar" in experiments.HOLDOUT_MOMENTS - experiments.EXPOSURE_MOMENTS


def test_the_same_withheld_offer_counts_once_per_session(client, db, monkeypatch):
    """La Home pide la recompra cada vez que vuelve a estar arriba; en tratamiento la app cuenta una sola mostrada por
    pestaña, y en control, una sola retenida por sesión (origen, concepto y vertical)."""
    monkeypatch.setattr(config, "OFFERS_CONTROL_PCT", 50)
    control = user_in(experiments.CONTROL)
    for days_ago in (7, 14, 21):  # café cada 7 días, el último hace 7: hoy le toca
        day = datetime.now(TZ).date() - timedelta(days=days_ago)
        line = {"entity_type": "catalog_item", "entity_id": "91004", "concept_id": "cafe", "unit_price": 1990}
        events.record_order(
            db, control, f"s-cafe-{days_ago}", f"c-cafe-{days_ago}", "supermercado", [line],
            ts=datetime.combine(day, datetime.min.time().replace(hour=12), TZ),
        )  # fmt: skip
    refresh_user_conn(db, control)

    def repeat(session):
        body = {"moment": "recompra", "user_id": control, "session_id": session, "surface": "home", "context": {}}
        return client.post("/agent/offer", json=body)

    for session in ("s-a", "s-a", "s-b"):
        reply = repeat(session)
        assert reply.status_code == 204 and reply.headers["x-offer-withheld"] == "1"
    rows = db.execute(
        "SELECT session_id, concept_id FROM app_events WHERE type = 'offer_withheld' ORDER BY session_id"
    ).fetchall()
    assert rows == [("s-a", "cafe"), ("s-b", "cafe")]
    # Sin oferta que retener (un momento sin nada) es un 204 sin la cabecera: la Home sí pide "¿Volvemos a…?".
    nothing = client.post("/agent/offer", json={"moment": "volver", "user_id": control, "session_id": "s-a",
                                                "surface": "home", "context": {}})  # fmt: skip
    assert nothing.status_code == 204 and "x-offer-withheld" not in nothing.headers


def test_a_withheld_offer_with_an_unseeded_concept_also_counts_once_per_session(client, db, monkeypatch):
    """Un concepto de taxonomy.toml aún sin sembrar se guarda nulo en el evento: la segunda vez igual se reconoce."""
    monkeypatch.setattr(config, "OFFERS_CONTROL_PCT", 50)
    real = api_agent.make_offer

    def unseeded(*args, **kwargs):
        found = real(*args, **kwargs)
        return replace(found, reason={**found.reason, "concept": "concepto-sin-sembrar"})

    monkeypatch.setattr(api_agent, "make_offer", unseeded)
    body = {"moment": "carrito", "user_id": user_in(experiments.CONTROL), "session_id": "s-of", "surface": "home",
            "context": {"product": {"entity_type": "catalog_item", "entity_id": CHIPS}}}  # fmt: skip
    for _ in range(2):
        reply = client.post("/agent/offer", json=body)
        assert reply.status_code == 204 and reply.headers["x-offer-withheld"] == "1"
    rows = db.execute("SELECT concept_id FROM app_events WHERE type = 'offer_withheld'").fetchall()
    assert rows == [(None,)]


def test_the_treatment_group_records_the_same_offer_as_eligible_once_per_session(client, db, monkeypatch):
    """La parte expuesta se cuenta con el mismo hecho del servidor en los dos grupos: en tratamiento la oferta se
    muestra y queda `offer_eligible`, con lo mismo que `offer_withheld` en control (payload, origen, concepto,
    elementos) y una vez por sesión. Lo pedido en el buscador, un plan y el experimento apagado no anotan nada."""
    monkeypatch.setattr(config, "OFFERS_CONTROL_PCT", 50)
    cart = {"product": {"entity_type": "catalog_item", "entity_id": CHIPS}}
    control, treated = user_in(experiments.CONTROL), user_in(experiments.TREATMENT)

    def ask(user_id, session="s-el", surface="home", moment="carrito", context=cart):
        body = {"moment": moment, "user_id": user_id, "session_id": session, "surface": surface, "context": context}
        return client.post("/agent/offer", json=body)

    shown = [ask(treated) for _ in range(2)]
    assert all(reply.status_code == 200 and "x-offer-withheld" not in reply.headers for reply in shown)
    assert ask(control).status_code == 204
    rows = db.execute(
        """SELECT e.user_id, e.type, e.payload, e.origin, e.surface, e.concept_id, e.results,
                  array_agg(i.entity_id ORDER BY i.position)
           FROM app_events e JOIN app_event_items i USING (event_id)
           WHERE e.type IN ('offer_withheld', 'offer_eligible') GROUP BY e.event_id ORDER BY e.type"""
    ).fetchall()
    products = [p["entity_id"] for p in shown[0].json()["products"]]
    concept = shown[0].json()["reason"]["concept"]
    assert rows == [
        (treated, "offer_eligible", {"moment": "carrito", "experiment": "ofertas_control", "variant": "tratamiento"},
         "agent-carrito", "home", concept, len(products), products),
        (control, "offer_withheld", {"moment": "carrito", "experiment": "ofertas_control", "variant": "control"},
         "agent-carrito", "home", concept, len(products), products),
    ]  # fmt: skip
    # Otra sesión sí cuenta otra vez; lo pedido en el buscador y un plan, no.
    assert ask(treated, session="s-el2").status_code == 200
    assert ask(treated, surface="agent").status_code == 200
    assert ask(treated, moment="plan", context={"occasion": "carrete"}).status_code == 200
    count = "SELECT count(*) FROM app_events WHERE type = 'offer_eligible'"
    assert db.execute(count).fetchone() == (2,)
    # Apagado, nadie entra y nada se anota.
    monkeypatch.setattr(config, "OFFERS_CONTROL_PCT", 0)
    assert ask(user_in(experiments.TREATMENT, pct=0), session="s-off").status_code == 200
    assert db.execute(count).fetchone() == (2,)


def test_a_refusal_in_the_app_does_not_change_what_the_api_records_in_either_group(client, db, monkeypatch):
    """Lo rechazado en la sesión lo filtra la app (`wasRefused`), después de la respuesta: la API anota igual la oferta
    en los dos grupos (`offer_eligible` y `offer_withheld`), así que ese filtro no sesga la cuenta."""
    monkeypatch.setattr(config, "OFFERS_CONTROL_PCT", 50)
    control, treated = user_in(experiments.CONTROL), user_in(experiments.TREATMENT)

    def ask(user_id, session):
        body = {"moment": "carrito", "user_id": user_id, "session_id": session, "surface": "home",
                "context": {"product": {"entity_type": "catalog_item", "entity_id": CHIPS}}}  # fmt: skip
        return client.post("/agent/offer", json=body)

    concept = ask(treated, "s-antes").json()["reason"]["concept"]
    for user_id in (treated, control):
        refused = {"type": "suggestion_dismissed", "session_id": "s-no", "concept_id": concept, "surface": "home",
                   "origin": "agent-carrito", "client_event_id": str(uuid.uuid4())}  # fmt: skip
        assert post(client, user_id, refused).status_code == 200
    assert ask(treated, "s-no").status_code == 200
    reply = ask(control, "s-no")
    assert reply.status_code == 204 and reply.headers["x-offer-withheld"] == "1"
    rows = db.execute(
        """SELECT user_id, type, concept_id FROM app_events
           WHERE session_id = 's-no' AND type IN ('offer_eligible', 'offer_withheld') ORDER BY 2"""
    ).fetchall()
    assert rows == [(treated, "offer_eligible", concept), (control, "offer_withheld", concept)]


def test_the_same_offer_is_recognized_within_a_day_of_the_session(client, db, monkeypatch):
    """La cuenta de "ya anotada en la sesión" mira las últimas 24 horas (la sesión de la app expira tras 30 minutos sin
    actividad): una anotación más vieja con la misma sesión ya no la frena."""
    monkeypatch.setattr(config, "OFFERS_CONTROL_PCT", 50)
    treated = user_in(experiments.TREATMENT)
    body = {"moment": "carrito", "user_id": treated, "session_id": "s-dia", "surface": "home",
            "context": {"product": {"entity_type": "catalog_item", "entity_id": CHIPS}}}  # fmt: skip
    for _ in range(2):
        assert client.post("/agent/offer", json=body).status_code == 200
    count = "SELECT count(*) FROM app_events WHERE type = 'offer_eligible'"
    assert db.execute(count).fetchone() == (1,)
    db.execute("UPDATE app_events SET ts = now() - interval '25 hours' WHERE type = 'offer_eligible'")
    assert client.post("/agent/offer", json=body).status_code == 200
    assert db.execute(count).fetchone() == (2,)


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


# ── Panel: experimentos ──────────────────────────────────────────────────────
def days_ago(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def assigned(db, user_id, variants, source="prototype", days=10):
    """La persona con estas variantes (`{experimento: variante}`), asignadas hace `days` días."""
    events.ensure_user(db, user_id, source)
    for experiment_id, variant in variants.items():
        experiments.assign(db, user_id, experiment_id, variant)
    db.execute("UPDATE experiment_assignments SET assigned_at = %s WHERE user_id = %s", (days_ago(days), user_id))


def ordered(db, user_id, vertical, days, source="prototype"):
    line = {"entity_type": "catalog_item", "entity_id": CHIPS, "unit_price": 1990}
    events.record_order(db, user_id, "s-exp", f"c-{uuid.uuid4().hex[:8]}", vertical, [line], source, days_ago(days))


def offer_event(db, user_id, kind, moment, days, source="prototype", surface="cart"):
    event = events.Event(user_id, "s-exp", kind, ts=days_ago(days), surface=surface, origin=f"agent-{moment}")
    events.record(db, [event], source=source)


def experiments_of(client, source):
    body = client.get(f"/analytics/experimentos?source={source}").json()
    assert body["source"] == source  # la población declarada: la que se pidió
    return {e["id"]: e for e in body["data"]["experimentos"]}


def test_the_experiments_panel_counts_each_variant_within_one_population(client, db):
    mode, offers = experiments.MODE, experiments.OFFERS_CONTROL
    assigned(db, "p-ctl", {mode: "propuesta", offers: "control"})
    assigned(db, "p-tra", {mode: "actual", offers: "tratamiento"})
    assigned(db, "p-nada", {mode: "propuesta", offers: "tratamiento"})
    assigned(db, "s-ctl", {mode: "propuesta", offers: "control"}, source="synthetic")
    # Control: su oferta retenida y, después, dos pedidos en dos verticales. El de antes de asignarse no cuenta.
    offer_event(db, "p-ctl", "offer_withheld", "carrito", days=8)
    ordered(db, "p-ctl", "supermercado", days=5)
    ordered(db, "p-ctl", "farmacia", days=4)
    ordered(db, "p-ctl", "restaurantes", days=12)
    # Tratamiento: una oferta del carro entregada (offer_eligible, la anota la API), mostrada y aceptada; un plan (lo
    # pide la persona) no es del experimento. Un pedido antes de la oferta y otro después.
    offer_event(db, "p-tra", "offer_eligible", "carrito", days=8)
    offer_event(db, "p-tra", "suggestion_shown", "carrito", days=8)
    offer_event(db, "p-tra", "suggestion_accepted", "carrito", days=8)
    offer_event(db, "p-tra", "suggestion_shown", "plan", days=7)
    ordered(db, "p-tra", "supermercado", days=9)
    ordered(db, "p-tra", "supermercado", days=3)
    # Lo simulado no entra en las cifras del prototipo.
    offer_event(db, "s-ctl", "offer_withheld", "carrito", days=8, source="synthetic")
    ordered(db, "s-ctl", "turbo", days=2, source="synthetic")

    proto = experiments_of(client, "prototype")
    assert list(proto) == ["modo_app", "ofertas_control"]
    assert proto["modo_app"]["al_azar"] is False and "describe" in proto["modo_app"]["nota"]
    assert proto["modo_app"]["variantes"] == [
        {"variante": "propuesta", "personas": 2, "con_pedido": 1, "verticales_por_persona": 2},
        {"variante": "actual", "personas": 1, "con_pedido": 1, "verticales_por_persona": 1},
    ]
    control = proto["ofertas_control"]
    assert control["al_azar"] is True and control["control_pct"] == config.OFFERS_CONTROL_PCT == 0
    assert control["variantes"] == [
        {
            "variante": "tratamiento",
            "personas": 2,
            "con_pedido": 1,
            "verticales_por_persona": 1,
            "ofertas": {"mostradas": 1, "retenidas": 0, "aceptadas": 1, "personas_con_oferta": 1, "pedidos_despues": 1},
        },
        {
            "variante": "control",
            "personas": 1,
            "con_pedido": 1,
            "verticales_por_persona": 2,
            "ofertas": {"mostradas": 0, "retenidas": 1, "aceptadas": 0, "personas_con_oferta": 1, "pedidos_despues": 2},
        },
    ]

    synthetic = experiments_of(client, "synthetic")
    assert [(v["variante"], v["personas"], v["con_pedido"]) for v in synthetic["modo_app"]["variantes"]] == [
        ("propuesta", 1, 1),
        ("actual", 0, 0),
    ]
    assert [(v["variante"], v["personas"], v["ofertas"]) for v in synthetic["ofertas_control"]["variantes"]] == [
        (
            "tratamiento",
            0,
            {"mostradas": 0, "retenidas": 0, "aceptadas": 0, "personas_con_oferta": 0, "pedidos_despues": 0},
        ),
        (
            "control",
            1,
            {"mostradas": 0, "retenidas": 1, "aceptadas": 0, "personas_con_oferta": 1, "pedidos_despues": 1},
        ),
    ]


def test_offers_asked_for_in_the_search_panel_do_not_count_in_the_offers_experiment(client, db):
    """Lo que la persona pide en el buscador lo ven los dos grupos: ni es una mostrada ni la expone."""
    offers = experiments.OFFERS_CONTROL
    assigned(db, "p-ctl", {offers: "control"})
    assigned(db, "p-tra", {offers: "tratamiento"})
    assigned(db, "p-pide", {offers: "tratamiento"})
    offer_event(db, "p-ctl", "suggestion_shown", "recompra", days=8, surface="agent")
    offer_event(db, "p-ctl", "offer_withheld", "recompra", days=7, surface="home")
    offer_event(db, "p-tra", "offer_eligible", "recompra", days=8, surface="home")
    offer_event(db, "p-tra", "suggestion_shown", "recompra", days=8, surface="home")
    offer_event(db, "p-tra", "suggestion_accepted", "recompra", days=8, surface="agent")
    offer_event(db, "p-pide", "suggestion_shown", "recompra", days=8, surface="agent")

    by_variant = {v["variante"]: v["ofertas"] for v in experiments_of(client, "prototype")[offers]["variantes"]}
    assert by_variant["control"] == {
        "mostradas": 0,
        "retenidas": 1,
        "aceptadas": 0,
        "personas_con_oferta": 1,
        "pedidos_despues": 0,
    }
    assert by_variant["tratamiento"] == {
        "mostradas": 1,
        "retenidas": 0,
        "aceptadas": 0,
        "personas_con_oferta": 1,
        "pedidos_despues": 0,
    }


def test_both_groups_count_exposure_with_the_offer_the_api_recorded(client, db):
    """Las personas con oferta se cuentan con lo que anotó la API en los dos grupos (`offer_eligible` en tratamiento,
    `offer_withheld` en control), no con lo que la app alcanzó a mostrar: una entregada que la app no mostró (la Home
    estaba tapada) expone igual, y una mostrada sin su anotación del servidor no."""
    offers = experiments.OFFERS_CONTROL
    assigned(db, "p-ctl", {offers: "control"})
    assigned(db, "p-entregada", {offers: "tratamiento"})
    assigned(db, "p-solo-app", {offers: "tratamiento"})
    offer_event(db, "p-ctl", "offer_withheld", "carrito", days=7, surface="home")
    offer_event(db, "p-entregada", "offer_eligible", "carrito", days=7, surface="home")
    offer_event(db, "p-solo-app", "suggestion_shown", "carrito", days=7, surface="home")
    ordered(db, "p-entregada", "turbo", days=2)

    by_variant = {v["variante"]: v["ofertas"] for v in experiments_of(client, "prototype")[offers]["variantes"]}
    assert by_variant["tratamiento"] == {
        "mostradas": 1,
        "retenidas": 0,
        "aceptadas": 0,
        "personas_con_oferta": 1,
        "pedidos_despues": 1,
    }
    assert by_variant["control"]["personas_con_oferta"] == 1


def test_an_experiment_without_assignments_lists_its_variants_empty(client, db, monkeypatch):
    nobody = {"personas": 0, "con_pedido": 0, "verticales_por_persona": None}
    none_offered = {"mostradas": 0, "retenidas": 0, "aceptadas": 0, "personas_con_oferta": 0, "pedidos_despues": 0}
    data = experiments_of(client, "prototype")
    assert data["modo_app"]["variantes"] == [{"variante": v, **nobody} for v in ("propuesta", "actual")]
    assert data["ofertas_control"]["variantes"] == [
        {"variante": v, **nobody, "ofertas": none_offered} for v in ("tratamiento", "control")
    ]
    assert data["ofertas_control"]["control_pct"] == 0  # apagado: nadie entra
    monkeypatch.setattr(config, "OFFERS_CONTROL_PCT", 10)
    assert experiments_of(client, "prototype")["ofertas_control"]["control_pct"] == 10


def local_month(months_back: int) -> datetime:
    """El primer instante del mes local de hace `months_back` meses."""
    now = datetime.now(TZ)
    year, month = divmod(now.month - 1 - months_back, 12)
    return datetime(now.year + year, month + 1, 1, tzinfo=TZ)


def assigned_on(db, user_id, variant, at, source="prototype"):
    events.ensure_user(db, user_id, source)
    experiments.assign(db, user_id, experiments.OFFERS_CONTROL, variant)
    db.execute("UPDATE experiment_assignments SET assigned_at = %s WHERE user_id = %s", (at, user_id))


def offer_on(db, user_id, kind, at, source="prototype"):
    event = events.Event(user_id, "s-exp", kind, ts=at, surface="home", origin="agent-carrito")
    events.record(db, [event], source=source)


def ordered_on(db, user_id, vertical, at, source="prototype"):
    line = {"entity_type": "catalog_item", "entity_id": CHIPS, "unit_price": 1990}
    events.record_order(db, user_id, "s-exp", f"c-{uuid.uuid4().hex[:8]}", vertical, [line], source, at)


def test_the_control_group_reads_m1_retention_and_a_new_vertical_within_the_cohort_with_its_next_month(client, db):
    month = local_month(2)  # M: su M+1 (el mes pasado) ya terminó
    at = month + timedelta(days=4, hours=12)
    following = local_month(1)
    # Tratamiento: t1 pedía Restaurantes y suma Supermercado, y pide en M+1; t2 no pedía y prueba Restaurantes (es
    # nueva para ella), sin M+1; t3 no pide.
    assigned_on(db, "t1", "tratamiento", at)
    ordered_on(db, "t1", "restaurantes", at - timedelta(days=3))
    ordered_on(db, "t1", "supermercado", at + timedelta(days=10))
    ordered_on(db, "t1", "restaurantes", following + timedelta(days=3))
    assigned_on(db, "t2", "tratamiento", at)
    ordered_on(db, "t2", "restaurantes", at + timedelta(days=2))
    assigned_on(db, "t3", "tratamiento", at)
    # Control: c1 repite Restaurantes (no es nueva) y pide en M+1 una vertical nueva, pero pasados los 28 días. c2 entró
    # este mes: su M+1 no terminó y no cuenta.
    assigned_on(db, "c1", "control", at)
    ordered_on(db, "c1", "restaurantes", at - timedelta(days=3))
    ordered_on(db, "c1", "restaurantes", at + timedelta(days=5))
    ordered_on(db, "c1", "farmacia", following + timedelta(days=10))
    assigned_on(db, "c2", "control", datetime.now(TZ) - timedelta(minutes=5))
    ordered_on(db, "c2", "turbo", datetime.now(TZ))
    # La parte expuesta, en la misma cohorte y con ofertas entre la asignación y el inicio de M+1, igual en los dos
    # grupos: t1 tuvo una en M (cuenta); t2, recién en M+1 (no cuenta); c1, una antes de su asignación (no cuenta) y
    # otra en M (cuenta). c2 no es de la cohorte y lo simulado no entra.
    offer_on(db, "t1", "offer_eligible", at + timedelta(days=1))
    offer_on(db, "t2", "offer_eligible", following + timedelta(days=1))
    offer_on(db, "c1", "offer_withheld", at - timedelta(days=1))
    offer_on(db, "c1", "offer_withheld", following - timedelta(minutes=1))
    offer_on(db, "c2", "offer_withheld", datetime.now(TZ))
    # Lo simulado no entra en las cifras del prototipo.
    assigned_on(db, "s1", "control", at, source="synthetic")
    ordered_on(db, "s1", "turbo", following + timedelta(days=1), source="synthetic")
    offer_on(db, "s1", "offer_withheld", at + timedelta(days=1), source="synthetic")

    retention = experiments_of(client, "prototype")["ofertas_control"]["retencion"]
    assert retention == {
        "variantes": [
            {
                "variante": "tratamiento",
                "personas": 3,
                "retencion_m1_pct": 33.3,
                "suma_vertical_pct": 66.7,
                "expuestas": 1,
                "expuestas_pct": 33.3,
            },
            {
                "variante": "control",
                "personas": 1,
                "retencion_m1_pct": 100.0,
                "suma_vertical_pct": 0.0,
                "expuestas": 1,
                "expuestas_pct": 100.0,
            },
        ],
        # Bajo el mínimo, sin intervalo: con 1 persona en control (100 % y 0 %), el de Wald se encoge y excluiría el 0.
        "diferencia": {
            "retencion_m1": {"puntos": -66.7, "ic95": None},
            "suma_vertical": {"puntos": 66.7, "ic95": None},
        },
        # +2 puntos sobre el 47 % de "solo Restaurantes", con el reparto de quienes tienen variante (2 de 5 en control);
        # +5, el mínimo de antes, como referencia.
        "minimo": {"tratamiento": 12245, "control": 8163},
        "referencia": {"efecto_puntos": 5, "tratamiento": 1961, "control": 1308},
        "efecto_minimo_puntos": 2,
        "base_pct": 47.0,
        "concluyente": False,
    }


def test_without_a_finished_cohort_the_retention_is_empty_and_not_conclusive(client, db):
    assigned(db, "p-ctl", {experiments.OFFERS_CONTROL: "control"})
    ordered(db, "p-ctl", "turbo", days=1)
    retention = experiments_of(client, "prototype")["ofertas_control"]["retencion"]
    assert retention["variantes"] == [
        {
            "variante": v,
            "personas": 0,
            "retencion_m1_pct": None,
            "suma_vertical_pct": None,
            "expuestas": 0,
            "expuestas_pct": None,
        }
        for v in ("tratamiento", "control")
    ]
    assert retention["diferencia"] is None and retention["minimo"] is None and retention["concluyente"] is False


def test_the_retention_is_conclusive_once_each_group_reaches_the_minimum(client, db, monkeypatch):
    monkeypatch.setattr(queries, "sample_size", lambda base, effect, share: (1, 2))
    at = local_month(2) + timedelta(days=4)
    for user_id, variant in (("t1", "tratamiento"), ("t2", "tratamiento"), ("c1", "control")):
        assigned_on(db, user_id, variant, at)
    ordered_on(db, "t1", "turbo", at + timedelta(days=1))
    ordered_on(db, "t1", "turbo", datetime.now(TZ))  # los datos llegan hasta hoy: M+1 ya terminó
    retention = experiments_of(client, "prototype")["ofertas_control"]["retencion"]
    assert retention["minimo"] == {"tratamiento": 2, "control": 1}
    assert retention["concluyente"] is True
    assert retention["diferencia"]["suma_vertical"] == {"puntos": 50.0, "ic95": [-19.3, 100.0]}  # ya con su intervalo


# ── Panel: las tres hipótesis (H1 retención, H2 frecuencia y Restaurantes → Turbo, H3 la encuesta) ─────────────────
def app_event(db, user_id, kind, days, source="prototype", **fields):
    events.record(db, [events.Event(user_id, "s-hip", kind, ts=days_ago(days), **fields)], source=source)


def answered(db, user_id, answer, days):
    app_event(db, user_id, "survey_answer", days, payload={"question": "p1", "answer": answer, "trigger": "busqueda"})


def seed_two_groups(db):
    """Dos grupos de `ofertas_control` asignados hace 40 días (con sus 28 y 30 días ya cumplidos) y una persona recién
    asignada, que todavía no cuenta en la frecuencia ni en Restaurantes → Turbo."""
    offers = experiments.OFFERS_CONTROL
    for user_id, variant, days in (
        ("t1", "tratamiento", 40),
        ("t2", "tratamiento", 40),
        ("t3", "tratamiento", 5),
        ("c1", "control", 40),
        ("c2", "control", 40),
    ):
        assigned(db, user_id, {offers: variant}, days=days)
    # t1: cliente de Restaurantes que pide Turbo en sus 28 días; 3 pedidos en sus 30; busca con Mochi; responde "Sí".
    ordered(db, "t1", "restaurantes", days=35)
    ordered(db, "t1", "turbo", days=30)
    ordered(db, "t1", "restaurantes", days=20)
    app_event(db, "t1", "ask", 20, surface="agent", payload={"mode": "propuesta"})
    answered(db, "t1", "si", days=10)
    # t2: no pide; silencia a Mochi y después lo oculta; responde "No".
    app_event(db, "t2", "agent_visibility", 20, payload={"visible": True, "quiet": True})
    app_event(db, "t2", "agent_visibility", 15, payload={"visible": False})
    answered(db, "t2", "no", days=10)
    # t3: recién asignada; pide Restaurantes y acepta una oferta de Mochi (usa a Mochi).
    app_event(db, "t3", "suggestion_accepted", 4, surface="cart", origin="agent-carrito")
    ordered(db, "t3", "restaurantes", days=3)
    # c1: cliente de Restaurantes sin Turbo; 2 pedidos; oculta a Mochi y lo trae de vuelta; responde "Sí".
    ordered(db, "c1", "restaurantes", days=35)
    ordered(db, "c1", "restaurantes", days=25)
    app_event(db, "c1", "agent_visibility", 30, payload={"visible": False})
    app_event(db, "c1", "agent_visibility", 20, payload={"visible": True})
    answered(db, "c1", "si", days=10)
    # c2: solo Turbo (no es cliente de Restaurantes); busca en "Rappi hoy" (no es usar a Mochi).
    ordered(db, "c2", "turbo", days=36)
    app_event(db, "c2", "ask", 10, surface="agent", payload={"mode": "actual"})
    # Lo simulado no entra en las cifras del prototipo.
    assigned(db, "s1", {offers: "tratamiento"}, source="synthetic", days=40)
    ordered(db, "s1", "turbo", days=30, source="synthetic")


def test_the_three_hypotheses_are_measured_by_group(client, db):
    seed_two_groups(db)
    control = experiments_of(client, "prototype")["ofertas_control"]

    # H2, frecuencia: pedidos en los 30 días desde la asignación, de quienes ya los cumplieron (t3 no).
    frequency = control["frecuencia"]
    assert [(v["variante"], v["personas_30d"], v["pedidos_30d"]) for v in frequency["variantes"]] == [
        ("tratamiento", 2, 1.5),
        ("control", 2, 1.5),
    ]
    assert frequency["dias"] == 30
    assert frequency["diferencia"]["pedidos_30d"] == {"valor": 0.0, "ic95": None}  # bajo el mínimo, sin intervalo
    # H2, Restaurantes → Turbo: de los clientes de Restaurantes, quién pide Turbo en sus 28 días.
    assert control["rest_a_turbo"] == {
        "variantes": [
            {"variante": "tratamiento", "personas": 1, "con_turbo": 1, "pct": 100.0},
            {"variante": "control", "personas": 1, "con_turbo": 0, "pct": 0.0},
        ],
        # Sin Turbo en control no hay tasa base: ni diferencia relativa ni mínimo.
        "diferencia": {"puntos": 100.0, "relativa_pct": None, "ic95": None},
        "meta_relativa_pct": 10,
        "dias": 28,
        "minimo": None,
        "concluyente": False,
    }
    # H3: el % de "Sí" de la P1 por grupo, sin prueba ni intervalo bajo el mínimo.
    assert control["encuesta"] == {
        "variantes": [
            {"variante": "tratamiento", "respondidas": 2, "si": 1, "si_pct": 50.0},
            {"variante": "control", "respondidas": 1, "si": 1, "si_pct": 100.0},
        ],
        "diferencia": {"puntos": -50.0, "ic95": None, "p_una_cola": None},
        "minimo": 100,
        "concluyente": False,
    }
    # Adopción y apagado: usar a Mochi (buscar con él o aceptar una oferta suya; "Rappi hoy" no), oculto (el último
    # cambio fue ocultarlo) y silenciado alguna vez (no cuenta como oculto).
    assert control["adopcion"] == {
        "variantes": [
            {
                "variante": "tratamiento",
                "personas": 3,
                "usaron": 2,
                "ocultos": 1,
                "silenciaron": 1,
                "usaron_pct": 66.7,
                "ocultos_pct": 33.3,
                "silenciaron_pct": 33.3,
            },
            {
                "variante": "control",
                "personas": 2,
                "usaron": 0,
                "ocultos": 0,
                "silenciaron": 0,
                "usaron_pct": 0.0,
                "ocultos_pct": 0.0,
                "silenciaron_pct": 0.0,
            },
        ]
    }
    # Toda la población (lo que el panel muestra con el control apagado), hasta el último evento (hace 3 días).
    population = control["poblacion"]
    assert population["rest_a_turbo"] == {"personas": 3, "con_turbo": 1, "pct": 33.3, "dias": 28}
    assert population["frecuencia"] == {"personas": 5, "pedidos": 4, "pedidos_por_persona": 0.8, "dias": 30}
    assert population["encuesta"] == {"respondidas": 3, "si": 2, "si_pct": 66.7}
    assert population["adopcion"] == {
        "personas": 5,
        "usaron": 2,
        "usaron_pct": 40.0,
        "ocultos_pct": 20.0,
        "silenciaron_pct": 20.0,
        "dias": 30,
    }
    assert set(population["retencion_m1"]) == {"mes", "mes_siguiente", "personas", "pct"}


def test_the_hypotheses_read_with_their_interval_once_each_group_reaches_its_minimum(client, db, monkeypatch):
    """Con el mínimo alcanzado: la H2 con su diferencia relativa, el intervalo de la frecuencia y el de Restaurantes →
    Turbo; la H3 con su intervalo y la prueba a una cola."""
    seed_two_groups(db)
    ordered(db, "c1", "turbo", days=30)  # el control también pide Turbo: hay tasa base
    assigned(db, "c3", {experiments.OFFERS_CONTROL: "control"}, days=40)
    ordered(db, "c3", "restaurantes", days=30)  # otra clienta de Restaurantes en control, sin Turbo
    monkeypatch.setattr(queries, "sample_size", lambda base, effect, share: (1, 1))
    monkeypatch.setattr(queries, "MIN_SURVEY_ANSWERS", 1)
    control = experiments_of(client, "prototype")["ofertas_control"]

    h2 = control["rest_a_turbo"]
    assert h2["minimo"] == {"tratamiento": 1, "control": 1} and h2["concluyente"] is True
    assert h2["diferencia"] == {"puntos": 50.0, "relativa_pct": 100.0, "ic95": [-19.3, 100.0]}
    assert control["frecuencia"]["diferencia"]["pedidos_30d"]["ic95"] is not None
    h3 = control["encuesta"]
    assert h3["concluyente"] is True
    assert h3["diferencia"]["ic95"] == [-100.0, 19.3] and h3["diferencia"]["p_una_cola"] == 0.807


def test_without_groups_the_hypotheses_keep_their_shape_and_the_population(client, db):
    """Con OFFERS_CONTROL_PCT en 0 nadie tiene variante: cada hipótesis queda vacía por grupo, sin diferencia, y la
    población completa sigue ahí para describir."""
    ordered(db, "u-rest", "restaurantes", days=10)
    ordered(db, "u-rest", "turbo", days=5)
    control = experiments_of(client, "prototype")["ofertas_control"]
    assert control["control_pct"] == 0
    assert control["rest_a_turbo"]["variantes"] == [
        {"variante": v, "personas": 0, "con_turbo": 0, "pct": None} for v in ("tratamiento", "control")
    ]
    assert control["rest_a_turbo"]["diferencia"] is None and control["rest_a_turbo"]["concluyente"] is False
    assert control["frecuencia"] == {
        "variantes": [
            {"variante": v, "personas_30d": 0, "pedidos_30d": None, "personas_m1": 0, "pedidos_m1": None}
            for v in ("tratamiento", "control")
        ],
        "diferencia": None,
        "dias": 30,
    }
    assert control["encuesta"]["diferencia"] is None and control["encuesta"]["concluyente"] is False
    assert [v["personas"] for v in control["adopcion"]["variantes"]] == [0, 0]
    assert control["retencion"]["minimo"] is None and control["retencion"]["referencia"] is None
    assert control["poblacion"]["rest_a_turbo"] == {"personas": 1, "con_turbo": 1, "pct": 100.0, "dias": 28}
    # Una fuente sin ningún evento: todo en cero, nada se cae.
    empty = experiments_of(client, "synthetic")["ofertas_control"]["poblacion"]
    assert empty["frecuencia"]["pedidos_por_persona"] is None and empty["retencion_m1"]["pct"] is None


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


def test_the_amplitude_bridge_keeps_kind_and_visible(client, db):
    """Migración 055: una oferta que se fue sola (kind "expirada") se distingue en el puente de un rechazo, y
    `agent_visibility` dice si ocultó a Mochi o lo trajo de vuelta (el false de jsonb no se pierde) y, desde la 058,
    si lo silenció o volvió a hablar (QUIET). KIND también sale en la mostrada (VIEW_COMPONENT): para contar los
    "Después" no basta con KIND, hay que mirar el event_type."""
    dismissed = {"type": "suggestion_dismissed", "session_id": "s-imp", "concept_id": "snacks-salados"}
    shown = {"type": "suggestion_shown", "session_id": "s-imp", "concept_id": "snacks-salados"}
    response = post(
        client,
        "u-kind",
        {**dismissed, "origin": "agent-home", "client_event_id": str(uuid.uuid4()), "payload": {"kind": "expirada"}},
        {**dismissed, "origin": "agent-home", "client_event_id": str(uuid.uuid4())},
        {**dismissed, "origin": "agent-volver", "client_event_id": str(uuid.uuid4()), "payload": {"kind": "volver"}},
        {"type": "agent_visibility", "session_id": "s-imp", "origin": "cuenta", "payload": {"visible": False}},
        {"type": "agent_visibility", "session_id": "s-imp", "origin": "cuenta", "payload": {"visible": True}},
        {"type": "agent_visibility", "session_id": "s-imp", "payload": {"visible": True, "quiet": True}},
        {"type": "agent_visibility", "session_id": "s-imp", "payload": {"visible": True, "quiet": False}},
        {**shown, "origin": "agent-volver", "client_event_id": str(uuid.uuid4()), "payload": {"kind": "volver"}},
        {**shown, "origin": "para-ti", "client_event_id": str(uuid.uuid4()), "payload": {"kind": "lo_mas_pedido"}},
    )
    assert response.status_code == 200, response.text
    rows = db.execute(
        """SELECT event_type, event_properties FROM capa.v_eventos_amplitude WHERE user_id = 'u-kind'
           ORDER BY event_id"""
    ).fetchall()
    kinds = [props.get("KIND") for name, props in rows if name == "MVP_SUGGESTION_DISMISSED"]
    assert kinds == ["expirada", None, "volver"]  # el rechazo no lleva KIND
    visible = [props.get("VISIBLE") for name, props in rows if name == "MVP_AGENT_VISIBILITY"]
    assert visible == [False, True, True, True]
    # Migración 058: silenciar y volver a hablar se distinguen de traerlo de vuelta (QUIET); ocultar y mostrar, sin él.
    quiet = [props.get("QUIET") for name, props in rows if name == "MVP_AGENT_VISIBILITY"]
    assert quiet == [None, None, True, False]
    assert all("KIND" not in props for name, props in rows if name == "MVP_AGENT_VISIBILITY")
    shown_kinds = [props.get("KIND") for name, props in rows if name == "VIEW_COMPONENT"]
    assert shown_kinds == ["volver", "lo_mas_pedido"]


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
        "offer_eligible",
        "survey_shown",
        "survey_answer",
        "survey_dismissed",
    }
    assert rows["survey_answer"] == ("MVP_SURVEY_ANSWER", False)
    assert rows["offer_eligible"] == ("MVP_OFFER_ELIGIBLE", False)
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


def test_synthetic_reformulations_feed_the_search_abandonment(db, monkeypatch):
    """Una búsqueda que reformula otra viene después de la misma mal escrita en su vertical, sin toque y poco antes: el
    abandono de búsqueda del panel la cuenta como rescatada. Esa primera no tiene concepto ni queda sin resultado."""
    from rappi_ia.analytics import queries

    seed_demo(db)
    monkeypatch.setattr(synth, "REFORMULATE", 1.0)
    generate(db, users=12, weeks=4, seed=11, until=date(2026, 10, 4))
    pairs = db.execute(
        """SELECT count(*) FILTER (WHERE a.vertical = b.vertical AND a.concept_id IS NULL AND NOT a.unmet
                                   AND a.query <> b.query
                                   AND b.ts - a.ts BETWEEN interval '20 seconds' AND interval '90 seconds'),
                  count(*)
           FROM app_events a
           JOIN LATERAL (SELECT * FROM app_events n WHERE n.session_id = a.session_id AND n.user_id = a.user_id
                           AND n.type = 'search' AND n.seq > a.seq ORDER BY n.seq LIMIT 1) b ON true
           WHERE a.source = 'synthetic' AND a.type = 'search' AND a.results BETWEEN 1 AND 3"""
    ).fetchone()
    assert pairs[1] > 0 and pairs[0] == pairs[1]
    abandonment = queries.unmet(db, "synthetic")["abandono"]
    # Se rescata si la búsqueda que la sigue tuvo un toque (quien solo mira, BROWSE_ONLY, no la rescata).
    assert 0 < abandonment["rescatadas"] <= pairs[1] and abandonment["con_clic"] > 0


def test_a_misspelled_search_drops_the_second_letter_of_its_longest_word():
    assert synth._misspelled("sushi") == "sshi"
    assert synth._misspelled("carnes y parrilla") == "carnes y prrilla"
    assert synth._misspelled("té") == "té"
