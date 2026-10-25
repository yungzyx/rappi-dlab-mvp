"""Búsqueda híbrida dentro de UN vertical: léxico (tsvector sin tildes) + vectorial (e5) → RRF → refuerzo por concepto.

- Los filtros duros (precio máximo, tipo de entidad) van dentro de cada recuperador, antes de fusionar, para que un
  tope de precio no deje la lista vacía por haber filtrado después.
- "Sin resultado" (demanda no satisfecha) exige las tres condiciones de docs/diseno-ia.md §1: nada calza todas las
  palabras, el coseno máximo queda bajo τ y ningún ítem del vertical comparte concepto con la consulta. El τ es el del
  vertical si la consulta nombra una ocasión, y UNNAMED_TAU si no nombra concepto ni ocasión.
"""

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from psycopg import Connection
from rappi_scraper.storage.search import VERTICALS

from ..catalog.cache import cached, cached_many
from ..concepts.assign import concept_matcher
from ..concepts.matcher import KeywordMatcher
from ..concepts.taxonomy import Occasion, load_taxonomy
from ..embeddings.base import TextEmbedder, to_pgvector
from ..text import FILLER_WORDS, normalize, tokens

RRF_K = 60  # constante estándar de Reciprocal Rank Fusion
CANDIDATES = 200  # tamaño del pool de cada recuperador
CONCEPT_BONUS = 0.5 / (RRF_K + 1)  # medio "primer lugar" extra si el ítem comparte concepto con la consulta
DEFAULT_TAU = 0.82  # coseno e5 mínimo para considerar que hay algo parecido; se calibra por vertical (eval)
# El τ de una consulta que no nombra concepto ni ocasión, en una vertical o en todas (agent/grouped_search: si ninguna
# vertical calza todas las palabras, solo entra una con este coseno). El τ de cada vertical (0,79 en Turbo, 0,70 en el
# Mall y las chocolaterías) dejaba pasar vecinos sin relación: «sofá de tres cuerpos» en Turbo traía pisco Tres Erres
# (0,821) y «xyzzy» un pastillero y libros. Calibrado con e5 en la base real: las negativas sin concepto ni ocasión de
# eval/queries.json llegan a 0,847 («refrigerador 300 litros» en Licores). Con una ocasión («regalo para mi polola»)
# sigue el τ de la vertical: lo pedido son productos que su nombre no dice, y ahí los vecinos vectoriales sirven.
UNNAMED_TAU = 0.85
MIN_CONCEPT_ITEMS = 3  # bajo esto (o bajo 0,05% del vertical) el concepto se considera ausente: surtido testimonial
MIN_CONCEPT_SHARE = 0.0005
THRESHOLDS_FILE = Path(__file__).resolve().parents[1] / "eval" / "thresholds.json"
MODES = ("lexico", "vector", "hibrido")


@dataclass(frozen=True)
class Filters:
    price_max: float | None = None
    entity_types: tuple[str, ...] = ("catalog_item", "menu_item")


@dataclass
class Hit:
    vertical: str
    entity_type: str
    entity_id: str
    content: str
    metadata: dict
    score: float
    concept_id: str | None = None
    cosine: float | None = None
    ranks: dict[str, int] = field(default_factory=dict)


@dataclass
class RetrievalResult:
    vertical: str
    query: str
    hits: list[Hit]
    query_concepts: list[str]
    strict_lexical_matches: int
    max_cosine: float | None
    concept_in_vertical: bool
    unmet: bool
    unmet_reason: str | None
    has_words: bool = True  # le queda alguna palabra sin las stopwords («té» no)
    # Ítems del concepto nombrado con más surtido en el vertical sobre los documentos del vertical (None si la consulta
    # no nombra ninguno): agent/tools._focus no muestra lo rotulado con un concepto que el vertical casi no tiene.
    concept_share: float | None = None
    names_occasion: bool = False  # sin concepto nombrado, si nombra una ocasión: decide el τ del vertical (`_unmet`)


def thresholds() -> dict[str, float]:
    """El τ de cada vertical (eval/thresholds.json). Queda en caché por fecha y tamaño del archivo, como las reglas de
    segmentos: cada búsqueda sin resultado lo consulta, y `make eval` lo puede reescribir."""
    try:
        stat = THRESHOLDS_FILE.stat()
    except FileNotFoundError:
        return {}
    return dict(_read_thresholds(THRESHOLDS_FILE, stat.st_mtime_ns, stat.st_size))


