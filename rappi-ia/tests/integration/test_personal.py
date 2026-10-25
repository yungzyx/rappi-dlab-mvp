"""Las señales de una persona para ofrecer (`offers/personal.py`): eventos, segmentos no sensibles y marcas."""

from datetime import UTC, datetime, timedelta

from psycopg.types.json import Jsonb

from rappi_ia.concepts.store import seed_taxonomy
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.events import store as events
from rappi_ia.offers.personal import MIN_BRAND_ORDERS, Interests, Signal, bought_brands, user_interests

NOW = datetime.now(UTC)


def _search(db, user, concept, days_ago=0, source="prototype"):
    events.record(
        db,
        [events.Event(user, "s1", "cart_add", ts=NOW - timedelta(days=days_ago), concept_id=concept, cart_id="c1")],
        source=source,
    )


def _segment(db, segment_id, sensitive=False):
    db.execute(
        """INSERT INTO segment_defs (segment_id, name, family, sensitive, rule, rules_version)
           VALUES (%s, %s, 'prueba', %s, '{}', 'test') ON CONFLICT DO NOTHING""",
        (segment_id, segment_id, sensitive),
    )


def _give_segment(db, user, segment_id, level, top):
    db.execute(
        """INSERT INTO user_segments (user_id, segment_id, score, level, signals, evidence)
           VALUES (%s, %s, 1, %s, 3, %s)""",
        (user, segment_id, level, Jsonb({"top": [{"kind": k, "id": i, "score": 1.0} for k, i in top]})),
    )


def _brand(db, brand_key, kind="marca", store_brand=False):
    db.execute(
        "INSERT INTO product_brands (brand_key, name, kind, is_store_brand) VALUES (%s, %s, %s, %s)"
        " ON CONFLICT DO NOTHING",
        (brand_key, brand_key, kind, store_brand),
    )


def _buy_brand(db, user, brand_key, product, kind="marca", source="prototype", store_brand=False):
    """Un pedido de un producto de esa marca."""
    _brand(db, brand_key, kind, store_brand)
    db.execute(
        """INSERT INTO item_brands (entity_type, entity_id, brand_key, source)
           VALUES ('catalog_item', %s, %s, 'regla') ON CONFLICT DO NOTHING""",
        (str(product), brand_key),
    )
    events.record_order(
        db, user, "s1", f"c-{user}-{product}", "supermercado",
        [{"entity_type": "catalog_item", "entity_id": str(product), "unit_price": 1000}],
        source=source,
    )  # fmt: skip


def test_interests_combine_events_and_non_sensitive_segments(db):
    seed_taxonomy(db, load_taxonomy())
    _search(db, "u1", "pizza")
    _segment(db, "pizzero")
    _give_segment(db, "u1", "pizzero", "alto", [("concepto", "pizza"), ("atributo", "economico")])

    interests = user_interests(db, "u1")

    event_score = events.profile(db, "u1")["pizza"]
    assert list(interests.concepts) == ["pizza"]
    assert abs(interests.concepts["pizza"] - (event_score + 3.0)) < 0.01  # el atributo del segmento no suma
    assert [(s.kind, s.id, s.source) for s in interests.basis["pizza"]] == [
        ("concepto", "pizza", "eventos"),
        ("concepto", "pizza", "segmento:pizzero"),
    ]
    assert interests.top(5) == ["pizza"]


def test_segment_levels_weigh_one_two_and_three(db):
    seed_taxonomy(db, load_taxonomy())
    db.execute("INSERT INTO app_users (user_id, source) VALUES ('u1', 'prototype')")
    for level, concept in (("bajo", "pizza"), ("medio", "galletas")):
        _segment(db, f"seg-{level}")
        _give_segment(db, "u1", f"seg-{level}", level, [("concepto", concept)])

    assert user_interests(db, "u1").concepts == {"galletas": 2.0, "pizza": 1.0}


def test_sensitive_segment_is_never_read(db):
    seed_taxonomy(db, load_taxonomy())
    db.execute("INSERT INTO app_users (user_id, source) VALUES ('u1', 'prototype')")
    _segment(db, "sensible", sensitive=True)
    _give_segment(db, "u1", "sensible", "alto", [("concepto", "pizza")])

    assert user_interests(db, "u1") == Interests.empty()


