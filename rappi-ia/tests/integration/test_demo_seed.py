"""El catálogo de prueba inventado: ocho verticales con precio, sin nada del catálogo real."""

import psycopg

from rappi_ia import cli
from rappi_ia.demo.seed import DEMO_VERTICALS, seed_demo


def test_seed_demo_fills_every_vertical_with_priced_products(db):
    result = seed_demo(db)

    assert set(result) == set(DEMO_VERTICALS)
    assert all(count >= 6 for count in result.values()), result
    documents = dict(db.execute("SELECT vertical, count(*) FROM search_documents GROUP BY 1").fetchall())
    assert all(documents.get(vertical, 0) >= 6 for vertical in DEMO_VERTICALS), documents
    unpriced = db.execute(
        """SELECT count(*) FROM catalog_items ci
           WHERE NOT EXISTS (SELECT 1 FROM store_products sp
                             JOIN price_snapshots ps ON ps.store_id = sp.store_id AND ps.sku = sp.sku
                             WHERE sp.master_product_id = ci.master_product_id)"""
    ).fetchone()[0]
    assert unpriced == 0


def test_demo_catalog_is_invented(db):
    seed_demo(db)

    for table in ("stores", "catalog_items", "menu_items"):
        rows = db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608 (tablas fijas)
        marked = db.execute(f"SELECT count(*) FROM {table} WHERE name ILIKE '%prueba%'").fetchone()[0]  # noqa: S608
        assert rows > 0 and marked == rows, table


def test_seed_demo_assigns_concepts(db):
    seed_demo(db)

    with_concept = {
        row[0]
        for row in db.execute(
            """SELECT DISTINCT d.vertical
               FROM item_concepts ic
               JOIN search_documents d ON d.entity_type = ic.entity_type AND d.entity_id = ic.entity_id"""
        )
    }
    assert with_concept == set(DEMO_VERTICALS)


def test_seed_demo_command_replaces_the_test_database(test_url, capsys):
    """`rappi-ia seed-demo` reconstruye la base de prueba desde cero (sin el fixture `db`: borra la base)."""
    cli.main(["seed-demo"])

    with psycopg.connect(test_url) as conn:
        verticals = conn.execute("SELECT count(DISTINCT vertical) FROM search_documents").fetchone()[0]
    assert verticals == len(DEMO_VERTICALS)
    out = capsys.readouterr().out
    assert out.startswith("Catálogo de prueba listo: ") and out.strip().endswith("ítems en 8 verticales")
