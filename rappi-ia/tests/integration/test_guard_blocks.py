"""El contador de las guardias (offers/blocked.py, migración 062): cuántos candidatos sacaron las guardias de ofertas al
armar lo que Mochi propone solo, por día, población, momento y motivo, sin persona ni producto; y `/analytics/guardias`,
que lo lee."""

import types
from collections import Counter
from datetime import date

import pytest

from owner_client import OwnerClient
from rappi_ia.agent.tools import _with_prices
from rappi_ia.analytics import queries
from rappi_ia.api import agent as api_agent
from rappi_ia.api import app as api
from rappi_ia.api.services import Services
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.delivery import PERSON_TABLES, unknown_person_tables
from rappi_ia.demo.seed import seed_demo
from rappi_ia.offers import blocked, guards
from rappi_ia.offers.engine import _offerable_deals, _offerable_products

BEER, DIAPERS, CHIPS = 94001, 91007, 91001


def test_each_blocked_concept_vertical_and_store_label_has_its_reason():
    concepts = load_taxonomy().concepts
    reasons = {c: guards.concept_reason(concepts[c]) for c in ("cerveza", "cigarrillos", "panales", "vitaminas")}
    assert reasons == {"cerveza": "alcohol", "cigarrillos": "mas18", "panales": "bebe", "vitaminas": "salud"}
    assert guards.concept_reason(concepts["snacks-salados"]) is None
    # Todo concepto que Mochi no ofrece tiene su motivo, y uno que ofrece no tiene ninguno.
    assert all((guards.concept_reason(c) is None) == guards.is_offerable(c) for c in concepts.values())
    assert [guards.vertical_reason(v) for v in ("licores", "farmacia", "turbo")] == ["alcohol", "farmacia", None]
    assert {s: guards.subvertical_reason(s) for s in guards.unofferable_subverticals()} == {
        "Farmacia": "farmacia",
        "Sex shop": "mas18",
        "Smoking shop": "mas18",
    }


def test_outside_a_count_nothing_is_counted_and_an_unknown_reason_fails():
    blocked.count("alcohol")  # sin `counting`: los trabajos, los tests y las evaluaciones no cuentan
    with blocked.counting() as counts:
        blocked.count("alcohol")
        blocked.count(None)
        with pytest.raises(ValueError):
            blocked.count("vino")
    assert counts == Counter({"alcohol": 1})
    assert guards.offerable_verticals(["licores", "turbo"]) == ["turbo"]  # fuera de `counting` tampoco cuenta


def test_save_adds_to_the_day_moment_and_reason(db):
    blocked.save(db, "carrito", Counter({"alcohol": 2, "bebe": 1}))
    blocked.save(db, "carrito", Counter({"alcohol": 3, "salud": 0}))
    blocked.save(db, "plan", Counter())  # sin nada, no escribe
    rows = db.execute("SELECT day, source, moment, reason, blocked FROM guard_blocks ORDER BY reason").fetchall()
    today = db.execute("SELECT current_date").fetchone()[0]
    assert rows == [(today, "prototype", "carrito", "alcohol", 5), (today, "prototype", "carrito", "bebe", 1)]


def _hit(product_id, concept=None, vertical="supermercado"):
    return types.SimpleNamespace(
        entity_type="catalog_item", entity_id=str(product_id), concept_id=concept, vertical=vertical, metadata={}
    )


def test_an_offer_counts_each_product_a_guard_takes_out(db):
    seed_demo(db)
    hits = [_hit(BEER, "cerveza"), _hit(DIAPERS, "panales"), _hit(CHIPS, "snacks-salados")]
    with blocked.counting() as counts:
        offered = _with_prices(db, "supermercado", hits, offer=True)
    assert [p.entity_id for p in offered] == [str(CHIPS)]
    assert counts == Counter({"alcohol": 1, "bebe": 1})  # los pañales: su nombre no dice bebé, su concepto sí
    with blocked.counting() as counts:
        found = _with_prices(db, "supermercado", hits)  # lo que la persona pide: sin guardias, nada que contar
    assert len(found) == 3 and counts == Counter()


def test_the_catalog_deals_count_what_the_guards_take_out(db):
    seed_demo(db)
    products = [
        {"name": "Cerveza rubia lata", "concept": "snacks-salados", "age_restricted": False, "store_id": None},
        {"name": "Cigarrillos", "concept": "cigarrillos", "age_restricted": True, "store_id": None},
        {"name": "Body para bebé", "concept": None, "age_restricted": False, "store_id": None},
        {"name": "Antiácido", "concept": None, "age_restricted": False, "store_id": 9111},  # tienda Farmacia
        {"name": "Vitamina C", "concept": "vitaminas", "age_restricted": False, "store_id": None},
        {"name": "Papas fritas", "concept": "snacks-salados", "age_restricted": False, "store_id": None},
    ]
    with blocked.counting() as counts:
        kept = _offerable_products(db, products)
    assert [p["name"] for p in kept] == ["Papas fritas"]
    assert counts == Counter({"alcohol": 1, "mas18": 1, "bebe": 1, "farmacia": 1, "salud": 1})


