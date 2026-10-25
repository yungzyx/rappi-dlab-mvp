"""`rappi-ia concepts`: carga la taxonomía, los complementos y el mapa de categorías, y asigna conceptos."""

import logging

from psycopg import Connection

from ..embeddings.base import TextEmbedder
from . import store
from .assign import assign_catalog_item, assign_menu_item, concept_matcher
from .taxonomy import load_complements, load_taxonomy

log = logging.getLogger(__name__)


def build_concepts(conn: Connection, embedder: TextEmbedder | None = None) -> dict:
    """Con `embedder`, refina con vecinos cercanos (kNN) sobre los nombres; sin él, solo categorías y reglas."""
    taxonomy = load_taxonomy()
    counts = {
        "conceptos": store.seed_taxonomy(conn, taxonomy),
        "complementos": store.seed_curated_edges(conn, load_complements()),
        "mapeos": store.load_category_map(
            conn, store.read_category_map_csv(), store.categories_reviewed_without_concept()
        ),
    }
    maps = store.read_category_maps(conn)
    matcher = concept_matcher(taxonomy)

    assignments = []
    for item_id, name, category in store.catalog_items_for_assignment(conn):
        assignment = assign_catalog_item(item_id, name, category, maps["categoria"], matcher)
        if assignment:
            assignments.append(assignment)
    catalog_assigned = len(assignments)
    for item_id, name, section, cuisines, description in store.menu_items_for_assignment(conn):
        assignment = assign_menu_item(
            item_id, name, section, cuisines, maps["seccion_menu"], maps["cocina"], matcher, description
        )
        if assignment:
            assignments.append(assignment)

    if embedder is not None:
        from .knn import refine

        assignments = refine(conn, embedder, assignments)
        catalog_assigned = sum(1 for a in assignments if a.entity_type == "catalog_item")

    store.save_assignments(conn, assignments)
    store.refresh_assortment(conn)
    conn.commit()
    counts["productos_con_concepto"] = catalog_assigned
    counts["platos_con_concepto"] = len(assignments) - catalog_assigned
    log.info("Capa 2: %s", counts)
    return counts
