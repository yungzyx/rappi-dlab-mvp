"""Los complementos de una persona (`carrito`, `checkout`, `proximo_pedido` y `/agent/ask`): sus compras cruzadas entran
como candidatas junto a las aristas curadas y, entre dos complementos parecidos, gana el de la vertical que completa la
combinación que más retiene (`motor`). Sobre el catálogo de prueba (`seed_demo`)."""

from datetime import UTC, datetime, timedelta

import pytest

from owner_client import OwnerClient
from rappi_ia.agent import tools
from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.rappi_agent import Context, RappiAgent
from rappi_ia.agent.tools import suggest_complement
from rappi_ia.api import app as api
from rappi_ia.api.services import Services
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents
from rappi_ia.events import store as events
from rappi_ia.layers.runs import finish_layer_run, start_layer_run

NOW = datetime.now(UTC)
SUSHI_ROLL = "98005"  # un plato de sushi del restaurante de prueba
PIZZA = {"entity_type": "menu_item", "entity_id": "98001"}  # una pizza del restaurante de prueba
REST_TO_TURBO = {"kind": "combinacion", "id": "restaurantes→restaurantes+turbo", "source": "rappi"}
ROTATION_MARGIN = tools.ROTATION_MARGIN


@pytest.fixture(autouse=True)
def without_alternation(monkeypatch):
    """Estos tests miden la combinación y la compra cruzada: sin la alternancia entre los dos mejores complementos, que
    depende del id de cada persona (`ROTATION_MARGIN`; sus tests están en test_complement_variety.py)."""
    monkeypatch.setattr(tools, "ROTATION_MARGIN", -1.0)


@pytest.fixture
def demo(db):
    seed_demo(db)
    embedder = HashEmbedder()
    embed_search_documents(db, embedder)
    # Solo pide sushi en restaurantes: su combinación es «rest» y el paso que más retiene le suma Turbo.
    line = {"entity_type": "menu_item", "entity_id": SUSHI_ROLL, "concept_id": "sushi", "unit_price": 6990}
    events.record_order(db, "u-sushi", "s-1", "c-1", "restaurantes", [line], ts=NOW - timedelta(days=2))
    db.commit()
    return db, embedder


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


def pizza_goes_with(db, weights):
    """Las aristas curadas de la pizza son solo estas: el café se vende solo en el súper y el hielo solo en Turbo."""
    db.execute("DELETE FROM concept_edges WHERE from_concept = 'pizza'")
    for concept, weight in weights.items():
        db.execute(
            """INSERT INTO concept_edges (from_concept, to_concept, method, weight, data_source)
               VALUES ('pizza', %s, 'curado', %s, 'curado')""",
            (concept, weight),
        )
    db.commit()


def rule(db, from_concept, to_concept, to_vertical, lift, orders=10):
    """Una compra cruzada de la población, con lo que pide en ese vertical (sin popularidad la regla no ofrece nada)."""
    db.execute(
        """INSERT INTO cross_sell_rules (data_source, from_concept, from_vertical, to_concept, to_vertical, lift)
           VALUES ('synthetic', %s, 'restaurantes', %s, %s, %s)""",
        (from_concept, to_concept, to_vertical, lift),
    )
    db.execute(
        """INSERT INTO trends (data_source, scope, vertical, item_key, concept_id, orders_now)
           VALUES ('synthetic', 'concepto', %s, %s, %s, %s)""",
        (to_vertical, to_concept, to_concept, orders),
    )
    db.commit()


def test_with_two_similar_complements_the_one_of_the_target_vertical_wins(demo):
    db, embedder = demo
    pizza_goes_with(db, {"cafe": 0.6, "hielo": 0.55})

    usual = suggest_complement(db, ["pizza"], "restaurantes", embedder)
    assert (usual.concept, usual.vertical, usual.basis) == ("cafe", "supermercado", [])

    chosen = suggest_complement(db, ["pizza"], "restaurantes", embedder, user_id="u-sushi")
    assert (chosen.concept, chosen.vertical) == ("hielo", "turbo")
    assert chosen.basis == [REST_TO_TURBO]
    assert chosen.reason == "Porque llevas 🍕 pizza"  # la razón sigue hablando de lo que lleva la persona


