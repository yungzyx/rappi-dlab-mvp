"""Preferencias explícitas con el agente (offers/preferences.py, migración 045) sobre el catálogo de prueba: se fijan
por chat o en el panel, filtran (dieta, alergias) y ordenan (favoritas) lo que Mochi muestra y ofrece, nunca son la
razón de una oferta ni quedan como consulta, y se borran con "olvida mis preferencias", "Olvidar" y la purga."""

from datetime import datetime, time, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from owner_client import OwnerClient
from rappi_ia import delivery
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
from rappi_ia.offers import preferences

USER = "u-prefs"


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


def say(client, message, user=USER, mode="propuesta", **extra):
    body = {"message": message, "user_id": user, "session_id": "s-prefs", "mode": mode, **extra}
    reply = client.post("/agent/ask", json=body)
    assert reply.status_code == 200, reply.text
    return reply.json()


def stored(db, user=USER):
    return db.execute(
        "SELECT kind, value FROM agent_preferences WHERE user_id = %s ORDER BY kind, value", (user,)
    ).fetchall()


def names(reply):
    return [p["name"] for p in reply["products"]]


def test_said_by_chat_it_is_saved_and_listed(client, db):
    saved = say(client, "Soy vegetariana y alérgica al maní")
    assert saved["intent"]["kind"] == "preferencia"
    assert stored(db) == [("alergia", "mani"), ("dieta", "vegetariano")]
    assert "revisa siempre los ingredientes" in saved["text"]
    assert {p["valor"] for p in saved["preferences"]} == {"vegetariano", "mani"}
    assert saved["actions"] == [{"label": "Ver mis preferencias", "panel": "preferencias"}]

    listed = say(client, "muéstrame mis preferencias")
    assert "Vegetariano" in listed["text"] and "Alergia al maní" in listed["text"]

    say(client, "ya no soy vegetariana")
    assert stored(db) == [("alergia", "mani")]
    forgotten = say(client, "olvida mis preferencias")
    assert stored(db) == [] and forgotten["preferences"] == []
    assert "Todavía no tengo preferencias" in say(client, "mis preferencias")["text"]


def test_a_diet_filters_what_mochi_shows_and_says_it_filters_by_name(client):
    before = say(client, "pizza", vertical="restaurants")
    assert "Pizza pepperoni familiar (prueba)" in names(before)
    say(client, "no como carne")
    after = say(client, "pizza", vertical="restaurants")
    assert "Pizza pepperoni familiar (prueba)" not in names(after)
    assert "Pizza margarita mediana (prueba)" in names(after)
    assert "saqué lo que dice tener carne" in after["text"]
    assert after["reason"] is None or "carne" not in str(after["reason"])  # nunca es la razón


def search_names(reply):
    if "groups" in reply:
        return [p["name"] for g in reply["groups"] for p in g["products"]]
    return [p["name"] for p in reply["products"]]


def test_the_search_filters_with_diet_and_allergies_like_mochi(client):
    """`/search` con `user_id`: la misma dieta filtra lo buscado y la respuesta lo dice; sin `user_id`, nada cambia."""
    say(client, "no como carne")
    for path in ("/search?q=pizza", "/search?q=pizza&vertical=restaurants"):
        anonymous = client.get(path).json()
        assert "Pizza pepperoni familiar (prueba)" in search_names(anonymous)
        assert anonymous["preferences_notice"] is None
        mine = client.get(f"{path}&user_id={USER}").json()
        assert "Pizza pepperoni familiar (prueba)" not in search_names(mine)
        assert "Pizza margarita mediana (prueba)" in search_names(mine)
        assert "saqué lo que dice tener carne" in mine["preferences_notice"]


def test_the_search_does_not_order_by_favorites(client):
    """En el buscador las favoritas no ordenan (solo filtran la dieta y las alergias): mismo orden, sin aviso."""
    anonymous = client.get("/search?q=pizza").json()
    say(client, "mi comida favorita es el sushi")
    mine = client.get(f"/search?q=pizza&user_id={USER}").json()
    assert search_names(mine) == search_names(anonymous)
    assert mine["preferences_notice"] is None


def test_a_search_emptied_by_preferences_is_not_unmet(client):
    """Si la dieta saca todo lo encontrado, el catálogo sí lo tenía: no es "sin resultado" ni ofrece "Lo que sea"."""
    say(client, "no como carne")
    found = client.get(f"/search?q=parrillada&user_id={USER}").json()
    assert found["groups"] == []
    assert found["unmet"] is False and found["whim_allowed"] is False
    assert "carne" in found["preferences_notice"]


def test_the_search_with_someone_elses_id_is_refused(client):
    """Las preferencias son de la persona: `/search?user_id=` sin su token no responde."""
    plain = TestClient(api.app)
    assert plain.get(f"/search?q=pizza&user_id={USER}").status_code == 401
    assert plain.get("/search?q=pizza").status_code == 200


def test_rappi_hoy_neither_saves_nor_applies_them(client, db):
    today = say(client, "soy vegetariano", mode="actual")
    assert stored(db) == [] and "Rappi hoy" in today["text"]
    say(client, "soy vegetariano")
    shown = say(client, "pizza", vertical="restaurants", mode="actual")
    assert "Pizza pepperoni familiar (prueba)" in names(shown)
    assert "preferencias" not in shown["text"]