def test_non_offerable_concepts_are_dropped(db):
    seed_taxonomy(db, load_taxonomy())
    for concept in ("cerveza", "panales", "medicamentos", "pizza"):
        _search(db, "u1", concept)
    _segment(db, "mixto")
    _give_segment(db, "u1", "mixto", "alto", [("concepto", "cerveza"), ("concepto", "no-existe")])

    assert list(user_interests(db, "u1").concepts) == ["pizza"]


def test_anonymous_and_synthetic_users_have_no_interests(db):
    seed_taxonomy(db, load_taxonomy())
    _search(db, "u-syn", "pizza", source="synthetic")
    _segment(db, "pizzero")
    _give_segment(db, "u-syn", "pizzero", "alto", [("concepto", "pizza")])

    assert user_interests(db, None) == Interests.empty()
    assert user_interests(db, "u-syn") == Interests.empty()
    assert user_interests(db, "nadie") == Interests.empty()


def test_interests_are_sorted_from_highest_and_to_dict(db):
    seed_taxonomy(db, load_taxonomy())
    _search(db, "u1", "galletas")
    _search(db, "u1", "pizza")
    _search(db, "u1", "pizza")

    interests = user_interests(db, "u1")

    assert interests.top(1) == ["pizza"] and interests.top(5) == ["pizza", "galletas"]
    assert Signal("concepto", "pizza", 6.0, "eventos").to_dict() == {
        "kind": "concepto", "id": "pizza", "score": 6.0, "source": "eventos",
    }  # fmt: skip
    assert Interests.empty().concepts == {} and Interests.empty().top(3) == []


def test_bought_brands_need_two_orders(db):
    seed_taxonomy(db, load_taxonomy())
    _buy_brand(db, "u1", "soprole", 1)
    _buy_brand(db, "u1", "nestle", 2)
    _buy_brand(db, "u1", "nestle", 3)
    _buy_brand(db, "u2", "soprole", 1)  # otra persona: no suma

    assert MIN_BRAND_ORDERS == 2
    assert bought_brands(db, "u1") == {"nestle": 2}
    assert user_interests(db, "u1").brands == {"nestle": 2}


def test_two_lines_of_a_brand_in_one_order_count_once(db):
    seed_taxonomy(db, load_taxonomy())
    _brand(db, "soprole")
    for product in (1, 2):
        db.execute(
            """INSERT INTO item_brands (entity_type, entity_id, brand_key, source)
               VALUES ('catalog_item', %s, 'soprole', 'regla')""",
            (str(product),),
        )
    events.record_order(
        db, "u1", "s1", "c1", "supermercado",
        [{"entity_type": "catalog_item", "entity_id": str(p), "unit_price": 1000} for p in (1, 2)],
    )  # fmt: skip

    assert bought_brands(db, "u1") == {}


def test_chain_brands_do_not_count(db):
    seed_taxonomy(db, load_taxonomy())
    _buy_brand(db, "u1", "mcdonalds", 1, kind="cadena")
    _buy_brand(db, "u1", "mcdonalds", 2, kind="cadena")

    assert bought_brands(db, "u1") == {}


def test_store_brands_do_not_count(db):
    seed_taxonomy(db, load_taxonomy())
    _buy_brand(db, "u1", "great-value", 1, store_brand=True)
    _buy_brand(db, "u1", "great-value", 2, store_brand=True)
    _buy_brand(db, "u1", "nestle", 3)
    _buy_brand(db, "u1", "nestle", 4)

    assert bought_brands(db, "u1") == {"nestle": 2}


def test_bought_brands_is_empty_for_synthetic_and_unknown_users(db):
    seed_taxonomy(db, load_taxonomy())
    _buy_brand(db, "u-syn", "nestle", 1, source="synthetic")
    _buy_brand(db, "u-syn", "nestle", 2, source="synthetic")

    assert bought_brands(db, "u-syn") == {} and bought_brands(db, "nadie") == {} and bought_brands(db, None) == {}


def test_equal_scores_are_ordered_by_concept_id(db):
    seed_taxonomy(db, load_taxonomy())
    db.execute("INSERT INTO app_users (user_id, source) VALUES ('u1', 'prototype')")
    _segment(db, "seg")
    _give_segment(db, "u1", "seg", "medio", [("concepto", "pizza"), ("concepto", "galletas"), ("concepto", "helados")])

    assert list(user_interests(db, "u1").concepts) == ["galletas", "helados", "pizza"]