def test_the_offers_of_a_vertical_count_what_the_guards_took_out_of_the_real_deals(db):
    """De punta a punta con el catálogo de prueba: entre las ofertas del súper hay un cepillo de una tienda Farmacia, y
    en Mall, unos chicles de un Smoking shop y una vela de un Sex shop. Mochi no propone ninguno, y quedan contados."""
    seed_demo(db)
    with blocked.counting() as counts:
        offered = _offerable_deals(db, "supermercado")
    assert offered and all(p["store_id"] != 9111 for p in offered)
    assert counts == Counter({"farmacia": 1})
    with blocked.counting() as counts:
        _offerable_deals(db, "mall")
    assert counts == Counter({"mas18": 2})


@pytest.fixture
def client(db):
    def conn_override():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    api.app.dependency_overrides[api.get_services] = lambda: Services(None, None)  # la oferta es falsa: sin modelo
    yield OwnerClient(api.app)
    api.app.dependency_overrides.clear()


def test_an_offer_request_saves_what_its_guards_took_out(client, db, monkeypatch):
    def offer(*_args, **_kwargs):
        blocked.count("alcohol")
        blocked.count("alcohol")
        blocked.count("salud")

    monkeypatch.setattr(api_agent, "make_offer", offer)
    for _ in range(2):
        reply = client.post("/agent/offer", json={"moment": "volver", "context": {}})
        assert reply.status_code == 204  # sin oferta, pero lo que las guardias sacaron queda contado
    rows = db.execute("SELECT moment, reason, blocked FROM guard_blocks ORDER BY reason").fetchall()
    assert rows == [("volver", "alcohol", 4), ("volver", "salud", 2)]


def test_the_panel_reads_the_counts_by_reason_and_moment_without_mixing_populations(client, db):
    db.execute(
        """INSERT INTO guard_blocks (day, source, moment, reason, blocked) VALUES
           ('2026-11-20', 'prototype', 'pregunta', 'alcohol', 3),
           ('2026-11-21', 'prototype', 'carrito', 'alcohol', 2),
           ('2026-11-21', 'prototype', 'carrito', 'bebe', 1),
           ('2026-11-22', 'prototype', 'otro-momento', 'salud', 1),
           ('2026-11-22', 'synthetic', 'carrito', 'farmacia', 9)"""
    )
    data = queries.guard_blocks(db, "prototype")
    assert data["total"] == 7
    assert data["motivos"] == [
        {"motivo": "alcohol", "candidatos": 5},
        {"motivo": "mas18", "candidatos": 0},
        {"motivo": "farmacia", "candidatos": 0},
        {"motivo": "bebe", "candidatos": 1},
        {"motivo": "salud", "candidatos": 1},
    ]
    # En el orden de los momentos del panel de ofertas; uno desconocido, al final.
    assert [(m["momento"], m["candidatos"]) for m in data["momentos"]] == [
        ("carrito", 3),
        ("pregunta", 3),
        ("otro-momento", 1),
    ]
    assert data["momentos"][0]["motivos"] == {"alcohol": 2, "mas18": 0, "farmacia": 0, "bebe": 1, "salud": 0}
    assert (data["desde"], data["hasta"]) == (date(2026, 11, 20), date(2026, 11, 22))
    assert queries.guard_blocks(db, "synthetic")["total"] == 9  # nunca mezcla poblaciones
    db.execute("DELETE FROM guard_blocks")
    assert queries.guard_blocks(db, "prototype") == {
        "total": 0,
        "motivos": [{"motivo": r, "candidatos": 0} for r in guards.GUARD_REASONS],
        "momentos": [],
        "desde": None,
        "hasta": None,
    }
    reply = client.get("/analytics/guardias", params={"source": "prototype"})
    assert reply.status_code == 200 and reply.json()["data"]["total"] == 0


def test_the_delivery_backup_leaves_out_the_prototype_counts(db):
    """Sin persona ni producto, pero lo del prototipo sale de su uso: no viaja, como los conteos del motor."""
    assert PERSON_TABLES["guard_blocks"] == "source = 'synthetic'"
    assert unknown_person_tables(db) == []
