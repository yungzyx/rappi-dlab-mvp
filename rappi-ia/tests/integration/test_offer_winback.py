"""«¿Volvemos a…?» (momento `volver`): lo que la persona pedía con ritmo y dejó de pedir (un concepto atrasado más de un
intervalo, o una vertical sin pedidos en más de un mes mientras pide en otra). La pausa es por persona: 7 días después
de mostrar una, solo esa; y hasta que la descarte dos veces. Sobre el catálogo de prueba (`seed_demo`)."""

from datetime import UTC, datetime, time, timedelta

import pytest
from psycopg.types.json import Jsonb

from owner_client import OwnerClient
from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.rappi_agent import RappiAgent
from rappi_ia.api import app as api
from rappi_ia.api.services import Services
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents
from rappi_ia.events import store as events
from rappi_ia.motor.build import build_motor, refresh_user_conn
from rappi_ia.motor.model import TZ
from rappi_ia.offers.winback import reach


def today():
    """El día de hoy en Santiago al momento de usarlo (no al importar: una corrida que cruza la medianoche dejaba
    los pedidos un día corridos respecto del día que usa la API)."""
    return datetime.now(TZ).date()


USER = "u-volver"
COFFEE = ("catalog_item", "91004")  # café molido, solo en el súper
COOKIES = ("catalog_item", "91002")
DIAPERS = ("catalog_item", "91007")
ICE_CREAM = ("catalog_item", "93001")  # helado, solo en Turbo
PARACETAMOL = ("catalog_item", "95001")  # farmacia


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


def offer(client, moment="volver", user_id=USER, context=None):
    body = {"moment": moment, "context": context or {}}
    if user_id:
        body["user_id"] = user_id
    return client.post("/agent/offer", json=body)


def bought(db, user, vertical, concept, entity, days_ago, mode="propuesta", source="prototype"):
    """Un pedido a mediodía (hora de Santiago) de hace `days_ago` días."""
    ts = datetime.combine(today() - timedelta(days=days_ago), time(12), TZ)
    line = {"entity_type": entity[0], "entity_id": entity[1], "concept_id": concept, "unit_price": 1990}
    cart = f"c-{user}-{vertical}-{concept}-{days_ago}-{mode}"
    events.record_order(db, user, f"s-{days_ago}", cart, vertical, [line], source=source, ts=ts, mode=mode)


def rhythm(db, user, vertical, concept, entity, last_days_ago, every=7, times=3, mode="propuesta"):
    """`times` pedidos del concepto cada `every` días; el último hace `last_days_ago` días. Recalcula su motor."""
    for n in range(times):
        bought(db, user, vertical, concept, entity, last_days_ago + n * every, mode=mode)
    refresh_user_conn(db, user)


def left_vertical(db, user, vertical, entity, last_days_ago, times=3, mode="propuesta"):
    """`times` pedidos sin concepto (no arman recompra) en la vertical, cada 10 días; el último hace `last_days_ago`."""
    for n in range(times):
        bought(db, user, vertical, None, entity, last_days_ago + n * 10, mode=mode)


def still_ordering(db, user, days_ago=5):
    bought(db, user, "supermercado", None, COOKIES, days_ago)
    refresh_user_conn(db, user)


def event(db, kind, concept=None, vertical=None, days_ago=0, mode=None, user=USER, of="volver"):
    """Un evento de la app con origen `agent-volver`; `of` es su `payload.kind` («volver» o «vuelta»)."""
    payload = {"origen": "agent-volver", "kind": of, **({"mode": mode} if mode else {})}
    events.ensure_user(db, user, "prototype")
    db.execute(
        """INSERT INTO app_events (user_id, session_id, ts, type, vertical, concept_id, payload, source)
           VALUES (%s, 's-ev', %s, %s, %s, %s, %s, 'prototype')""",
        (user, datetime.now(UTC) - timedelta(days=days_ago, hours=1), kind, vertical, concept, Jsonb(payload)),
    )


