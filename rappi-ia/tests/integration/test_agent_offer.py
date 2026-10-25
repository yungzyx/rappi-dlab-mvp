"""`POST /agent/offer` y `GET /agent/plans`: lo que el agente propone en cada momento, sobre el catálogo de prueba
(`seed_demo`), con las guardias de `offers/guards.py`."""

import pytest
from fastapi.testclient import TestClient

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
from rappi_ia.offers.guards import OFFER_BLOCKED_VERTICALS, is_offerable, is_plannable

# Tiendas de prueba que Rappi rotula Sex shop, Smoking shop y Farmacia: el agente no ofrece nada de ellas.
BLOCKED_STORES = {9611, 9612, 9111}
BLOCKED_PRODUCTS = {"96101", "96102", "96201", "96202", "91401", "91402"}

BEER, WINE, PISCO = "94001", "94003", "94005"
CHIPS, COLA = "91001", "91003"
DIAPERS, PARACETAMOL, VITAMIN_C, SEX_GEL = "91007", "95001", "95003", "96102"
PIZZA_DISH = "98001"


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


def item(entity_id: str, entity_type: str = "catalog_item") -> dict:
    return {"entity_type": entity_type, "entity_id": entity_id}


def offer(client, moment: str, context: dict, user_id: str | None = None):
    body = {"moment": moment, "context": context}
    if user_id:
        body["user_id"] = user_id
    return client.post("/agent/offer", json=body)


def order(db, user_id: str, vertical: str, mode: str = "propuesta") -> None:
    """Un pedido de la persona en esa vertical (con un producto cualquiera: aquí solo cuenta dónde pidió)."""
    line = {"entity_type": "catalog_item", "entity_id": CHIPS, "unit_price": 1990}
    events.record_order(db, user_id, f"s-{vertical}", f"c-{vertical}-{mode}", vertical, [line], mode=mode)


def without_why(reason: dict) -> dict:
    """Las claves de siempre del `reason` (lo que lee la app), sin `text` ni `basis`."""
    return {k: v for k, v in reason.items() if k not in ("text", "basis")}


def assert_offerable(body: dict) -> None:
    """Lo que el agente propone sola: nada de alcohol, farmacia, bebé, salud, sensibles, +18 ni tiendas bloqueadas."""
    concepts = load_taxonomy().concepts
    assert body["vertical"] not in OFFER_BLOCKED_VERTICALS
    assert body["products"]
    for product in body["products"]:
        assert product["vertical"] not in OFFER_BLOCKED_VERTICALS, product
        assert not product["age_restricted"], product
        assert product["store_id"] not in BLOCKED_STORES and product["entity_id"] not in BLOCKED_PRODUCTS, product
        assert product["concept"] not in concepts or is_offerable(concepts[product["concept"]]), product


def test_plan_kit_spreads_across_verticals_and_includes_chosen_alcohol_with_age_mark(client):
    reply = offer(client, "plan", {"occasion": "carrete"})

    assert reply.status_code == 200, reply.text
    body = reply.json()
    products = body["products"]
    assert body["moment"] == "plan" and without_why(body["reason"]) == {"occasion": "carrete"}
    assert len(products) == 4 and len({p["entity_id"] for p in products}) == 4  # un producto por concepto
    assert len({p["concept"] for p in products}) == 4
    assert len({p["vertical"] for p in products}) >= 3  # repartido entre verticales
    assert "farmacia" not in {p["vertical"] for p in products}
    beers = [p for p in products if p["concept"] == "cerveza"]  # el alcohol de la ocasión elegida, con su marca +18
    assert beers and beers[0]["age_restricted"] and beers[0]["vertical"] == "licores"
    assert all(p["age_restricted"] == (p["concept"] in ("cerveza", "pisco", "ron")) for p in products)
    assert all(p["vertical"] != "licores" for p in products if not p["age_restricted"])  # Licores solo para el alcohol
    assert body["vertical"] == products[0]["vertical"] and body["prototype_vertical"]
    assert body["text"].startswith("Tu kit «Carrete»: cerveza, ") and body["actions"][0]["query"].startswith("Cerveza")


def test_agent_offer_and_plans_routes(client):
    """Las rutas son /agent/offer y /agent/plans; las de /mochi/* ya no existen."""
    plans = client.get("/agent/plans")
    assert plans.status_code == 200 and {"id", "name", "emoji"} <= set(plans.json()[0])
    assert offer(client, "plan", {"occasion": "carrete"}).status_code == 200
    assert client.get("/mochi/plans").status_code == 404
    assert client.post("/mochi/offer", json={"moment": "plan", "context": {}}).status_code == 404


