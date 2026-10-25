"""Grafo de conocimiento: relaciones entre conceptos, atributos, marcas, verticales y términos. Las curadas viven en
`concepts/relations.toml`; las demás se derivan de la taxonomía, del catálogo y de los eventos (co-búsqueda)."""

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path

from psycopg import Connection
from rappi_scraper.storage.search import VERTICALS

from ..concepts.taxonomy import load_taxonomy
from ..text import normalize
from .attributes import load_attribute_rules
from .runs import finish_layer_run, rules_version, start_layer_run
from .segments import RULES_FILE as SEGMENTS_FILE
from .segments import load_segment_rules

log = logging.getLogger(__name__)

RULES_FILE = Path(__file__).resolve().parents[1] / "concepts" / "relations.toml"
TAXONOMY_FILE = Path(__file__).resolve().parents[1] / "concepts" / "taxonomy.toml"
KINDS = frozenset(
    {"concept", "group", "attribute", "segment", "brand", "vertical", "occasion", "service", "canonical", "term"}
)
MIN_ATTRIBUTE_SHARE = 0.05  # un concepto «tiene» un atributo si al menos el 5 % de sus ítems lo lleva…
MIN_ATTRIBUTE_ITEMS = 3  # …y son al menos tantos ítems
MIN_BRAND_ITEMS = 5  # una marca «es de» un concepto si vende al menos tantos ítems ahí…
MIN_BRAND_SHARE = 0.03  # …y son el 3 % de sus productos (una marca mal asignada no se cuela)
MIN_VERTICAL_ITEMS = 3  # un concepto «se vende en» una vertical con al menos tantos ítems…
MIN_VERTICAL_SHARE = 0.05  # …y el 5 % de lo que tiene en la vertical donde más vende
MIN_SESSIONS = 30  # sesiones mínimas para aprender que dos conceptos se buscan juntos…
MIN_USERS = 5  # …de al menos tantas personas distintas: una sola no hace una relación (y no se re-identifica)
SEARCH_TYPES = ("search", "chat", "ask", "view_item")  # lo que la persona hace; el carro puede venir de una sugerencia
DERIVED_RELATIONS = ("es_tipo_de", "de_ocasion", "se_vende_en", "tiene_atributo") + (
    "marca_de",
    "equivale",
    "sinonimo",
    "afin_a",
)
KEYWORD_WEIGHT = 1.0  # las keywords asignan productos
QUERY_KEYWORD_WEIGHT = 0.8  # las de consulta solo ayudan a entender lo que la persona escribe


@dataclass(frozen=True)
class RelationDef:
    relation: str
    name: str
    from_kinds: tuple[str, ...]
    to_kinds: tuple[str, ...]
    is_symmetric: bool
    description: str


@dataclass(frozen=True)
class CuratedEdge:
    source: str  # «tipo:id»
    relation: str
    target: str
    weight: float


def split_node(ref: str) -> tuple[str, str]:
    kind, _, ident = ref.partition(":")
    return kind, ident


def load_relation_rules(path: Path | None = None) -> tuple[str, list[RelationDef], list[CuratedEdge]]:
    raw = tomllib.loads((path or RULES_FILE).read_text(encoding="utf-8"))
    relations = [
        RelationDef(
            r["id"],
            r["name"],
            tuple(r["from_kinds"]),
            tuple(r["to_kinds"]),
            r.get("is_symmetric", False),
            r.get("description", ""),
        )
        for r in raw["relation"]
    ]
    edges = [CuratedEdge(e["from"], e["relation"], e["to"], float(e["weight"])) for e in raw.get("edge", ())]
    _validate(relations, edges)
    return raw["version"], relations, edges


def _node_exists(kind: str, ident: str) -> bool:
    taxonomy = load_taxonomy()
    if kind == "concept":
        return ident in taxonomy.concepts
    if kind == "group":
        return ident in taxonomy.groups
    if kind == "occasion":
        return ident in taxonomy.occasions
    if kind == "service":
        return ident in taxonomy.services
    if kind == "vertical":
        return ident in VERTICALS or ident == "restaurantes"
    if kind == "attribute":
        return ident in {a.attribute_id for a in load_attribute_rules()[1]}
    return True  # segmentos, marcas, canónicos y términos se validan donde se definen