@pytest.mark.parametrize("alternation", [False, True])
def test_with_the_three_groups_the_tie_goes_to_the_vertical_of_the_fine_step(demo, monkeypatch, alternation):
    """Quien ya pide en los tres grupos sigue subiendo dentro de Retail: el complemento de la vertical del paso fino
    (aquí la chocolatería, la que más abre) gana el desempate. Con la alternancia, a u-tres le toca primero el segundo
    de la pizza, justo los chocolates: la base dice igual que los eligió la combinación."""
    if alternation:
        monkeypatch.setattr(tools, "ROTATION_MARGIN", ROTATION_MARGIN)
    db, embedder = demo
    pizza_goes_with(db, {"cafe": 0.6, "chocolates": 0.55})  # el café solo está en el súper, que ya pide
    line = {"entity_type": "catalog_item", "entity_id": "91001", "concept_id": None, "unit_price": 1990}
    for vertical in ("restaurantes", "turbo", "supermercado"):
        events.record_order(db, "u-tres", f"s-{vertical}", f"c-{vertical}", vertical, [line], ts=NOW)
    opens = [events.Event("u-tres", "s1", "vertical_open", ts=NOW, vertical="chocolateria") for _ in range(5)]
    events.record(db, opens)
    db.commit()

    chosen = suggest_complement(db, ["pizza"], "restaurantes", embedder, user_id="u-tres")

    assert (chosen.concept, chosen.vertical) == ("chocolates", "chocolateria")
    current = "restaurantes+turbo+supermercado"
    assert chosen.basis == [
        {"kind": "combinacion", "id": f"{current}→{current}+chocolateria", "source": "rappi+supuesto"}
    ]


def coffee_brand(db):
    """El café del súper de prueba (91004) es de una marca que la persona compra."""
    db.execute("INSERT INTO product_brands (brand_key, name) VALUES ('marca-cafe', 'Café del Sur')")
    db.execute(
        """INSERT INTO item_brands (entity_type, entity_id, brand_key, source)
           VALUES ('catalog_item', '91004', 'marca-cafe', 'regla')"""
    )
    db.commit()


def test_with_two_similar_complements_the_brand_you_buy_beats_the_combination(demo):
    db, embedder = demo
    pizza_goes_with(db, {"cafe": 0.6, "hielo": 0.55})
    coffee_brand(db)

    chosen = suggest_complement(db, ["pizza"], "restaurantes", embedder, set(), {"marca-cafe": 2}, "u-sushi")

    assert (chosen.concept, chosen.vertical, chosen.brand) == ("cafe", "supermercado", "marca-cafe")
    assert chosen.products[0].entity_id == "91004"
    assert chosen.basis == []  # no lo eligió el desempate


def test_with_two_similar_complements_and_no_brand_of_theirs_the_combination_wins(demo):
    db, embedder = demo
    pizza_goes_with(db, {"cafe": 0.6, "hielo": 0.55})
    coffee_brand(db)

    chosen = suggest_complement(db, ["pizza"], "restaurantes", embedder, set(), {"otra-marca": 3}, "u-sushi")

    assert (chosen.concept, chosen.vertical, chosen.brand) == ("hielo", "turbo", None)
    assert chosen.basis == [REST_TO_TURBO]


def test_with_one_clearly_better_that_one_wins(demo):
    db, embedder = demo
    pizza_goes_with(db, {"cafe": 0.7, "hielo": 0.55})

    chosen = suggest_complement(db, ["pizza"], "restaurantes", embedder, user_id="u-sushi")

    assert (chosen.concept, chosen.vertical, chosen.basis) == ("cafe", "supermercado", [])


def test_a_difference_of_exactly_the_margin_is_not_similar(demo):
    db, embedder = demo
    pizza_goes_with(db, {"cafe": 0.4, "hielo": 0.3})  # `real`: 0,4 − 0,3 no es 0,0999…

    chosen = suggest_complement(db, ["pizza"], "restaurantes", embedder, user_id="u-sushi")

    assert chosen.concept == "cafe"


def test_if_the_best_already_completes_the_combination_nothing_changes(demo):
    db, embedder = demo
    pizza_goes_with(db, {"hielo": 0.6, "cafe": 0.55})

    chosen = suggest_complement(db, ["pizza"], "restaurantes", embedder, user_id="u-sushi")

    assert (chosen.concept, chosen.vertical, chosen.basis) == ("hielo", "turbo", [])