def test_every_plannable_occasion_stays_clear_of_sensitive_baby_health_and_blocked_stores(client):
    concepts = load_taxonomy().concepts
    plans = client.get("/agent/plans").json()
    assert len(plans) == 13

    for plan in plans:
        reply = offer(client, "plan", {"occasion": plan["id"]})
        assert reply.status_code in (200, 204), plan
        for product in reply.json()["products"] if reply.status_code == 200 else []:
            assert product["vertical"] != "farmacia" and product["store_id"] not in BLOCKED_STORES, plan
            assert is_plannable(concepts[product["concept"]]), (plan, product)
            assert product["age_restricted"] == (product["concept"] in ("cerveza", "pisco", "ron", "vino", "espumante"))


def test_every_plan_speaks_good_spanish_whatever_the_occasion_name(client):
    """«Para tu un mimo…» y «fiestas patrias» en minúscula: el texto no depende de la gramática del nombre."""
    concepts = load_taxonomy().concepts
    occasions = load_taxonomy().occasions
    answered = 0
    for plan in client.get("/agent/plans").json():
        reply = offer(client, "plan", {"occasion": plan["id"]})
        if reply.status_code != 200:
            continue
        answered += 1
        body = reply.json()
        assert body["text"].startswith(f"Tu kit «{plan['name']}»: "), body["text"]  # con la mayúscula de la taxonomía
        assert "Para tu un" not in body["text"] and "Para tu" not in body["text"]
        [action] = body["actions"]
        assert action["label"] == "Más ideas" and action["query"].strip()
        assert action["query"] not in (plan["name"], plan["name"].lower(), plan["id"])
        # la búsqueda es de los conceptos de la ocasión que el agente arma
        assert action["query"].split(" ")[0] in {c.name.split(" ")[0] for c in concepts.values()}
        assert set(occasions[plan["id"]].concepts) & {c.id for c in concepts.values() if c.name in action["query"]}
    assert answered >= 8


def test_plan_rejects_baby_and_sick_occasions(client):
    for occasion in ("guagua", "enfermo", "no-existe"):
        reply = offer(client, "plan", {"occasion": occasion})
        assert reply.status_code == 422, occasion
        assert occasion in reply.json()["detail"]


def test_cart_offer_never_returns_alcohol_or_pharmacy_even_if_cart_has_them(client):
    for product in (BEER, WINE, PISCO, DIAPERS, PARACETAMOL, VITAMIN_C, SEX_GEL, CHIPS):
        reply = offer(client, "carrito", {"product": item(product)})
        assert reply.status_code in (200, 204), product
        if reply.status_code == 200:
            assert_offerable(reply.json())

    beer = offer(client, "carrito", {"product": item(BEER)}).json()
    assert beer["moment"] == "carrito" and without_why(beer["reason"]) == {
        "concept": "snacks-salados",
        "from_concept": "cerveza",
    }
    assert beer["vertical"] == "conveniencia" and beer["prototype_vertical"] == "express"
    assert "cerveza" not in beer["text"].lower()  # el origen no se nombra: el agente no habla de alcohol sola
    assert beer["text"] == "Para completar tu pedido: snacks salados, en Express."
    assert {p["concept"] for p in beer["products"]} == {"snacks-salados"} and len(beer["products"]) <= 3
    assert beer["actions"][0]["route"] == ["express"] and beer["actions"][0]["query"] == "snacks salados"

    chips = offer(client, "carrito", {"product": item(CHIPS)}).json()
    assert chips["reason"]["from_concept"] == "snacks-salados" and chips["text"].startswith(
        "Para acompañar snacks salados"
    )


def test_checkout_offer_skips_items_already_in_cart(client):
    alone = offer(client, "checkout", {"cart": [item(PISCO)]}).json()
    assert alone["reason"]["concept"] == "gaseosas"  # la arista más fuerte del pisco

    both = offer(client, "checkout", {"cart": [item(PISCO), item(COLA)]})

    assert both.status_code == 200, both.text
    body = both.json()
    # Las gaseosas ya van en el carro: no se ofrecen. Gana la arista más fuerte que queda (gaseosas → snacks salados).
    assert body["moment"] == "checkout" and without_why(body["reason"]) == {
        "concept": "snacks-salados",
        "from_concept": "gaseosas",
    }
    assert {p["entity_id"] for p in body["products"]}.isdisjoint({PISCO, COLA})
    assert body["text"].startswith("Para completar lo que llevas") and "pisco" not in body["text"].lower()
    assert_offerable(body)

    mixed = offer(client, "checkout", {"cart": [item(BEER), item(CHIPS), item(DIAPERS)]}).json()
    assert mixed["reason"]["concept"] == "gaseosas"  # snacks ya está en el carrito, cerveza y bebé no se ofrecen
    assert_offerable(mixed)