def _validate(relations: list[RelationDef], edges: list[CuratedEdge]) -> None:
    ids = [r.relation for r in relations]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Relaciones repetidas: {sorted({i for i in ids if ids.count(i) > 1})}")
    for r in relations:
        bad = (set(r.from_kinds) | set(r.to_kinds)) - KINDS
        if bad:
            raise ValueError(f"Relación {r.relation} con tipos de nodo desconocidos: {sorted(bad)}")
    defs = {r.relation: r for r in relations}
    seen: set[tuple] = set()
    for e in edges:
        if e.relation not in defs:
            raise ValueError(f"Arista con relación desconocida: {e}")
        if e.relation in DERIVED_RELATIONS:
            raise ValueError(f"{e.relation} se deriva; no puede ser curada: {e}")
        (from_kind, from_id), (to_kind, to_id) = split_node(e.source), split_node(e.target)
        if from_kind not in defs[e.relation].from_kinds or to_kind not in defs[e.relation].to_kinds:
            raise ValueError(f"Tipos de nodo inválidos para {e.relation}: {e}")
        if not 0 <= e.weight <= 1:
            raise ValueError(f"Peso fuera de [0, 1]: {e}")
        for kind, ident in ((from_kind, from_id), (to_kind, to_id)):
            if not _node_exists(kind, ident):
                raise ValueError(f"Arista con nodo desconocido ({kind}:{ident}): {e}")
        key = (e.relation, e.source, e.target)
        if defs[e.relation].is_symmetric:
            key = (e.relation, *sorted((e.source, e.target)))
        if e.source == e.target or key in seen:
            raise ValueError(f"Arista repetida o hacia sí misma: {e}")
        seen.add(key)


def build_relations(conn: Connection) -> dict:
    """Recalcula las relaciones curadas y derivadas del grafo (`complementa` y las aprendidas de pedidos no se tocan).
    Idempotente: borra y vuelve a escribir solo lo que esta capa gestiona."""
    taxonomy = load_taxonomy()
    version, relations, curated = load_relation_rules()
    run = start_layer_run(
        conn, "relations", rules_version(version, RULES_FILE, TAXONOMY_FILE, SEGMENTS_FILE, Path(__file__))
    )
    for r in relations:
        conn.execute(
            """INSERT INTO relation_defs (relation, name, from_kinds, to_kinds, is_symmetric, description)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (relation) DO UPDATE SET name = EXCLUDED.name, from_kinds = EXCLUDED.from_kinds,
                 to_kinds = EXCLUDED.to_kinds, is_symmetric = EXCLUDED.is_symmetric,
                 description = EXCLUDED.description""",
            (r.relation, r.name, list(r.from_kinds), list(r.to_kinds), r.is_symmetric, r.description),
        )
    conn.execute(
        "DELETE FROM knowledge_edges WHERE (method = 'curado' AND relation <> 'complementa')"
        " OR (method = 'derivado' AND relation = ANY(%s)) OR relation = 'co_busqueda'",
        (list(DERIVED_RELATIONS),),
    )
    symmetric = {r.relation for r in relations if r.is_symmetric}
    rows = []
    for e in curated:
        (fk, fid), (tk, tid) = split_node(e.source), split_node(e.target)
        rows.append((fk, fid, e.relation, tk, tid, e.weight, "curado", "curado", "relations.toml", run))
        if e.relation in symmetric:
            rows.append((tk, tid, e.relation, fk, fid, e.weight, "curado", "curado", "relations.toml", run))
    counts = {"curadas": len(rows)}
    _insert(conn, rows + _taxonomy_rows(taxonomy, run) + _segment_rows(run))
    counts.update(_derive_from_catalog(conn, run))
    counts.update(_learn_co_search(conn, run))
    counts["sinonimos"] = conn.execute("SELECT count(*) FROM knowledge_edges WHERE relation = 'sinonimo'").fetchone()[0]
    finish_layer_run(conn, run, counts)
    conn.commit()
    conn.execute("ANALYZE knowledge_edges")
    log.info("Relaciones del grafo: %s", counts)
    return counts


