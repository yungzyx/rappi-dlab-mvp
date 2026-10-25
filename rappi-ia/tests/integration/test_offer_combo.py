"""La vertical por probar busca la combinación de verticales que más retiene (`motor`): el grupo que le falta a la
persona según la tabla de Rappi, y dentro de él la vertical con mejor predicción, con productos de sus compras cruzadas,
de lo más pedido o, si no hay, de las ofertas de siempre. Sobre el catálogo de prueba (`seed_demo`)."""

from datetime import UTC, datetime, timedelta

import pytest

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
from rappi_ia.layers.runs import finish_layer_run, start_layer_run
from rappi_ia.motor.recommend import CrossPick
from rappi_ia.offers import engine
from rappi_ia.offers.engine import _cross_offer, _top_offer
from rappi_ia.offers.guards import is_offerable

NOW = datetime.now(UTC)
SUSHI_ROLL = "98005"  # un plato de sushi del restaurante de prueba
REST_TO_TURBO = {"kind": "combinacion", "id": "restaurantes→restaurantes+turbo", "source": "rappi"}


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


def to_try(client, user_id=None):
    body = {"moment": "vertical_por_probar", "context": {}}
    if user_id:
        body["user_id"] = user_id
    reply = client.post("/agent/offer", json=body)
    assert reply.status_code == 200, reply.text
    return reply.json()


def order(db, user, vertical, concept=None, days_ago=0, entity=("catalog_item", "91001")):
    line = {"entity_type": entity[0], "entity_id": entity[1], "concept_id": concept, "unit_price": 1990}
    events.record_order(
        db, user, f"s-{vertical}-{days_ago}", f"c-{user}-{vertical}-{days_ago}", vertical, [line],
        ts=NOW - timedelta(days=days_ago),
    )  # fmt: skip


def sushi_lover(db, user="u-sushi"):
    """Solo pide sushi en restaurantes: su combinación es «rest»."""
    order(db, user, "restaurantes", "sushi", entity=("menu_item", SUSHI_ROLL))


def concept_trends(db, rows):
    for (concept, vertical), n in rows.items():
        db.execute(
            """INSERT INTO trends (data_source, scope, vertical, item_key, concept_id, orders_now)
               VALUES ('synthetic', 'concepto', %s, %s, %s, %s)""",
            (vertical, concept, concept, n),
        )


def rule(db, from_concept, to_concept, to_vertical, lift):
    db.execute(
        """INSERT INTO cross_sell_rules (data_source, from_concept, from_vertical, to_concept, to_vertical, lift)
           VALUES ('synthetic', %s, 'restaurantes', %s, %s, %s)""",
        (from_concept, to_concept, to_vertical, lift),
    )


def product_trends(db, vertical, items):
    for rank, (entity_type, entity_id) in enumerate(items, start=1):
        db.execute(
            """INSERT INTO trends (data_source, scope, vertical, item_key, entity_type, entity_id, orders_now, rank)
               VALUES ('synthetic', 'producto', %s, %s, %s, %s, %s, %s)""",
            (vertical, f"{entity_type}:{entity_id}", entity_type, entity_id, 100 - rank, rank),
        )


def test_without_orders_it_is_the_usual_offer(client, db):
    db.execute("INSERT INTO app_users (user_id, source) VALUES ('nuevo', 'prototype')")

    for user in (None, "nuevo"):
        body = to_try(client, user)
        assert body["vertical"] == "supermercado"
        assert body["text"] == "Aún no pides en el súper: mira estas ofertas."
        assert body["reason"]["basis"] == [{"kind": "sin_pedidos", "id": "supermercado", "source": "contexto"}]