def test_no_good_offer_is_204(client):
    for moment, context in (
        ("carrito", {"product": item(DIAPERS)}),  # solo complementa con dermocosmética (salud)
        ("carrito", {"product": item(PARACETAMOL)}),  # sensible
        ("carrito", {"product": item("123456789")}),  # un producto sin concepto
        ("checkout", {"cart": [item(DIAPERS), item(VITAMIN_C)]}),
        ("proximo_pedido", {"items": [item(PARACETAMOL)]}),
        ("sin_resultado", {"query": "xyzzy"}),  # no nombra ningún concepto
        ("sin_resultado", {"query": "cerveza helada"}),  # lo que se pide por su nombre no lo ofrece el agente sola
        ("sin_resultado", {"query": "pañales talla g"}),
    ):
        reply = offer(client, moment, context)
        assert reply.status_code == 204 and not reply.content, (moment, context)


def test_vertical_to_try_is_204_when_every_offerable_vertical_and_service_is_used(client, db):
    for vertical in ("supermercado", "conveniencia", "turbo", "chocolateria", "restaurantes", "mall"):
        order(db, "u1", vertical)
    assert offer(client, "vertical_por_probar", {}, "u1").json()["products"] == []  # el paso es un servicio
    opened = [{"servicio": "rappifavor"}, {"servicio": "rappitravel"}]  # ya usa los dos (test_offer_combo.py)
    events.record(db, [events.Event("u1", "s1", "service_opened", payload=payload) for payload in opened])

    reply = offer(client, "vertical_por_probar", {}, "u1")

    assert reply.status_code == 204 and not reply.content


def test_vertical_to_try_without_orders_starts_with_the_supermarket(client):
    first = offer(client, "vertical_por_probar", {})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["moment"] == "vertical_por_probar" and body["vertical"] == "supermercado"
    assert body["prototype_vertical"] == "grocery" and 1 <= len(body["products"]) <= 3
    assert body["text"] == "Aún no pides en el súper: mira estas ofertas."
    assert_offerable(body)  # la farmacia que Rappi lista entre los súper tiene ofertas y no sale


def test_vertical_to_try_skips_verticals_with_orders_and_pharmacy(client, db):
    # Pedidos en varias verticales; Licores y Farmacia no se proponen nunca, haya pedido o no.
    for vertical in ("supermercado", "conveniencia", "turbo"):
        order(db, "u1", vertical)
    after_three = offer(client, "vertical_por_probar", {}, "u1").json()
    # Turbo y retail: a su combinación le faltan los restaurantes (test_offer_combo.py)
    assert after_three["vertical"] == "restaurantes" and after_three["text"].endswith("lo que más piden.")

    order(db, "u1", "chocolateria")
    order(db, "u1", "restaurantes")
    mall = offer(client, "vertical_por_probar", {}, "u1").json()
    assert mall["vertical"] == "mall"  # con la combinación completa, la de siempre: salta Licores y Farmacia
    assert_offerable(mall)  # el sex shop y el smoking shop del mall tienen ofertas y no salen

    order(db, "u2", "supermercado")
    for vertical in ("conveniencia", "turbo", "chocolateria", "mall"):
        order(db, "u2", vertical)
    restaurants = offer(client, "vertical_por_probar", {}, "u2").json()
    assert restaurants["vertical"] == "restaurantes" and restaurants["text"].endswith("lo que más piden.")
    assert {p["entity_type"] for p in restaurants["products"]} == {"menu_item"}
    assert_offerable(restaurants)


def test_vertical_to_try_ignores_actual_mode_orders(client, db):
    order(db, "u1", "supermercado", mode="actual")  # «Rappi hoy»: no cuenta como probado

    body = offer(client, "vertical_por_probar", {}, "u1").json()

    assert body["vertical"] == "supermercado"


def test_vertical_to_try_ignores_the_orders_of_other_people(client, db):
    order(db, "u2", "supermercado")

    assert offer(client, "vertical_por_probar", {}, "u1").json()["vertical"] == "supermercado"
    assert offer(client, "vertical_por_probar", {}).json()["vertical"] == "supermercado"


def test_vertical_to_try_rejects_an_unknown_context(client):
    reply = offer(client, "vertical_por_probar", {"probadas": []})

    assert reply.status_code == 422