def _insert(conn: Connection, rows: list[tuple]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO knowledge_edges (from_kind, from_id, relation, to_kind, to_id, weight, method, data_source,
                                            evidence, run_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT DO NOTHING""",
            rows,
        )


def _taxonomy_rows(taxonomy, run: int) -> list[tuple]:
    """Lo que dice la taxonomía por sí sola: grupo de cada concepto, ocasiones y vocabulario de consulta."""
    rows = [
        ("concept", c.id, "es_tipo_de", "group", c.parent, 1.0, "derivado", "curado", "taxonomy.toml", run)
        for c in taxonomy.concepts.values()
    ]
    rows += [
        ("concept", concept, "de_ocasion", "occasion", o.id, 1.0, "derivado", "curado", "taxonomy.toml", run)
        for o in taxonomy.occasions.values()
        for concept in o.concepts
    ]
    terms: dict[tuple[str, str], float] = {}
    for c in taxonomy.concepts.values():
        for word, weight in (
            *((w, KEYWORD_WEIGHT) for w in (*c.keywords, c.name)),
            *((w, QUERY_KEYWORD_WEIGHT) for w in c.query_keywords),
        ):
            term = normalize(word)
            if term:
                terms[(term, c.id)] = max(weight, terms.get((term, c.id), 0))
    rows += [
        ("term", term, "sinonimo", "concept", concept, weight, "derivado", "curado", "taxonomy.toml", run)
        for (term, concept), weight in terms.items()
    ]
    return rows


def _segment_rows(run: int) -> list[tuple]:
    """Qué mirar primero para cada segmento, leído de su propia regla. Los sensibles no tienen aristas: nada que los
    nombre debe servir para sugerir."""
    kinds = {"concepts": "concept", "groups": "group", "attributes": "attribute", "verticals": "vertical"}
    return [
        ("segment", r.id, "afin_a", kind, target, 1.0, "derivado", "curado", "segments.toml", run)
        for r in load_segment_rules()[1]
        if not r.sensitive
        for piece, kind in kinds.items()
        for target in r.signals.get(piece, ())
    ]


def _derive_from_catalog(conn: Connection, run: int) -> dict:
    # Los platos de restaurante y los productos de catálogo no se pueden comparar (un menú cuenta cada plato de cada
    # local): el peso es relativo dentro del catálogo, y «restaurantes» es presencia (1.0) si hay platos suficientes.
    sell = conn.execute(
        """WITH catalog AS (
               SELECT concept_id, vertical, items, max(items) OVER (PARTITION BY concept_id) AS top
               FROM concept_assortment WHERE vertical <> 'restaurantes')
           INSERT INTO knowledge_edges (from_kind, from_id, relation, to_kind, to_id, weight, method, data_source,
                                        support, evidence, run_id)
           SELECT 'concept', concept_id, 'se_vende_en', 'vertical', vertical, items::real / top, 'derivado',
                  'catalogo', items, 'concept_assortment', %(run)s
           FROM catalog WHERE items >= %(items)s AND items::real / top >= %(share)s
           UNION ALL
           SELECT 'concept', concept_id, 'se_vende_en', 'vertical', vertical, 1.0, 'derivado', 'catalogo', items,
                  'concept_assortment', %(run)s
           FROM concept_assortment WHERE vertical = 'restaurantes' AND items >= %(items)s
           ON CONFLICT DO NOTHING""",
        {"run": run, "items": MIN_VERTICAL_ITEMS, "share": MIN_VERTICAL_SHARE},
    ).rowcount
    # La parte se mide sobre el tipo de ítem al que el atributo aplica: «económico» solo existe en productos, y 40
    # platos no pueden bajar su parte en pizzas.
    has = conn.execute(
        """WITH per_type AS (SELECT concept_id, entity_type, count(*) AS n FROM item_concepts GROUP BY 1, 2),
                denominator AS (
                    SELECT d.attribute_id, t.concept_id, sum(t.n) AS n
                    FROM attribute_defs d JOIN per_type t ON d.applies_to = 'both' OR d.applies_to = t.entity_type
                    GROUP BY 1, 2),
                per_attribute AS (
                    SELECT ic.concept_id, ia.attribute_id, count(*) AS n
                    FROM item_concepts ic
                    JOIN item_attributes ia ON ia.entity_type = ic.entity_type AND ia.entity_id = ic.entity_id
                    GROUP BY 1, 2)
           INSERT INTO knowledge_edges (from_kind, from_id, relation, to_kind, to_id, weight, method, data_source,
                                        support, evidence, run_id)
           SELECT 'concept', pa.concept_id, 'tiene_atributo', 'attribute', pa.attribute_id,
                  (pa.n::real / dn.n), 'derivado', 'catalogo', pa.n, 'item_attributes', %s
           FROM per_attribute pa JOIN denominator dn USING (concept_id, attribute_id)
           WHERE pa.n >= %s AND pa.n::real / dn.n >= %s
           ON CONFLICT DO NOTHING""",
        (run, MIN_ATTRIBUTE_ITEMS, MIN_ATTRIBUTE_SHARE),
    ).rowcount
    brands = conn.execute(
        """WITH per_brand AS (SELECT brand_key, count(*) AS n FROM item_brands WHERE entity_type = 'catalog_item'
                              GROUP BY 1),
                per_pair AS (
                    SELECT b.brand_key, ic.concept_id, count(*) AS n
                    FROM item_brands b
                    JOIN item_concepts ic ON ic.entity_type = b.entity_type AND ic.entity_id = b.entity_id
                    WHERE b.entity_type = 'catalog_item'
                    GROUP BY 1, 2)
           INSERT INTO knowledge_edges (from_kind, from_id, relation, to_kind, to_id, weight, method, data_source,
                                        support, evidence, run_id)
           SELECT 'brand', pp.brand_key, 'marca_de', 'concept', pp.concept_id, (pp.n::real / pb.n), 'derivado',
                  'catalogo', pp.n, 'item_brands', %s
           FROM per_pair pp JOIN per_brand pb USING (brand_key)
           WHERE pp.n >= %s AND pp.n::real / pb.n >= %s
           ON CONFLICT DO NOTHING""",
        (run, MIN_BRAND_ITEMS, MIN_BRAND_SHARE),
    ).rowcount
    equal = conn.execute(
        """WITH per_vertical AS (
                SELECT ic.canonical_id, iv.vertical, count(DISTINCT ic.master_product_id) AS n
                FROM item_canonical ic JOIN v_item_verticals iv USING (master_product_id)
                GROUP BY 1, 2)
           INSERT INTO knowledge_edges (from_kind, from_id, relation, to_kind, to_id, weight, method, data_source,
                                        support, evidence, run_id)
           SELECT 'canonical', canonical_id::text, 'equivale', 'vertical', vertical, 1.0, 'derivado', 'catalogo', n,
                  'item_canonical', %s
           FROM per_vertical
           WHERE canonical_id IN (SELECT canonical_id FROM per_vertical GROUP BY 1 HAVING count(*) >= 2)
           ON CONFLICT DO NOTHING""",
        (run,),
    ).rowcount
    return {"se_vende_en": sell, "tiene_atributo": has, "marca_de": brands, "equivale": equal}


def _learn_co_search(conn: Connection, run: int) -> dict:
    """P(B | A) entre sesiones que buscan, preguntan o miran A, por fuente de datos; sin conceptos sensibles. Una
    sesión es (persona, id de sesión): el cliente elige el id, dos personas pueden repetirlo. No guarda a nadie: el
    resultado son conceptos, con cuántas sesiones y cuántas personas distintas lo respaldan."""
    learned = conn.execute(
        """WITH used AS (
               SELECT DISTINCT e.source, e.user_id, e.session_id, e.concept_id
               FROM app_events e JOIN concepts c ON c.concept_id = e.concept_id
               WHERE e.type = ANY(%s) AND NOT c.sensitive),
           per_concept AS (SELECT source, concept_id, count(*) AS n FROM used GROUP BY 1, 2),
           sessions AS (SELECT source, count(DISTINCT (user_id, session_id))::real AS n FROM used GROUP BY 1),
           pairs AS (
               SELECT a.source, a.concept_id AS a, b.concept_id AS b, count(*) AS both_n,
                      count(DISTINCT a.user_id) AS both_users
               FROM used a JOIN used b ON a.source = b.source AND a.user_id = b.user_id
                                       AND a.session_id = b.session_id AND a.concept_id <> b.concept_id
               GROUP BY 1, 2, 3)
           INSERT INTO knowledge_edges (from_kind, from_id, relation, to_kind, to_id, weight, method, data_source,
                                        support, evidence, run_id)
           SELECT 'concept', p.a, 'co_busqueda', 'concept', p.b, least(1.0, p.both_n::real / pa.n), 'coocurrencia',
                  p.source, p.both_n, 'app_events', %s
           FROM pairs p
           JOIN per_concept pa ON pa.source = p.source AND pa.concept_id = p.a
           JOIN per_concept pb ON pb.source = p.source AND pb.concept_id = p.b
           JOIN sessions s ON s.source = p.source
           WHERE p.both_n >= %s AND p.both_users >= %s AND p.both_n::real / pa.n / (pb.n / s.n) > 1
           ON CONFLICT DO NOTHING""",
        (list(SEARCH_TYPES), run, MIN_SESSIONS, MIN_USERS),
    ).rowcount
    return {"co_busqueda": learned}