def test_with_rest_turbo_and_the_supermarket_it_is_another_retail_vertical(client, db):
    """La escalera sigue dentro de Retail: Express, Mall o Chocolatería, con el supuesto declarado en la `basis`."""
    for vertical in ("restaurantes", "turbo", "supermercado"):
        order(db, "u1", vertical)
    for vertical in ("farmacia", "licores"):  # lo que más abre: aun así, nunca se le ofrece
        events.record(db, [events.Event("u1", "s1", "vertical_open", ts=NOW, vertical=vertical) for _ in range(9)])

    body = to_try(client, "u1")

    assert body["vertical"] in ("conveniencia", "mall", "chocolateria")
    current = "restaurantes+turbo+supermercado"
    assert body["reason"]["basis"][0] == {
        "kind": "combinacion",
        "id": f"{current}→{current}+{body['vertical']}",  # las tres van después del súper en el orden fino
        "source": "rappi+supuesto",
    }
    assert body["products"] and all(p["vertical"] == body["vertical"] for p in body["products"])
    assert "retención" not in body["text"] + body["reason"]["text"]


def every_offerable_vertical(db, user="u1"):
    for vertical in ("restaurantes", "turbo", "supermercado", "conveniencia", "mall", "chocolateria"):
        order(db, user, vertical)


def opened(db, user, service, mode=None):
    payload = {"servicio": service, **({"mode": mode} if mode else {})}
    events.record(db, [events.Event(user, "s1", "service_opened", ts=NOW, payload=payload)])


ALL_SIX = "restaurantes+turbo+supermercado+conveniencia+mall+chocolateria"


def test_with_every_offerable_vertical_it_offers_rappifavor_without_products(client, db):
    every_offerable_vertical(db)

    body = to_try(client, "u1")

    assert body["moment"] == "vertical_por_probar"
    assert body["text"] == (
        "¿Conoces RappiFavor? Un Rappitendero lleva lo que necesites de un punto a otro, te compra en cualquier"
        " tienda o hace tu trámite."
    )
    assert body["products"] == [] and body["vertical"] is None and body["prototype_vertical"] is None
    assert (
        body["reason"]["text"] == "Porque ya pides en 6 verticales: RappiFavor te ayuda con lo que no está en la app."
    )
    assert body["reason"]["basis"] == [
        {"kind": "combinacion", "id": f"{ALL_SIX}→{ALL_SIX}+favor", "source": "rappi+supuesto"}
    ]
    assert body["actions"] == [{"label": "Abrir RappiFavor", "route": ["favor"], "service": "rappifavor"}]


def test_after_rappifavor_it_offers_rappitravel_and_then_the_usual(client, db):
    every_offerable_vertical(db)
    opened(db, "u1", "rappifavor")

    body = to_try(client, "u1")

    assert body["text"] == (
        "¿Conoces RappiTravel? Vuelos, hoteles, autos, seguros y paquetes, pagando con tus RappiCréditos y con"
        " cashback."
    )
    assert body["products"] == [] and body["vertical"] is None
    assert body["reason"]["text"] == "Porque ya pides en 6 verticales: con RappiTravel planeas el viaje."
    assert body["reason"]["basis"] == [
        {"kind": "combinacion", "id": f"{ALL_SIX}+favor→{ALL_SIX}+favor+travel", "source": "rappi+supuesto"}
    ]
    assert body["actions"] == [{"label": "Abrir RappiTravel", "route": ["travel"], "service": "rappitravel"}]

    opened(db, "u1", "rappitravel", mode="actual")  # en «Rappi hoy» no cuenta
    assert to_try(client, "u1")["actions"][0]["service"] == "rappitravel"

    opened(db, "u1", "rappitravel")  # ya usa todo: sin paso, la de siempre (y ya pidió en todas las que se ofrecen)
    reply = client.post("/agent/offer", json={"moment": "vertical_por_probar", "user_id": "u1", "context": {}})
    assert reply.status_code == 204


@pytest.mark.parametrize("own_only", ["farmacia", "licores"])
def test_the_basis_never_names_pharmacy_or_liquor_even_when_the_person_ordered_there(client, db, own_only):
    """Lo que el agente no propone no entra a la base: Farmacia y Licores cuentan en la combinación de la persona
    (y en el paso), pero el id de la `combinacion` no los nombra."""
    sushi_lover(db)
    order(db, "u-sushi", own_only)

    body = to_try(client, "u-sushi")

    step = next(s for s in body["reason"]["basis"] if s["kind"] == "combinacion")
    assert step["id"] == "restaurantes→restaurantes+turbo"
    assert "farmacia" not in step["id"] and "licores" not in step["id"]


