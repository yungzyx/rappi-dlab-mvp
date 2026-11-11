"""Licores no encabeza lo que no es +18 (agent/verticals.py: `liquor_last`)."""

from rappi_ia.agent import grouped_search
from rappi_ia.agent.verticals import liquor_last
from rappi_ia.retrieval.hybrid import occasion_search

TYPICAL = ["licores", "conveniencia", "supermercado"]


def test_without_anything_adult_licores_goes_last():
    assert liquor_last(TYPICAL, ["snacks-salados"]) == ["conveniencia", "supermercado", "licores"]
    assert liquor_last(TYPICAL, ["gaseosas", "hielo"]) == ["conveniencia", "supermercado", "licores"]


def test_alcohol_or_tobacco_keeps_the_order():
    assert liquor_last(TYPICAL, ["cerveza"]) == TYPICAL
    assert liquor_last(TYPICAL, ["gaseosas", "pisco"]) == TYPICAL  # "piscola": pide pisco
    assert liquor_last(TYPICAL, ["cigarrillos"]) == TYPICAL


def test_only_licores_moves():
    assert liquor_last(["farmacia", "supermercado"], ["cuidado-cabello"]) == ["farmacia", "supermercado"]
    assert liquor_last(["supermercado", "licores", "turbo"], ["jugos"]) == ["supermercado", "turbo", "licores"]
    assert liquor_last([], ["jugos"]) == []


def test_an_occasion_with_a_fixed_vertical_can_leave_licores_out(monkeypatch):
    """ "estoy triste" (ocasión `animo`, vertical fija chocolaterías): sin nada +18, Licores pasa al final de las
    típicas y, con la fija adelante y el tope de 3, queda fuera. Antes se buscaba chocolateria > licores > conveniencia.
    Que no se busque alcohol para alguien triste es lo que se quiere."""
    _, concepts, occasion = occasion_search("estoy triste")
    assert occasion.vertical == "chocolateria"
    ranked = ["licores", "conveniencia", "supermercado", "restaurantes", "chocolateria"]  # rappi_staging, 11-11-2026
    monkeypatch.setattr(grouped_search, "ranked_verticals", lambda conn, ids: ranked)

    searched = grouped_search._verticals_to_search(None, concepts, None, occasion.vertical)

    assert searched == ["chocolateria", "conveniencia", "supermercado"]
