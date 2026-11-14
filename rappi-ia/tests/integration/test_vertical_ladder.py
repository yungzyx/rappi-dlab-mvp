"""La escalera de verticales (el momento `escalera` de `POST /agent/offer`): la de quien todavía no tiene un perfil de
gusto. Un peldaño por vertical en el orden de los pasos del motor (sin pedidos: Restaurantes, Turbo y después Retail),
con productos reales de cada una, sin suponer un gusto, con las guardias de siempre y retenida al grupo de control
("Mochi apagado"). Sobre el catálogo de prueba (`seed_demo`)."""

from datetime import UTC, datetime, timedelta

import pytest

from owner_client import OwnerClient
from rappi_ia import config
from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.rappi_agent import RappiAgent
from rappi_ia.api import app as api
from rappi_ia.api.services import Services
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents
from rappi_ia.events import experiments
from rappi_ia.events import store as events
from rappi_ia.motor.combos import NONE_COMBO
from rappi_ia.motor.predict import ladder_steps
from rappi_ia.offers.guards import OFFER_BLOCKED_VERTICALS, alcohol_in_name, is_offerable

NOW = datetime.now(UTC)
SUSHI_ROLL = "98005"  # un plato de sushi del restaurante de prueba
RETAIL = {"supermercado", "conveniencia", "mall", "chocolateria"}
# Lo que un texto de la escalera no puede decir: supondría un gusto que la persona no tiene.
TASTE_WORDS = ("por tu gusto", "te gusta", "tu perfil", "por tu interés")


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


def ladder(client, user_id=None, status=200, **extra):
    body = {"moment": "escalera", "context": {}, **({"user_id": user_id} if user_id else {}), **extra}
    reply = client.post("/agent/offer", json=body)
    assert reply.status_code == status, reply.text
    return reply.json() if status == 200 else reply


def order(db, user, vertical, concept=None, entity=("catalog_item", "91001"), days_ago=0):
    line = {"entity_type": entity[0], "entity_id": entity[1], "concept_id": concept, "unit_price": 1990}
    events.record_order(
        db, user, f"s-{vertical}", f"c-{user}-{vertical}", vertical, [line], ts=NOW - timedelta(days=days_ago)
    )


def newcomer(db, user="nuevo"):
    db.execute("INSERT INTO app_users (user_id, source) VALUES (%s, 'prototype')", (user,))
    return user


def test_the_steps_of_a_newcomer_go_restaurants_turbo_and_then_retail(client, db):
    steps = ladder_steps(db, newcomer(db))

    verticals = [s.vertical for s in steps]
    assert verticals[:2] == ["restaurantes", "turbo"]
    assert set(verticals[2:]) == RETAIL  # una vez cada una, sin Farmacia ni Licores
    assert steps[0].current == NONE_COMBO and steps[0].target == "restaurantes"
    for before, after in zip(steps, steps[1:], strict=False):  # cada paso sube desde lo que dejó el anterior
        assert after.current == before.target
    assert [s.used_assumption for s in steps[:3]] == [False, False, False]  # la tabla de Rappi, grupo por grupo
    assert all(s.used_assumption for s in steps[3:])  # dentro de Retail: el rendimiento decreciente, supuesto propio


def test_a_newcomer_sees_one_step_per_vertical_with_real_products_and_an_honest_why(client, db):
    body = ladder(client, newcomer(db))

    assert body["moment"] == "escalera"
    assert body["perfil"] is None and body["viaje"] is None
    verticals = [s["vertical"] for s in body["escalera"]]
    assert verticals[:2] == ["restaurantes", "turbo"]
    assert set(verticals[2:]) <= RETAIL and len(verticals) == len(set(verticals)) >= 3
    for step in body["escalera"]:
        assert 1 <= len(step["products"]) <= 3
        assert all(p["vertical"] == step["vertical"] for p in step["products"])
        assert step["texto"] in ("Lo más pedido aquí", "Ofertas para empezar", "Platos populares para empezar")
    names = [p["name"].lower() for s in body["escalera"] for p in s["products"]]
    assert len(names) == len(set(names))  # un nombre no se repite entre peldaños
    assert [a["route"] for a in body["actions"]] == [[s["prototype_vertical"]] for s in body["escalera"]]

    why = body["reason"]["text"]
    assert why.startswith("Todavía no conozco tus gustos, así que esto sigue la escalera de verticales: parte en ")
    assert "tabla de combinaciones de Rappi" in why and "correlación" in why
    assert "supuesto propio" in why  # el orden dentro de Retail
    assert "retención" not in why and "%" not in why  # sin cifras
    said = (body["text"] + why + " ".join(s["texto"] for s in body["escalera"])).lower()
    assert not any(word in said for word in TASTE_WORDS)
    kinds = [b["kind"] for b in body["reason"]["basis"]]
    assert kinds.count("combinacion") == len(body["escalera"])
    assert body["reason"]["basis"][0]["id"] == "ninguna→restaurantes"
    assert {b["source"] for b in body["reason"]["basis"] if b["kind"] == "combinacion"} <= {"rappi", "rappi+supuesto"}
    assert set(kinds) <= {"combinacion", "lo_mas_pedido", "ofertas", "populares"}


