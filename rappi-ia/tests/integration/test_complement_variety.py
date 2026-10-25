"""Complementos más variados: el sushi abre con las bebidas asiáticas y un complemento que Mochi ya ofreció a la persona
en los últimos `COMPLEMENT_REPEAT_DAYS` días y antes de su último pedido cede su lugar al siguiente mejor. Lo ofrecido
desde ese pedido (la compra en curso) no cuenta: el complemento no cambia mientras se arma el mismo pedido. Sobre el
catálogo de prueba."""

from datetime import UTC, datetime, timedelta

import pytest

from owner_client import OwnerClient
from rappi_ia.agent import tools
from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.rappi_agent import RappiAgent
from rappi_ia.agent.tools import COMPLEMENT_REPEAT_DAYS, suggest_complement
from rappi_ia.api import app as api
from rappi_ia.api.services import Services
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents
from rappi_ia.events import store as events

NOW = datetime.now(UTC)
SUSHI_ROLL = {"entity_type": "menu_item", "entity_id": "98005"}  # un plato de sushi del restaurante de prueba
SUSHI_COMPLEMENTS = ["bebidas-asiaticas", "postres", "despensa-asiatica", "gaseosas"]  # 0,5 · 0,4 · 0,3 · 0,3 (por id)
PERSON = "u-variada"
ROTATION_MARGIN = tools.ROTATION_MARGIN


@pytest.fixture
def demo(db):
    seed_demo(db)
    embedder = HashEmbedder()
    embed_search_documents(db, embedder)
    events.ensure_user(db, PERSON)
    events.ensure_user(db, "u-otra")
    db.commit()
    return db, embedder


@pytest.fixture(autouse=True)
def without_alternation(monkeypatch):
    """«No repetir» se mide con el orden de siempre: sin la alternancia entre los dos mejores complementos, que depende
    del id de cada persona. Sus tests piden `people`, que la vuelve a encender."""
    monkeypatch.setattr(tools, "ROTATION_MARGIN", -1.0)


@pytest.fixture
def client(demo):
    db, embedder = demo

    def conn_override():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    api.app.dependency_overrides[api.get_services] = lambda: Services(
        RappiAgent(embedder, TemplateComposer()), embedder
    )
    yield OwnerClient(api.app)
    api.app.dependency_overrides.clear()


def offered(db, concept, days_ago, user=PERSON, origin="agent-carrito", **extra):
    """Mochi le mostró `concept` a la persona hace `days_ago` días (el `suggestion_shown` que registra la app)."""
    payload = {"origen": origin, **extra.pop("payload", {})}
    event = events.Event(
        user, "s-1", "suggestion_shown", ts=NOW - timedelta(days=days_ago), concept_id=concept, payload=payload, **extra
    )
    events.record(db, [event])
    db.commit()


MINUTES = 1 / 1440  # `offered(..., 10 * MINUTES)`: hace diez minutos


def ordered(db, days_ago, user=PERSON, mode="propuesta"):
    """La persona hizo un pedido hace `days_ago` días."""
    line = {"entity_type": "menu_item", "entity_id": SUSHI_ROLL["entity_id"], "concept_id": "sushi", "unit_price": 6990}
    events.record_order(
        db, user, "s-1", f"c-{days_ago}-{mode}", "restaurantes", [line], ts=NOW - timedelta(days=days_ago), mode=mode
    )
    db.commit()


def first(db, embedder, user=PERSON):
    return suggest_complement(db, ["sushi"], "restaurantes", embedder, user_id=user)


def test_the_window_is_a_week():
    assert COMPLEMENT_REPEAT_DAYS == 7


def test_the_first_complement_of_sushi_is_asian_drinks(demo):
    db, embedder = demo

    chosen = suggest_complement(db, ["sushi"], "restaurantes", embedder)

    assert chosen.concept == "bebidas-asiaticas"
    assert chosen.vertical in ("conveniencia", "supermercado")  # donde el catálogo de prueba las vende