def test_the_usual_first_that_completes_the_combination_beats_the_alternation(demo, monkeypatch):
    """A u-maki le toca primero el segundo complemento de la pizza (el café), pero el primero de siempre (el hielo,
    solo en Turbo) completa su combinación: va él."""
    monkeypatch.setattr(tools, "ROTATION_MARGIN", ROTATION_MARGIN)
    db, embedder = demo
    pizza_goes_with(db, {"hielo": 0.6, "cafe": 0.55})
    line = {"entity_type": "menu_item", "entity_id": SUSHI_ROLL, "concept_id": "sushi", "unit_price": 6990}
    events.record_order(db, "u-maki", "s-1", "c-1", "restaurantes", [line], ts=NOW - timedelta(days=2))
    db.commit()

    chosen = suggest_complement(db, ["pizza"], "restaurantes", embedder, user_id="u-maki")

    assert (chosen.concept, chosen.vertical, chosen.basis) == ("hielo", "turbo", [])
    # u-nori, sin pedidos (sin paso del motor), es de la misma mitad: a ella le toca el café.
    assert suggest_complement(db, ["pizza"], "restaurantes", embedder, user_id="u-nori").concept == "cafe"


def test_without_a_step_of_the_motor_it_is_the_usual_order(demo):
    db, embedder = demo
    pizza_goes_with(db, {"cafe": 0.6, "hielo": 0.55})
    db.execute("INSERT INTO app_users (user_id, source) VALUES ('nuevo', 'prototype')")

    chosen = suggest_complement(db, ["pizza"], "restaurantes", embedder, user_id="nuevo")

    assert (chosen.concept, chosen.basis) == ("cafe", [])


def test_a_cross_sell_rule_from_the_source_is_a_candidate_and_says_so(demo):
    db, embedder = demo
    rule(db, "sushi", "despensa-asiatica", "turbo", 4.0)  # peso min(1, (4 − 1) / 3) = 1 > 0,4 de las curadas

    usual = suggest_complement(db, ["sushi"], "restaurantes", embedder)
    assert usual.concept != "despensa-asiatica"  # la arista curada pesa 0,3: no es la primera

    chosen = suggest_complement(db, ["sushi"], "restaurantes", embedder, user_id="u-sushi")
    assert (chosen.concept, chosen.source_concept, chosen.vertical) == ("despensa-asiatica", "sushi", "turbo")
    assert chosen.basis == [
        {"kind": "compra_cruzada", "id": "sushi→despensa-asiatica@turbo", "source": "poblacion:synthetic"}
    ]


def test_a_cross_sell_rule_of_the_person_is_not_swapped_with_the_next_complement(demo, monkeypatch):
    """Entre dos complementos que pesan parecido, a la mitad de las personas les toca primero el segundo
    (`ROTATION_MARGIN`); una compra cruzada de la persona es suya y va primero igual."""
    monkeypatch.setattr(tools, "ROTATION_MARGIN", ROTATION_MARGIN)
    db, embedder = demo
    # Sin la regla, a u-sushi le toca el segundo de la sushi: los postres antes que las bebidas asiáticas.
    assert suggest_complement(db, ["sushi"], "restaurantes", embedder, user_id="u-sushi").concept == "postres"
    rule(db, "sushi", "despensa-asiatica", "turbo", 2.65)  # peso 0,55: apenas sobre las bebidas asiáticas (0,5)

    chosen = suggest_complement(db, ["sushi"], "restaurantes", embedder, user_id="u-sushi")

    assert (chosen.concept, chosen.vertical) == ("despensa-asiatica", "turbo")


def test_a_cross_sell_rule_is_only_searched_in_the_vertical_of_the_rule(demo):
    db, embedder = demo
    # El hielo solo se vende en Turbo y la regla es de Express, donde no hay: la sushi no tiene arista al hielo, así que
    # se ofrece la primera curada de siempre (las bebidas asiáticas, la de mayor peso), sin compra cruzada.
    rule(db, "sushi", "hielo", "conveniencia", 4.0)

    chosen = suggest_complement(db, ["sushi"], "restaurantes", embedder, user_id="u-sushi")

    usual = suggest_complement(db, ["sushi"], "restaurantes", embedder)
    assert (chosen.concept, chosen.vertical, chosen.basis) == (usual.concept, usual.vertical, [])
    assert chosen.concept == "bebidas-asiaticas"


