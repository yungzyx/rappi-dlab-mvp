""" "Juzgar la búsqueda": la muestra a ciegas, el juicio guardado en search_judgments (migración 063) y
`eval-human --desde-base`, contra un catálogo de prueba y una muestra de tres pares."""

import json
from argparse import Namespace

import pytest
from fastapi.testclient import TestClient

from conftest import add_dish, add_price, add_product, add_store
from rappi_ia import cli
from rappi_ia.api import app as api
from rappi_ia.eval import human_judgments, sheets

PAIRS = [
    {
        "id": "P0000000001",
        "vertical": "supermercado",
        "consulta": "papas fritas",
        "tipo": "exacta",
        "posicion": 1,
        "estrato": "top3",
        "relevante_auto": True,
        "discrepa": False,
        "entity_type": "catalog_item",
        "entity_id": "100",
    },
    {
        "id": "P0000000002",
        "vertical": "restaurantes",
        "consulta": "poke",
        "tipo": "exacta",
        "posicion": 7,
        "estrato": "4-10",
        "relevante_auto": False,
        "discrepa": True,
        "entity_type": "menu_item",
        "entity_id": "500",
    },
    {  # el producto ya no está en el catálogo de esta base
        "id": "P0000000003",
        "vertical": "supermercado",
        "consulta": "ramitas",
        "tipo": "exacta",
        "posicion": 2,
        "estrato": "top3",
        "relevante_auto": True,
        "discrepa": False,
        "entity_type": "catalog_item",
        "entity_id": "999",
    },
]


@pytest.fixture
def sample(db, tmp_path, monkeypatch):
    path = tmp_path / "planilla-busqueda-ids.json"
    path.write_text(json.dumps({"semilla": 7, "pares": PAIRS}), encoding="utf-8")
    monkeypatch.setattr(human_judgments, "SEARCH_IDS_FILE", path)
    monkeypatch.setattr(sheets, "SEARCH_IDS_FILE", path)
    add_store(db, 1, "supermercado", "Súper")
    add_store(db, 2, "supermercado", "Súper Caro")
    add_store(db, 3, "restaurantes", "Poke House")
    add_product(db, 100, "Papas fritas Lays 180 g", 1, "Snacks salados")
    db.execute("INSERT INTO store_products (store_id, sku, master_product_id) VALUES (2, 'sku-100', 100)")
    add_price(db, 1, 100, 1990)
    add_price(db, 2, 100, 2490)
    add_dish(db, 500, "Poke de salmón", 3, "Pokes")
    db.execute("INSERT INTO scrape_runs (run_id, kind, status) VALUES (999, 'restaurants', 'done')")
    db.execute("INSERT INTO menu_price_snapshots (run_id, item_id, price) VALUES (999, 500, 7990)")
    db.commit()
    return path


@pytest.fixture
def client(db, sample):
    def conn_override():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    try:
        yield TestClient(api.app)
    finally:
        api.app.dependency_overrides.clear()


def test_pairs_are_blind_and_show_what_the_app_showed(db, sample):
    data = human_judgments.pairs_to_judge(db, "J1")

    assert (data["muestra"], data["fuera_del_catalogo"]) == (3, 1)
    by_id = {row["id"]: row for row in data["pares"]}
    assert by_id["P0000000001"] == {
        "id": "P0000000001",
        "consulta": "papas fritas",
        "vertical": "supermercado",
        "nombre": "Papas fritas Lays 180 g",
        "presentacion": None,
        "tienda": "Súper",  # la oferta vigente más barata del vertical
        "precio": 1990.0,
        "imagen": None,
        "categoria": "Snacks salados",
        "juicio": None,
    }
    assert by_id["P0000000002"]["tienda"] == "Poke House"
    assert by_id["P0000000002"]["precio"] == 7990.0
    assert by_id["P0000000002"]["categoria"] == "Pokes"
    for row in data["pares"]:  # ni el método, ni la posición, ni el juez por concepto
        assert not {"posicion", "estrato", "relevante_auto", "discrepa", "tipo", "entity_type"} & row.keys()
    # Un orden barajado fijo: el mismo cada vez.
    assert [r["id"] for r in human_judgments.pairs_to_judge(db, "J1")["pares"]] == [r["id"] for r in data["pares"]]


