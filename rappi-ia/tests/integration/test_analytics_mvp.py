"""Métricas del uso del MVP en el panel: ofertas por momento y búsquedas sin resultado."""

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from rappi_ia.analytics import queries
from rappi_ia.api import app as api
from rappi_ia.concepts.store import seed_taxonomy
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.events import store as events

NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
EMPTY = {
    "offers": {"personas": 0, "momentos": []},
    "unmet": {"personas": 0, "busquedas": 0, "sin_resultado": 0, "por_vertical": []},
}


def _offer(user, origen=None, kind="suggestion_shown"):
    payload = {} if origen is None else {"origen": origen}
    return events.Event(user, "s1", kind, ts=NOW, concept_id="cerveza", vertical="licores", payload=payload)


def _search(user, unmet, concept=None, vertical="restaurantes", query="algo", kind="search"):
    return events.Event(user, "s1", kind, ts=NOW, vertical=vertical, concept_id=concept, query=query, unmet=unmet)


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
            _offer("u2", "para-ti-local"),  # nombres viejos de «Para ti»
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
    """El momento `perfil` (perfiles de gusto) tiene su fila: sus ofertas no se pierden en «sin momento»."""
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
        "momentos": [{"momento": "sin_momento", "mostradas": 4, "aceptadas": 0, "aceptacion_pct": None}],
    }


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
    assert queries.unmet(db, "prototype") == {"personas": 1, "busquedas": 1, "sin_resultado": 0, "por_vertical": []}
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
