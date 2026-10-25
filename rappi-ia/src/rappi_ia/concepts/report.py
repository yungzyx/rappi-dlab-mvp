"""Reporte de cobertura de la capa 2: cuánto del catálogo y de los menús tiene concepto, y cómo se asignó."""

import csv
from pathlib import Path

from psycopg import Connection

from .. import config
from .store import categories_reviewed_without_concept

MIN_COVERAGE_PCT = 85  # meta de la etapa 1 (docs/diseno-ia.md §7)
LISTED_UNMAPPED = 10
MIN_SUGGESTION_SHARE = 0.5  # se sugiere un concepto si lo tiene al menos la mitad de los productos de la categoría
CATEGORY_MAP_COLUMNS = ["tipo", "nombre", "concept_id", "confianza", "metodo", "revision", "nota", "productos"]

# Categorías del catálogo sin mapeo (curado o LLM, los de category_map.csv, o propuesto por Jev, que se cuenta aparte
# en `mapeos_jev`): sus productos quedan en manos de las reglas por nombre o del kNN. El concepto sugerido es el más
# común entre los productos que ya lo tienen. Las revisadas sin concepto (filas «ninguno» del CSV, el parámetro)
# tampoco se listan.
UNMAPPED_CATEGORIES = """
WITH products AS (
    SELECT c.name, i.master_product_id::text AS id
    FROM catalog_items i JOIN categories c USING (category_id)
    WHERE lower(trim(c.name)) <> ALL(%s)
      AND NOT EXISTS (SELECT 1 FROM category_map m
                      WHERE m.source_kind = 'categoria' AND m.source_key = lower(trim(c.name))
                        AND m.method IN ('curado', 'llm', 'jev'))
),
tagged AS (
    SELECT p.name, p.id, ic.concept_id
    FROM products p
    LEFT JOIN item_concepts ic ON ic.entity_type = 'catalog_item' AND ic.entity_id = p.id
),
top AS (
    SELECT DISTINCT ON (name) name, concept_id, count(*) AS n
    FROM tagged WHERE concept_id IS NOT NULL
    GROUP BY name, concept_id
    ORDER BY name, count(*) DESC, concept_id
)
SELECT t.name, count(*), count(*) FILTER (WHERE t.concept_id IS NULL), top.concept_id, coalesce(top.n, 0)
FROM tagged t LEFT JOIN top USING (name)
GROUP BY t.name, top.concept_id, top.n
ORDER BY 2 DESC, 1
"""


def jev_review_path() -> Path:
    """Cola de categorías que Jev deja para revisión humana (fuera de git: lleva nombres del catálogo)."""
    return config.DATA_DIR / "concepts" / "revision-jev.csv"


def coverage_report(conn: Connection) -> dict:
    by_vertical = conn.execute(
        """SELECT iv.vertical, count(DISTINCT iv.master_product_id), count(DISTINCT ic.entity_id)
           FROM v_item_verticals iv
           LEFT JOIN item_concepts ic ON ic.entity_type = 'catalog_item' AND ic.entity_id = iv.master_product_id::text
           GROUP BY 1
           UNION ALL
           SELECT 'restaurantes', count(*), count(ic.entity_id)
           FROM menu_items mi
           LEFT JOIN item_concepts ic ON ic.entity_type = 'menu_item' AND ic.entity_id = mi.item_id::text
           ORDER BY 2 DESC"""
    ).fetchall()
    totals = conn.execute(
        """SELECT 'catalog_item', count(*), count(ic.entity_id) FROM catalog_items i
           LEFT JOIN item_concepts ic ON ic.entity_type = 'catalog_item' AND ic.entity_id = i.master_product_id::text
           UNION ALL
           SELECT 'menu_item', count(*), count(ic.entity_id) FROM menu_items mi
           LEFT JOIN item_concepts ic ON ic.entity_type = 'menu_item' AND ic.entity_id = mi.item_id::text"""
    ).fetchall()
    by_method = conn.execute(
        "SELECT entity_type, method, count(*) FROM item_concepts GROUP BY 1, 2 ORDER BY 1, 3 DESC"
    ).fetchall()
    top_concepts = conn.execute(
        """SELECT c.emoji || ' ' || c.name, count(*) FROM item_concepts ic JOIN concepts c USING (concept_id)
           GROUP BY 1 ORDER BY 2 DESC LIMIT 15"""
    ).fetchall()
    empty_concepts = conn.execute(
        """SELECT c.concept_id FROM concepts c
           WHERE c.parent_id IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM item_concepts ic WHERE ic.concept_id = c.concept_id)
           ORDER BY 1"""
    ).fetchall()
    unmapped = [
        {"nombre": name, "productos": n, "sin_concepto": missing, "sugerido": concept, "con_sugerido": with_concept}
        for name, n, missing, concept, with_concept in conn.execute(
            UNMAPPED_CATEGORIES, (categories_reviewed_without_concept(),)
        )
    ]
    jev_mappings = conn.execute("SELECT count(*) FROM category_map WHERE method = 'jev'").fetchone()[0]
    return {
        "categorias_sin_mapear": unmapped,
        "mapeos_jev": jev_mappings,
        "revision_jev": _count_rows(jev_review_path()),
        "totales": {kind: _pct_row(total, mapped) for kind, total, mapped in totals},
        "por_vertical": {vertical: _pct_row(total, mapped) for vertical, total, mapped in by_vertical},
        "por_metodo": [{"tipo": t, "metodo": m, "n": n} for t, m, n in by_method],
        "conceptos_top": [{"concepto": name, "n": n} for name, n in top_concepts],
        "conceptos_sin_items": [row[0] for row in empty_concepts],
    }


