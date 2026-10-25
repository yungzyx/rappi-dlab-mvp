"""Lectura y escritura de la capa 2 en Postgres: conceptos, mapeos, asignaciones y complementos."""

import csv
from collections.abc import Iterable
from pathlib import Path

from psycopg import Connection

from .assign import Assignment, MappedName
from .taxonomy import DATA_DIR, Taxonomy

CATEGORY_MAP_CSV = DATA_DIR / "category_map.csv"
# Los mapeos `llm` salieron de dos agentes independientes + un juez (flujo del 27-09-2026).
LLM_MAP_VERSION = "claude-opus-5-5/2-mapeadores+juez/2026-09-27"
NO_CONCEPT = "ninguno"
# `concepts` recalcula todo en cada corrida; los `jev` se heredan de los mapeos de category_map, que el CSV no borra.
MANAGED_METHODS = ("curado", "llm", "regla", "embedding", "jev")


def seed_taxonomy(conn: Connection, taxonomy: Taxonomy) -> int:
    """Carga grupos y conceptos (upsert) y borra los que ya no están en la taxonomía."""
    for node in taxonomy.all_nodes():
        conn.execute(
            """INSERT INTO concepts (concept_id, name, parent_id, emoji, keywords, sensitive, age_restricted,
                                     prepared, taxonomy_version, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
               ON CONFLICT (concept_id) DO UPDATE SET
                 name = EXCLUDED.name, parent_id = EXCLUDED.parent_id, emoji = EXCLUDED.emoji,
                 keywords = EXCLUDED.keywords, sensitive = EXCLUDED.sensitive,
                 age_restricted = EXCLUDED.age_restricted, prepared = EXCLUDED.prepared,
                 taxonomy_version = EXCLUDED.taxonomy_version,
                 updated_at = now()""",
            (
                node.id,
                node.name,
                node.parent,
                node.emoji,
                list(node.keywords),
                node.sensitive,
                node.age_restricted,
                node.prepared,
                taxonomy.version,
            ),
        )
    ids = [n.id for n in taxonomy.all_nodes()]
    # Primero las hojas (sus padres pueden estar en la misma lista de borrado).
    conn.execute("DELETE FROM concepts WHERE concept_id <> ALL(%s) AND parent_id IS NOT NULL", (ids,))
    conn.execute("DELETE FROM concepts WHERE concept_id <> ALL(%s)", (ids,))
    # El grafo no tiene claves foráneas hacia los conceptos (sus nodos son de varios tipos): se limpia a mano.
    conn.execute(
        """DELETE FROM knowledge_edges e WHERE
           (e.from_kind = 'concept' AND NOT EXISTS (SELECT 1 FROM concepts c WHERE c.concept_id = e.from_id))
           OR (e.to_kind = 'concept' AND NOT EXISTS (SELECT 1 FROM concepts c WHERE c.concept_id = e.to_id))"""
    )
    return len(ids)


def seed_curated_edges(conn: Connection, edges: Iterable[tuple[str, str, float]]) -> int:
    conn.execute("DELETE FROM concept_edges WHERE method = 'curado'")
    rows = [(s, t, w) for s, t, w in edges]
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO concept_edges (from_concept, to_concept, method, weight, data_source)
               VALUES (%s, %s, 'curado', %s, 'curado')""",
            rows,
        )
    return len(rows)


def read_category_map_csv(path: Path = CATEGORY_MAP_CSV) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    _check_reviewed(rows)
    _check_one_concept_per_key(rows)
    return [row for row in rows if row["concept_id"] != NO_CONCEPT]


def categories_reviewed_without_concept(path: Path = CATEGORY_MAP_CSV) -> list[str]:
    """Claves de las categorías revisadas que a propósito no tienen concepto (filas «ninguno»). No se guardan en
    category_map, así que el reporte las recibe aparte para no volver a proponerlas."""
    with path.open(encoding="utf-8") as f:
        return [
            row["nombre"].strip().lower()
            for row in csv.DictReader(f)
            if row["tipo"] == "categoria" and row["concept_id"] == NO_CONCEPT
        ]


PROPOSAL_METHODS = ("jev", "sugerido")


def _check_reviewed(rows: list[dict]) -> None:
    """Una fila de jev o sugerido es una propuesta de la máquina, no una revisión: al promoverla, la persona cambia su
    metodo a «curado». Si no, el CSV la daría por revisada y pisaría el mapeo de Jev sin que nadie lo haya mirado."""
    for number, row in enumerate(rows, start=2):  # la fila 1 es el encabezado
        if row["metodo"] in PROPOSAL_METHODS:
            raise ValueError(
                f"category_map.csv, fila {number}: «{row['nombre'].strip().lower()}» tiene metodo «{row['metodo']}»,"
                " que es una propuesta sin revisar; cámbialo a «curado» cuando una persona la apruebe"
            )


def _check_one_concept_per_key(rows: list[dict]) -> None:
    """La clave de category_map es el nombre en minúsculas: dos filas con la misma clave y distinto concepto se
    pisarían en silencio (gana la última del archivo)."""
    seen: dict[tuple[str, str], str] = {}
    for row in rows:
        kind, key = row["tipo"], row["nombre"].strip().lower()
        first = seen.setdefault((kind, key), row["concept_id"])
        if first != row["concept_id"]:
            raise ValueError(f"category_map.csv: «{key}» ({kind}) tiene dos conceptos: {first} y {row['concept_id']}")


def load_category_map(conn: Connection, rows: list[dict], rejected: Iterable[str] = ()) -> int:
    """Reemplaza los mapeos curados/LLM por los del CSV versionado en el repo. Los de Jev (propuestos por máquina,
    sin revisión) se conservan, salvo los que el CSV también trae: ahí gana la revisión humana, también cuando dice
    «ninguno» (`rejected`: claves de categorías revisadas sin concepto)."""
    conn.execute("DELETE FROM category_map WHERE method IN ('curado', 'llm')")
    conn.execute(
        "DELETE FROM category_map WHERE method = 'jev' AND source_kind = 'categoria' AND source_key = ANY(%s)",
        (list(rejected),),
    )
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO category_map (source_kind, source_key, source_name, concept_id, method, confidence,
                                         model_version, note)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (source_kind, source_key) DO UPDATE SET
                 source_name = EXCLUDED.source_name, concept_id = EXCLUDED.concept_id, method = EXCLUDED.method,
                 confidence = EXCLUDED.confidence, model_version = EXCLUDED.model_version, note = EXCLUDED.note,
                 valid_from = now()""",
            [
                (
                    row["tipo"],
                    row["nombre"].strip().lower(),
                    row["nombre"],
                    row["concept_id"],
                    row["metodo"],
                    float(row["confianza"]),
                    LLM_MAP_VERSION if row["metodo"] == "llm" else None,
                    row.get("nota") or None,
                )
                for row in rows
            ],
        )
    return len(rows)