@lru_cache(maxsize=4)
def _read_thresholds(path: Path, _mtime_ns: int, _size: int) -> dict[str, float]:
    return json.loads(path.read_text(encoding="utf-8"))


def vertical_doc_count(conn: Connection, vertical: str) -> int:
    """Los documentos de la vertical (el N del IDF léxico y de la cuota mínima de un concepto), de la caché del
    catálogo (catalog/cache.py): contar la partición entera en cada búsqueda leía cientos de MB (restaurantes)."""
    return cached(
        f"docs:{vertical}",
        conn,
        lambda: conn.execute("SELECT count(*) FROM search_documents WHERE vertical = %s", (vertical,)).fetchone()[0],
    )


def retrieve(
    conn: Connection,
    vertical: str,
    query: str,
    embedder: TextEmbedder | None = None,
    k: int = 10,
    filters: Filters | None = None,
    mode: str = "hibrido",
    concepts: list[str] | None = None,
    words: bool | None = None,
) -> RetrievalResult:
    """`words`: lo que da `has_words(conn, query)`, si quien llama ya lo sabe (la búsqueda en varias verticales lo
    calcula una vez)."""
    if vertical not in VERTICALS:
        raise ValueError(f"Vertical desconocido: {vertical}")
    if mode not in MODES:
        raise ValueError(f"Modo desconocido: {mode}")
    filters = filters or Filters()
    query_concepts = concepts if concepts is not None else _query_concepts(query)
    doc_count = vertical_doc_count(conn, vertical)

    lexical = _lexical(conn, vertical, query, filters, doc_count) if mode != "vector" else []
    vector: list[tuple[tuple[str, str], float]] = []
    query_vector = None
    if mode != "lexico" and embedder is not None:
        query_vector = embedder.embed_queries([query])[0]
        vector = _vector(conn, vertical, query_vector, embedder, filters)

    scores: dict[tuple[str, str], float] = {}
    ranks: dict[tuple[str, str], dict[str, int]] = {}
    for name, ranked in (("lexico", [key for key, _ in lexical]), ("vector", [key for key, _ in vector])):
        for position, key in enumerate(ranked, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + position)
            ranks.setdefault(key, {})[name] = position

    if query_concepts and mode == "hibrido":  # sin refuerzo, el concepto de cada ítem lo trae `_hydrate`
        item_concepts = concepts_of(conn, list(scores))
        for key in scores:
            if item_concepts.get(key) in query_concepts:
                scores[key] += CONCEPT_BONUS

    top = sorted(scores, key=scores.get, reverse=True)[:k]
    cosines = dict(vector)
    hits = _hydrate(conn, vertical, top, scores, cosines, ranks)

    # Si ningún documento calza alguna palabra (sin tope de precio, el mismo universo), ninguno las calza todas: la
    # búsqueda sin coincidencias («xyz») no pregunta lo que ya sabe en cada una de las 8 verticales.
    if mode != "vector" and filters.price_max is None and not lexical:
        strict = 0
    else:
        strict = _strict_lexical_count(conn, vertical, query, filters)
    max_cosine = max(cosines.values()) if cosines else None
    if filters.price_max is not None and query_vector is not None:
        # Como la coincidencia estricta, el coseno de "sin resultado" se mide sin el tope: lo que el vertical tiene a
        # otro precio no es demanda no satisfecha (el agente dice cuánto cuesta lo más barato).
        unfiltered = _vector(conn, vertical, query_vector, embedder, Filters(entity_types=filters.entity_types))
        max_cosine = max((cosine for _, cosine in unfiltered), default=None)
    concept_items = _concept_items(conn, vertical, query_concepts)
    concept_here = bool(query_concepts) and concept_items >= _concept_floor(doc_count)
    if words is None:
        words = has_words(conn, query)
    occasion = not query_concepts and named_occasion(query) is not None
    unmet, reason = _unmet(
        vertical,
        strict,
        max_cosine,
        concept_here,
        bool(query_concepts),
        has_vectors=embedder is not None,
        has_words=words,
        names_occasion=occasion,
    )
    share = concept_items / doc_count if query_concepts and doc_count else None
    return RetrievalResult(
        vertical, query, hits, query_concepts, strict, max_cosine, concept_here, unmet, reason, words, share, occasion
    )


def _query_concepts(query: str) -> list[str]:
    return [m.target for m in _matcher().matches(query)]