def test_vertical_to_try_reason_says_no_orders(client, db):
    order(db, "u1", "supermercado")

    body = offer(client, "vertical_por_probar", {}, "u1").json()

    assert body["vertical"] == "turbo"  # lo que más retiene sumarle al súper (sin población: sus ofertas de siempre)
    assert body["reason"]["text"] == "Porque aún no pides en Turbo."
    assert body["reason"]["basis"] == [
        {"kind": "combinacion", "id": "supermercado→turbo+supermercado", "source": "rappi"},
        {"kind": "sin_pedidos", "id": "turbo", "source": "contexto"},
    ]


def test_vertical_to_try_reason_keeps_the_article_of_the_label(client):
    body = offer(client, "vertical_por_probar", {}).json()

    assert body["vertical"] == "supermercado"
    assert body["reason"]["text"] == "Porque aún no pides en el súper."


def test_offer_texts_never_say_de_el_or_a_el(client):
    texts = []
    for occasion in client.get("/agent/plans").json():
        reply = offer(client, "plan", {"occasion": occasion["id"]})
        if reply.status_code == 200:
            texts += [reply.json()["text"], reply.json()["reason"]["text"]]
    assert texts
    for text in texts:
        assert " de el " not in text and " a el " not in text, text


def test_vertical_to_try_shows_what_is_typical_of_the_vertical_before_a_bigger_discount(client):
    """En el Súper de prueba las galletas (típicas de chocolaterías) tienen más descuento que el café, que es lo típico
    del súper: el café va primero y las otras completan hasta tres."""
    body = offer(client, "vertical_por_probar", {}).json()

    assert body["vertical"] == "supermercado"
    concepts = [p["concept"] for p in body["products"]]
    assert concepts[0] == "cafe"
    assert {"galletas", "gaseosas"} <= set(concepts) and len(concepts) == 3  # completa, no queda corta


def test_plans_lists_offerable_occasions_in_home_order(client):
    reply = client.get("/agent/plans")

    assert reply.status_code == 200
    plans = reply.json()
    ids = [p["id"] for p in plans]
    assert ids[:5] == ["once", "carrete", "asado", "panorama", "regalo"]
    assert "guagua" not in ids and "enfermo" not in ids and len(ids) == len(set(ids)) == 13
    # Sin guagua ni enfermo, ni las que solo sirven para entender preguntas (`plan = false`: picnic, frío)
    occasions = load_taxonomy().occasions
    assert set(ids) == {o for o in occasions if occasions[o].plan} - {"guagua", "enfermo"}
    assert plans[1] == {"id": "carrete", "name": "Carrete", "emoji": "🎉"}


def test_no_result_points_to_the_offerable_vertical_that_has_the_concept(client):
    reply = offer(client, "sin_resultado", {"query": "pizza hawaiana"})

    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["vertical"] == "restaurantes" and without_why(body["reason"]) == {"concept": "pizza"}
    assert body["text"] == "No encontré «pizza hawaiana», pero pizza sí hay en restaurantes."
    assert {p["concept"] for p in body["products"]} == {"pizza"} and len(body["products"]) <= 3
    assert_offerable(body)


def test_next_order_offers_a_complement_of_what_was_ordered(client):
    reply = offer(client, "proximo_pedido", {"items": [item(PIZZA_DISH, "menu_item")]})

    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert without_why(body["reason"]) == {
        "concept": "gaseosas",
        "from_concept": "pizza",
    }  # la cerveza de la pizza no se ofrece
    assert body["text"].startswith("Para tu próximo pedido: bebidas gaseosas")
    assert_offerable(body)


def test_invalid_requests_are_422(client):
    assert client.post("/agent/offer", json={"moment": "nada", "context": {}}).status_code == 422
    assert offer(client, "carrito", {"product": {"entity_type": "store", "entity_id": "1"}}).status_code == 422
    assert offer(client, "checkout", {"cart": []}).status_code == 422
    assert offer(client, "sin_resultado", {"query": ""}).status_code == 422
    assert offer(client, "plan", {}).status_code == 422


class RecordingEmbedder(HashEmbedder):
    def __init__(self):
        super().__init__()
        self.queries: list[str] = []

    def embed_queries(self, texts):
        self.queries += texts
        return super().embed_queries(texts)


