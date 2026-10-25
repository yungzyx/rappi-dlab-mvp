"""La búsqueda léxica con el df de cada palabra en la caché del catálogo y el puntaje por documento sin JOIN ni GROUP BY
(`retrieval/hybrid._lexical`): da los mismos documentos con el mismo puntaje que el SQL anterior (queda aquí como
referencia) y el mismo orden salvo entre empates, que ahora salen por `entity_id`; una segunda búsqueda no vuelve a
contar el df. Vence con la caché del catálogo."""

import pytest
from rappi_scraper.storage.search import VERTICALS, build_search_documents

from conftest import add_price, add_product
from rappi_ia.catalog import cache
from rappi_ia.demo.seed import seed_demo
from rappi_ia.retrieval import hybrid
from rappi_ia.retrieval.hybrid import CANDIDATES, Filters, vertical_doc_count

# El `_lexical` de antes de la caché de df, tal cual.
OLD_SQL = """WITH lexemes AS (
                SELECT DISTINCT lexeme FROM unnest(to_tsvector('spanish', es_unaccent(%(query)s)))
            ),
            weights AS MATERIALIZED (
                SELECT l.lexeme, quote_literal(l.lexeme)::tsquery AS q,
                       ln(1 + %(n)s::float / (1 + (SELECT count(*) FROM search_documents d
                                                   WHERE d.vertical = %(vertical)s
                                                     AND d.tsv_unaccent @@ quote_literal(l.lexeme)::tsquery)))
                       AS idf
                FROM lexemes l
            ),
            any_q AS (SELECT string_agg(quote_literal(lexeme), ' | ')::tsquery AS q FROM lexemes)
            SELECT d.entity_type, d.entity_id,
                   sum(w.idf) + max(ts_rank_cd(d.tsv_unaccent, any_q.q)) AS score
            FROM search_documents d
            CROSS JOIN any_q
            JOIN weights w ON d.tsv_unaccent @@ w.q
            WHERE d.vertical = %(vertical)s AND d.entity_type = ANY(%(types)s) AND any_q.q IS NOT NULL
              AND d.tsv_unaccent @@ any_q.q
              AND (%(price_max)s::numeric IS NULL OR price_min <= %(price_max)s::numeric)
            GROUP BY d.entity_type, d.entity_id
            ORDER BY score DESC, d.entity_id
            LIMIT %(k)s"""

QUERIES = [
    "papas fritas",
    "cerveza",
    "pizza",
    "café molido",
    "chocolate amargo 70% cacao",
    "algo para el carrete",
    "coca-cola",
    "pañales talla g",
    "panales",
    "sushi acevichado",
    "té",
    "xyz",
    "leche descremada sin lactosa",
]
FILTERS = [Filters(), Filters(price_max=2500), Filters(entity_types=("catalog_item",))]


def old_lexical(conn, vertical: str, query: str, filters: Filters, n: int):
    rows = conn.execute(
        OLD_SQL,
        {
            "query": query,
            "vertical": vertical,
            "n": n,
            "types": list(filters.entity_types),
            "price_max": filters.price_max,
            "k": CANDIDATES,
        },
    ).fetchall()
    return [((t, i), r) for t, i, r in rows]