def read_category_maps(conn: Connection) -> dict[str, dict[str, MappedName]]:
    maps: dict[str, dict[str, MappedName]] = {"categoria": {}, "seccion_menu": {}, "cocina": {}}
    for kind, key, concept_id, method, confidence, version in conn.execute(
        "SELECT source_kind, source_key, concept_id, method, confidence, model_version FROM category_map"
    ):
        maps[kind][key] = MappedName(concept_id, method, confidence, version)
    return maps


def catalog_items_for_assignment(conn: Connection) -> list[tuple[str, str, str | None]]:
    """(id, nombre, categoría). Los productos importados del CSV antiguo traen la categoría solo en `raw`."""
    return conn.execute(
        """SELECT i.master_product_id::text, i.name, coalesce(c.name, legacy.category)
           FROM catalog_items i
           LEFT JOIN categories c USING (category_id)
           LEFT JOIN LATERAL (
               SELECT sp.raw ->> 'category_name' AS category
               FROM store_products sp
               WHERE i.category_id IS NULL AND sp.master_product_id = i.master_product_id AND sp.raw ? 'category_name'
               LIMIT 1
           ) legacy ON true"""
    ).fetchall()


def menu_items_for_assignment(conn: Connection) -> list[tuple[str, str, str | None, list[str], str]]:
    """(id, nombre, sección, cocinas del restaurante, descripción)."""
    return conn.execute(
        """SELECT mi.item_id::text, mi.name, ms.name,
                  coalesce(array_agg(rc.cuisine ORDER BY rc.cuisine) FILTER (WHERE rc.cuisine IS NOT NULL), '{}'),
                  coalesce(mi.description, '')
           FROM menu_items mi
           LEFT JOIN menu_sections ms ON ms.store_id = mi.store_id AND ms.section_id = mi.section_id
           LEFT JOIN restaurant_cuisines rc ON rc.store_id = mi.store_id
           GROUP BY mi.item_id, mi.name, ms.name, mi.description"""
    ).fetchall()


def refresh_assortment(conn: Connection) -> None:
    """Surtido por concepto y vertical (y por tienda, para «También en») que leen el agente y el panel: vistas
    materializadas de las migraciones 012 y 016. CONCURRENTLY: la API sigue leyendo la versión anterior mientras
    se recalculan."""
    conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY concept_assortment")
    conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY concept_store_assortment")


def save_assignments(conn: Connection, assignments: list[Assignment]) -> int:
    """Upsert de las asignaciones y borra las gestionadas aquí que ya no aplican (p. ej. cambió la taxonomía)."""
    conn.execute("""CREATE TEMP TABLE new_item_concepts (LIKE item_concepts INCLUDING DEFAULTS) ON COMMIT DROP""")
    with (
        conn.cursor() as cur,
        cur.copy(
            """COPY new_item_concepts (entity_type, entity_id, concept_id, method, confidence, model_version, source)
           FROM STDIN"""
        ) as copy,
    ):
        for a in assignments:
            copy.write_row(
                (a.entity_type, a.entity_id, a.concept_id, a.method, a.confidence, a.model_version, a.source)
            )
    conn.execute(
        """INSERT INTO item_concepts (entity_type, entity_id, concept_id, method, confidence, model_version, source)
           SELECT entity_type, entity_id, concept_id, method, confidence, model_version, source FROM new_item_concepts
           ON CONFLICT (entity_type, entity_id) DO UPDATE SET
             concept_id = EXCLUDED.concept_id, method = EXCLUDED.method, confidence = EXCLUDED.confidence,
             model_version = EXCLUDED.model_version, source = EXCLUDED.source, updated_at = now()"""
    )
    conn.execute(
        """DELETE FROM item_concepts ic
           WHERE ic.method = ANY(%s)
             AND NOT EXISTS (SELECT 1 FROM new_item_concepts n
                             WHERE n.entity_type = ic.entity_type AND n.entity_id = ic.entity_id)""",
        (list(MANAGED_METHODS),),
    )
    return len(assignments)
