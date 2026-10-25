"""La búsqueda de la app sin vertical: la misma consulta en todas las verticales que corresponden, agrupada.

Es la búsqueda que la persona escribe, así que no lleva las guardias de las ofertas del agente (la cerveza trae
Licores) ni se personaliza; lo sensible, como siempre, solo si se nombra (`_allowed` en agent/tools.py). Los resultados
son productos y platos, nunca tiendas.
"""

import contextvars
import queue
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, ExitStack, suppress
from dataclasses import dataclass, field

from psycopg import Connection
from psycopg import Error as DatabaseError
from rappi_scraper.storage.search import VERTICALS

from ..concepts.taxonomy import load_taxonomy
from ..embeddings.base import MemoizedQueryEmbedder, TextEmbedder
from ..retrieval.hybrid import UNNAMED_TAU, detect_concepts, has_words, named_occasion
from ..retrieval.spelling import correct_query
from .rappi_agent import PROTOTYPE_VERTICALS
from .tools import Product, search_products
from .verticals import ranked_verticals

TYPICAL_VERTICALS = 3  # con un concepto detectado, las verticales donde es más típico

# Verticales que se buscan a la vez además de la de la conexión del request: cada una ocupa una conexión más del pool
# (API_POOL_MAX, 10 por defecto) y un hilo mientras dura la búsqueda. Una consulta va a 3 o 4 verticales con concepto y
# a las 8 sin él. Las conexiones extra nunca toman la reserva del pool (api/deps.spare_reserve).
PARALLEL_SEARCHES = 3

# Lo que entrega una conexión extra (api/deps.spare_connection): una conexión, o None si no sobra ninguna.
SpareConnector = Callable[[], AbstractContextManager[Connection | None]]

# Pantalla de la app de cada vertical: la de `PROTOTYPE_VERTICALS`, salvo que Turbo abre su propia pantalla
# (el resto de la API lo agrupa con Express).
SCREEN_VERTICALS = {**PROTOTYPE_VERTICALS, "turbo": "turbo"}


@dataclass
class VerticalGroup:
    vertical: str
    prototype_vertical: str
    products: list[Product]

    def to_dict(self) -> dict:
        return {
            "vertical": self.vertical,
            "prototype_vertical": self.prototype_vertical,
            "products": [p.to_dict() for p in self.products],
        }


@dataclass
class GroupedResult:
    query: str
    groups: list[VerticalGroup] = field(default_factory=list)
    unmet: bool = False
    unmet_reason: str | None = None
    corrected_query: str | None = None  # lo que se buscó si se corrigieron errores de tipeo (retrieval/spelling.py)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "groups": [g.to_dict() for g in self.groups],
            "unmet": self.unmet,
            "unmet_reason": self.unmet_reason,
            "corrected_query": self.corrected_query,
        }


def _verticals_to_search(
    conn: Connection, concepts: list[str], current: str | None, fixed: str | None = None
) -> list[str]:
    """Con un concepto detectado, sus verticales típicas (hasta 3; primero la fija de la ocasión, si tiene) y la de la
    pantalla; si no, las 8."""
    typical = ranked_verticals(conn, concepts)[:TYPICAL_VERTICALS] if concepts else []
    if fixed:
        typical = [fixed, *[v for v in typical if v != fixed]][:TYPICAL_VERTICALS]
    if not typical:
        return list(VERTICALS)
    return typical + [current] if current in VERTICALS and current not in typical else typical


def search_each[T, V](
    conn: Connection,
    verticals: list[V],
    search: Callable[[Connection, V], T],
    spare: SpareConnector | None,
) -> list[T]:
    """`search(conn, vertical)` en cada vertical (o en cada peldaño de un perfil de gusto, `offers/profiles.ladder`),
    con los resultados en el orden de `verticals`. Con `spare` (una conexión extra del pool si sobra, o None), hasta
    PARALLEL_SEARCHES verticales más a la vez, cada una con su conexión; las que no consiguen una se reparten entre las
    que hay. Sin ninguna, todo en serie con la conexión del
    request: no hace fila por una conexión (cada extra espera a lo más SPARE_WAIT_S y unas idas y vueltas) ni pasa el
    tope del pool. En paralelo, cada vertical cierra su transacción al terminar (si no, una conexión que ya terminó
    queda «idle in transaction» hasta la vertical más lenta, y Postgres la corta a los 10 s) y corre con el contexto
    del request (su id en los registros). Un error de una vertical llega a quien llamó, después de que terminan las
    demás y se devuelven las conexiones."""
    if spare is None or len(verticals) < 2:
        return [search(conn, vertical) for vertical in verticals]
    with ExitStack() as stack:
        extra = []
        for _ in range(min(PARALLEL_SEARCHES, len(verticals) - 1)):
            connection = stack.enter_context(spare())
            if connection is None:
                break
            extra.append(connection)
        if not extra:
            return [search(conn, vertical) for vertical in verticals]
        free: queue.SimpleQueue[Connection] = queue.SimpleQueue()
        for connection in (conn, *extra):
            free.put(connection)

        def run(vertical: V) -> T:
            connection = free.get()  # hay tantos hilos como conexiones: siempre hay una
            try:
                result = search(connection, vertical)
                connection.commit()
                return result
            except BaseException:
                with suppress(DatabaseError):  # la siguiente vertical en esta conexión no hereda el error
                    connection.rollback()
                raise
            finally:
                free.put(connection)

        with ThreadPoolExecutor(len(extra) + 1, thread_name_prefix="busqueda-vertical") as pool:
            tasks = [pool.submit(contextvars.copy_context().run, run, vertical) for vertical in verticals]
            return [task.result() for task in tasks]