def test_a_lapsed_person_climbs_from_the_combination_of_90_days(client, db):
    order(db, "u-vuelve", "restaurantes", "sushi", days_ago=60, entity=("menu_item", SUSHI_ROLL))
    order(db, "u-lejos", "restaurantes", "sushi", days_ago=120, entity=("menu_item", SUSHI_ROLL))

    lapsed = to_try(client, "u-vuelve")
    assert lapsed["vertical"] == "turbo"
    assert lapsed["reason"]["basis"][0] == REST_TO_TURBO

    gone = to_try(client, "u-lejos")  # sin pedidos en 90 días: la de siempre
    assert not any(s["kind"] == "combinacion" for s in gone["reason"]["basis"])
    assert gone["vertical"] == "supermercado"


def test_only_restaurants_goes_for_turbo_with_the_combination_as_basis(client, db):
    sushi_lover(db)

    body = to_try(client, "u-sushi")

    assert body["vertical"] == "turbo" and body["prototype_vertical"] == "turbo"
    assert body["reason"]["basis"][0] == REST_TO_TURBO
    assert body["actions"] == [{"label": "Abrir Turbo", "route": ["turbo"]}]
    assert body["products"] and all(p["vertical"] == "turbo" for p in body["products"])
    # Sin datos de la población: las ofertas de siempre, con su porqué de siempre detrás del paso.
    assert body["text"] == "Aún no pides en Turbo: mira estas ofertas."
    assert body["reason"]["basis"][1:] == [{"kind": "sin_pedidos", "id": "turbo", "source": "contexto"}]


def test_a_cross_sell_rule_from_their_concept_brings_its_products_and_says_why(client, db):
    sushi_lover(db)
    concept_trends(db, {("despensa-asiatica", "turbo"): 10, ("helados", "turbo"): 50})
    rule(db, "sushi", "despensa-asiatica", "turbo", 10.0)  # 10 × (1 + 9) = 100 > 50

    body = to_try(client, "u-sushi")

    assert body["vertical"] == "turbo"
    assert body["text"] == "Para tu pedido de sushi: despensa asiática en Turbo."
    # No afirma lo que hace la población (en la demo es simulada): eso lo declara la `basis`.
    assert body["reason"]["text"] == ("Porque pides 🍣 sushi. Para acompañar: despensa asiática, en Turbo.")
    assert body["reason"]["basis"] == [
        REST_TO_TURBO,
        {"kind": "compra_cruzada", "id": "sushi→despensa-asiatica@turbo", "source": "poblacion:synthetic"},
    ]
    assert (body["reason"]["concept"], body["reason"]["from_concept"]) == ("despensa-asiatica", "sushi")
    assert 1 <= len(body["products"]) <= 3
    assert {p["concept"] for p in body["products"]} == {"despensa-asiatica"}
    assert all(p["vertical"] == "turbo" and not p["age_restricted"] for p in body["products"])
    assert "retención" not in body["text"] + body["reason"]["text"]  # habla de la persona, no de cifras


def test_without_the_push_of_a_rule_it_is_the_most_ordered(client, db):
    sushi_lover(db)
    concept_trends(db, {("despensa-asiatica", "turbo"): 10, ("helados", "turbo"): 50})
    rule(db, "sushi", "despensa-asiatica", "turbo", 10.0)
    run = start_layer_run(db, "motor", "v")
    finish_layer_run(db, run, {"fuente": "synthetic", "lambda_cruzada": 0.0})  # la validación eligió no empujar

    body = to_try(client, "u-sushi")

    assert body["vertical"] == "turbo"
    assert body["text"] == "Lo más pedido en Turbo."
    assert body["reason"]["text"] == "Porque aún no pides en Turbo: esto es lo que más se pide."
    assert body["reason"]["basis"] == [
        REST_TO_TURBO,
        {"kind": "lo_mas_pedido", "id": "turbo", "source": "poblacion:synthetic"},
    ]
    assert {p["concept"] for p in body["products"]} == {"helados"}


