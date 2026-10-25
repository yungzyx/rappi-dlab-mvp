"""La API de los perfiles de gusto: `GET /profile/{user_id}/gustos` y el momento `perfil` de `POST /agent/offer`, sobre
el catálogo de las pruebas del motor (test_profiles_engine.py), que suma lo que una escalera nunca debe mostrar (un soju
en «Gaseosas» y globos de un sex shop). La persona se prepara como en la app: con `POST /events` y `POST /orders`."""

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from test_profiles_engine import (  # noqa: F401 (el fixture)
    CHAIN_BRANCH,
    OTHER_SUSHI,
    ROLL_CALIFORNIA,
    ROLL_SALMON,
    SUSHI_STORE,
    catalog,
)

from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.grouped_search import SCREEN_VERTICALS
from rappi_ia.agent.rappi_agent import RappiAgent
from rappi_ia.api import app as api
from rappi_ia.api import identity
from rappi_ia.api.services import Services
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.offers.guards import OFFER_BLOCKED_VERTICALS, alcohol_in_name, unofferable_subverticals
from rappi_ia.offers.profiles import STEP_PRODUCTS, load_profiles

SUSHI_LOVER = "u-sushi"
WHY = "Pediste 🍣 sushi 2 veces, y buscaste 🥡 comida asiática 1 vez."
ASIAN = {"id": "asiatico", "nombre": "Amante de lo asiático", "emoji": "🥢"}
ALL_ASIAN_STEPS = ["restaurantes", "turbo", "conveniencia", "supermercado", "chocolateria"]


@pytest.fixture
def client(catalog, db):  # noqa: F811
    @contextmanager
    def shared_connection():  # el recálculo de segmentos después de un pedido, con la conexión del test
        yield db

    api.app.dependency_overrides[api.get_conn] = lambda: (yield db)
    api.app.dependency_overrides[api.get_connector] = lambda: shared_connection
    api.app.dependency_overrides[api.get_services] = lambda: Services(RappiAgent(catalog, TemplateComposer()), catalog)
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def as_owner(user_id: str) -> dict:
    return {identity.TOKEN_HEADER: identity.sign(user_id)}


def sushi_lover(client, user: str = SUSHI_LOVER) -> str:
    """Busca ramen y pide sushi dos veces en el local de los rolls, en tres sesiones: cada pedido recalcula sus
    segmentos (`asiatica` queda en nivel medio)."""
    search = {"type": "search", "session_id": "s1", "concept_id": "asiatica", "query": "ramen", "results": 3}
    assert client.post("/events", json={"user_id": user, "events": [search]}, headers=as_owner(user)).status_code == 200
    for n, roll in enumerate((ROLL_CALIFORNIA, ROLL_SALMON), start=2):
        order = {
            "user_id": user,
            "session_id": f"s{n}",
            "cart_id": f"c{n}",
            "vertical": "restaurants",
            "lines": [{"entity_type": "menu_item", "entity_id": roll, "concept_id": "sushi"}],
        }
        reply = client.post("/orders", json=order, headers=as_owner(user))
        assert reply.status_code == 200 and reply.json()["lineas_omitidas"] == 0, reply.text
    return user


def newcomer(client, user: str = "u-nuevo") -> str:
    """Una persona del prototipo que solo abrió la app: sin segmentos."""
    opened = {"user_id": user, "events": [{"type": "app_open", "session_id": "s1"}]}
    assert client.post("/events", json=opened, headers=as_owner(user)).status_code == 200
    return user


def tastes(client, user: str):
    return client.get(f"/profile/{user}/gustos", headers=as_owner(user))


def offer(client, context: dict, user: str | None = None, headers: dict | None = None):
    body = {"moment": "perfil", "context": context, **({"user_id": user} if user else {})}
    if headers is None:
        headers = as_owner(user) if user else {}
    return client.post("/agent/offer", json=body, headers=headers)


# ── GET /profile/{user_id}/gustos ────────────────────────────────────────────


def test_tastes_and_the_personal_moment_need_the_owner_token(client):
    sushi_lover(client)

    for headers, status, detail in (({}, 401, "Falta la sesión"), (as_owner("u-otra"), 403, "No autorizado")):
        reply = client.get(f"/profile/{SUSHI_LOVER}/gustos", headers=headers)
        assert (reply.status_code, reply.json()) == (status, {"detail": detail})
        reply = offer(client, {"perfil": None}, SUSHI_LOVER, headers=headers)
        assert (reply.status_code, reply.json()) == (status, {"detail": detail})