def detect_concepts(query: str) -> list[str]:
    """Los conceptos que nombra la consulta (los mismos que usa `retrieve` cuando no se le dan)."""
    return _query_concepts(query)


_MATCHER = None


def _matcher():
    global _MATCHER
    if _MATCHER is None:
        _MATCHER = concept_matcher(load_taxonomy(), for_queries=True)
    return _MATCHER


_OCCASIONS = None


def named_occasion(q: str) -> Occasion | None:
    """La ocasión que nombra la consulta («algo para el carrete»), con las keywords de taxonomy.toml."""
    global _OCCASIONS
    taxonomy = load_taxonomy()
    if _OCCASIONS is None:
        _OCCASIONS = KeywordMatcher((o.id, kw) for o in taxonomy.occasions.values() for kw in o.keywords)
    match = _OCCASIONS.best(normalize(q))
    return taxonomy.occasions[match.target] if match else None


_PRICE = "price_min"  # columna generada desde metadata (migración 013), con índice (vertical, price_min)
# Con tope de precio, si califican hasta esta cantidad de documentos se revisan todos (búsqueda exacta): el HNSW
# filtrado corta en hnsw.max_scan_tuples y con un tope muy bajo en un vertical grande devolvería de menos.
EXACT_SEARCH_MAX = 5000
# random_page_cost del plan de la búsqueda vectorial (el de un SSD; Postgres trae 4, el de un disco giratorio). Con 4,
# en las verticales de 5 a 8 mil documentos (conveniencia, farmacia, licores) el planificador prefería recorrerlas
# enteras (10–16 ms) al HNSW (2–2,5 ms); con 1.1 lo usa. En staging, recall@10 contra la búsqueda exacta de 0,994–0,996
# en las consultas de eval/queries.json de esas verticales; las grandes ya usaban el índice y no cambian.
VECTOR_RANDOM_PAGE_COST = 1.1
# La léxica con más de una palabra puntúa en dos etapas (`_lexical`): ts_rank_cd solo en los documentos con la mayor
# suma de IDF, estos y los que empatan con el último. Con 1000, en staging el top-200 quedó igual en 196 de 198
# consultas (las otras dos, con el mismo top-10) y las listas léxicas de `make eval` no cambiaron; con 500 cambiaba un
# top-10, y con 2000 se ganaba menos.
LEXICAL_RANK_POOL = 1000