def test_a_single_vertical_occasion_stays_in_its_vertical_and_embeds_each_concept_once(db):
    """«Hambre ya» es comida lista: el kit sale de restaurantes, sin repartirse. Cada concepto se embebe una vez."""
    seed_demo(db)
    embedder = RecordingEmbedder()
    embed_search_documents(db, embedder)
    embedder.queries.clear()
    api.app.dependency_overrides[api.get_conn] = lambda: (yield db)
    api.app.dependency_overrides[api.get_services] = lambda: Services(
        RappiAgent(embedder, TemplateComposer()), embedder
    )
    try:
        body = offer(TestClient(api.app), "plan", {"occasion": "hambre"}).json()
    finally:
        api.app.dependency_overrides.clear()

    assert load_taxonomy().occasions["hambre"].vertical == "restaurantes"
    assert len(body["products"]) >= 3 and {p["vertical"] for p in body["products"]} == {"restaurantes"}
    assert body["vertical"] == "restaurantes"
    assert embedder.queries and len(embedder.queries) == len(set(embedder.queries))  # nada se embebe dos veces


def test_a_kit_never_takes_a_concept_from_a_vertical_where_it_barely_exists(client, db):
    """El concepto se busca solo donde compite (masa mínima): un puñado de productos de otro lado no lo representa."""
    from rappi_ia.agent.verticals import contending_verticals

    for plan in client.get("/agent/plans").json():
        reply = offer(client, "plan", {"occasion": plan["id"]})
        fixed = load_taxonomy().occasions[plan["id"]].vertical
        for product in reply.json()["products"] if reply.status_code == 200 else []:
            allowed = set(contending_verticals(db, [product["concept"]]))
            assert product["vertical"] in allowed | {fixed}, (plan["id"], product["name"], product["vertical"])


def test_a_kit_is_still_built_without_an_embedding_model(db):
    """Sin modelo (RAPPI_IA_LIGHT=1) no hay búsqueda vectorial: el kit se busca por palabras, como siempre."""
    seed_demo(db)
    api.app.dependency_overrides[api.get_conn] = lambda: (yield db)
    api.app.dependency_overrides[api.get_services] = lambda: Services(RappiAgent(None, TemplateComposer()), None)
    try:
        reply = offer(TestClient(api.app), "plan", {"occasion": "carrete"})
    finally:
        api.app.dependency_overrides.clear()

    assert reply.status_code == 200 and len(reply.json()["products"]) >= 3


def test_every_moment_has_reason_text_and_basis(client):
    replies = {
        "plan": offer(client, "plan", {"occasion": "carrete"}),
        "carrito": offer(client, "carrito", {"product": item(CHIPS)}),
        "checkout": offer(client, "checkout", {"cart": [item(PISCO)]}),
        "proximo_pedido": offer(client, "proximo_pedido", {"items": [item(PIZZA_DISH, "menu_item")]}),
        "sin_resultado": offer(client, "sin_resultado", {"query": "pizza hawaiana"}),
        "vertical_por_probar": offer(client, "vertical_por_probar", {}),
    }

    for moment, reply in replies.items():
        assert reply.status_code == 200, (moment, reply.text)
        reason = reply.json()["reason"]
        assert reason["text"].startswith(("Porque ", "Por tu ", "Para ")), moment
        assert isinstance(reason["basis"], list), moment

    assert replies["plan"].json()["reason"]["text"] == "Porque elegiste «Carrete»."
    assert replies["plan"].json()["reason"]["basis"] == [{"kind": "ocasion", "id": "carrete", "source": "contexto"}]
    assert replies["carrito"].json()["reason"]["text"] == "Porque llevas 🥨 snacks salados."
    assert replies["sin_resultado"].json()["reason"]["text"] == "Porque buscaste «pizza hawaiana» y aquí sí hay."
    assert replies["sin_resultado"].json()["reason"]["basis"] == [
        {"kind": "busqueda", "id": "pizza hawaiana", "source": "contexto"}
    ]
    to_try = replies["vertical_por_probar"].json()
    assert to_try["reason"]["text"] == "Porque aún no pides en el súper."
    assert to_try["reason"]["basis"] == [{"kind": "sin_pedidos", "id": to_try["vertical"], "source": "contexto"}]
    assert "text" in to_try["reason"] and "basis" in to_try["reason"]


def test_a_non_offerable_origin_is_not_named_in_the_reason(client):
    beer = offer(client, "carrito", {"product": item(BEER)}).json()["reason"]

    assert beer["text"] == "Para completar lo que llevas." and beer["basis"] == []
    pisco = offer(client, "checkout", {"cart": [item(PISCO)]}).json()["reason"]
    assert pisco["text"] == "Para completar lo que llevas." and pisco["basis"] == []
