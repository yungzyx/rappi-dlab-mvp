"""Cómo se busca una ocasión sin concepto nombrado (retrieval.hybrid.occasion_search): la misma reescritura en la
búsqueda agrupada y en la de una vertical."""

from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.retrieval.hybrid import occasion_search


def test_an_occasion_is_searched_by_its_concepts_without_the_sensitive_ones():
    taxonomy = load_taxonomy()
    once = taxonomy.occasions["once"]
    concepts = [c for c in once.concepts if not taxonomy.concepts[c].sensitive]

    query, found, occasion = occasion_search("algo para la once")

    assert occasion is once and found == concepts
    assert query == " ".join(taxonomy.concepts[c].name for c in concepts[:4])


def test_a_named_concept_or_no_occasion_is_searched_as_written():
    assert occasion_search("café para la once") is None  # nombra un concepto: manda lo pedido
    assert occasion_search("cuchuflíes") is None
