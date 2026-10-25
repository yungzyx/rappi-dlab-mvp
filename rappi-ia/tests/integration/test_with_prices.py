"""Precios de la búsqueda (`agent/tools.py:_with_prices`) contra `rappi_ia_test`, con un catálogo armado a mano."""

import types

from conftest import add_store
from rappi_ia.agent.tools import _with_prices

SUPER, SAME_FORMAT, NO_AISLES = 1, 2, 3


def _offer(db, run_id: int, store_id: int, product_id: int, price: int, aisle_id: int | None = None) -> None:
    sku = f"sku-{product_id}-{store_id}"
    db.execute(
        "INSERT INTO store_products (store_id, sku, master_product_id, aisle_id) VALUES (%s, %s, %s, %s)",
        (store_id, sku, product_id, aisle_id),
    )
    db.execute(
        "INSERT INTO price_snapshots (run_id, store_id, sku, price, in_stock) VALUES (%s, %s, %s, %s, true)",
        (run_id, store_id, sku, price),
    )


def _hit(product_id: int):
    return types.SimpleNamespace(
        entity_type="catalog_item", entity_id=str(product_id), concept_id=None, vertical="supermercado", metadata={}
    )


def test_one_price_per_product_preferring_a_store_that_opens(db):
    add_store(db, SUPER, "supermercado", "Súper")
    add_store(db, SAME_FORMAT, "supermercado", "Súper Express")
    add_store(db, NO_AISLES, "supermercado", "Súper sin pasillos")
    # Dos sucursales del mismo formato con distinta subvertical: v_store_verticals le da dos filas a cada una.
    db.execute("UPDATE stores SET store_type = 'formato' WHERE store_id IN (%s, %s)", (SUPER, SAME_FORMAT))
    db.execute("UPDATE store_verticals SET subvertical = 'Hiper' WHERE store_id = %s", (SUPER,))
    db.execute("UPDATE store_verticals SET subvertical = 'Express' WHERE store_id = %s", (SAME_FORMAT,))
    db.execute(
        "INSERT INTO aisles (store_id, aisle_id, parent_aisle_id, name) VALUES (%s, 10, NULL, 'Despensa')", (SUPER,)
    )
    run_id = db.execute("INSERT INTO scrape_runs (kind, status) VALUES ('stores', 'done') RETURNING run_id")
    run_id = run_id.fetchone()[0]
    db.execute("INSERT INTO catalog_items (master_product_id, name) VALUES (100, 'Arroz'), (101, 'Té verde')")
    _offer(db, run_id, SUPER, 100, 1500, aisle_id=10)
    _offer(db, run_id, NO_AISLES, 100, 1000)  # más barato, pero la tienda no se abre
    _offer(db, run_id, NO_AISLES, 101, 900)
    rows = db.execute("SELECT subvertical FROM v_store_verticals WHERE store_id = %s ORDER BY 1", (SUPER,)).fetchall()
    assert rows == [("Express",), ("Hiper",)]

    products = _with_prices(db, "supermercado", [_hit(100), _hit(101)])

    assert [(p.entity_id, p.price_value, p.store_id, p.store) for p in products] == [
        ("100", 1500.0, SUPER, "Súper"),  # la que se abre gana aunque sea más cara, una sola vez
        ("101", 900.0, None, "Súper sin pasillos"),  # sin ninguna que se abra: la más barata, sin id de tienda
    ]