def test_a_complement_offered_three_days_ago_and_an_order_since_is_skipped_for_the_next_best(demo):
    db, embedder = demo
    offered(db, "bebidas-asiaticas", 3)
    ordered(db, 1)

    chosen = first(db, embedder)

    assert chosen.concept == "postres"
    assert chosen.reason == "Porque llevas 🍣 sushi"  # la razón sigue siendo cierta
    assert chosen.basis == []


def test_the_skipping_goes_on_down_the_list(demo):
    db, embedder = demo
    offered(db, "bebidas-asiaticas", 3)
    offered(db, "postres", 2)
    ordered(db, 1)

    assert first(db, embedder).concept == "despensa-asiatica"  # a igual peso que las gaseosas, por id
    offered(db, "despensa-asiatica", 2)
    assert first(db, embedder).concept == "gaseosas"


def test_what_is_offered_while_the_order_is_being_built_is_not_skipped(demo):
    db, embedder = demo
    ordered(db, 1)
    offered(db, "bebidas-asiaticas", 10 * MINUTES)  # después del último pedido: la compra en curso

    assert first(db, embedder).concept == "bebidas-asiaticas"


def test_without_orders_nothing_is_skipped(demo):
    db, embedder = demo
    offered(db, "bebidas-asiaticas", 3)

    assert first(db, embedder).concept == "bebidas-asiaticas"


def test_a_complement_offered_eight_days_ago_is_not_skipped(demo):
    db, embedder = demo
    offered(db, "bebidas-asiaticas", 8)
    ordered(db, 1)

    assert first(db, embedder).concept == "bebidas-asiaticas"


def test_rappi_hoy_does_not_count(demo):
    db, embedder = demo
    ordered(db, 1)
    # En «Rappi hoy» el evento va sin concepto y marcado `payload.mode = 'actual'`; con concepto tampoco cuenta.
    offered(db, None, 3, payload={"mode": "actual"})
    offered(db, "bebidas-asiaticas", 3, payload={"mode": "actual"})
    assert first(db, embedder).concept == "bebidas-asiaticas"

    # Un pedido de «Rappi hoy» no es «el último pedido» de Mochi: lo mostrado antes sigue siendo la compra en curso.
    other = "u-actual"
    offered(db, "bebidas-asiaticas", 3, user=other)
    ordered(db, 1, user=other, mode="actual")
    assert first(db, embedder, other).concept == "bebidas-asiaticas"


def test_if_every_candidate_was_offered_the_best_is_still_offered(demo):
    db, embedder = demo
    for concept in SUSHI_COMPLEMENTS:
        offered(db, concept, 3)
    ordered(db, 1)

    assert first(db, embedder).concept == "bebidas-asiaticas"


def test_if_the_rest_have_no_products_the_best_recent_one_is_still_offered(demo):
    db, embedder = demo
    db.execute("DELETE FROM concept_edges WHERE from_concept = 'sushi' AND to_concept <> 'bebidas-asiaticas'")
    db.commit()
    offered(db, "bebidas-asiaticas", 3)
    ordered(db, 1)

    assert first(db, embedder).concept == "bebidas-asiaticas"


def test_only_what_was_offered_to_this_person_as_a_complement_counts(demo):
    db, embedder = demo
    ordered(db, 1)
    offered(db, "bebidas-asiaticas", 3, user="u-otra")  # otra persona
    offered(db, "bebidas-asiaticas", 3, origin="agent-recompra")  # no era un complemento
    offered(db, "bebidas-asiaticas", 3, origin="para-ti")

    assert first(db, embedder).concept == "bebidas-asiaticas"


@pytest.mark.parametrize("origin", ["agent-carrito", "agent-checkout", "agent-proximo_pedido", "agent-ask"])
def test_any_moment_that_offers_complements_counts(demo, origin):
    db, embedder = demo
    offered(db, "bebidas-asiaticas", 3, origin=origin)
    ordered(db, 1)

    assert first(db, embedder).concept == "postres"


PEOPLE = [f"u-{i}" for i in range(8)]


