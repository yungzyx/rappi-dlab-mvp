"""La léxica en dos etapas (`retrieval/hybrid._lexical`): con más de una palabra ordena primero por la suma de IDF, se
queda con los LEXICAL_RANK_POOL mejores y los que empatan con el último, y recién ahí suma ts_rank_cd. En el catálogo de
prueba (pocos documentos por consulta) da la misma lista, con los mismos puntajes y el mismo orden, que el SQL de una
etapa de antes (aquí como referencia). Con un corte chico, conserva los empates del corte y ordena a los que quedan
igual que antes."""

import pytest
from rappi_scraper.storage.search import VERTICALS, build_search_documents

from conftest import add_price, add_product
from rappi_ia.demo.seed import seed_demo
from rappi_ia.retrieval import hybrid
from rappi_ia.retrieval.hybrid import CANDIDATES, Filters, vertical_doc_count

# El `_lexical` de una etapa, tal cual estaba: ts_rank_cd en todo lo que calza.
ONE_STAGE_SQL = """WITH weights AS MATERIALIZED (
                SELECT quote_literal(w.lexeme)::tsquery AS q, ln(1 + %(n)s::float / (1 + w.df)) AS idf
                FROM unnest(%(lexemes)s::text[], %(dfs)s::bigint[]) AS w(lexeme, df)
            ),
            any_q AS (SELECT string_agg(quote_literal(l), ' | ')::tsquery AS q FROM unnest(%(lexemes)s::text[]) AS l)
            SELECT d.entity_type, d.entity_id,
                   (SELECT sum(w.idf) FROM weights w WHERE d.tsv_unaccent @@ w.q)
                   + ts_rank_cd(d.tsv_unaccent, any_q.q) AS score,
                   (SELECT sum(w.idf) FROM weights w WHERE d.tsv_unaccent @@ w.q) AS idf
            FROM search_documents d
            CROSS JOIN any_q
            WHERE d.vertical = %(vertical)s AND d.entity_type = ANY(%(types)s)
              AND d.tsv_unaccent @@ any_q.q
              AND (%(price_max)s::numeric IS NULL OR price_min <= %(price_max)s::numeric)
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
    "sushi acevichado",
    "té",
    "xyz",
    "leche descremada sin lactosa",
    "sushi roll wok chapsui",
]
FILTERS = [Filters(), Filters(price_max=2500), Filters(entity_types=("catalog_item",))]


def one_stage(conn, vertical: str, query: str, filters: Filters, n: int, k: int = CANDIDATES):
    """[((tipo, id), puntaje, idf)] con el SQL de una etapa."""
    lexemes = hybrid._lexemes(conn, query)
    if not lexemes:
        return []
    rows = conn.execute(
        ONE_STAGE_SQL,
        {
            "lexemes": lexemes,
            "dfs": hybrid._document_frequencies(conn, vertical, lexemes, n),
            "vertical": vertical,
            "n": n,
            "types": list(filters.entity_types),
            "price_max": filters.price_max,
            "k": k,
        },
    ).fetchall()
    return [((t, i), score, idf) for t, i, score, idf in rows]


@pytest.fixture
def catalog(db):
    seed_demo(db)
    db.commit()
    return db


def test_two_stages_give_the_same_list_as_one_stage_on_the_test_catalog(catalog):
    compared = 0
    for query in QUERIES:
        for vertical in VERTICALS:
            n = vertical_doc_count(catalog, vertical)
            for filters in FILTERS:
                old = one_stage(catalog, vertical, query, filters, n)
                assert len(old) < hybrid.LEXICAL_RANK_POOL  # aquí el corte no deja nada fuera
                new = hybrid._lexical(catalog, vertical, query, filters, n)
                assert new == [(key, score) for key, score, _ in old], (query, vertical, filters)
                compared += len(hybrid._lexemes(catalog, query)) > 1 and bool(new)
    assert compared >= 20  # con más de una palabra (las dos etapas) y con resultados


def test_the_cut_keeps_the_ties_of_the_last_one_and_ranks_them_as_before(catalog, monkeypatch):
    """Doce «papas fritas» y doce de una sola de las dos palabras: con un corte de 3, quedan todas las que tienen las
    dos palabras (empatan en IDF con la tercera, así que no se cortan al azar) y en el mismo orden que con una etapa;
    las de una palabra, que con una etapa venían después, quedan fuera."""
    store = catalog.execute(
        "SELECT store_id FROM store_verticals WHERE vertical = 'supermercado' ORDER BY store_id LIMIT 1"
    ).fetchone()[0]
    names = [f"Papas fritas caseras {i}" for i in range(4)] + [
        f"Bolsa grande de papas fritas onduladas {i}" for i in range(8)
    ]
    names += [f"Papas nativas {i}" for i in range(6)] + [f"Cebollas fritas {i}" for i in range(6)]
    for i, name in enumerate(names):
        add_product(catalog, 992_000 + i, name, store)
        add_price(catalog, store, 992_000 + i, 1500)
    catalog.commit()
    build_search_documents(catalog)
    catalog.commit()
    n = vertical_doc_count(catalog, "supermercado")
    everything = one_stage(catalog, "supermercado", "papas fritas", Filters(), n)
    best_idf = max(idf for _, _, idf in everything)
    both_words = [(key, score) for key, score, idf in everything if idf == best_idf]
    assert len(both_words) >= 12 and len(everything) > len(both_words) + 10

    monkeypatch.setattr(hybrid, "LEXICAL_RANK_POOL", 3)
    cut = hybrid._lexical(catalog, "supermercado", "papas fritas", Filters(), n)

    assert cut == both_words
    assert cut == [(key, score) for key, score, _ in everything[: len(cut)]]  # y es el comienzo de la lista de antes
