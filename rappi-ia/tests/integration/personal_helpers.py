"""Dos personas con historias distintas, preparadas solo a través de la API (`POST /events` y `POST /orders`), para los
tests que miran la personalización (`test_personalization_done.py`) y la guardia de que la búsqueda no la usa
(`test_search_not_personal.py`). Cada módulo la expone con un fixture de dos líneas (`yield from prepare_people(...)`):
un `conftest.py` aquí taparía el `conftest` de `tests/`, que otros tests importan por nombre."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from fastapi.testclient import TestClient
from psycopg import Connection

from owner_client import OwnerClient
from rappi_ia.agent.compose import TemplateComposer
from rappi_ia.agent.rappi_agent import RappiAgent
from rappi_ia.api import app as api
from rappi_ia.api.services import Services
from rappi_ia.demo import seed
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents

SWEET, GRILL, NEWBIE = "u-dulce", "u-asado", "u-nuevo"

# El catálogo de prueba no vende carne ni carbón, y de galletas hay una por vertical: se suman cuatro productos (dos
# cortes de carne, así «carne» devuelve más de uno) al súper y a la chocolatería. La galleta de avena es la segunda de
# ahí, así que su marca puede ir antes que la de siempre.
BEEF, CHARCOAL, OAT_COOKIES, SIRLOIN = 99001, 99002, 97008, 99003
# fmt: off
EXTRA_PRODUCTS = [
    (BEEF, "Asado de tira 1 kg (prueba)", "Res", False, {"supermercado": (9990, 10490)}),
    (SIRLOIN, "Lomo vetado 1 kg (prueba)", "Res", False, {"supermercado": (11990, 12490)}),
    (CHARCOAL, "Carbón vegetal 3 kg (prueba)", "Carbón, Leña y chispa", False, {"supermercado": (3990, 4190)}),
    (OAT_COOKIES, "Galletas de avena 150 g (prueba)", "Galletas", False, {"chocolateria": (1890, 1890)}),
]
# fmt: on
MILK_CHOCOLATE, DARK_CHOCOLATE = 92002, 97001
SWEET_BRAND = ("marca-dulce", "Dulces Sur")
COFFEE = "91004"  # en el carro, su complemento natural son las galletas (arista curada café → galletas)


def _line(product, concept, price):
    return {"entity_type": "catalog_item", "entity_id": str(product), "concept_id": concept, "unit_price": price}


@dataclass
class People:
    client: TestClient
    sweet_history: set[str]  # los conceptos de u-dulce: lo que buscó, agregó y pidió
    grill_history: set[str]
    sweet_brand_product: str  # la galleta de la marca que u-dulce compra, la que debe ir primero en su complemento


def prepare_people(db: Connection, monkeypatch) -> Iterator[People]:
    """El cliente de la API sobre el catálogo de prueba y las dos personas del prototipo.

    - u-dulce busca y pide chocolates y galletas; dos pedidos, con la misma marca (Dulces Sur) en los dos.
    - u-asado busca y pide carne y carbón (dos pedidos).
    """
    monkeypatch.setattr(seed, "_PRODUCTS", [*seed._PRODUCTS, *EXTRA_PRODUCTS])
    for aisle_id, category in ((1900, "Res"), (2000, "Carbón, Leña y chispa")):  # pasillos propios, como los demás
        monkeypatch.setitem(seed._AISLE_OF_CATEGORY, category, (aisle_id, None))
        monkeypatch.setitem(seed._AISLE_NAMES, aisle_id, (category, None))
    seed.seed_demo(db)
    embedder = HashEmbedder()
    embed_search_documents(db, embedder)
    db.execute("INSERT INTO product_brands (brand_key, name) VALUES (%s, %s)", SWEET_BRAND)
    for product in (MILK_CHOCOLATE, DARK_CHOCOLATE, OAT_COOKIES):
        db.execute(
            """INSERT INTO item_brands (entity_type, entity_id, brand_key, source)
               VALUES ('catalog_item', %s, %s, 'regla')""",
            (str(product), SWEET_BRAND[0]),
        )
    db.commit()

    @contextmanager
    def connector():  # el recálculo de segmentos tras un pedido usa la conexión del test, sin cerrarla
        yield db

    def conn_override():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    api.app.dependency_overrides[api.get_connector] = lambda: connector
    api.app.dependency_overrides[api.get_services] = lambda: Services(
        RappiAgent(embedder, TemplateComposer()), embedder
    )
    client = OwnerClient(api.app)

    def search_and_add(user, session, concept, query, product, vertical):
        events = [
            {"type": "search", "session_id": session, "concept_id": concept, "query": query, "results": 3},
            {
                "type": "cart_add",
                "session_id": session,
                "concept_id": concept,
                "vertical": vertical,
                "entity_type": "catalog_item",
                "entity_id": str(product),
                "cart_id": f"c-{session}",
            },
        ]
        reply = client.post("/events", json={"user_id": user, "events": events})
        assert reply.status_code == 200, reply.text

    def order(user, session, vertical, *lines):
        body = {"user_id": user, "session_id": session, "cart_id": f"c-{session}", "vertical": vertical, "lines": lines}
        reply = client.post("/orders", json=body)
        assert reply.status_code == 200, reply.text

    for n in (1, 2):
        session = f"s-dulce-{n}"
        search_and_add(SWEET, session, "chocolates", "chocolate", MILK_CHOCOLATE, "conveniencia")
        search_and_add(SWEET, session, "galletas", "galletas", OAT_COOKIES, "chocolateria")
        order(
            SWEET,
            session,
            "chocolateria",
            _line(DARK_CHOCOLATE if n == 2 else MILK_CHOCOLATE, "chocolates", 2490),
            _line(OAT_COOKIES, "galletas", 1890),
        )
        session = f"s-asado-{n}"
        search_and_add(GRILL, session, "carnes", "carne para el asado", BEEF, "supermercado")
        search_and_add(GRILL, session, "carbon", "carbón", CHARCOAL, "supermercado")
        order(GRILL, session, "supermercado", _line(BEEF, "carnes", 9990), _line(CHARCOAL, "carbon", 3990))

    yield People(client, {"chocolates", "galletas"}, {"carnes", "carbon"}, str(OAT_COOKIES))
    api.app.dependency_overrides.clear()