def test_judging_again_replaces_the_judgment_per_judge(db, sample):
    human_judgments.save(db, "P0000000001", 2, "J1")
    human_judgments.save(db, "P0000000001", 1, "J1")
    human_judgments.save(db, "P0000000002", 0, "J1")
    human_judgments.save(db, "P0000000001", 0, "J2")

    assert human_judgments.load(db, "J1") == {"P0000000001": 1, "P0000000002": 0}
    assert human_judgments.load(db, "J2") == {"P0000000001": 0}
    progress = human_judgments.progress(db, "J1")
    assert progress["juzgados"] == 2
    assert progress["por_valor"] == {"sirve": 0, "a medias": 1, "no sirve": 1}
    assert progress["jueces"] == [{"juez": "J1", "juzgados": 2}, {"juez": "J2", "juzgados": 1}]
    with pytest.raises(human_judgments.UnknownPair):
        human_judgments.save(db, "P9999999999", 2, "J1")


def test_api_lists_saves_and_counts(client):
    pairs = client.get("/analytics/juicio-busqueda/pares", params={"juez": "J1"})
    assert pairs.status_code == 200
    assert len(pairs.json()["pares"]) == 2

    saved = client.put("/analytics/juicio-busqueda/pares/P0000000002", json={"nivel": 2, "juez": "J1"})
    assert saved.status_code == 200
    assert (saved.json()["juzgados"], saved.json()["por_valor"]["sirve"]) == (1, 1)
    again = client.get("/analytics/juicio-busqueda/pares", params={"juez": "J1"}).json()["pares"]
    assert {row["id"]: row["juicio"] for row in again} == {"P0000000001": None, "P0000000002": 2}
    assert client.get("/analytics/juicio-busqueda/avance", params={"juez": "J1"}).json()["juzgados"] == 1
    assert client.get("/analytics/juicio-busqueda/avance", params={"juez": "J2"}).json()["juzgados"] == 0


@pytest.mark.parametrize(
    ("pair", "body"),
    [
        ("P0000000002", {"nivel": 3, "juez": "J1"}),  # no hay nivel 3
        ("P0000000002", {"nivel": 2, "juez": "ana@correo.cl"}),  # un rótulo, nunca un correo
        ("P0000000002", {"nivel": 2, "juez": "Ana María"}),
        ("cualquier-cosa", {"nivel": 2, "juez": "J1"}),
    ],
)
def test_api_rejects_what_is_not_a_judgment(client, pair, body):
    assert client.put(f"/analytics/juicio-busqueda/pares/{pair}", json=body).status_code == 422


def test_api_rejects_a_pair_outside_the_sample(client):
    assert client.put("/analytics/juicio-busqueda/pares/P9999999999", json={"nivel": 2}).status_code == 404


def test_eval_human_reads_the_judgments_from_the_database(db, sample, capsys):
    human_judgments.save(db, "P0000000001", 2, "J1")  # el juez por concepto también dijo relevante
    human_judgments.save(db, "P0000000002", 1, "J1")  # "a medias"; el juez por concepto dijo no relevante
    db.commit()

    cli.cmd_eval_human(db, Namespace(desde_base=True, juez=None))
    out = capsys.readouterr().out
    assert 'Juicios en la base (juez "J1"): 2 de 3 pares juzgados (1 sin juicio' in out
    assert "acuerdo 1.0" in out  # "a medias" no es "sirve": coincide con el no relevante

    human_judgments.save(db, "P0000000001", 0, "J2")
    db.commit()
    with pytest.raises(SystemExit, match="elige uno con --juez"):
        cli.cmd_eval_human(db, Namespace(desde_base=True, juez=None))
    cli.cmd_eval_human(db, Namespace(desde_base=True, juez="J2"))
    assert 'juez "J2"): 1 de 3' in capsys.readouterr().out
    with pytest.raises(SystemExit, match="Todavía no hay juicios"):
        cli.cmd_eval_human(db, Namespace(desde_base=True, juez="J9"))