def test_if_the_rule_finds_nothing_the_curated_edge_of_the_same_concept_is_tried_in_its_verticals(demo):
    db, embedder = demo
    # El café solo se vende en el súper: la regla de Turbo no encuentra nada, la arista curada sushi → café sí.
    rule(db, "sushi", "cafe", "turbo", 4.0)
    db.execute(
        """INSERT INTO concept_edges (from_concept, to_concept, method, weight, data_source)
           VALUES ('sushi', 'cafe', 'curado', 0.2, 'curado')"""
    )
    db.commit()

    chosen = suggest_complement(db, ["sushi"], "restaurantes", embedder, user_id="u-sushi")

    assert (chosen.concept, chosen.source_concept, chosen.vertical) == ("cafe", "sushi", "supermercado")
    assert chosen.reason == "Porque llevas 🍣 sushi"
    assert chosen.basis == []  # no la trajo la regla


def test_without_a_recent_order_of_the_source_the_rules_of_the_person_do_not_apply(demo):
    db, embedder = demo
    rule(db, "pizza", "hielo", "turbo", 4.0)  # u-sushi no ha pedido pizza
    pizza_goes_with(db, {"cafe": 0.9})

    chosen = suggest_complement(db, ["pizza"], "restaurantes", embedder, user_id="u-sushi")

    assert chosen.concept == "cafe" and chosen.basis == []


def test_equal_weights_keep_the_same_order_every_time(demo):
    db, embedder = demo
    pizza_goes_with(db, {"hielo": 0.6, "cafe": 0.6})

    assert suggest_complement(db, ["pizza"], "restaurantes", embedder).concept == "cafe"  # a igual peso, por id


def test_a_rule_the_validation_chose_not_to_push_is_not_a_candidate(demo):
    db, embedder = demo
    rule(db, "sushi", "despensa-asiatica", "turbo", 4.0)
    run = start_layer_run(db, "motor", "v")
    finish_layer_run(db, run, {"fuente": "synthetic", "lambda_cruzada": 0.0})

    chosen = suggest_complement(db, ["sushi"], "restaurantes", embedder, user_id="u-sushi")

    assert chosen.concept != "despensa-asiatica"
    assert not any(signal["kind"] == "compra_cruzada" for signal in chosen.basis)


def test_a_rule_to_alcohol_or_a_rule_from_another_concept_is_never_the_complement(demo):
    db, embedder = demo
    rule(db, "sushi", "cerveza", "turbo", 20.0)  # +18: las guardias de cross_picks
    rule(db, "sushi", "vino", "licores", 20.0)
    pizza_goes_with(db, {"cafe": 0.6})

    chosen = suggest_complement(db, ["sushi"], "restaurantes", embedder, user_id="u-sushi")
    assert chosen.concept not in ("cerveza", "vino") and chosen.vertical != "licores"

    # La regla sale del sushi: lo que lleva ahora es una pizza, así que no cuenta.
    rule(db, "sushi", "hielo", "turbo", 4.0)
    assert suggest_complement(db, ["pizza"], "restaurantes", embedder, user_id="u-sushi").concept == "cafe"


def test_the_cart_offer_declares_the_combination(client, demo):
    db, _ = demo
    pizza_goes_with(db, {"cafe": 0.6, "hielo": 0.55})

    body = {"moment": "carrito", "context": {"product": PIZZA}}
    anonymous = client.post("/agent/offer", json=body).json()
    assert anonymous["reason"]["concept"] == "cafe"
    assert anonymous["reason"]["basis"] == [{"kind": "carrito", "id": "pizza", "source": "contexto"}]

    offer = client.post("/agent/offer", json={**body, "user_id": "u-sushi"}).json()
    assert offer["vertical"] == "turbo" and offer["reason"]["concept"] == "hielo"
    assert offer["reason"]["basis"] == [{"kind": "carrito", "id": "pizza", "source": "contexto"}, REST_TO_TURBO]


def test_the_agent_uses_the_person_only_in_the_final_prototype(demo):
    db, embedder = demo
    pizza_goes_with(db, {"cafe": 0.6, "hielo": 0.55})
    agent = RappiAgent(embedder, TemplateComposer())

    final = agent.reply(db, "pizza", Context(vertical="restaurantes", user_id="u-sushi"))
    assert final["suggestion"]["concept"] == "hielo" and final["suggestion"]["vertical"] == "turbo"
    assert final["suggestion"]["basis"] == [REST_TO_TURBO]  # /agent/ask también declara la fuente

    anonymous = agent.reply(db, "pizza", Context(vertical="restaurantes"))
    assert anonymous["suggestion"]["concept"] == "cafe" and anonymous["suggestion"]["basis"] == []

    today = agent.reply(db, "pizza", Context(vertical="restaurantes", mode="actual", user_id="u-sushi"))
    assert "suggestion" not in today  # «Rappi hoy» no sugiere nada cruzado
