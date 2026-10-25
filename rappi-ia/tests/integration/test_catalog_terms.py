"""`GET /catalog/terms`: las condiciones de compra que trae el catálogo (envío, compra mínima y tarifa de servicio) para
las tiendas del carro, sobre el catálogo de `seed_demo` (catalog/terms.py). Lo que no trae va en null."""

import pytest
from fastapi.testclient import TestClient

from rappi_ia.api import app as api
from rappi_ia.catalog.terms import store_terms
from rappi_ia.demo.seed import seed_demo

SUPER_CENTRO, SUPER_NORTE, EXPRESS, TURBO, PIZZERIA, SUSHI = 9101, 9102, 9201, 9301, 9801, 9802


@pytest.fixture
def seeded(db):
    seed_demo(db)
    return db


@pytest.fixture
def client(seeded):
    def conn_override():
        yield seeded

    api.app.dependency_overrides[api.get_conn] = conn_override
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def test_each_store_has_what_the_catalog_knows(seeded):
    terms = {t["store_id"]: t for t in store_terms(seeded, [SUPER_CENTRO, SUPER_NORTE, EXPRESS, TURBO, PIZZERIA])}
    # «Sin mínimo» es un dato (mov_value 0); el envío es el delivery_price de la tienda.
    assert terms[SUPER_CENTRO] == {"store_id": SUPER_CENTRO, "delivery_fee": 1990, "min_order": 0, "service_pct": None}
    assert terms[SUPER_NORTE] == {"store_id": SUPER_NORTE, "delivery_fee": 990, "min_order": 8490, "service_pct": 5}
    assert terms[EXPRESS]["delivery_fee"] == 1290  # el de `charges` manda sobre delivery_price
    # Sin mínimo ni tarifa en el raw: desconocidos (la app pone su supuesto).
    assert terms[TURBO] == {"store_id": TURBO, "delivery_fee": 1490, "min_order": None, "service_pct": None}
    # Un restaurante: su delivery_cost; la base no guarda su mínimo.
    assert terms[PIZZERIA] == {"store_id": PIZZERIA, "delivery_fee": 1490, "min_order": None, "service_pct": None}


def test_a_delivery_price_that_is_not_pesos_is_unknown(seeded):
    """La descarga sin dirección trae `delivery_price` 30: no es un envío en pesos."""
    seeded.execute(
        """UPDATE stores SET raw = raw || '{"delivery_price": 30, "percentage_service_fee": 0}' WHERE store_id = %s""",
        (TURBO,),
    )
    [terms] = store_terms(seeded, [TURBO])
    assert terms["delivery_fee"] is None and terms["service_pct"] is None


def test_a_zero_delivery_cost_is_unknown_and_a_missing_store_does_not_come(seeded):
    terms = store_terms(seeded, [SUSHI, 123456789, SUSHI])
    assert terms == [{"store_id": SUSHI, "delivery_fee": None, "min_order": None, "service_pct": None}]
    assert store_terms(seeded, []) == []


def test_route(client):
    reply = client.get(f"/catalog/terms?stores={PIZZERIA},{SUPER_NORTE}")
    assert reply.status_code == 200
    assert [t["store_id"] for t in reply.json()["stores"]] == [SUPER_NORTE, PIZZERIA]
    for bad in ("", "a,b", "1,,2", "-1", "1;2"):
        assert client.get(f"/catalog/terms?stores={bad}").status_code == 422, bad
    too_many = ",".join(str(9000 + n) for n in range(21))
    assert client.get(f"/catalog/terms?stores={too_many}").status_code == 422
    # Un id que no cabe en bigint no rompe la consulta: no existe.
    assert client.get(f"/catalog/terms?stores={2**63}").json() == {"stores": []}
