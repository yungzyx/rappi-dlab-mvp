"""Exporta el catálogo por vertical a CSV (`rappi export-csv`)."""

import codecs
from pathlib import Path

from psycopg import Connection

EXPORT_SQL = """
COPY (
    SELECT iv.vertical, array_to_string(iv.subverticals, '|') AS subverticales, ci.master_product_id,
           ci.name AS nombre, ci.trademark AS marca, ci.presentation AS presentacion, c.name AS categoria,
           ci.description AS descripcion, iv.stores AS tiendas, ci.image_url AS imagen_url
    FROM v_item_verticals iv
    JOIN catalog_items ci USING (master_product_id)
    LEFT JOIN categories c USING (category_id)
    ORDER BY iv.vertical, ci.name
) TO STDOUT WITH (FORMAT csv, HEADER)
"""


def export_catalog_csv(conn: Connection, target: Path) -> Path:
    """Exporta el catálogo (un producto por vertical) a CSV, con BOM para que Excel lea bien los acentos."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as f, conn.cursor().copy(EXPORT_SQL) as copy:
        f.write(codecs.BOM_UTF8)
        for chunk in copy:
            f.write(chunk)
    return target
