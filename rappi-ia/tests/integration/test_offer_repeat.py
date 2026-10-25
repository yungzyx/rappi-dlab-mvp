"""La recompra («¿Repetimos?»): lo que la persona pide con ritmo (`replenishment`, del motor) y está por tocarle, con el
último producto que compró si sigue a la venta en esa vertical. Sobre el catálogo de prueba (`seed_demo`)."""

from datetime import date, datetime, time, timedelta

import pytest

from owner_client import OwnerClient
from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.rappi_agent import RappiAgent
from rappi_ia.api import app as api
from rappi_ia.api.services import Services
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents
from rappi_ia.events import store as events
from rappi_ia.motor.build import refresh_user_conn
from rappi_ia.motor.model import TZ
from rappi_ia.offers.engine import _days_ago, _every


def today():
    """El día de hoy en Santiago al momento de usarlo (no al importar: una corrida que cruza la medianoche dejaba
    los pedidos un día corridos respecto del día que usa la API)."""
    return datetime.now(TZ).date()


COFFEE = ("catalog_item", "91004")  # café molido, solo en el súper
COLA_SMALL = ("catalog_item", "92001")  # gaseosa de 500 cc: Express y Turbo, no el súper
DIAPERS = ("catalog_item", "91007")


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


def repeat(client, user_id="u-ritmo", context=None):
    body = {"moment": "recompra", "context": context or {}}
    if user_id:
        body["user_id"] = user_id
    return client.post("/agent/offer", json=body)


def bought(db, user, vertical, concept, entity, days_ago, mode="propuesta"):
    """Un pedido a mediodía (hora de Santiago) de hace `days_ago` días."""
    day = today() - timedelta(days=days_ago)
    line = {"entity_type": entity[0], "entity_id": entity[1], "concept_id": concept, "unit_price": 1990}
    events.record_order(
        db, user, f"s-{concept}-{days_ago}", f"c-{user}-{concept}-{days_ago}-{mode}", vertical, [line],
        ts=datetime.combine(day, time(12), TZ), mode=mode,
    )  # fmt: skip


def rhythm(db, user, vertical, concept, entity, last_days_ago, every=7, times=3):
    """`times` pedidos del concepto cada `every` días; el último hace `last_days_ago` días. Recalcula su recompra."""
    for n in range(times):
        bought(db, user, vertical, concept, entity, last_days_ago + n * every)
    refresh_user_conn(db, user)


def test_what_is_due_today_comes_with_the_last_product_and_says_why(client, db):
    rhythm(db, "u-ritmo", "supermercado", "cafe", COFFEE, last_days_ago=7)

    reply = repeat(client)

    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["moment"] == "recompra"
    assert body["text"] == "¿Repetimos café? Pides cada 7 días."
    assert body["reason"] == {
        "concept": "cafe",
        "text": "Porque pides café cada 7 días y tu último pedido fue hace 7 días.",
        "basis": [{"kind": "recompra", "id": "cafe", "source": "pedidos"}],
    }
    assert body["vertical"] == "supermercado" and body["prototype_vertical"] == "grocery"
    [product] = body["products"]
    assert (product["entity_type"], product["entity_id"]) == COFFEE
    assert product["vertical"] == "supermercado" and product["price_value"]
    assert body["actions"] == [{"label": "Ver producto", "route": ["grocery"], "store_id": product["store_id"]}]


@pytest.mark.parametrize(
    ("last_days_ago", "offered"),
    [
        (5, True),  # le toca en 2 días: ya se ofrece
        (4, False),  # en 3 días: todavía no
        (14, True),  # le tocó hace 7 días (un intervalo): todavía
        (15, False),  # hace 8: ya pasó
    ],
)
def test_the_window_goes_from_one_interval_late_to_two_days_early(client, db, last_days_ago, offered):
    rhythm(db, "u-ritmo", "supermercado", "cafe", COFFEE, last_days_ago=last_days_ago)

    assert repeat(client).status_code == (200 if offered else 204)


def test_the_most_overdue_concept_goes_first(client, db):
    rhythm(db, "u-ritmo", "supermercado", "cafe", COFFEE, last_days_ago=7)  # le toca hoy
    rhythm(db, "u-ritmo", "supermercado", "galletas", ("catalog_item", "91002"), last_days_ago=10)  # hace 3 días

    body = repeat(client).json()

    assert body["reason"]["concept"] == "galletas"
    assert body["reason"]["text"] == "Porque pides galletas cada 7 días y tu último pedido fue hace 10 días."


def test_a_product_no_longer_sold_in_the_vertical_is_replaced_by_one_of_the_concept(client, db):
    # Pide la gaseosa chica en el súper (que no la vende): se busca otra gaseosa del súper.
    rhythm(db, "u-ritmo", "supermercado", "gaseosas", COLA_SMALL, last_days_ago=7)

    body = repeat(client).json()

    [product] = body["products"]
    assert product["concept"] == "gaseosas" and product["vertical"] == "supermercado"
    assert product["entity_id"] != COLA_SMALL[1]


def test_what_the_agent_does_not_push_is_never_repeated(client, db):
    rhythm(db, "u-ritmo", "supermercado", "panales", DIAPERS, last_days_ago=9)  # bebé, el más atrasado
    rhythm(db, "u-ritmo", "licores", "cerveza", ("catalog_item", "94001"), last_days_ago=8)  # alcohol, en Licores
    assert repeat(client).status_code == 204

    rhythm(db, "u-ritmo", "supermercado", "cafe", COFFEE, last_days_ago=7)
    assert repeat(client).json()["reason"]["concept"] == "cafe"


def test_without_a_person_or_a_rhythm_there_is_nothing(client, db):
    assert repeat(client, user_id=None).status_code == 204
    bought(db, "u-ritmo", "supermercado", "cafe", COFFEE, 7)  # una sola vez: no hay ritmo
    refresh_user_conn(db, "u-ritmo")
    assert repeat(client).status_code == 204


def test_orders_in_rappi_hoy_do_not_teach_a_rhythm(client, db):
    for days in (7, 14, 21):
        bought(db, "u-ritmo", "supermercado", "cafe", COFFEE, days, mode="actual")
    refresh_user_conn(db, "u-ritmo")

    assert repeat(client).status_code == 204


def test_a_forgotten_concept_does_not_come_back(client, db):
    rhythm(db, "u-ritmo", "supermercado", "cafe", COFFEE, last_days_ago=7)
    assert repeat(client).status_code == 200

    assert client.delete("/profile/u-ritmo", params={"concept": "cafe"}).status_code == 200

    assert repeat(client).status_code == 204


def test_the_context_is_empty_and_strict(client):
    assert repeat(client, context={"concept": "cafe"}).status_code == 422


def test_a_daily_rhythm_reads_every_day(client, db):
    rhythm(db, "u-ritmo", "supermercado", "cafe", COFFEE, last_days_ago=1, every=1)

    body = repeat(client).json()

    assert body["text"] == "¿Repetimos café? Pides cada día."
    assert body["reason"]["text"] == "Porque pides café cada día y tu último pedido fue ayer."


def test_every_reads_in_spanish():
    assert _every(1) == "cada día"
    assert _every(2) == "cada 2 días"
    assert _every(14) == "cada 14 días"


def test_days_ago_reads_in_spanish():
    noon = datetime.combine(date(2026, 10, 16), time(12), TZ)
    assert _days_ago(date(2026, 10, 16), noon) == "hoy"
    assert _days_ago(date(2026, 10, 17), noon) == "ayer"
    assert _days_ago(date(2026, 10, 23), noon) == "hace 7 días"
