"""La vertical por probar y las ocasiones de la Home se ordenan por lo que le gusta a la persona
(`offers/personal.py`), sin saltarse las guardias: nada sensible ni que el agente no ofrezca cuenta nunca."""

from datetime import UTC, datetime

import pytest
from psycopg.types.json import Jsonb

from owner_client import OwnerClient
from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.rappi_agent import RappiAgent
from rappi_ia.api import app as api
from rappi_ia.api.services import Services
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents
from rappi_ia.events import store as events

NOW = datetime.now(UTC)


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


def _like(db, user, *concepts, source="prototype"):
    """Un `cart_add` de cada concepto: interés en eso."""
    events.record(
        db,
        [events.Event(user, "s1", "cart_add", ts=NOW, concept_id=c, cart_id=f"c-{user}-{c}") for c in concepts],
        source=source,
    )


def _sensitive_segment(db, user, concept):
    db.execute(
        """INSERT INTO segment_defs (segment_id, name, family, sensitive, rule, rules_version)
           VALUES ('seg-sensible', 'seg-sensible', 'prueba', true, '{}', 'test') ON CONFLICT DO NOTHING"""
    )
    db.execute(
        """INSERT INTO user_segments (user_id, segment_id, score, level, signals, evidence)
           VALUES (%s, 'seg-sensible', 1, 'alto', 3, %s)""",
        (user, Jsonb({"top": [{"kind": "concepto", "id": concept, "score": 1.0}]})),
    )


def _order(db, user, *verticals, mode="propuesta"):
    """Un pedido de la persona en cada vertical: lo que ya probó."""
    line = {"entity_type": "catalog_item", "entity_id": "91001", "unit_price": 1990}
    for vertical in verticals:
        events.record_order(db, user, f"s-{vertical}", f"c-{user}-{vertical}", vertical, [line], mode=mode)


def to_try(client, user_id=None):
    body = {"moment": "vertical_por_probar", "context": {}}
    if user_id:
        body["user_id"] = user_id
    reply = client.post("/agent/offer", json=body)
    assert reply.status_code == 200, reply.text
    return reply.json()


def plans(client, user_id=None):
    reply = client.get("/agent/plans", params={"user_id": user_id} if user_id else None)
    assert reply.status_code == 200, reply.text
    return reply.json()


def test_vertical_to_try_follows_affinity(client, db):
    _like(db, "u1", "chocolates")

    body = to_try(client, "u1")

    assert body["vertical"] == "chocolateria"  # sin historia saldría el súper
    assert body["reason"]["text"] == "Por tu interés en 🍫 chocolates: en chocolaterías hay más."
    assert [(s["kind"], s["id"], s["source"]) for s in body["reason"]["basis"]] == [
        ("concepto", "chocolates", "eventos")
    ]
    assert body["reason"]["basis"][0]["score"] > 0
    assert to_try(client)["vertical"] == "supermercado"


def test_vertical_to_try_without_history_keeps_the_default_order(client, db):
    _like(db, "u1", "chocolates", source="synthetic")  # simulado: no cuenta

    for user in (None, "nadie", "u1"):
        body = to_try(client, user)
        assert body["vertical"] == "supermercado"
        assert body["reason"]["text"] == "Porque aún no pides en el súper."
        assert body["reason"]["basis"] == [{"kind": "sin_pedidos", "id": "supermercado", "source": "contexto"}]


def test_vertical_to_try_skips_verticals_with_orders_even_with_affinity(client, db):
    _like(db, "u1", "chocolates")
    _order(db, "u1", "chocolateria", "restaurantes", "turbo")  # la combinación completa: la vertical de siempre

    body = to_try(client, "u1")

    assert body["vertical"] == "supermercado"
    assert body["reason"]["text"].startswith("Porque aún no pides en")


def test_vertical_to_try_never_offers_farmacia_or_licores_even_with_affinity(client, db):
    _like(db, "u1", "medicamentos", "cerveza", "vino", "pisco", "panales", "vitaminas")  # lo que el agente no ofrece
    _like(db, "u2", "vino", "pisco", "chocolates")

    assert to_try(client, "u1") == to_try(client)  # lo que no ofrece no cambia nada
    assert to_try(client, "u2")["vertical"] == "chocolateria"  # y el chocolate sí
    for user in ("u1", "u2"):
        for tried in ((), ("supermercado",), ("conveniencia", "turbo", "chocolateria")):
            _order(db, user, *tried)
            body = to_try(client, user)
            assert body["vertical"] not in ("farmacia", "licores")
            assert body["moment"] == "vertical_por_probar"