def _lexical(
    conn: Connection, vertical: str, query: str, filters: Filters, doc_count: int
) -> list[tuple[tuple[str, str], float]]:
    """Cualquier palabra de la consulta (OR), puntuada por IDF dentro del vertical: las palabras raras pesan más.

    Sin IDF, una unidad como "g" (presente en miles de productos) tapaba a "pañales" en "pañales talla g".
    ts_rank_cd pesa poco (≈0,1 por aparición; palabras más juntas, más arriba). Cada lexema ya normalizado entra al
    tsquery tal cual (`::tsquery`): `to_tsquery` lo volvía a separar ("coca-col" → 'coca-col' <-> 'coca' <-> 'col',
    y 'coca' no existe en el índice), así que las palabras con guion perdían su peso.

    El df de cada lexema sale de la caché del catálogo (`_document_frequencies`): contarlo en cada búsqueda costaba
    tanto como puntuar con una palabra frecuente («sushi» en restaurantes, ~45 mil documentos).

    El puntaje de cada documento es la suma de los IDF de las palabras que tiene más ts_rank_cd, en una subconsulta
    sobre las palabras en vez de un JOIN más GROUP BY (unas 3 veces más rápida con palabras frecuentes). Es la misma
    suma, pero ahora siempre en el orden de la consulta: el JOIN más GROUP BY la hacía en el orden en que un Sort
    inestable entregaba las filas, y documentos con las mismas palabras quedaban con puntajes que diferían en el último
    bit (hasta ~4e-15), así que su desempate quedaba al azar. Ahora los empates salen por `entity_id`, como dice el
    ORDER BY. En la base real el orden cambió solo entre documentos empatados (87 de 3.552 listas) y la evaluación de
    búsqueda dio el mismo reporte. (`search_documents` es única por vertical, tipo e id: sin GROUP BY no hay filas
    repetidas.) tests/integration/test_lexical_df_cache.py lo compara con el SQL anterior.

    Con más de una palabra, en dos etapas: primero ordena por la suma de IDF (barata) y se queda con los
    LEXICAL_RANK_POOL mejores más los que empatan con el último (`WITH TIES`: un empate no se corta al azar); recién
    ahí suma ts_rank_cd, lo caro (~2 µs por documento: «sushi roll wok chapsui» calza 49 mil platos). La segunda etapa
    vuelve a leer cada documento por su `ctid` y su partición (`tableoid`: un ctid solo es único dentro de una), la
    misma fila en la misma consulta: arrastrar el tsvector en el orden lo mandaba a disco. Como ts_rank_cd pesa poco
    (≈0,1 por aparición, contra un IDF de 1,5 o más), el orden es el mismo salvo que un documento con menos IDF lo
    supere por ts_rank_cd desde fuera de los primeros mil. Con una sola palabra todos tienen el mismo IDF: una etapa.
    """
    lexemes = _lexemes(conn, query)
    if not lexemes:  # solo stopwords («té»): nada que calzar
        return []
    params = {
        "lexemes": lexemes,
        "dfs": _document_frequencies(conn, vertical, lexemes, doc_count),
        "vertical": vertical,
        "n": doc_count,
        "types": list(filters.entity_types),
        "price_max": filters.price_max,
        "k": CANDIDATES,
        "pool": LEXICAL_RANK_POOL,
    }
    weights = """WITH weights AS MATERIALIZED (
                SELECT quote_literal(w.lexeme)::tsquery AS q, ln(1 + %(n)s::float / (1 + w.df)) AS idf
                FROM unnest(%(lexemes)s::text[], %(dfs)s::bigint[]) AS w(lexeme, df)
            ),
            any_q AS (SELECT string_agg(quote_literal(l), ' | ')::tsquery AS q FROM unnest(%(lexemes)s::text[]) AS l)"""
    idf = "(SELECT sum(w.idf) FROM weights w WHERE d.tsv_unaccent @@ w.q)"
    matching = f"""FROM search_documents d
            CROSS JOIN any_q
            WHERE d.vertical = %(vertical)s AND d.entity_type = ANY(%(types)s)
              AND d.tsv_unaccent @@ any_q.q
              AND (%(price_max)s::numeric IS NULL OR {_PRICE} <= %(price_max)s::numeric)"""
    if len(lexemes) == 1:  # todos los que calzan tienen el mismo IDF: ts_rank_cd ordena solo
        sql = f"""{weights}
            SELECT d.entity_type, d.entity_id, {idf} + ts_rank_cd(d.tsv_unaccent, any_q.q) AS score
            {matching}
            ORDER BY score DESC, d.entity_id
            LIMIT %(k)s"""
    else:
        sql = f"""{weights},
            best AS MATERIALIZED (
                SELECT d.tableoid AS tbl, d.ctid AS row_id, d.entity_type, d.entity_id, {idf} AS idf
                {matching}
                ORDER BY idf DESC
                FETCH FIRST %(pool)s ROWS WITH TIES
            )
            SELECT b.entity_type, b.entity_id, b.idf + ts_rank_cd(d.tsv_unaccent, any_q.q) AS score
            FROM best b
            JOIN search_documents d ON d.vertical = %(vertical)s AND d.tableoid = b.tbl AND d.ctid = b.row_id
            CROSS JOIN any_q
            ORDER BY score DESC, b.entity_id
            LIMIT %(k)s"""
    rows = conn.execute(sql, params).fetchall()
    return [((t, i), r) for t, i, r in rows]


def _lexemes(conn: Connection, query: str) -> list[str]:
    """Las palabras de la consulta como las indexa `tsv_unaccent` (sin tildes ni stopwords, con su raíz), sin repetir.
    La misma consulta se busca en varias verticales: se calculan una vez."""

    def extract(queries: list[str]) -> dict[str, list[str]]:
        return {
            q: conn.execute(
                """SELECT coalesce(array_agg(lexeme), '{}')
                   FROM (SELECT DISTINCT lexeme FROM unnest(to_tsvector('spanish', es_unaccent(%s)))) l""",
                (q,),
            ).fetchone()[0]
            for q in queries
        }

    return cached_many("lexemes", conn, [query], extract)[query]