def test_tastes_list_the_active_profiles(client):
    sushi_lover(client)

    reply = tastes(client, SUSHI_LOVER)

    assert reply.status_code == 200, reply.text
    [asian] = reply.json()["perfiles"]
    assert asian == {**ASIAN, "nivel": "medio", "principal": True, "por_que": WHY, "basis": asian["basis"]}
    assert {"kind": "concepto", "id": "sushi", "score": 2, "source": "pedidos"} in asian["basis"]
    assert {"kind": "concepto", "id": "asiatica", "score": 1, "source": "busquedas"} in asian["basis"]
    assert "segmento:asiatica" in {s["source"] for s in asian["basis"]}


def test_tastes_are_an_empty_list_without_profiles(client):
    newcomer(client)
    sushi_lover(client)

    for user in ("u-nuevo", "u-no-existe"):
        reply = tastes(client, user)
        assert (reply.status_code, reply.json()) == (200, {"perfiles": []}), user

    # «Olvidar» borra sus segmentos: el perfil se va con ellos
    assert client.delete(f"/profile/{SUSHI_LOVER}", headers=as_owner(SUSHI_LOVER)).status_code == 200
    assert tastes(client, SUSHI_LOVER).json() == {"perfiles": []}


# ── POST /agent/offer, momento «perfil» ──────────────────────────────────────


def test_the_profile_moment_for_a_person_is_their_first_profile_with_its_why(client):
    sushi_lover(client)
    basis = tastes(client, SUSHI_LOVER).json()["perfiles"][0]["basis"]

    reply = offer(client, {}, SUSHI_LOVER)  # sin `perfil`: el primero de sus perfiles

    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["moment"] == "perfil"
    assert body["perfil"] == {**ASIAN, "nivel": "medio", "por_que": WHY}
    assert body["reason"] == {"text": WHY, "basis": basis}
    assert body["text"] == "Por tu gusto por lo asiático, mira esto en otras verticales."
    # Restaurantes deja fuera el local donde ya pidió y la otra sucursal de su cadena: queda el otro local de sushi
    assert [s["vertical"] for s in body["escalera"]] == ALL_ASIAN_STEPS
    assert [p["store_id"] for p in body["escalera"][0]["products"]] == [OTHER_SUSHI]
    assert not {SUSHI_STORE, CHAIN_BRANCH} & {p["store_id"] for s in body["escalera"] for p in s["products"]}
    assert body["viaje"]["id"] == "japon"


def test_the_profile_moment_without_a_person_is_only_the_ladder(client):
    reply = offer(client, {"perfil": "asiatico"})

    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["perfil"] == ASIAN  # sin nivel ni «por qué» personal
    assert body["reason"] == {
        "text": "Porque elegiste «Amante de lo asiático».",
        "basis": [{"kind": "perfil", "id": "asiatico", "source": "contexto"}],
    }
    assert [s["vertical"] for s in body["escalera"]] == ALL_ASIAN_STEPS


def test_a_person_who_picks_a_profile_gets_their_why_only_if_it_is_theirs(client):
    sushi_lover(client)

    own = offer(client, {"perfil": "asiatico"}, SUSHI_LOVER).json()
    assert own["perfil"]["por_que"] == WHY and own["reason"]["text"] == WHY
    assert [p["store_id"] for p in own["escalera"][0]["products"]] == [OTHER_SUSHI]

    other = offer(client, {"perfil": "carrete"}, SUSHI_LOVER).json()
    assert other["perfil"] == {"id": "carrete", "nombre": "Carrete", "emoji": "🎉"}
    assert other["reason"]["text"] == "Porque elegiste «Carrete»."
    assert SUSHI_STORE not in {p["store_id"] for s in other["escalera"] for p in s["products"]}


def test_the_restaurants_step_is_in_the_city_of_the_person(client, db):
    """Los restaurantes de la escalera son de la ciudad de la persona (`app_users.city`) o, si no la tiene (la app no
    la pide), de PROFILE_CITY: Santiago de Chile."""
    db.execute("UPDATE stores SET city = 'Viña del Mar' WHERE store_id = %s", (OTHER_SUSHI,))
    user = newcomer(client)

    def places():
        body = offer(client, {"perfil": "asiatico"}, user).json()
        return {p["store_id"] for s in body["escalera"] if s["vertical"] == "restaurantes" for p in s["products"]}

    assert OTHER_SUSHI not in places()
    db.execute("UPDATE app_users SET city = 'Viña del Mar' WHERE user_id = %s", (user,))
    assert places() == {OTHER_SUSHI}