def test_what_is_said_about_oneself_is_not_kept_as_a_query(client, db):
    say(client, "tengo alergia al maní")
    row = db.execute(
        "SELECT query, concept_id, payload->>'intent' FROM app_events WHERE user_id = %s AND type = 'ask'", (USER,)
    ).fetchone()
    assert row == (None, None, "preferencia")
    assert db.execute("SELECT count(*) FROM user_segments WHERE user_id = %s", (USER,)).fetchone()[0] == 0


def test_a_favorite_store_must_exist_and_only_orders(client, db):
    missing = say(client, "mi tienda favorita es la tienda inventada")
    assert "No encontré" in missing["text"] and stored(db) == []
    say(client, "mi tienda favorita es Botillería de prueba Centro")
    assert stored(db) == [("tienda", "Botillería de prueba Centro")]
    # Una tienda favorita de Licores no sube Licores: la vertical por probar sigue siendo una que Mochi propone.
    tried = client.post("/agent/offer", json={"moment": "vertical_por_probar", "user_id": USER, "context": {}})
    assert tried.status_code in (200, 204)
    if tried.status_code == 200:
        assert tried.json()["vertical"] not in ("licores", "farmacia")


def test_the_panel_reads_replaces_and_clears_them(client, db):
    empty = client.get(f"/profile/{USER}/preferencias").json()
    assert empty["preferencias"] == []
    assert {"tipo": "alergia", "valor": "mani", "nombre": "Alergia al maní"} in empty["opciones"]
    assert not any(o["tipo"] == "tienda" for o in empty["opciones"])

    body = {
        "preferencias": [
            {"tipo": "dieta", "valor": "vegano"},
            {"tipo": "cocina", "valor": "sushi"},
            {"tipo": "cocina", "valor": "cerveza"},  # no es una cocina: se ignora
            {"tipo": "alergia", "valor": "inventada"},
            {"tipo": "tienda", "valor": "Pizzería de prueba Centro"},
            {"tipo": "tienda", "valor": "No existe"},
        ]
    }
    put = client.put(f"/profile/{USER}/preferencias", json=body).json()
    assert [(p["tipo"], p["valor"]) for p in put["preferencias"]] == [
        ("dieta", "vegano"),
        ("cocina", "sushi"),
        ("tienda", "Pizzería de prueba Centro"),
    ]
    cleared = client.put(f"/profile/{USER}/preferencias", json={"preferencias": []}).json()
    assert cleared["preferencias"] == [] and stored(db) == []


def test_offers_are_filtered_too_and_an_empty_one_is_no_offer(client, db):
    """La recompra de helado (cada 7 días, el último hace 7) no se ofrece a quien dijo que no toma leche."""
    today = datetime.now(TZ).date()
    line = {"entity_type": "catalog_item", "entity_id": "93001", "concept_id": "helados", "unit_price": 3990}
    for days in (21, 14, 7):
        ts = datetime.combine(today - timedelta(days=days), time(12), TZ)
        events.record_order(db, USER, f"s-helado-{days}", f"c-helado-{days}", "turbo", [line], ts=ts)
    refresh_user_conn(db, USER)
    offer = {"moment": "recompra", "user_id": USER, "context": {}}
    assert client.post("/agent/offer", json=offer).status_code == 200
    say(client, "soy intolerante a la lactosa")
    assert client.post("/agent/offer", json=offer).status_code == 204


def test_they_go_with_the_person(client, db):
    say(client, "mi comida favorita es el sushi")
    say(client, "soy vegano")
    # "Olvidar" un concepto lo saca de sus cocinas; "Olvidar" todo se lleva a la persona y sus preferencias.
    assert client.delete(f"/profile/{USER}?concept=sushi").status_code == 200
    assert stored(db) == [("dieta", "vegano")]
    assert client.delete(f"/profile/{USER}").status_code == 200
    assert stored(db) == []
    say(client, "soy vegano")
    db.execute("UPDATE app_users SET created_at = now() - interval '400 days' WHERE user_id = %s", (USER,))
    db.execute("UPDATE app_events SET ts = now() - interval '400 days' WHERE user_id = %s", (USER,))
    assert events.purge_inactive_users(db, 30) == 1
    assert stored(db) == []


def test_a_simulated_person_cannot_set_them(client, db):
    db.execute("INSERT INTO app_users (user_id, source) VALUES ('u-simulada', 'synthetic')")
    reply = client.post("/agent/ask", json={"message": "soy vegano", "user_id": "u-simulada", "mode": "propuesta"})
    assert reply.status_code == 400
    assert stored(db, "u-simulada") == []


def test_the_base_keeps_the_population_of_the_person(db):
    """Como en agent_autonomy (049): una preferencia del prototipo nunca queda colgada de alguien simulado (051)."""
    db.execute("INSERT INTO app_users (user_id, source) VALUES ('u-simulada', 'synthetic')")
    with pytest.raises(psycopg.errors.RaiseException), db.transaction():
        preferences.add(db, "u-simulada", [("dieta", "vegano")], source="prototype")
    assert preferences.add(db, "u-simulada", [("dieta", "vegano")], source="synthetic") == 1


def test_it_is_a_person_table(db):
    assert "agent_preferences" in delivery.PERSON_TABLES
    assert delivery.unknown_person_tables(db) == []
    comment = db.execute("SELECT obj_description('agent_preferences'::regclass)").fetchone()[0]
    assert "PERSON_TABLES" in comment