def render_text(report: dict) -> str:
    lines = []
    warnings = [
        f"{kind} {row['pct']}%"
        for kind, row in report["totales"].items()
        if row["total"] and row["pct"] < MIN_COVERAGE_PCT
    ]
    lines.append(
        f"⚠ Cobertura bajo {MIN_COVERAGE_PCT}%: {', '.join(warnings)}"
        if warnings
        else f"✓ Cobertura ≥ {MIN_COVERAGE_PCT}% en productos y platos"
    )
    lines.append("")
    lines.append("Cobertura por vertical (con concepto / total):")
    for vertical, row in report["por_vertical"].items():
        lines.append(f"  {vertical:<14} {row['mapped']:>7} / {row['total']:<7} {row['pct']:>5}%")
    lines.append("")
    lines.append("Cómo se asignó:")
    for row in report["por_metodo"]:
        lines.append(f"  {row['tipo']:<13} {row['metodo']:<10} {row['n']:>7}")
    lines.append("")
    top = ", ".join(f"{r['concepto']} ({r['n']})" for r in report["conceptos_top"])
    lines.append(f"Conceptos con más ítems: {top}")
    if report["conceptos_sin_items"]:
        lines.append("Conceptos sin ítems todavía: " + ", ".join(report["conceptos_sin_items"]))
    if report["mapeos_jev"] or report["revision_jev"]:
        lines.append(
            f"Jev: {report['mapeos_jev']} categorías mapeadas sin revisión humana y {report['revision_jev']} en"
            " revisión; `rappi-ia map-categories --jev --exportar` las exporta para revisarlas y pasarlas a"
            " category_map.csv."
        )
    unmapped = report["categorias_sin_mapear"]
    if unmapped:
        products = sum(row["productos"] for row in unmapped)
        missing = sum(row["sin_concepto"] for row in unmapped)
        lines.append("")
        lines.append(
            f"⚠ {len(unmapped)} categorías sin mapeo revisado ({products} productos, {missing} sin concepto);"
            " `rappi-ia map-categories` las exporta con un concepto sugerido. Las más grandes:"
        )
        for row in unmapped[:LISTED_UNMAPPED]:
            lines.append(f"  {row['nombre']} ({row['productos']} productos, {row['sin_concepto']} sin concepto)")
    return "\n".join(lines)


def write_category_proposals(rows: list[dict], path: Path) -> None:
    """CSV con el formato de category_map.csv (método «sugerido», revisión «pendiente»): se revisa, se cambia el
    método a «curado» y se copia al mapa versionado."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CATEGORY_MAP_COLUMNS)
        writer.writeheader()
        for row in rows:
            share = row["con_sugerido"] / row["productos"] if row["productos"] else 0.0
            suggested = row["sugerido"] if row["sugerido"] and share >= MIN_SUGGESTION_SHARE else "ninguno"
            writer.writerow(
                {
                    "tipo": "categoria",
                    "nombre": row["nombre"],
                    "concept_id": suggested,
                    "confianza": f"{share:.2f}",
                    "metodo": "sugerido",
                    "revision": "pendiente",
                    "nota": f"{row['con_sugerido']} de {row['productos']} productos ya tienen ese concepto",
                    "productos": row["productos"],
                }
            )


def _count_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8", newline="") as f:
        return sum(1 for _ in csv.DictReader(f))


def _pct_row(total: int, mapped: int) -> dict:
    return {"total": total, "mapped": mapped, "pct": round(100 * mapped / total, 1) if total else 0.0}