def test_no_profile_or_no_ladder_is_204(client):
    newcomer(client)

    for context, user in (
        ({"perfil": None}, None),  # nadie y ningún perfil
        ({}, "u-nuevo"),  # una persona sin perfiles
        ({"perfil": "mascotas"}, None),  # el catálogo de prueba no vende comida de perro: no hay escalera
    ):
        reply = offer(client, context, user)
        assert reply.status_code == 204 and not reply.content, (context, user)


def test_an_unknown_profile_is_422_in_spanish(client):
    reply = offer(client, {"perfil": "vegano"})

    assert (reply.status_code, reply.json()) == (422, {"detail": "Perfil desconocido: «vegano»"})
    assert offer(client, {"perfil": "x" * 65}).status_code == 422
    assert offer(client, {"perfil": ""}).status_code == 422
    assert client.post("/agent/offer", json={"moment": "perfil"}).status_code == 422  # sin `context`


def test_the_profile_moment_has_the_shape_of_the_spec(client):
    product_keys = set(client.get("/search", params={"q": "soya", "vertical": "turbo"}).json()["products"][0])

    body = offer(client, {"perfil": "asiatico"}).json()

    assert set(body) == {"moment", "text", "perfil", "escalera", "viaje", "reason", "actions"}
    for step in body["escalera"]:
        assert set(step) == {"vertical", "prototype_vertical", "texto", "products"}
        assert step["prototype_vertical"] == SCREEN_VERTICALS[step["vertical"]] and step["texto"]
        assert 1 <= len(step["products"]) <= STEP_PRODUCTS
        assert all(set(p) == product_keys and p["vertical"] == step["vertical"] for p in step["products"])
    trip = body["viaje"]
    assert {k: v for k, v in trip.items() if k != "hechos"} == {
        "id": "japon",
        "nombre": "Japón",
        "texto": "¿Y si un día vas a Japón?",
        "etiqueta": "Idea para RappiTravel",
        "route": ["travel"],
    }
    assert len(trip["hechos"]) == 2
    assert all(set(f) == {"texto", "fuente", "url"} and f["url"].startswith("https://") for f in trip["hechos"])
    assert body["actions"] == [
        {"label": "Abrir restaurantes", "route": ["restaurants"]},
        {"label": "Abrir Turbo", "route": ["turbo"]},
        {"label": "Abrir Express", "route": ["express"]},
        {"label": "Abrir el súper", "route": ["grocery"]},
        {"label": "Abrir chocolaterías", "route": ["chocolates"]},
        {"label": "Abrir RappiTravel", "route": ["travel"], "service": "rappitravel"},
    ]

    party = offer(client, {"perfil": "carrete"}).json()  # sin viaje
    assert party["viaje"] is None
    assert [a["route"] for a in party["actions"]] == [[SCREEN_VERTICALS[s["vertical"]]] for s in party["escalera"]]


def test_no_profile_offers_alcohol_adult_products_or_blocked_stores_through_the_api(client, db):
    # Sin las guardias de oferta, la búsqueda sí encuentra el soju (una gaseosa) y los globos del sex shop
    assert "Soju uva verde 360 ml (prueba)" in {
        p["name"] for p in client.get("/search", params={"q": "soju", "vertical": "turbo"}).json()["products"]
    }
    blocked = {
        store_id
        for (store_id,) in db.execute(
            "SELECT store_id FROM store_verticals WHERE subvertical = ANY(%s)", (unofferable_subverticals(),)
        )
    }
    adult = {c.id for c in load_taxonomy().concepts.values() if c.age_restricted}

    offered = []
    for profile_id in load_profiles():
        reply = offer(client, {"perfil": profile_id})
        assert reply.status_code in (200, 204), (profile_id, reply.text)
        if reply.status_code == 200:
            offered += [p for step in reply.json()["escalera"] for p in step["products"]]

    assert offered
    assert not [p["name"] for p in offered if p["age_restricted"] or p["concept"] in adult]
    assert not [p["name"] for p in offered if alcohol_in_name(p["entity_type"], p["name"])]
    assert not [p["name"] for p in offered if p["store_id"] in blocked or p["vertical"] in OFFER_BLOCKED_VERTICALS]
    assert not {"Soju uva verde 360 ml (prueba)", "Globos de colores x 10 (prueba)"} & {p["name"] for p in offered}