def _related(outcomes: list) -> list:
    """Sin concepto: las verticales que calzan todas las palabras; si ninguna, las de coseno ≥ UNNAMED_TAU."""
    exact = [o for o in outcomes if o[1].result.strict_lexical_matches]
    return exact or [o for o in outcomes if (o[1].result.max_cosine or 0.0) >= UNNAMED_TAU]


def search_grouped(
    conn: Connection,
    q: str,
    embedder: TextEmbedder | None,
    current: str | None,
    limit: int,
    price_max: float | None = None,
    mode: str = "hibrido",
    spare: SpareConnector | None = None,
    correct: bool = True,
) -> GroupedResult:
    """Productos por vertical, con `limit` por grupo y solo los grupos que traen algo. Con un concepto detectado el
    orden es el de sus verticales típicas. Una ocasión sin concepto nombrado («algo para el carrete») se busca como
    el agente: sus conceptos (sin los sensibles: una ocasión no los nombra), en sus verticales típicas. Sin ninguno de
    los dos, solo las verticales que calzan todas las palabras o, si ninguna, las muy cercanas (UNNAMED_TAU):
    primero las que calzan y luego por la cercanía vectorial. La pantalla actual (`current`), si trae productos, va
    siempre primero (el resto conserva su orden); sin productos, no aparece. `unmet` solo si ningún grupo trae
    productos. Con `spare` (las conexiones extra de la API), las verticales se buscan a la vez (`search_each`); el
    resultado es el mismo que en serie. Con `correct`, si ninguna vertical calza todas las palabras, corrige una vez los
    errores de tipeo con el vocabulario de todas las verticales (`retrieval.spelling`) y vuelve a buscar: si así hay
    grupos y alguna vertical calza todas las palabras, los devuelve con `corrected_query`."""
    found, strict = _search_grouped(conn, q, embedder, current, limit, price_max, mode, spare)
    if not correct or strict or (fixed := correct_query(conn, q, None)) is None:
        return found
    again, strict = _search_grouped(conn, fixed, embedder, current, limit, price_max, mode, spare)
    if not again.groups or not strict:
        return found
    return GroupedResult(q, again.groups, corrected_query=fixed)


def _search_grouped(
    conn: Connection,
    q: str,
    embedder: TextEmbedder | None,
    current: str | None,
    limit: int,
    price_max: float | None,
    mode: str,
    spare: SpareConnector | None,
) -> tuple[GroupedResult, bool]:
    """El resultado y si alguna vertical calza todas las palabras."""
    concepts = detect_concepts(q)
    occasion = None if concepts else named_occasion(q)
    query, fixed = q, None
    if occasion:
        taxonomy = load_taxonomy()
        concepts = [c for c in occasion.concepts if not taxonomy.concepts[c].sensitive]
        query, fixed = " ".join(taxonomy.concepts[c].name for c in concepts[:4]), occasion.vertical
    memo = MemoizedQueryEmbedder(embedder) if embedder is not None else None
    words = has_words(conn, query)  # una vez, no una por vertical
    verticals = _verticals_to_search(conn, concepts, current, fixed)

    def search(connection: Connection, vertical: str):
        return search_products(connection, vertical, query, concepts, memo, price_max, k=limit, mode=mode, words=words)

    searched = list(zip(verticals, search_each(conn, verticals, search, spare), strict=True))
    strict = any(o.result.strict_lexical_matches for _, o in searched)
    outcomes = searched if concepts else _related(searched)
    if not concepts:  # sorted es estable: a igual relevancia queda el orden de VERTICALS
        outcomes.sort(key=lambda o: (o[1].result.strict_lexical_matches == 0, -(o[1].result.max_cosine or 0.0)))
    groups = [
        VerticalGroup(vertical, SCREEN_VERTICALS[vertical], outcome.products)
        for vertical, outcome in outcomes
        if outcome.products
    ]
    if groups:
        groups.sort(key=lambda group: group.vertical != current)  # estable: solo sube la de la pantalla actual
        return GroupedResult(q, groups), strict
    reason = next((o.result.unmet_reason for _, o in searched if o.result.unmet_reason), None)
    if reason is None and not concepts:
        best = max((o.result.max_cosine or 0.0 for _, o in searched), default=0.0)
        reason = f"sin coincidencia léxica ni concepto ni ocasión; coseno máx {best:.3f} < τ {UNNAMED_TAU} en todas"
    return GroupedResult(q, [], unmet=True, unmet_reason=reason), strict
