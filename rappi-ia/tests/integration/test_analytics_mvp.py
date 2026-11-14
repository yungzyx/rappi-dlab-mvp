"""Métricas del uso del MVP en el panel: ofertas por momento y búsquedas sin resultado."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from rappi_ia.analytics import queries
from rappi_ia.api import app as api
from rappi_ia.concepts.store import seed_taxonomy
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.events import store as events

NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
NO_ABANDONMENT = {
    "busquedas": 0,
    "con_clic": 0,
    "rescatadas": 0,
    "abandonadas": 0,
    "abandono_pct": None,
    "plazo_minutos": 2,
}
EMPTY = {
    "offers": {"personas": 0, "momentos": [], "autopedidos": {"pedidos": 0, "personas": 0}},
    "unmet": {"personas": 0, "busquedas": 0, "sin_resultado": 0, "por_vertical": [], "abandono": NO_ABANDONMENT},
}


def _offer(user, origen=None, kind="suggestion_shown"):
    payload = {} if origen is None else {"origen": origen}
    return events.Event(user, "s1", kind, ts=NOW, concept_id="cerveza", vertical="licores", payload=payload)


def _search(user, unmet, concept=None, vertical="restaurantes", query="algo", kind="search"):
    return events.Event(user, "s1", kind, ts=NOW, vertical=vertical, concept_id=concept, query=query, unmet=unmet)


def _searched(user, request, seconds=0, session="s1", concept="pizza", vertical="restaurantes"):
    """Una búsqueda de la app: lleva el request_id de su respuesta de /search."""
    ts = NOW + timedelta(seconds=seconds)
    return events.Event(
        user,
        session,
        "search",
        ts=ts,
        vertical=vertical,
        concept_id=concept,
        query="algo",
        unmet=False,
        surface="search",
        request_id=request,
    )


def _tapped(user, request, seconds=0, session="s1", kind="view_item"):
    """Un toque en un resultado de esa búsqueda (mismo request_id)."""
    ts = NOW + timedelta(seconds=seconds)
    return events.Event(
        user,
        session,
        kind,
        ts=ts,
        vertical="restaurantes",
        entity_type="menu_item",
        entity_id="m1",
        surface="search",
        origin="resultados",
        position=1,
        request_id=request,
    )


def _moments(data):
    return [(m["momento"], m["mostradas"], m["aceptadas"], m["aceptacion_pct"]) for m in data["momentos"]]


@pytest.fixture
def concepts(db):
    seed_taxonomy(db, load_taxonomy())
    return db


def test_offers_group_old_and_new_origins_by_moment(concepts):
    db = concepts
    events.record(
        db,
        [
            _offer("u1", "mochi-plan"),  # nombre viejo del mismo momento
            _offer("u1", "agent-plan"),
            _offer("u1", "agent-plan", "suggestion_accepted"),
            _offer("u2", "agent-carrito"),
            _offer("u2", "agent-proximo_pedido"),
            _offer("u2", "chat"),  # la pregunta al agente, con su nombre viejo
            _offer("u2", "agent-ask"),
            _offer("u2", "para-ti"),
            _offer("u2", "para-ti-local"),  # nombres viejos de "Para ti"
            _offer("u2", "vertical-para-ti"),
            # Los servicios tienen su propia vista y el aviso no es una oferta: no entran, ni su persona.
            _offer("u3", "rappitravel"),
            _offer("u3", "rappifavor"),
            _offer("u3", "aviso"),
            _offer("u2", "agent-plan", "suggestion_dismissed"),  # ignorar no es mostrar ni aceptar
        ],
    )

    data = queries.offers(db, "prototype")

    assert data["personas"] == 2
    assert _moments(data) == [
        ("plan", 2, 1, None),
        ("carrito", 1, 0, None),
        ("proximo_pedido", 1, 0, None),
        ("pregunta", 2, 0, None),
        ("para_ti", 3, 0, None),
    ]


def test_offers_of_the_taste_profile_have_their_own_moment(concepts):
    """El momento `perfil` (perfiles de gusto) tiene su fila: sus ofertas no se pierden en "sin momento"."""
    db = concepts
    events.record(
        db,
        [
            _offer("u1", "agent-perfil"),
            _offer("u1", "agent-perfil", "suggestion_accepted"),
            _offer("u2", "mochi-perfil"),  # el nombre viejo de los momentos también vale
            _offer("u2", "agent-vertical_por_probar"),
            _offer("u2", "agent-ask"),
        ],
    )

    data = queries.offers(db, "prototype")

    assert "perfil" in queries.OFFER_MOMENTS
    assert _moments(data) == [
        ("vertical_por_probar", 1, 0, None),
        ("perfil", 2, 1, None),
        ("pregunta", 1, 0, None),
    ]


def test_offers_unknown_origin_is_sin_momento(concepts):
    db = concepts
    events.record(db, [_offer("u1"), _offer("u1", "agent-nuevo"), _offer("u1", "otra-cosa"), _offer("u1", "")])

    data = queries.offers(db, "prototype")

    assert data == {
        "personas": 1,
        "momentos": [
            {
                "momento": "sin_momento",
                "mostradas": 4,
                "aceptadas": 0,
                "rechazadas": 0,
                "abiertas": 0,
                "por_que_abiertos": 0,
                "aceptacion_pct": None,
            }
        ],
        "autopedidos": {"pedidos": 0, "personas": 0},  # los que Mochi pidió solo van aparte
    }


def test_offers_count_rejections_and_opened_whys_by_moment(concepts):
    """ "Ahora no" o "Después" (`suggestion_dismissed`) y el "¿Por qué?" abierto (`offer_why_open`) se cuentan en el
    momento de su origen, aparte de las mostradas y aceptadas: la tasa sigue siendo de aceptación."""
    db = concepts
    events.record(
        db,
        [
            _offer("u1", "agent-carrito"),
            _offer("u1", "agent-carrito", "suggestion_dismissed"),
            _offer("u1", "agent-carrito", "offer_why_open"),
            _offer("u1", "agent-carrito", "offer_why_open"),
            _offer("u1", "agent-recompra"),
            _offer("u1", "agent-recompra", "suggestion_dismissed"),
            _offer("u2", "agent-vertical_por_probar"),
            _offer("u2", "agent-vertical_por_probar", "suggestion_accepted"),
            _offer("u2", "agent-vertical_por_probar", "offer_why_open"),
            _offer("u3", "aviso", "suggestion_dismissed"),  # el aviso sobre el carro no es una oferta
        ],
    )

    data = queries.offers(db, "prototype")

    assert data["personas"] == 2
    assert [
        (m["momento"], m["mostradas"], m["aceptadas"], m["rechazadas"], m["por_que_abiertos"]) for m in data["momentos"]
    ] == [
        ("carrito", 1, 0, 1, 2),
        ("vertical_por_probar", 1, 1, 0, 1),
        ("recompra", 1, 0, 1, 0),
    ]


def test_offers_count_verticals_opened_from_the_offer_apart_from_acceptance(concepts):
    """La vertical abierta desde una oferta ("Ver …", "Abrir …": `vertical_open` con el origen `agent-<momento>`) se
    cuenta en `abiertas`, no como aceptada; los toques a los accesos de la Home y otros orígenes no entran."""
    db = concepts

    def opened(user, origin, surface="home"):
        return events.Event(
            user, "s1", "vertical_open", ts=NOW, vertical="supermercado", surface=surface, origin=origin
        )

    events.record(
        db,
        [
            _offer("u1", "agent-vertical_por_probar"),
            opened("u1", "agent-vertical_por_probar"),
            opened("u1", "agent-vertical_por_probar"),
            _offer("u1", "agent-carrito"),
            opened("u1", "agent-carrito"),
            opened("u2", "accesos"),  # un acceso de la Home no es una oferta, ni su persona
            opened("u2", "agent-nuevo"),  # un origen de Mochi que no es un momento tampoco
            opened("u2", "tambien-en", surface="agent"),
        ],
    )

    data = queries.offers(db, "prototype")

    assert data["personas"] == 1
    assert [(m["momento"], m["mostradas"], m["aceptadas"], m["abiertas"]) for m in data["momentos"]] == [
        ("carrito", 1, 0, 1),
        ("vertical_por_probar", 1, 0, 2),
    ]


def test_offers_that_went_away_by_themselves_are_not_rejections(concepts):
    """La oferta que se fue sola del globo (`suggestion_dismissed` con `payload.kind` "expirada") no es un "Ahora no"
    ni un "Después": no cuenta en las rechazadas ni en las ignoradas de las sugerencias."""
    db = concepts
    expired = {"origen": "agent-carrito", "kind": events.EXPIRED_KIND}
    events.record(
        db,
        [
            _offer("u1", "agent-carrito"),
            events.Event(
                "u1", "s1", "suggestion_dismissed", ts=NOW, concept_id="cerveza", vertical="licores", payload=expired
            ),
            _offer("u2", "agent-carrito"),
            _offer("u2", "agent-carrito", "suggestion_dismissed"),
        ],
    )

    [carrito] = queries.offers(db, "prototype")["momentos"]
    assert (carrito["mostradas"], carrito["rechazadas"]) == (2, 1)
    [row] = queries.suggestions(db, "prototype")
    assert (row["mostradas"], row["ignoradas"]) == (2, 1)


def test_offers_rate_only_from_ten_shown(concepts):
    db = concepts
    # Una persona y dos eventos: se muestran las cuentas, no una tasa de 100 %.
    events.record(db, [_offer("u1", "agent-plan"), _offer("u1", "agent-plan", "suggestion_accepted")])
    assert _moments(queries.offers(db, "prototype")) == [("plan", 1, 1, None)]

    events.record(db, [_offer("u1", "agent-carrito") for _ in range(9)])
    events.record(db, [_offer("u1", "agent-carrito", "suggestion_accepted") for _ in range(3)])
    assert _moments(queries.offers(db, "prototype"))[1] == ("carrito", 9, 3, None)

    events.record(db, [_offer("u1", "agent-carrito")])
    assert queries.MIN_SUGGESTIONS_SHOWN == 10
    assert _moments(queries.offers(db, "prototype"))[1] == ("carrito", 10, 3, 30.0)


def test_unmet_totals_ignore_sensitive_concepts_too(concepts):
    db = concepts
    sensitive = next(c.id for c in load_taxonomy().concepts.values() if c.sensitive)
    events.record(db, [_search("u1", True, "pizza"), _search("u2", False, "cerveza", vertical="licores")])
    before = queries.unmet(db, "prototype")

    events.record(
        db,
        [
            _search("u3", True, sensitive, vertical="farmacia", query="remedio privado"),
            _search("u3", False, sensitive, vertical="farmacia", query="otro remedio", kind="chat"),
        ],
    )

    assert queries.unmet(db, "prototype") == before
    assert (before["personas"], before["busquedas"], before["sin_resultado"]) == (2, 2, 1)


def test_unmet_never_returns_query_text_or_sensitive_concepts(concepts):
    db = concepts
    sensitive = next(c.id for c in load_taxonomy().concepts.values() if c.sensitive)
    events.record(
        db,
        [
            _search("u1", True, "pizza", query="pizza de juan pérez"),
            _search("u2", True, "pizza", query="pizza hawaiana", kind="ask"),
            _search("u2", True, None, query="kebab secreto"),
            _search("u3", True, sensitive, vertical="farmacia", query="remedio privado", kind="chat"),
            _search("u3", False, "cerveza", vertical="licores", query="cerveza"),
            _search("u4", None, "pizza", query="pizza local"),  # la búsqueda local no sabe si hay: no cuenta
        ],
    )

    data = queries.unmet(db, "prototype")

    assert data == {
        "personas": 3,  # la búsqueda sensible no cuenta en ninguna cifra, ni en los totales
        "busquedas": 4,
        "sin_resultado": 3,
        "por_vertical": [
            {"vertical": "restaurantes", "concepto": "🍕 Pizza", "sin_resultado": 2},
            {"vertical": "restaurantes", "concepto": None, "sin_resultado": 1},
        ],
        "abandono": NO_ABANDONMENT,  # ninguna trae request_id: no se sabe qué se tocó desde ellas
    }
    text = json.dumps(data, ensure_ascii=False)
    for secret in ("juan", "hawaiana", "kebab", "remedio", "farmacia", sensitive):
        assert secret not in text


def test_unmet_shows_at_most_twenty_rows(concepts):
    db = concepts
    ids = [c.id for c in load_taxonomy().concepts.values() if not c.sensitive][:25]
    events.record(db, [_search("u1", True, concept) for concept in ids])

    data = queries.unmet(db, "prototype")

    assert data["sin_resultado"] == 25
    assert len(data["por_vertical"]) == 20


def test_search_abandonment_counts_taps_rescues_and_abandoned_searches(concepts):
    db = concepts
    sensitive = next(c.id for c in load_taxonomy().concepts.values() if c.sensitive)
    events.record(
        db,
        [
            _searched("u1", "r1"),  # con toque
            _tapped("u1", "r1", seconds=20),
            _searched("u1", "r2", seconds=60),  # sin toque, pero la reformula y toca al minuto: rescatada
            _searched("u1", "r3", seconds=120),
            _tapped("u1", "r3", seconds=130, kind="cart_add"),
            _searched("u2", "r4"),  # sin toque y la siguiente con toque llega a los 3 minutos: abandonada
            _searched("u2", "r5", seconds=180),
            _tapped("u2", "r5", seconds=190, kind="recommendation_click"),
            _searched("u3", "r6"),  # el toque con su request_id es de otra sesión: no cuenta
            _tapped("u3", "r6", seconds=10, session="s2"),
            _searched("u3", "r7", seconds=30),  # sin toque y sin otra búsqueda después: abandonada
            # No cuentan: una búsqueda sin request_id (no se sabe qué se tocó desde ella) ni una de concepto sensible.
            _search("u4", False, "pizza"),
            _searched("u4", "r8", concept=sensitive, vertical="farmacia"),
        ],
    )

    data = queries.unmet(db, "prototype")["abandono"]

    assert data == {
        "busquedas": 7,
        "con_clic": 3,
        "rescatadas": 1,
        "abandonadas": 3,
        "abandono_pct": None,  # menos de 10 búsquedas
        "plazo_minutos": 2,
    }

    events.record(db, [_searched("u5", f"q{n}", seconds=n * 600) for n in range(3)])
    assert queries.MIN_SEARCHES_FOR_RATE == 10
    assert queries.unmet(db, "prototype")["abandono"]["abandono_pct"] == 60.0  # 6 de 10


def test_every_new_metric_never_mixes_sources(concepts):
    db = concepts
    simulated = [
        _offer("s1", "agent-plan"),
        _offer("s1", "agent-plan", "suggestion_accepted"),
        _offer("s1"),
        _search("s1", True, "pizza"),
    ]
    events.record(db, simulated, source="synthetic")
    for name in EMPTY:
        assert getattr(queries, name)(db, "prototype") == EMPTY[name], name

    events.record(db, [_offer("p1", "agent-carrito"), _search("p1", False)])
    assert _moments(queries.offers(db, "prototype")) == [("carrito", 1, 0, None)]
    assert _moments(queries.offers(db, "synthetic")) == [("plan", 1, 1, None), ("sin_momento", 1, 0, None)]
    assert queries.unmet(db, "prototype") == {
        "personas": 1,
        "busquedas": 1,
        "sin_resultado": 0,
        "por_vertical": [],
        "abandono": NO_ABANDONMENT,
    }
    assert queries.unmet(db, "synthetic")["sin_resultado"] == 1
    with pytest.raises(ValueError):
        queries.offers(db, "real")


def test_unknown_metric_is_404(db):
    def conn_override():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    try:
        client = TestClient(api.app)
        assert client.get("/analytics/nada", params={"source": "prototype"}).status_code == 404
        for name in EMPTY:
            for source in ("prototype", "synthetic"):
                reply = client.get(f"/analytics/{name}", params={"source": source})
                assert reply.status_code == 200, name
                assert reply.json() == {"source": source, "data": EMPTY[name]}
            assert client.get(f"/analytics/{name}", params={"source": "real"}).status_code == 422
    finally:
        api.app.dependency_overrides.clear()


def _visibility(user, visible, days_ago):
    return events.Event(
        user, "s1", "agent_visibility", ts=NOW - timedelta(days=days_ago), origin="cuenta", payload={"visible": visible}
    )


def _reorder_shown(user):
    return events.Event(
        user,
        "s1",
        "vertical_reorder_shown",
        ts=NOW,
        vertical="mall",
        position=0,
        origin="agent-reorden",
        payload={"antes": 2},
    )


def test_presence_counts_who_has_the_agent_hidden_now_and_the_home_explanations(db):
    events.record(
        db,
        [
            _visibility("u1", False, 2),
            _visibility("u1", True, 1),  # lo trajo de vuelta: no está oculto
            _visibility("u2", False, 1),
            _visibility("u3", False, 3),
            _visibility("u3", True, 2),
            _visibility("u3", False, 1),  # lo volvió a ocultar: cuenta su último cambio
            events.Event("u4", "s1", "app_open", ts=NOW),  # activa, nunca lo ocultó
            _visibility("u5", False, 60),  # sin actividad en los últimos 30 días: no entra en nada
            _reorder_shown("u1"),
            _reorder_shown("u1"),
            _reorder_shown("u4"),
        ],
    )
    events.record(db, [_visibility("s1", False, 0), _reorder_shown("s1")], source="synthetic")

    assert queries.presence(db, "prototype") == {
        "personas_activas": 4,
        "ocultos": 2,
        "ocultos_pct": 50.0,
        "ocultadas": 4,
        "volvieron": 2,
        "silenciadas": 0,
        "silenciaron": 0,
        "silenciaron_pct": 0.0,
        "explicaciones": 3,
        "explicaciones_personas": 2,
    }
    assert queries.presence(db, "synthetic") == {
        "personas_activas": 1,
        "ocultos": 1,
        "ocultos_pct": 100.0,
        "ocultadas": 1,
        "volvieron": 0,
        "silenciadas": 0,
        "silenciaron": 0,
        "silenciaron_pct": 0.0,
        "explicaciones": 1,
        "explicaciones_personas": 1,
    }


def _quiet(user, quiet, days_ago):
    """ "Silenciar por hoy" (`quiet: true`) o "Volver a hablar" (`quiet: false`): Mochi sigue a la vista."""
    return events.Event(
        user,
        "s1",
        "agent_visibility",
        ts=NOW - timedelta(days=days_ago),
        origin="menu-mochi",
        payload={"visible": True, "quiet": quiet},
    )


def test_presence_counts_silences_apart_from_hiding(db):
    events.record(
        db,
        [
            _quiet("u1", True, 3),
            _quiet("u1", False, 2),  # lo despertó: no es "lo trajo de vuelta"
            _quiet("u1", True, 1),
            _quiet("u2", True, 1),  # solo lo silenció: no está oculto
            _visibility("u3", False, 2),
            _quiet("u3", True, 1),  # un silencio después de ocultarlo no lo deja a la vista
            events.Event("u4", "s1", "app_open", ts=NOW),
            _quiet("u5", True, 60),  # fuera de los 30 días: no cuenta
            events.Event("u5", "s1", "app_open", ts=NOW),
        ],
    )

    assert queries.presence(db, "prototype") == {
        "personas_activas": 5,
        "ocultos": 1,
        "ocultos_pct": 20.0,
        "ocultadas": 1,
        "volvieron": 0,
        "silenciadas": 4,
        "silenciaron": 3,
        "silenciaron_pct": 60.0,
        "explicaciones": 0,
        "explicaciones_personas": 0,
    }


def test_presence_without_events_is_all_zero_and_no_rate(db):
    def conn_override():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    try:
        reply = TestClient(api.app).get("/analytics/presencia", params={"source": "prototype"})
    finally:
        api.app.dependency_overrides.clear()

    assert reply.status_code == 200
    assert reply.json() == {
        "source": "prototype",
        "data": {
            "personas_activas": 0,
            "ocultos": 0,
            "ocultos_pct": None,
            "ocultadas": 0,
            "volvieron": 0,
            "silenciadas": 0,
            "silenciaron": 0,
            "silenciaron_pct": None,
            "explicaciones": 0,
            "explicaciones_personas": 0,
        },
    }
