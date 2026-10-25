"""«Para ti» (`/recommendations`) suma, si le quedan filas libres, «Lo más pedido en {vertical}»: la vertical que mejor
le calza a la persona según el motor, con lo que más pide la población ahí (`trends`). Nunca Farmacia ni Licores. Sobre
el catálogo de prueba (`seed_demo`)."""

from datetime import UTC, datetime, timedelta

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

NOW = datetime.now(UTC)
TOP_TURBO = {"kind": "lo_mas_pedido", "id": "turbo", "source": "poblacion:synthetic"}


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


def product_trends(db, vertical, ids):
    for rank, entity_id in enumerate(ids, start=1):
        db.execute(
            """INSERT INTO trends (data_source, scope, vertical, item_key, entity_type, entity_id, orders_now, rank)
               VALUES ('synthetic', 'producto', %s, %s, 'catalog_item', %s, %s, %s)""",
            (vertical, f"catalog_item:{entity_id}", entity_id, 100 - rank, rank),
        )
    db.commit()


def for_you(client, user_id="u1", **params):
    reply = client.get("/recommendations", params={"user_id": user_id, **params})
    assert reply.status_code == 200, reply.text
    return reply.json()["rows"]


def test_without_interests_for_you_shows_the_most_ordered(client, db):
    product_trends(db, "turbo", ["93002", "93001", "93003", "92001"])

    rows = for_you(client)

    assert len(rows) == 1
    row = rows[0]
    # Sin historia, el orden del motor parte con restaurantes (sin tendencias de productos) y sigue con Turbo.
    assert {k: v for k, v in row.items() if k != "products"} == {
        "kind": "lo_mas_pedido",
        "reason": "Lo más pedido estas semanas en Turbo",
        "concept": None,
        "vertical": "turbo",
        "prototype_vertical": "express",
        "basis": [TOP_TURBO],
    }
    assert [p["entity_id"] for p in row["products"]] == ["93002", "93001", "93003"]  # hasta tres, en su orden
    assert all(p["vertical"] == "turbo" and p["price_value"] for p in row["products"])


def test_the_reason_contracts_the_article(client, db):
    product_trends(db, "supermercado", ["91004"])

    assert for_you(client)[0]["reason"] == "Lo más pedido estas semanas en el súper"


def test_never_pharmacy_nor_liquor_nor_what_the_agent_does_not_offer(client, db):
    # La persona pide en farmacia y en Licores: el motor los pone primero, pero el agente no los propone.
    line = {"entity_type": "catalog_item", "entity_id": "95004", "concept_id": None, "unit_price": 1990}
    for n, vertical in enumerate(("farmacia", "licores", "farmacia")):
        events.record_order(db, "u1", f"s-{n}", f"c-{n}", vertical, [line], ts=NOW - timedelta(days=n + 1))
    db.execute("INSERT INTO app_users (user_id, source) VALUES ('u1', 'prototype') ON CONFLICT DO NOTHING")
    product_trends(db, "farmacia", ["95004", "95005"])
    product_trends(db, "licores", ["94003"])
    product_trends(db, "supermercado", ["94001", "91007"])  # cerveza (+18) y pañales (bebé) en el súper
    db.commit()

    assert for_you(client) == []

    product_trends(db, "conveniencia", ["92003"])
    rows = for_you(client)
    assert [row["vertical"] for row in rows] == ["conveniencia"]
    assert [p["entity_id"] for p in rows[0]["products"]] == ["92003"]


def test_not_the_current_vertical_nor_one_already_shown_and_only_with_room(client, db):
    pizza = {"type": "search", "session_id": "s1", "vertical": "restaurants", "concept_id": "pizza", "query": "pizza"}
    assert client.post("/events", json={"user_id": "u1", "events": [pizza]}).status_code == 200
    product_trends(db, "turbo", ["93001"])
    product_trends(db, "conveniencia", ["92003"])
    product_trends(db, "supermercado", ["91004"])

    rows = for_you(client, vertical="turbo")
    assert rows[0]["reason"] == "Por tu interés en 🍕 pizza" and rows[0]["vertical"] == "conveniencia"
    assert "kind" not in rows[0]
    # Turbo es la pantalla y conveniencia ya tiene su fila: el súper.
    assert [(row.get("kind"), row["vertical"]) for row in rows[1:]] == [("lo_mas_pedido", "supermercado")]

    assert len(for_you(client, vertical="turbo", limit=1)) == 1  # sin filas libres, nada más


def dish_trends(db, ids):
    for rank, entity_id in enumerate(ids, start=1):
        db.execute(
            """INSERT INTO trends (data_source, scope, vertical, item_key, entity_type, entity_id, orders_now, rank)
               VALUES ('synthetic', 'producto', 'restaurantes', %s, 'menu_item', %s, %s, %s)""",
            (f"menu_item:{entity_id}", entity_id, 100 - rank, rank),
        )
    db.commit()


def new_dish(db, item_id, name, store_id, section, price, concept):
    """Un plato con foto, precio y concepto en un local que puede ser nuevo."""
    run_id = db.execute("SELECT max(run_id) FROM scrape_runs WHERE kind = 'restaurants'").fetchone()[0]
    db.execute(
        "INSERT INTO menu_sections (store_id, section_id, name, position) VALUES (%s, %s, %s, 9)",
        (store_id, item_id, section),
    )
    db.execute(
        """INSERT INTO menu_items (item_id, rappi_item_id, store_id, section_id, name, image_url)
                  VALUES (%s, %s, %s, %s, %s, 'https://imagenes.prueba.invalid/plato.png')""",
        (item_id, item_id, store_id, item_id, name),
    )
    db.execute(
        "INSERT INTO menu_price_snapshots (run_id, item_id, price, is_available) VALUES (%s, %s, %s, true)",
        (run_id, item_id, price),
    )
    db.execute(
        """INSERT INTO item_concepts (entity_type, entity_id, concept_id, method, confidence, source)
                  VALUES ('menu_item', %s, %s, 'llm', 0.7, 'cocina:Pizzas')""",
        (str(item_id), concept),
    )


def test_the_most_ordered_dishes_are_main_dishes_with_photo_from_the_city_one_per_concept(client, db):
    # El chicle de $650 de la caja de una pizzería (concepto pizza por la cocina del local), una pizza de otra ciudad,
    # la bebida de la sección «Bebidas», el roll sin foto y el tiramisú (postres) no son «lo más pedido en
    # restaurantes»; tres pizzas tampoco.
    new_dish(db, 98101, "Chicle refrescante (prueba)", 9801, "Para llevar", 650, "pizza")
    db.execute("""INSERT INTO stores (store_id, name, store_type, city, path)
                  VALUES (9899, 'Pizzería de prueba - Rancagua', 'restaurant', 'Rancagua', '/tiendas/9899')""")
    new_dish(db, 98102, "Pizza napolitana familiar (prueba)", 9899, "Pizzas", 9990, "pizza")
    # Cuesta como un plato y su concepto es el de la cocina del local: solo la sección dice que es una bebida.
    new_dish(db, 98103, "Bebida cola 1,5 L (prueba)", 9801, "Bebidas", 3990, "pizza")
    dish_trends(db, ["98101", "98102", "98103", "98001", "98002", "98005", "98004", "98006", "98007"])

    rows = for_you(client)

    assert [row["vertical"] for row in rows] == ["restaurantes"]
    assert [p["entity_id"] for p in rows[0]["products"]] == ["98001", "98006", "98007"]
    assert [p["concept"] for p in rows[0]["products"]] == ["pizza", "sushi", "hamburguesa"]
