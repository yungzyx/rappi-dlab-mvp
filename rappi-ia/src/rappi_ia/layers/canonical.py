"""Producto canónico: el mismo producto (marca + nombre + tamaño) aunque Rappi lo liste con distintos ids, tiendas o
verticales. Ante la duda no une: unir mal dos productos es peor que no unirlos."""

import logging
import re
from collections import Counter, defaultdict
from pathlib import Path

from psycopg import Connection

from ..text import normalize
from .measures import NAME_MEASURE
from .runs import finish_layer_run, rules_version, start_layer_run

log = logging.getLogger(__name__)

RULES_VERSION = "2026-10-06"
# «6 x» de «6 x 350 ml» solo es un pack cuando una medida lo sigue; «20 x 30 cm», «X12» o «Talla 1 x 50» no se tocan.
_PACK_BEFORE_MEASURE = re.compile(
    r"\b\d{1,2}\s*x\s*(?=\d+(?:[.,]\d+)?\s*(?:ml|cc|lts?|l|gr?s?|kg|oz)\b)", re.IGNORECASE
)
_ARTICLES = {"de", "la", "el", "los", "las", "y"}
# Palabras que describen sin distinguir: «Coca-Cola Bebida Gaseosa Original» es «Coca-Cola Original».
_FILLER = {"bebida", "gaseosa", "sabor", "refresco", "botella", "en", "a"}


def name_key(name: str, brand_words: set[str]) -> str:
    """El nombre sin marca ni tamaño, con las palabras ordenadas: «Coca-Cola Original 1.5L» y «Coca Cola Original
    1,5 L» dan la misma clave; «Zero» u «Original», «con» y «sin lactosa», «20W» y «35W», «12 Unidades» y «4 Unidades»,
    o un pack y la unidad, no. Un combo («Alto 1lt + Coca 1.5lt») no tiene clave."""
    if "+" in name:
        return ""
    text = NAME_MEASURE.sub(" ", _PACK_BEFORE_MEASURE.sub(" ", name))
    ignored = brand_words | _ARTICLES | _FILLER
    words = [w for w in normalize(text).split() if w not in ignored]
    return " ".join(sorted(words))


def build_canonical(conn: Connection) -> dict:
    """Recalcula `canonical_products` e `item_canonical` de los productos con marca y medida comparable (sin medida
    sospechosa); los demás no se unen. Idempotente."""
    run = start_layer_run(conn, "canonical", rules_version(RULES_VERSION, Path(__file__)))
    brand_words = {
        key: {*normalize(name).split(), normalize(name).replace(" ", "")}  # «coca cola» y «cocacola»
        for key, name in conn.execute("SELECT brand_key, name FROM product_brands")
    }
    rows = conn.execute(
        """SELECT ci.master_product_id, ci.name, b.brand_key, m.total, m.unit
           FROM catalog_items ci
           JOIN item_brands b ON b.entity_type = 'catalog_item' AND b.entity_id = ci.master_product_id::text
           JOIN item_measures m ON m.entity_type = 'catalog_item' AND m.entity_id = ci.master_product_id::text
           WHERE m.total > 0 AND m.suspect IS NULL AND m.unit IN ('g', 'ml', 'und')"""
    ).fetchall()
    groups: dict[tuple, list] = defaultdict(list)
    for master_id, name, brand_key, total, unit in rows:
        key = (brand_key, name_key(name or "", brand_words.get(brand_key, set())), total, unit)
        if key[1]:
            groups[key].append((master_id, name))
    # En el lugar: el mismo producto conserva su canonical_id entre corridas (otras tablas y herramientas lo citan).
    conn.execute("DELETE FROM item_canonical WHERE method <> 'curado'")
    curated = {r[0] for r in conn.execute("SELECT master_product_id FROM item_canonical")}
    members, seen = [], []
    with conn.cursor() as cur:
        for (brand_key, key, total, unit), items in groups.items():
            label = Counter(name for _id, name in items).most_common(1)[0][0]
            canonical_id = cur.execute(
                """INSERT INTO canonical_products (brand_key, name_key, total, unit, label, items)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (brand_key, name_key, total, unit) DO UPDATE SET label = EXCLUDED.label,
                     items = EXCLUDED.items
                   RETURNING canonical_id""",
                (brand_key, key, total, unit, label, len(items)),
            ).fetchone()[0]
            seen.append(canonical_id)
            members += [(m, canonical_id, "exacto", 0.9, run) for m, _name in items if m not in curated]
        cur.executemany(
            "INSERT INTO item_canonical (master_product_id, canonical_id, method, confidence, run_id) "
            "VALUES (%s, %s, %s, %s, %s)",
            members,
        )
        conn.execute(
            """DELETE FROM canonical_products c WHERE c.canonical_id <> ALL(%s)
               AND NOT EXISTS (SELECT 1 FROM item_canonical i WHERE i.canonical_id = c.canonical_id)""",
            (seen,),
        )
    conn.execute("ANALYZE canonical_products")
    conn.execute("ANALYZE item_canonical")
    counts = {
        "canonicos": len(groups),
        "items": len(members),
        "compartidos": sum(1 for items in groups.values() if len(items) > 1),
    }
    finish_layer_run(conn, run, counts)
    log.info("Canónicos: %s", counts)
    return counts