def test_a_rule_from_a_concept_the_agent_does_not_offer_is_never_named(client, db):
    order(db, "u-chela", "restaurantes", "cerveza")  # pide cerveza en un restaurante
    concept_trends(db, {("despensa-asiatica", "turbo"): 10, ("helados", "turbo"): 50})
    rule(db, "cerveza", "despensa-asiatica", "turbo", 10.0)

    body = to_try(client, "u-chela")

    assert body["vertical"] == "turbo"
    assert body["text"] == "Para sumar en Turbo."  # la regla eligió los productos: no son «lo más pedido»
    assert body["reason"]["text"] == "Porque aún no pides en Turbo."
    assert "cerveza" not in body["reason"]["text"] and "cerveza" not in str(body["reason"]["basis"])
    # La regla movió el orden: su fuente se declara, sin nombrar de dónde sale.
    assert body["reason"]["basis"] == [
        REST_TO_TURBO,
        {"kind": "compra_cruzada", "id": "despensa-asiatica@turbo", "source": "poblacion:synthetic"},
        {"kind": "lo_mas_pedido", "id": "turbo", "source": "poblacion:synthetic"},
    ]
    assert {p["concept"] for p in body["products"]} == {"despensa-asiatica"}


def test_a_rule_from_a_concept_to_itself_says_it_is_also_there(client, db):
    order(db, "u-hielo", "restaurantes", "hielo")
    concept_trends(db, {("hielo", "turbo"): 10, ("helados", "turbo"): 50})
    rule(db, "hielo", "hielo", "turbo", 10.0)  # el mismo concepto, en otra vertical

    body = to_try(client, "u-hielo")

    assert body["vertical"] == "turbo"
    assert body["text"] == "También hay hielo en Turbo."
    assert body["reason"]["text"] == "Porque pides 🧊 hielo; en Turbo también hay."
    assert body["reason"]["basis"][1] == {
        "kind": "compra_cruzada",
        "id": "hielo→hielo@turbo",
        "source": "poblacion:synthetic",
    }
    assert {p["concept"] for p in body["products"]} == {"hielo"}


def test_without_a_push_the_most_ordered_products_go_before_the_most_ordered_concept(client, db):
    sushi_lover(db)
    concept_trends(db, {("helados", "turbo"): 50})  # sin regla: el concepto más pedido
    product_trends(db, "turbo", [("catalog_item", "93003")])  # el producto más pedido: té helado

    body = to_try(client, "u-sushi")

    assert body["text"] == "Lo más pedido en Turbo."
    assert [p["entity_id"] for p in body["products"]] == ["93003"]
    assert body["reason"]["basis"] == [
        REST_TO_TURBO,
        {"kind": "lo_mas_pedido", "id": "turbo", "source": "poblacion:synthetic"},
    ]


def test_the_most_ordered_products_are_current_offerable_and_of_the_vertical(client, db):
    sushi_lover(db)
    product_trends(
        db,
        "turbo",
        [
            ("catalog_item", "94001"),  # cerveza (+18): nunca
            ("catalog_item", "97001"),  # solo se vende en la chocolatería
            ("catalog_item", "93001"),  # helado
            ("menu_item", "98001"),  # un plato no es de Turbo
            ("catalog_item", "999999"),  # ya no existe
            ("catalog_item", "93003"),  # té helado
        ],
    )

    body = to_try(client, "u-sushi")

    assert body["text"] == "Lo más pedido en Turbo."
    assert [p["entity_id"] for p in body["products"]] == ["93001", "93003"]
    assert body["reason"]["basis"] == [
        REST_TO_TURBO,
        {"kind": "lo_mas_pedido", "id": "turbo", "source": "poblacion:synthetic"},
    ]


