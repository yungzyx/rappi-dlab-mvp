"""Reglas del set de evaluación (src/rappi_ia/eval/queries.json)."""

from collections import Counter

from rappi_scraper.storage.search import VERTICALS

from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.eval.search_eval import load_queries

MIN_NEGATIVES = 5  # con 1 a 4 negativas, la precisión ≥ 0,9 de «sin resultado» es 1,0 o nada
MIN_POSITIVES_NEW_VERTICALS = 10
TIPOS = {"exacta", "necesidad", "sin_tildes", "negativa"}


def test_every_vertical_is_evaluated_with_enough_negatives():
    queries = load_queries()
    negatives = Counter(q["vertical"] for q in queries if q["tipo"] == "negativa")
    assert {v: negatives[v] for v in VERTICALS if negatives[v] < MIN_NEGATIVES} == {}


def test_pharmacy_and_turbo_have_positive_queries():
    positives = Counter(q["vertical"] for q in load_queries() if q["tipo"] != "negativa")
    assert positives["farmacia"] >= MIN_POSITIVES_NEW_VERTICALS
    assert positives["turbo"] >= MIN_POSITIVES_NEW_VERTICALS


def test_queries_are_well_formed_and_unique():
    queries = load_queries()
    concepts = load_taxonomy().concepts
    for q in queries:
        assert q["tipo"] in TIPOS, q
        assert q["vertical"] in VERTICALS, q
        assert all(c in concepts for c in q["concepts"]), q
        assert bool(q["concepts"]) == (q["tipo"] != "negativa"), q  # las negativas no esperan nada
        assert not any(concepts[c].sensitive for c in q["concepts"]), q  # nada sensible en el set
    keys = Counter((q["vertical"], q["query"]) for q in queries)
    assert [k for k, n in keys.items() if n > 1] == []