def _document_frequencies(conn: Connection, vertical: str, lexemes: list[str], doc_count: int) -> list[int]:
    """En cuántos documentos del vertical está cada lexema (el df del IDF), en una sola consulta para los que faltan.
    Solo cambia al rearmar los documentos: vive en la caché del catálogo como `vertical_doc_count`, con la cuenta de
    documentos en la clave para que el N y el df del IDF sean del mismo catálogo."""

    def count(missing: list[str]) -> dict[str, int]:
        return dict(
            conn.execute(
                """SELECT l.lexeme, (SELECT count(*) FROM search_documents d
                                     WHERE d.vertical = %s AND d.tsv_unaccent @@ quote_literal(l.lexeme)::tsquery)
                   FROM unnest(%s::text[]) AS l(lexeme)""",
                (vertical, missing),
            ).fetchall()
        )

    found = cached_many(f"df:{vertical}:{doc_count}", conn, lexemes, count)
    return [found[lexeme] for lexeme in lexemes]


def _strict_lexical_count(conn: Connection, vertical: str, query: str, filters: Filters) -> int:
    """Cuántos documentos calzan TODAS las palabras (sin filtro de precio: sirve para 'sin resultado')."""
    return conn.execute(
        """SELECT count(*) FROM (
               SELECT 1 FROM search_documents
               WHERE vertical = %s AND entity_type = ANY(%s)
                 AND tsv_unaccent @@ plainto_tsquery('spanish', es_unaccent(%s))
               LIMIT 50) s""",
        (vertical, list(filters.entity_types), query),
    ).fetchone()[0]


def has_words(conn: Connection, query: str) -> bool:
    """¿Le queda alguna palabra a la consulta sin las stopwords? «té» es stopword: no hay nada que calzar. Tampoco
    cuentan las de saludo, cortesía o pedido en cualquier lugar: el agente solo las limpia al inicio («té porfa»)."""
    words = " ".join(word for word in tokens(query) if word not in FILLER_WORDS)
    return conn.execute("SELECT length(to_tsvector('spanish', es_unaccent(%s))) > 0", (words,)).fetchone()[0]


def _vector(
    conn: Connection, vertical: str, query_vector, embedder: TextEmbedder, filters: Filters
) -> list[tuple[tuple[str, str], float]]:
    dim = int(embedder.dim)
    model = embedder.model_name.replace("'", "''")  # literal: el índice parcial exige conocer el modelo al planificar
    params = {
        "v": to_pgvector(query_vector),
        "vertical": vertical,
        "types": list(filters.entity_types),
        "price_max": filters.price_max,
        "k": CANDIDATES,
        "cap": EXACT_SEARCH_MAX + 1,
    }
    where = f"""vertical = %(vertical)s AND embedding_model = '{model}' AND entity_type = ANY(%(types)s)
                AND (%(price_max)s::numeric IS NULL OR {_PRICE} <= %(price_max)s::numeric)"""
    distance = f"(embedding::vector({dim})) <=> %(v)s::vector({dim})"
    if filters.price_max is not None and _few_within_price(conn, where, params):
        rows = conn.execute(
            f"""WITH pool AS MATERIALIZED (SELECT entity_type, entity_id, embedding FROM search_documents WHERE {where})
                SELECT entity_type, entity_id, 1 - ({distance}) AS cosine FROM pool
                ORDER BY {distance}
                LIMIT %(k)s""",
            params,
        ).fetchall()
        return [((t, i), float(c)) for t, i, c in rows]
    # SET LOCAL de los tres en una sola consulta: solo esta transacción (la conexión vuelve a un pool). random_page_cost
    # queda en 1.1 para lo que sigue en la transacción (precios con v_latest_offers, documentos, conceptos): en staging,
    # las 165 consultas de eval (de /search y de oferta) y las escaleras dieron los mismos productos y precios, y esas
    # consultas no tardaron más (4,9–5,0 s contra 5,0–5,1 s devolviéndolo enseguida).
    conn.execute(
        f"SELECT set_config('hnsw.ef_search', '{CANDIDATES}', true), "
        "set_config('hnsw.iterative_scan', 'relaxed_order', true), "
        f"set_config('random_page_cost', '{VECTOR_RANDOM_PAGE_COST}', true)"
    )
    rows = conn.execute(
        f"""SELECT entity_type, entity_id, 1 - ({distance}) AS cosine
            FROM search_documents
            WHERE {where}
            ORDER BY {distance}
            LIMIT %(k)s""",
        params,
    ).fetchall()
    return [((t, i), float(c)) for t, i, c in rows]


def _few_within_price(conn: Connection, where: str, params: dict) -> bool:
    """¿Califican a lo más EXACT_SEARCH_MAX documentos? Usa el índice (vertical, price_min) y corta al pasarse."""
    return (
        conn.execute(
            f"SELECT count(*) FROM (SELECT 1 FROM search_documents WHERE {where} LIMIT %(cap)s) s", params
        ).fetchone()[0]
        <= EXACT_SEARCH_MAX
    )