@pytest.fixture
def people(demo, monkeypatch):
    monkeypatch.setattr(tools, "ROTATION_MARGIN", ROTATION_MARGIN)
    db, _ = demo
    for person in PEOPLE:
        events.ensure_user(db, person)
    db.commit()
    return PEOPLE


def test_people_split_between_the_two_best_complements_when_they_weigh_alike(demo, people):
    """Bebidas asiáticas (0,5) y postres (0,4) pesan parecido (`ROTATION_MARGIN`): a cada persona le toca uno fijo,
    así no todos ven lo mismo. Las gaseosas (0,3) siguen al final."""
    db, embedder = demo

    firsts = {person: first(db, embedder, person).concept for person in people}

    assert set(firsts.values()) == {"bebidas-asiaticas", "postres"}
    assert firsts == {person: first(db, embedder, person).concept for person in people}  # siempre el mismo


def test_a_second_complement_well_below_the_first_is_not_swapped(demo, people):
    db, embedder = demo
    db.execute(
        "UPDATE concept_edges SET weight = 0.75 WHERE from_concept = 'sushi' AND to_concept = 'bebidas-asiaticas'"
    )
    db.commit()

    assert {first(db, embedder, person).concept for person in people} == {"bebidas-asiaticas"}


def test_who_gets_the_second_moves_on_to_the_first_after_seeing_it(demo, people):
    db, embedder = demo
    person = next(p for p in people if first(db, embedder, p).concept == "postres")
    offered(db, "postres", 3, user=person)
    ordered(db, 1, user=person)

    assert first(db, embedder, person).concept == "bebidas-asiaticas"


def test_a_brand_the_person_buys_in_the_first_complement_beats_the_alternation(demo, people):
    """Como en el desempate por la combinación: si el primero trae un producto de una marca que la persona compra, va
    primero aunque a ella le toque el segundo."""
    db, embedder = demo
    person = next(p for p in people if first(db, embedder, p).concept == "postres")
    drink = suggest_complement(db, ["sushi"], "restaurantes", embedder).products[0]
    db.execute("INSERT INTO product_brands (brand_key, name) VALUES ('kirin', 'Kirin')")
    db.execute(
        "INSERT INTO item_brands (entity_type, entity_id, brand_key, source) VALUES (%s, %s, 'kirin', 'regla')",
        (drink.entity_type, drink.entity_id),
    )
    db.commit()

    chosen = suggest_complement(db, ["sushi"], "restaurantes", embedder, set(), {"kirin": 2}, person)

    assert (chosen.concept, chosen.brand) == ("bebidas-asiaticas", "kirin")
    other = suggest_complement(db, ["sushi"], "restaurantes", embedder, set(), {"otra": 2}, person)
    assert (other.concept, other.brand) == ("postres", None)


def test_without_a_person_the_order_never_changes(demo):
    db, embedder = demo
    offered(db, "bebidas-asiaticas", 3)
    ordered(db, 1)

    assert suggest_complement(db, ["sushi"], "restaurantes", embedder).concept == "bebidas-asiaticas"


def test_the_cart_and_the_checkout_keep_the_complement_and_the_next_order_changes_it(client, demo):
    db, _ = demo
    ordered(db, 20)  # ya había pedido antes: la regla no depende de que sea la primera vez
    cart = {"moment": "carrito", "context": {"product": SUSHI_ROLL}, "user_id": PERSON}
    checkout = {"moment": "checkout", "context": {"cart": [SUSHI_ROLL]}, "user_id": PERSON}
    assert client.post("/agent/offer", json=cart).json()["reason"]["concept"] == "bebidas-asiaticas"

    offered(db, "bebidas-asiaticas", 10 * MINUTES)  # la app registra lo que mostró
    same = client.post("/agent/offer", json=checkout).json()
    assert same["reason"]["concept"] == "bebidas-asiaticas"  # el mismo pedido, el mismo complemento
    assert same["reason"]["from_concept"] == "sushi"

    ordered(db, 0)  # paga: el pedido siguiente ya no repite lo que se ofreció antes de este
    assert client.post("/agent/offer", json=cart).json()["reason"]["concept"] == "postres"