def test_a_concept_left_behind_comes_with_its_last_product_and_says_why(client, db):
    rhythm(db, USER, "supermercado", "cafe", COFFEE, last_days_ago=20)

    reply = offer(client)

    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["moment"] == "volver"
    assert body["text"] == "¿Volvemos a café? La última vez que pediste café fue hace 20 días."
    assert body["reason"] == {
        "concept": "cafe",
        "text": "Porque pedías café cada 7 días y la última vez fue hace 20 días.",
        "basis": [{"kind": "volver", "id": "cafe", "source": "pedidos"}],
    }
    assert body["vertical"] == "supermercado" and body["prototype_vertical"] == "grocery"
    [product] = body["products"]
    assert (product["entity_type"], product["entity_id"]) == COFFEE
    assert body["actions"] == [{"label": "Ver producto", "route": ["grocery"], "store_id": product["store_id"]}]


@pytest.mark.parametrize(
    ("every", "last_days_ago", "winback", "repeat"),
    [
        (7, 14, False, True),  # le tocó hace un intervalo: todavía es la recompra
        (7, 15, True, False),  # un día más: ya es volver, y la recompra no
        (7, 90, True, False),  # hasta 90 días
        (7, 91, False, False),  # más ya no se le recuerda
        (3, 10, False, False),  # atrasado más de un intervalo, pero menos de 14 días no es dejar de pedir
        (3, 14, True, False),
    ],
)
def test_the_window_starts_where_the_repeat_ends(client, db, every, last_days_ago, winback, repeat):
    rhythm(db, USER, "supermercado", "cafe", COFFEE, last_days_ago=last_days_ago, every=every)

    assert offer(client).status_code == (200 if winback else 204)
    assert offer(client, "recompra").status_code == (200 if repeat else 204)


def test_a_vertical_left_while_ordering_elsewhere(client, db):
    left_vertical(db, USER, "turbo", ICE_CREAM, last_days_ago=40)
    still_ordering(db, USER)

    body = offer(client).json()

    assert body["text"] == "¿Volvemos a Turbo? Tu último pedido ahí fue hace 40 días."
    assert body["reason"] == {
        "text": "Porque pediste 3 veces en Turbo y tu último pedido ahí fue hace 40 días.",
        "basis": [{"kind": "vuelta", "id": "turbo", "source": "pedidos"}],
    }
    [product] = body["products"]
    assert (product["entity_type"], product["entity_id"]) == ICE_CREAM and product["vertical"] == "turbo"
    assert body["actions"][0]["route"] == ["turbo"]


@pytest.mark.parametrize(
    ("times", "last_days_ago", "elsewhere", "offered"),
    [
        (2, 40, True, False),  # dos días no son un ritmo
        (3, 30, True, False),  # un mes justo todavía no
        (3, 40, False, False),  # sin pedidos en otra parte: no se le invita a volver a una vertical
        (3, 91, True, False),  # más de 90 días
    ],
)
def test_a_vertical_needs_a_rhythm_a_month_away_and_orders_elsewhere(
    client, db, times, last_days_ago, elsewhere, offered
):
    left_vertical(db, USER, "turbo", ICE_CREAM, last_days_ago=last_days_ago, times=times)
    if elsewhere:
        still_ordering(db, USER)

    assert offer(client).status_code == (200 if offered else 204)


def test_a_concept_goes_before_a_vertical(client, db):
    left_vertical(db, USER, "turbo", ICE_CREAM, last_days_ago=40)
    rhythm(db, USER, "supermercado", "cafe", COFFEE, last_days_ago=20)
    still_ordering(db, USER)

    assert offer(client).json()["reason"]["basis"][0] == {"kind": "volver", "id": "cafe", "source": "pedidos"}


def test_shown_in_the_last_week_the_same_invitation_stays_and_no_other(client, db):
    rhythm(db, USER, "supermercado", "cafe", COFFEE, last_days_ago=20)
    left_vertical(db, USER, "turbo", ICE_CREAM, last_days_ago=40)
    still_ordering(db, USER)
    # La primera es café; se le mostró la de Turbo hace 6 días: la pausa es por persona y vuelve esa, no café.
    event(db, "suggestion_shown", vertical="turbo", concept="helados", days_ago=6, of="vuelta")

    assert offer(client).json()["reason"]["basis"][0] == {"kind": "vuelta", "id": "turbo", "source": "pedidos"}

    db.execute("UPDATE app_events SET ts = ts - interval '2 days' WHERE type = 'suggestion_shown'")
    assert offer(client).json()["reason"]["concept"] == "cafe"  # pasada la semana, la mejor otra vez


