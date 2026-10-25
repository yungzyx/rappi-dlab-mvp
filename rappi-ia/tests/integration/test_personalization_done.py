"""Hecho cuando (etapa 5): dos personas con historias distintas reciben ofertas distintas, y cada porqué se puede
rastrear hasta algo que esa persona hizo. La preparación (`people`, en `personal_helpers.py`) usa solo la API."""

import pytest
from personal_helpers import COFFEE, GRILL, SWEET, SWEET_BRAND, prepare_people

from rappi_ia.concepts.taxonomy import load_taxonomy


@pytest.fixture
def people(db, monkeypatch):
    yield from prepare_people(db, monkeypatch)


def to_try(client, user):
    reply = client.post("/agent/offer", json={"moment": "vertical_por_probar", "user_id": user, "context": {}})
    assert reply.status_code == 200, reply.text
    return reply.json()


def plans(client, user):
    reply = client.get("/agent/plans", params={"user_id": user})
    assert reply.status_code == 200, reply.text
    return reply.json()


def checkout(client, user):
    """Un carro con café y una torta: su complemento son las galletas, que en la chocolatería son dos."""
    cart = [{"entity_type": "catalog_item", "entity_id": i} for i in (COFFEE, "97004")]
    body = {"moment": "checkout", "context": {"cart": cart}, "user_id": user}
    reply = client.post("/agent/offer", json=body)
    assert reply.status_code == 200, reply.text
    return reply.json()


def names_top_concept_of_basis(reason):
    """El texto de la razón nombra el concepto que más suma en su propia base (con margen para un empate)."""
    totals: dict[str, float] = {}
    for signal in reason["basis"]:
        totals[signal["id"]] = totals.get(signal["id"], 0) + signal["score"]
    concepts = load_taxonomy().concepts
    return any(
        concepts[c].name.lower() in reason["text"]
        for c, total in totals.items()
        if total >= max(totals.values()) - 0.01
    )


def assert_traceable(db, user, reason, history):
    """Cada señal de la base viene de algo que la persona hizo: sus eventos, un segmento suyo (con ese concepto en su
    evidencia) o sus pedidos; y las de concepto son de su historia."""
    assert reason["basis"]
    for signal in reason["basis"]:
        assert signal["kind"] == "concepto" and signal["id"] in history and signal["score"] > 0, signal
        if signal["source"].startswith("segmento:"):
            segment = signal["source"].removeprefix("segmento:")
            evidence = db.execute(
                "SELECT evidence FROM user_segments WHERE user_id = %s AND segment_id = %s", (user, segment)
            ).fetchone()
            assert evidence and signal["id"] in {t["id"] for t in evidence[0]["top"]}, signal
        else:
            assert signal["source"] == "eventos", signal
    assert "eventos" in {s["source"] for s in reason["basis"]}  # lo que hizo en la app siempre suma


def test_two_users_with_different_histories_get_different_offers(people, db):
    client = people.client
    histories = {SWEET: people.sweet_history, GRILL: people.grill_history}

    to_try_offers = {user: to_try(client, user) for user in histories}
    first_plans = {user: plans(client, user)[0] for user in histories}

    # Cada una ya pidió en la vertical que le gusta (chocolatería y súper), las dos de retail: la vertical por probar
    # es la que más retiene sumarles (Turbo) y se explica con sus pedidos, no con sus gustos.
    for user in histories:
        offered = to_try_offers[user]
        ordered = {v for (v,) in db.execute("SELECT vertical FROM app_orders WHERE user_id = %s", (user,))}
        assert offered["vertical"] == "turbo" and offered["vertical"] not in ordered
        [vertical] = ordered
        assert offered["reason"]["basis"] == [
            {"kind": "combinacion", "id": f"{vertical}→turbo+{vertical}", "source": "rappi"},
            {"kind": "sin_pedidos", "id": "turbo", "source": "contexto"},
        ]
    assert first_plans[SWEET]["id"] != first_plans[GRILL]["id"]
    assert (first_plans[SWEET]["id"], first_plans[GRILL]["id"]) == ("antojo", "asado")
    for user, history in histories.items():
        reason = first_plans[user]["reason"]
        assert reason["text"].startswith("Por tu interés en")
        assert names_top_concept_of_basis(reason), reason
        assert_traceable(db, user, reason, history)


def test_complement_puts_the_brand_you_buy_first(people, db):
    client = people.client
    anonymous = checkout(client, None)
    sweet, grill = checkout(client, SWEET), checkout(client, GRILL)

    ids = [p["entity_id"] for p in anonymous["products"]]
    assert people.sweet_brand_product in ids and ids[0] != people.sweet_brand_product  # no era la primera
    assert [p["entity_id"] for p in sweet["products"]][0] == people.sweet_brand_product
    assert sweet["reason"]["text"].endswith(f" Es {SWEET_BRAND[1]}, la marca que compras.")
    assert not any(s["kind"] == "combinacion" for s in sweet["reason"]["basis"])  # su marca gana al desempate
    brand = [s for s in sweet["reason"]["basis"] if s["kind"] == "marca"]
    assert brand == [{"kind": "marca", "id": SWEET_BRAND[0], "score": 2, "source": "pedidos"}]  # sus dos pedidos
    ordered = db.execute(
        """SELECT count(DISTINCT o.order_id) FROM app_orders o JOIN app_order_lines l USING (order_id)
           JOIN item_brands b ON b.entity_type = l.entity_type AND b.entity_id = l.entity_id
           WHERE o.user_id = %s AND b.brand_key = %s""",
        (SWEET, SWEET_BRAND[0]),
    ).fetchone()[0]
    assert ordered == brand[0]["score"]  # rastreable hasta sus pedidos
    # Quien no compra esa marca no la ve nombrada. Sin una marca suya, entre complementos parecidos gana el que completa
    # su combinación (solo pide en Retail: el té helado de Turbo), y la base lo dice.
    assert not any(s["kind"] == "marca" for s in grill["reason"]["basis"])
    assert "la marca que compras" not in grill["reason"]["text"]
    step = {"kind": "combinacion", "id": "supermercado→turbo+supermercado", "source": "rappi"}
    assert step in grill["reason"]["basis"]