def test_vertical_to_try_basis_has_the_three_concepts_that_contribute_most(client, db):
    # De la chocolatería (su vertical típica): chocolates 6, galletas, helados y pastelería 3.
    # Golosinas es de Express (con pedido) y no cuenta. La base lleva solo tres: los de más puntaje y, en empate,
    # por id.
    _like(db, "u1", "chocolates", "helados", "golosinas", "galletas", "pasteleria")
    _like(db, "u1", "chocolates")  # otra vez: chocolate pesa más

    # Solo le falta la chocolatería: es el paso del motor, sin datos de la población (sus ofertas de siempre).
    _order(db, "u1", "supermercado", "conveniencia", "mall", "turbo", "restaurantes")

    body = to_try(client, "u1")

    assert body["vertical"] == "chocolateria"
    assert body["reason"]["text"] == "Por tu interés en 🍫 chocolates: en chocolaterías hay más."
    step, *likes = body["reason"]["basis"]
    assert step["kind"] == "combinacion" and step["id"].endswith(
        "→restaurantes+turbo+supermercado+conveniencia+mall+chocolateria"
    )
    assert [s["id"] for s in likes] == ["chocolates", "galletas", "helados"]
    # NOW se toma al importar el módulo: con unos minutos de tests encima el decaimiento resta milésimas
    assert [s["score"] for s in likes] == pytest.approx([6.0, 3.0, 3.0], abs=0.05)


def test_vertical_to_try_reason_names_the_concept_of_the_offered_vertical_not_the_global_top(client, db):
    # Lo que más le gusta (chocolate) es de la chocolatería, donde ya pidió: el paso del motor es el súper (le falta
    # Retail), y el porqué nombra lo que le gusta del súper (pastas, y después café), no el chocolate.
    _like(db, "u1", "chocolates")
    _like(db, "u1", "chocolates", "pastas")
    events.record(
        db, [events.Event("u1", "s1", "search", ts=NOW, concept_id="cafe", query="cafe")], source="prototype"
    )  # café pesa menos que pastas

    _order(db, "u1", "chocolateria", "restaurantes", "turbo")

    body = to_try(client, "u1")

    pastas = load_taxonomy().concepts["pastas"]
    assert body["vertical"] == "supermercado"
    assert body["reason"]["text"] == f"Por tu interés en {pastas.emoji} {pastas.name.lower()}: en el súper hay más."
    assert [s["id"] for s in body["reason"]["basis"]] == [
        "restaurantes+turbo+chocolateria→restaurantes+turbo+supermercado+chocolateria",
        "pastas",
        "cafe",
    ]


def test_plans_order_by_interest(client, db):
    _like(db, "u1", "carnes", "carbon")

    ids = [p["id"] for p in plans(client, "u1")]
    asado = next(p for p in plans(client, "u1") if p["id"] == "asado")

    assert ids[0] == "asado"
    assert asado["reason"]["text"].startswith("Por tu interés en ")
    assert {s["id"] for s in asado["reason"]["basis"]} == {"carnes", "carbon"}
    assert all(s["source"] == "eventos" for s in asado["reason"]["basis"])


def test_plans_with_interest_put_scored_occasions_first_and_the_rest_in_default_order(client, db):
    default = [p["id"] for p in plans(client)]
    _like(db, "u1", "chocolates")

    shown = plans(client, "u1")

    scored = [p for p in shown if "reason" in p]
    assert scored and [p["id"] for p in shown[: len(scored)]] == [p["id"] for p in scored]
    assert all(p["reason"]["text"] == "Por tu interés en 🍫 chocolates." for p in scored)
    assert [p["id"] for p in shown if "reason" not in p] == [i for i in default if i not in {p["id"] for p in scored}]
    assert sorted(p["id"] for p in shown) == sorted(default)
    # ocasiones con chocolate: empatan y mandan HOME_OCCASIONS y la taxonomía
    assert [p["id"] for p in scored][:1] == ["regalo"]


def test_plans_without_user_keep_the_default_order(client, db):
    _like(db, "u1", "chocolates", source="synthetic")
    default = plans(client)

    assert [p["id"] for p in default[:5]] == ["once", "carrete", "asado", "panorama", "regalo"]
    assert all("reason" not in p for p in default)
    assert plans(client, "nadie") == default
    assert plans(client, "u1") == default  # simulado: no cuenta


def test_plans_rejects_a_long_user_id(client):
    assert client.get("/agent/plans", params={"user_id": "x" * 65}).status_code == 422


def test_only_sensitive_or_non_offerable_history_changes_nothing(client, db):
    _like(db, "u1", "cerveza", "vino", "pisco", "medicamentos", "panales", "vitaminas")
    _sensitive_segment(db, "u1", "chocolates")
    db.execute("INSERT INTO app_users (user_id, source) VALUES ('base', 'prototype') ON CONFLICT DO NOTHING")

    assert to_try(client, "u1") == to_try(client, "base") == to_try(client)
    for tried in (("supermercado",), ("conveniencia", "turbo")):
        _order(db, "u1", *tried)
        _order(db, "base", *tried)
        assert to_try(client, "u1") == to_try(client, "base")
    assert plans(client, "u1") == plans(client, "base") == plans(client)