def test_the_next_invitation_does_not_take_the_place_of_one_shown_lately(client, db):
    rhythm(db, USER, "supermercado", "cafe", COFFEE, last_days_ago=20)
    left_vertical(db, USER, "turbo", ICE_CREAM, last_days_ago=40)
    still_ordering(db, USER)
    event(db, "suggestion_shown", concept="cafe", vertical="supermercado", days_ago=1)

    assert offer(client).json()["reason"]["concept"] == "cafe"  # la misma, no la de Turbo


def test_shown_lately_and_no_longer_due_means_nothing_else_this_week(client, db):
    rhythm(db, USER, "supermercado", "cafe", COFFEE, last_days_ago=20)
    left_vertical(db, USER, "turbo", ICE_CREAM, last_days_ago=40)
    still_ordering(db, USER)
    event(db, "suggestion_shown", concept="cafe", vertical="supermercado", days_ago=1)
    bought(db, USER, "supermercado", "cafe", COFFEE, 0)  # volvió a pedir café (el motor aún no lo recalcula)

    assert offer(client).status_code == 204  # Turbo también califica, pero no antes de una semana


def test_a_concept_invitation_is_not_the_invitation_of_its_vertical(client, db):
    # Ayer se mostró una invitación de concepto (galletas) en el súper; la persona dejó el súper como vertical, pero esa
    # es otra invitación: no es «la misma», así que durante la pausa no hay nada. Si se mostró la del súper, vuelve.
    left_vertical(db, USER, "supermercado", COOKIES, last_days_ago=40)
    bought(db, USER, "turbo", None, ICE_CREAM, 3)
    refresh_user_conn(db, USER)
    event(db, "suggestion_shown", concept="galletas", vertical="supermercado", days_ago=1)
    assert offer(client).status_code == 204

    event(db, "suggestion_shown", concept="galletas", vertical="supermercado", days_ago=1, of="vuelta")
    assert offer(client).json()["reason"]["basis"][0] == {"kind": "vuelta", "id": "supermercado", "source": "pedidos"}


def test_a_vertical_without_a_product_with_concept_is_not_offered(client, db):
    # Lo único que pidió en Turbo es un plato sin concepto en el catálogo: sin concepto la app no registra la mostrada
    # y la pausa no empezaría.
    db.execute("DELETE FROM item_concepts WHERE entity_type = 'catalog_item' AND entity_id = %s", (ICE_CREAM[1],))
    left_vertical(db, USER, "turbo", ICE_CREAM, last_days_ago=40)
    still_ordering(db, USER)

    assert offer(client).status_code == 204


def test_dismissed_twice_since_the_last_order_it_stops(client, db):
    rhythm(db, USER, "supermercado", "cafe", COFFEE, last_days_ago=20)
    event(db, "suggestion_dismissed", concept="cafe", vertical="supermercado", days_ago=10)
    assert offer(client).status_code == 200  # una vez: sigue

    event(db, "suggestion_dismissed", concept="cafe", vertical="supermercado", days_ago=9)
    assert offer(client).status_code == 204


def test_dismissals_of_another_kind_do_not_count(client, db):
    left_vertical(db, USER, "supermercado", COOKIES, last_days_ago=40)
    bought(db, USER, "turbo", None, ICE_CREAM, 3)
    refresh_user_conn(db, USER)
    for days in (10, 9):  # descartó dos veces café en el súper (de concepto), no la vertical
        event(db, "suggestion_dismissed", concept="cafe", vertical="supermercado", days_ago=days)

    assert offer(client).json()["reason"]["basis"][0]["kind"] == "vuelta"


def test_dismissals_before_the_last_order_do_not_count(client, db):
    event(db, "suggestion_dismissed", concept="cafe", vertical="supermercado", days_ago=40)
    event(db, "suggestion_dismissed", concept="cafe", vertical="supermercado", days_ago=39)
    rhythm(db, USER, "supermercado", "cafe", COFFEE, last_days_ago=20)

    assert offer(client).status_code == 200