def mall_browser(db, user="u1"):
    """Pide en restaurantes y en Turbo (le falta retail) y abre mucho Farmacia y Licores, y algo el mall."""
    order(db, user, "restaurantes")
    order(db, user, "turbo")
    opened = [("farmacia", 6), ("licores", 6), ("mall", 2)]
    events.record(
        db,
        [
            events.Event(user, "s1", "vertical_open", ts=NOW, vertical=vertical)
            for vertical, times in opened
            for _ in range(times)
        ],
    )


def test_the_step_skips_pharmacy_and_liquor_and_follows_the_prediction(client, db):
    mall_browser(db)

    body = to_try(client, "u1")

    assert body["vertical"] == "mall"  # Farmacia y Licores predicen más, pero no se ofrecen; sin el mall, el súper
    assert body["reason"]["basis"][0] == {
        "kind": "combinacion",
        "id": "restaurantes+turbo→restaurantes+turbo+mall",
        "source": "rappi",
    }
    assert all(p["vertical"] == "mall" for p in body["products"])


def test_the_most_ordered_never_comes_from_a_store_the_agent_does_not_push(client, db):
    mall_browser(db)
    product_trends(db, "mall", [("catalog_item", "96101"), ("catalog_item", "96007")])  # la vela del sex shop, y otra

    body = to_try(client, "u1")

    assert body["vertical"] == "mall" and body["text"] == "Lo más pedido en Rappi Mall."
    assert [p["entity_id"] for p in body["products"]] == ["96007"]


def test_the_most_ordered_has_the_price_of_the_vertical_even_if_it_is_cheaper_elsewhere(client, db):
    sushi_lover(db)
    product_trends(db, "turbo", [("catalog_item", "91001")])  # papas: $1.990 en el súper, $2.490 en Turbo

    body = to_try(client, "u-sushi")

    [chips] = body["products"]
    assert (chips["entity_id"], chips["vertical"], chips["price"]) == ("91001", "turbo", "$2.490")
    assert chips["store"].startswith("Tienda turbo")


def test_a_vertical_of_the_group_tried_long_ago_is_still_offered_as_a_comeback(client, db):
    sushi_lover(db)
    order(db, "u-sushi", "turbo", days_ago=40)  # probó Turbo hace más de un mes: su combinación sigue siendo «rest»
    back = {"kind": "vuelta", "id": "turbo", "source": "pedidos"}

    body = to_try(client, "u-sushi")

    assert body["vertical"] == "turbo"
    assert body["text"] == "Vuelve a Turbo: mira estas ofertas."
    assert body["reason"]["text"] == "Porque hace más de un mes que no pides en Turbo."
    assert body["reason"]["basis"] == [REST_TO_TURBO, back]

    product_trends(db, "turbo", [("catalog_item", "93001")])
    body = to_try(client, "u-sushi")
    assert body["text"] == "Vuelve a Turbo: mira lo más pedido."
    assert body["reason"]["text"] == "Porque hace más de un mes que no pides en Turbo."
    assert body["reason"]["basis"] == [
        REST_TO_TURBO,
        {"kind": "lo_mas_pedido", "id": "turbo", "source": "poblacion:synthetic"},
        back,
    ]

    concept_trends(db, {("despensa-asiatica", "turbo"): 10})
    rule(db, "sushi", "despensa-asiatica", "turbo", 10.0)
    body = to_try(client, "u-sushi")
    assert body["text"] == "Para tu pedido de sushi: despensa asiática en Turbo."  # sigue siendo cierto
    assert [s["kind"] for s in body["reason"]["basis"]] == ["combinacion", "compra_cruzada"]


def test_a_comeback_to_the_supermarket_contracts_the_article(client, db):
    order(db, "u1", "restaurantes")
    order(db, "u1", "turbo")
    for vertical in ("supermercado", "conveniencia", "mall", "chocolateria"):
        order(db, "u1", vertical, days_ago=40)

    body = to_try(client, "u1")

    assert body["vertical"] == "supermercado"
    assert body["text"] == "Vuelve al súper: mira estas ofertas."
    assert body["reason"]["text"] == "Porque hace más de un mes que no pides en el súper."


OFFERABLE = [c for c in load_taxonomy().concepts.values() if is_offerable(c)]


def _all_texts(offer):
    return [offer.text, offer.reason["text"]]