class CountingConnection:
    def __init__(self, conn):
        self._conn = conn
        self.statements: list[str] = []

    def execute(self, query, *args, **kwargs):
        self.statements.append(str(query))
        return self._conn.execute(query, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _df_counts(statements: list[str]) -> list[str]:
    return [s for s in statements if "count(*)" in s and "tsv_unaccent" in s]


@pytest.fixture
def catalog(db):
    seed_demo(db)
    db.commit()
    return db


def by_score(rows):
    """Los documentos de cada puntaje, del mayor al menor. El puntaje se redondea a 1e-9: el SQL anterior sumaba los IDF
    en el orden que le entregaba un Sort inestable, y documentos con las mismas palabras quedaban con puntajes que
    diferían en el último bit (hasta ~4e-15). Así se comparan los documentos, los puntajes y el orden entre puntajes
    distintos, sin el orden de los empates."""
    groups: dict[float, set] = {}
    for key, score in rows:
        groups.setdefault(round(score, 9), set()).add(key)
    return sorted(groups.items(), reverse=True)


def test_lexical_gives_the_same_documents_scores_and_order_as_the_old_sql_except_among_ties(catalog):
    with_results = 0
    for query in QUERIES:
        for vertical in VERTICALS:
            n = vertical_doc_count(catalog, vertical)
            for filters in FILTERS:
                new = hybrid._lexical(catalog, vertical, query, filters, n)
                old = old_lexical(catalog, vertical, query, filters, n)
                assert len(old) < CANDIDATES  # el corte del LIMIT no parte un empate
                assert by_score(new) == by_score(old), (query, vertical, filters)
                with_results += bool(new)
    assert with_results >= 20  # la comparación no es entre listas vacías


def test_documents_with_the_same_score_come_out_ordered_by_entity_id(catalog):
    """Cuarenta productos con el mismo nombre (varias palabras, de IDF distinto) y ids en desorden: el mismo puntaje,
    exacto, y el desempate de `ORDER BY score DESC, entity_id`. Con el JOIN más GROUP BY, la suma de los IDF dependía
    del orden en que un Sort inestable entregaba las filas y los puntajes diferían en el último bit: el desempate
    quedaba al azar (con este mismo catálogo daba dos puntajes y los ids en desorden)."""
    store = catalog.execute(
        "SELECT store_id FROM store_verticals WHERE vertical = 'supermercado' ORDER BY store_id LIMIT 1"
    ).fetchone()[0]
    name = "Papas fritas nativas premium con sal de mar"
    ids = [str(991_000 + (17 * i) % 40) for i in range(40)]  # 17 y 40 son primos entre sí: todos distintos y revueltos
    assert ids != sorted(ids)
    for pid in ids:
        add_product(catalog, int(pid), name, store)
        add_price(catalog, store, int(pid), 1500)
    catalog.commit()
    build_search_documents(catalog)
    catalog.commit()

    found = hybrid._lexical(catalog, "supermercado", name, Filters(), vertical_doc_count(catalog, "supermercado"))

    tied = [(key, score) for key, score in found if key[1] in set(ids)]
    assert len(tied) == len(ids)
    assert len({score for _, score in tied}) == 1  # el mismo puntaje, bit a bit
    assert [key[1] for key, _ in tied] == sorted(ids)
    assert [key[1] for key, _ in found[: len(ids)]] == sorted(ids)  # y ellos van primero


def test_a_second_search_does_not_count_the_df_again(catalog):
    counting = CountingConnection(catalog)
    n = vertical_doc_count(catalog, "supermercado")

    first = hybrid._lexical(counting, "supermercado", "papas fritas", Filters(), n)
    assert first and _df_counts(counting.statements)  # la primera cuenta el df de «papas» y «frit»

    counting.statements.clear()
    second = hybrid._lexical(counting, "supermercado", "papas fritas", Filters(price_max=2500), n)
    assert [s for s in counting.statements if "scrape_runs" not in s] == [counting.statements[-1]]  # solo puntúa

    counting.statements.clear()
    third = hybrid._lexical(counting, "supermercado", "papas", Filters(), n)  # otra consulta: sus lexemas, sin df
    assert _df_counts(counting.statements) == []
    assert len([s for s in counting.statements if "scrape_runs" not in s]) == 2

    assert by_score(second) == by_score(
        old_lexical(catalog, "supermercado", "papas fritas", Filters(price_max=2500), n)
    )
    assert by_score(third) == by_score(old_lexical(catalog, "supermercado", "papas", Filters(), n))


def test_the_df_is_counted_again_when_the_catalog_cache_expires(catalog, monkeypatch):
    """El df vive en la caché del catálogo: como el conteo de documentos de la vertical, se vuelve a contar con una
    corrida nueva o al vencer su TTL (lo que cambia sin corrida, como un `make post-refresh`)."""
    now = [1000.0]
    monkeypatch.setattr(cache, "_now", lambda: now[0])
    before = hybrid._lexical(catalog, "supermercado", "papas", Filters(), vertical_doc_count(catalog, "supermercado"))

    store = catalog.execute(
        "SELECT store_id FROM store_verticals WHERE vertical = 'supermercado' ORDER BY store_id LIMIT 1"
    ).fetchone()[0]
    for pid in range(990_001, 990_004):
        add_product(catalog, pid, f"Papas nativas de prueba {pid}", store)
        add_price(catalog, store, pid, 1500)
    catalog.commit()
    build_search_documents(catalog)
    catalog.commit()

    counting = CountingConnection(catalog)
    stale_n = vertical_doc_count(counting, "supermercado")
    hybrid._lexical(counting, "supermercado", "papas", Filters(), stale_n)
    assert _df_counts(counting.statements) == []  # todavía en caché

    now[0] += cache.DEFAULT_TTL_S + 1
    n = vertical_doc_count(counting, "supermercado")
    after = hybrid._lexical(counting, "supermercado", "papas", Filters(), n)

    assert n > stale_n and _df_counts(counting.statements)  # contó de nuevo
    assert after != before
    assert by_score(after) == by_score(old_lexical(catalog, "supermercado", "papas", Filters(), n))