def test_what_happens_in_rappi_hoy_does_not_count(client, db):
    rhythm(db, USER, "supermercado", "cafe", COFFEE, last_days_ago=20)
    event(db, "suggestion_shown", concept="cafe", vertical="supermercado", days_ago=1, mode="actual")
    for days in (3, 2):
        event(db, "suggestion_dismissed", concept="cafe", vertical="supermercado", days_ago=days, mode="actual")
    assert offer(client).status_code == 200


def test_orders_in_rappi_hoy_teach_nothing(client, db):
    rhythm(db, USER, "supermercado", "cafe", COFFEE, last_days_ago=20, mode="actual")
    left_vertical(db, USER, "turbo", ICE_CREAM, last_days_ago=40, mode="actual")
    still_ordering(db, USER)

    assert offer(client).status_code == 204


def test_what_the_agent_does_not_push_is_never_offered(client, db):
    rhythm(db, USER, "supermercado", "panales", DIAPERS, last_days_ago=20)  # bebé
    rhythm(db, USER, "licores", "cerveza", ("catalog_item", "94001"), last_days_ago=20)  # alcohol, en Licores
    left_vertical(db, USER, "farmacia", PARACETAMOL, last_days_ago=40)  # Farmacia
    left_vertical(db, USER, "licores", ("catalog_item", "94002"), last_days_ago=40)  # Licores
    still_ordering(db, USER)

    assert offer(client).status_code == 204


def test_a_sensitive_concept_is_never_offered_even_if_the_table_had_it(client, db):
    rhythm(db, USER, "supermercado", "cafe", COFFEE, last_days_ago=20)
    db.execute("UPDATE replenishment SET concept_id = 'medicamentos' WHERE user_id = %s", (USER,))

    assert offer(client).status_code == 204


def test_without_a_person_or_with_context_there_is_nothing(client, db):
    assert offer(client, user_id=None).status_code == 204
    assert offer(client, context={"concept": "cafe"}).status_code == 422


def test_a_simulated_person_and_the_prototype_do_not_mix(client, db):
    # Una persona simulada que dejó el café: su tabla la arma `build_motor` de la fuente simulada.
    for n in range(3):
        bought(db, "u-sim", "supermercado", "cafe", COFFEE, 20 + n * 7, source="synthetic")
    build_motor(db, "synthetic", evaluate=False)
    rhythm(db, USER, "supermercado", "cafe", COFFEE, last_days_ago=7)  # al prototipo le toca la recompra, no volver

    assert offer(client, user_id="u-sim").json()["reason"]["concept"] == "cafe"
    assert offer(client).status_code == 204
    synthetic, prototype = reach(db, "synthetic"), reach(db, "prototype")
    assert synthetic == {
        "dia": (today() - timedelta(days=20)).isoformat(),  # el último pedido simulado
        "personas": 1,
        "califican": 0,  # ese día lo acababa de pedir
        "por_concepto": 0,
        "por_vertical": 0,
        "recompra": 0,
    }
    assert prototype == {
        "dia": None,
        "personas": 1,
        "califican": 0,
        "por_concepto": 0,
        "por_vertical": 0,
        "recompra": 1,
    }


def test_the_panel_counts_who_qualifies_by_kind(client, db):
    rhythm(db, USER, "supermercado", "cafe", COFFEE, last_days_ago=20)
    left_vertical(db, "u-otra", "turbo", ICE_CREAM, last_days_ago=40)
    still_ordering(db, "u-otra")
    event(db, "suggestion_shown", concept="cafe", vertical="supermercado", days_ago=1)  # mostrada: igual califica

    reply = client.get("/analytics/volver", params={"source": "prototype"})

    assert reply.status_code == 200
    assert reply.json() == {
        "source": "prototype",
        "data": {"dia": None, "personas": 2, "califican": 2, "por_concepto": 1, "por_vertical": 1, "recompra": 0},
    }


def test_the_panel_does_not_count_who_gets_the_repeat(client, db):
    rhythm(db, USER, "supermercado", "cafe", COFFEE, last_days_ago=20)  # volver…
    rhythm(db, USER, "supermercado", "galletas", COOKIES, last_days_ago=7)  # …pero la Home le muestra la recompra

    assert reach(db, "prototype") == {
        "dia": None,
        "personas": 1,
        "califican": 0,
        "por_concepto": 0,
        "por_vertical": 0,
        "recompra": 1,
    }
