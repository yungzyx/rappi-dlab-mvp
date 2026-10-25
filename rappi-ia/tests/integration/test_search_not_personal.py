"""La búsqueda no se personaliza: lo que se encuentra con una consulta no depende de lo que la persona hizo antes.
Solo las ofertas del agente (`/agent/offer`, `/agent/plans`) usan su historia. Las dos personas vienen de `people`."""

import pytest
from personal_helpers import GRILL, NEWBIE, SWEET, prepare_people

from rappi_ia.api import app as api

QUERIES = ("chocolate", "carne")


@pytest.fixture
def people(db, monkeypatch):
    yield from prepare_people(db, monkeypatch)


def test_search_route_takes_no_user():
    route = next(r for r in api.app.routes if getattr(r, "path", None) == "/search")
    params = {
        p.name for p in (*route.dependant.query_params, *route.dependant.path_params, *route.dependant.body_params)
    }
    assert "user_id" not in params and "profile" not in params


def count_products(body):
    """Los productos de una respuesta de /search, agrupada (`groups`) o de una vertical (`products`)."""
    if "groups" in body:
        return sum(len(group["products"]) for group in body["groups"])
    return len(body["products"])


# (consulta, parámetros extra, mínimo de productos): todas las búsquedas comparadas tienen resultados reales.
SEARCHES = [
    ("chocolate", {}, 2),
    ("chocolate", {"vertical": "chocolateria"}, 2),
    ("chocolate", {"mode": "vector"}, 2),
    ("carne", {}, 2),
    ("carne", {"vertical": "supermercado"}, 2),
]


@pytest.mark.parametrize(("query", "extra", "minimum"), SEARCHES)
def test_search_results_do_not_depend_on_history(people, query, extra, minimum):
    client = people.client

    def search(**who):
        reply = client.get("/search", params={"q": query, **extra, **who})
        assert reply.status_code == 200, reply.text
        return reply.json()

    anonymous = search()
    assert count_products(anonymous) >= minimum  # hay resultados con qué comparar
    # Aunque se le pase un usuario, la ruta lo ignora: ve lo mismo quien tiene historia que quien no.
    for user in (SWEET, GRILL, NEWBIE):
        assert search(user_id=user) == anonymous
    assert search() == anonymous  # y lo que ya hicieron (sus eventos y pedidos) no la movió


@pytest.mark.parametrize("message", QUERIES)
def test_ask_products_do_not_depend_on_history(people, message):
    client = people.client

    def ask(user):
        reply = client.post("/agent/ask", json={"message": message, "user_id": user, "session_id": f"s-ask-{user}"})
        assert reply.status_code == 200, reply.text
        return reply.json()["products"]

    anonymous = ask(None)
    assert len(anonymous) >= 2  # productos reales que comparar
    for user in (SWEET, GRILL, NEWBIE):
        assert ask(user) == anonymous  # el texto puede cambiar; los productos no