def concepts_of(conn: Connection, keys: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
    if not keys:
        return {}
    rows = conn.execute(
        """SELECT ic.entity_type, ic.entity_id, ic.concept_id
           FROM item_concepts ic
           JOIN unnest(%s::text[], %s::text[]) AS k(entity_type, entity_id) USING (entity_type, entity_id)""",
        ([t for t, _ in keys], [i for _, i in keys]),
    ).fetchall()
    return {(t, i): c for t, i, c in rows}


def _concept_floor(doc_count: int) -> int:
    """Ítems que necesita un concepto para estar en un vertical de `doc_count` documentos: MIN_CONCEPT_ITEMS y el
    MIN_CONCEPT_SHARE del vertical, redondeado como lo hacía la consulta en Postgres (round de un double: la mitad, al
    par, igual que `round` de Python). Bajo eso, el surtido es testimonial."""
    return max(MIN_CONCEPT_ITEMS, round(MIN_CONCEPT_SHARE * doc_count))


def _concept_items(conn: Connection, vertical: str, concepts: list[str]) -> int:
    """Los ítems del concepto con más surtido en el vertical (0 si no tiene ninguno)."""
    if not concepts:
        return 0
    return conn.execute(
        "SELECT coalesce(max(items), 0) FROM concept_assortment WHERE vertical = %s AND concept_id = ANY(%s)",
        (vertical, concepts),
    ).fetchone()[0]


def _hydrate(conn, vertical, keys, scores, cosines, ranks) -> list[Hit]:
    """Los hits de `keys`, en ese orden, con su texto y su concepto."""
    if not keys:
        return []
    rows = conn.execute(
        """SELECT d.entity_type, d.entity_id, d.content, d.metadata, ic.concept_id
           FROM search_documents d
           JOIN unnest(%s::text[], %s::text[]) AS k(entity_type, entity_id) USING (entity_type, entity_id)
           LEFT JOIN item_concepts ic USING (entity_type, entity_id)
           WHERE d.vertical = %s""",
        ([t for t, _ in keys], [i for _, i in keys], vertical),
    ).fetchall()
    by_key = {(t, i): (content, metadata, concept) for t, i, content, metadata, concept in rows}
    return [
        Hit(
            vertical,
            key[0],
            key[1],
            by_key[key][0],
            by_key[key][1],
            round(scores[key], 6),
            by_key[key][2],
            cosines.get(key),
            ranks.get(key, {}),
        )
        for key in keys
        if key in by_key
    ]


def _unmet(
    vertical: str,
    strict: int,
    max_cosine: float | None,
    concept_here: bool,
    names_concept: bool,
    has_vectors: bool,
    has_words: bool = True,
    names_occasion: bool = False,
) -> tuple[bool, str | None]:
    """Sin resultado = nada calza todas las palabras Y (el concepto nombrado no está en el vertical, o bien,
    si la consulta no nombra un concepto, el coseno máximo queda bajo τ).

    Con e5 los cosenos se concentran (0,78–0,90), así que cuando la consulta nombra un concepto, su presencia
    en el vertical es mejor señal que el coseno ("pizza" en Rappi Mall: no hay; aunque el coseno sea 0,82).
    Sin concepto, τ es el del vertical si la consulta nombra una ocasión, y si no, UNNAMED_TAU: el del vertical no
    separa («sofá de tres cuerpos» en Turbo, 0,821, contra «cuchuflis» con un error de tipeo, 0,843).
    Sin palabras que buscar («té» es stopword), que nada calce no dice nada y el coseno solo no basta: no se marca.
    """
    if strict > 0:
        return False, None
    if names_concept:
        if concept_here:
            return False, None
        return (
            True,
            f"sin coincidencia léxica; el concepto pedido no está en {vertical} (o es testimonial)",
        )
    if not has_words:
        return False, None
    tau = thresholds().get(vertical, DEFAULT_TAU) if names_occasion else UNNAMED_TAU
    if not has_vectors or max_cosine is None or max_cosine < tau:
        cosine = f"{max_cosine:.3f}" if max_cosine is not None else "sin vectores"
        occasion = "" if names_occasion else " ni ocasión"
        return True, f"sin coincidencia léxica ni concepto{occasion}; coseno máx {cosine} < τ {tau}"
    return False, None