def test_without_a_person_it_is_the_newcomers_ladder(client, db):
    assert [s["vertical"] for s in ladder(client)["escalera"]][:2] == ["restaurantes", "turbo"]


def test_it_starts_after_what_the_person_already_uses(client, db):
    order(db, "u-sushi", "restaurantes", "sushi", entity=("menu_item", SUSHI_ROLL))

    body = ladder(client, "u-sushi")

    verticals = [s["vertical"] for s in body["escalera"]]
    assert verticals[0] == "turbo" and "restaurantes" not in verticals
    assert body["reason"]["text"].startswith("Ya pides en restaurantes, así que esto sigue la escalera de verticales")
    assert body["reason"]["basis"][0] == {
        "kind": "combinacion",
        "id": "restaurantes→restaurantes+turbo",
        "source": "rappi",
    }


def test_with_every_offerable_vertical_there_is_no_ladder(client, db):
    for vertical in ("restaurantes", "turbo", "supermercado", "conveniencia", "mall", "chocolateria"):
        order(db, "u1", vertical)

    ladder(client, "u1", status=204)


@pytest.mark.parametrize("own_only", ["farmacia", "licores"])
def test_pharmacy_and_liquor_are_never_a_step_nor_named(client, db, own_only):
    order(db, "u1", own_only)  # aunque la persona pida ahí

    body = ladder(client, "u1")

    assert not {s["vertical"] for s in body["escalera"]} & set(OFFER_BLOCKED_VERTICALS)
    said = body["reason"]["text"] + str(body["reason"]["basis"])
    assert own_only not in said.lower()


def test_every_product_passes_the_offer_guards(client, db):
    concepts = load_taxonomy().concepts
    body = ladder(client, newcomer(db))

    for step in body["escalera"]:
        for p in step["products"]:
            assert not p["age_restricted"], p
            assert not alcohol_in_name(p.get("entity_type", "catalog_item"), p["name"], p["concept"]), p
            assert p["concept"] not in concepts or is_offerable(concepts[p["concept"]]), p


def test_the_most_ordered_of_the_population_goes_first_and_is_declared(client, db):
    db.execute(
        """INSERT INTO trends (data_source, scope, vertical, item_key, entity_type, entity_id, orders_now, rank)
           VALUES ('synthetic', 'producto', 'turbo', 'catalog_item:91001', 'catalog_item', '91001', 99, 1)"""
    )
    body = ladder(client, newcomer(db))

    turbo = next(s for s in body["escalera"] if s["vertical"] == "turbo")
    if turbo["texto"] == "Lo más pedido aquí":  # si ese producto sigue a la venta en Turbo
        assert {"kind": "lo_mas_pedido", "id": "turbo", "source": "poblacion:synthetic"} in body["reason"]["basis"]
    else:
        assert {"kind": "ofertas", "id": "turbo", "source": "catalogo"} in body["reason"]["basis"]


def test_the_control_group_never_gets_it_and_nothing_is_recorded(client, db, monkeypatch):
    """ "Mochi apagado": su buscador es el de siempre. Si algo le pidiera la escalera, la API no la entrega y no la
    anota como impresión contrafactual: sale en el buscador con Mochi, que el control no tiene."""
    monkeypatch.setattr(config, "OFFERS_CONTROL_PCT", 100)
    user = newcomer(db, "u-control")
    assert experiments.offers_variant(db, user) == experiments.CONTROL

    reply = ladder(client, user, status=204, session_id="s1", surface="agent")

    assert reply.headers["X-Offer-Withheld"] == "1"
    recorded = db.execute(
        "SELECT count(*) FROM app_events WHERE user_id = %s AND type IN ('offer_withheld', 'offer_eligible')", (user,)
    ).fetchone()[0]
    assert recorded == 0


def test_a_context_with_fields_is_rejected(client, db):
    reply = client.post("/agent/offer", json={"moment": "escalera", "context": {"perfil": "asiatico"}})
    assert reply.status_code == 422