def _assert_reads_well(texts, name):
    for text in texts:
        assert "  " not in text and text == text.strip(), text
        assert "combina" not in text, text  # el verbo no concuerda con un plural ni con un compuesto
        assert f"tu {name}" not in text.lower() and f"tus {name}" not in text.lower(), text
        assert " de el " not in text and " a el " not in text, text


# Singulares («sushi»), plurales («frutas»), compuestos con «y» («sándwiches y completos») y con comas.
@pytest.mark.parametrize("origin_id", [c.id for c in OFFERABLE])
def test_cross_texts_read_well_with_any_concept_as_origin_and_destination(origin_id):
    concepts = load_taxonomy().concepts
    origin = concepts[origin_id]
    combo = REST_TO_TURBO
    for destination_id in (origin_id, "frutas", "sandwiches"):
        assert destination_id in concepts
        pick = CrossPick(destination_id, "turbo", 1.0, origin_id, 5.0)
        offer = _cross_offer("turbo", [], pick, origin, combo, "synthetic")
        name = concepts[destination_id].name.lower()
        _assert_reads_well(_all_texts(offer), name)
        assert offer.text.endswith(".") and offer.reason["text"].endswith(".")
        assert name in offer.text and origin.name.lower() in offer.reason["text"]


@pytest.mark.parametrize("vertical", ["turbo", "supermercado", "mall"])
def test_a_rule_without_a_nameable_origin_never_claims_the_most_ordered(vertical):
    combo = REST_TO_TURBO
    rule = {"kind": "compra_cruzada", "id": f"helados@{vertical}", "source": "poblacion:synthetic"}

    new = _top_offer(vertical, [], combo, "synthetic", False, rule)
    back = _top_offer(vertical, [], combo, "synthetic", True, rule)
    plain = _top_offer(vertical, [], combo, "synthetic", False)

    for offer in (new, back):
        assert "más pedido" not in (offer.text + offer.reason["text"]) and "más se pide" not in offer.reason["text"]
    assert new.text.startswith("Para sumar en ") and new.reason["text"].startswith("Porque aún no pides en ")
    assert back.text.startswith("Vuelve a") and back.reason["text"].startswith("Porque hace más de un mes")
    assert plain.text.startswith("Lo más pedido en ")  # sin regla, sí son lo más pedido de la población


VERBS_THAT_AGREE = ("combina", "te gusta", "te interesa", "lo pides", "los pides", "las pides", "lo llevas")


TEMPLATES = (
    "CART_TEXT",
    "CART_TEXT_ANONYMOUS",
    "CHECKOUT_TEXT",
    "NEXT_ORDER_TEXT",
    "NO_RESULT_TEXT",
    "REASON_CART",
    "REASON_CART_ANONYMOUS",
    "REASON_NEXT",
    "REASON_NEXT_ANONYMOUS",
    "REASON_REPEAT",
    "REPEAT_TEXT",
    "REASON_LIKES_VERTICAL",
    "REASON_LIKES_OCCASION",
    "PROFILE_TEXT",
    "TO_TRY_CROSS_TEXT",
    "REASON_TO_TRY_CROSS",
    "TO_TRY_SAME_TEXT",
    "REASON_TO_TRY_SAME",
)


@pytest.mark.parametrize("concept", OFFERABLE, ids=lambda c: c.id)
def test_every_person_facing_template_reads_well_with_any_concept(concept):
    """Ninguna plantilla conjuga un verbo ni un pronombre con el nombre del concepto (singular, plural o compuesto)."""
    name = concept.name.lower()
    args = {
        "destino": name,
        "origen": name,
        "name": name,
        "emoji": concept.emoji,
        "vertical": "Turbo",
        "cada": "cada 7 días",
        "hace": "ayer",
        "likes": name,
        "query": name,
        "occasion": name,
    }
    for const in TEMPLATES:
        text = getattr(engine, const).format(**args)
        _assert_reads_well([text], name)
        assert not any(verb in text.lower() for verb in VERBS_THAT_AGREE), (const, text)
