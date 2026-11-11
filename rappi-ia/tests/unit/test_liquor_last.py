"""Licores no encabeza lo que no es +18 (agent/verticals.py: `liquor_last`)."""

from rappi_ia.agent.verticals import liquor_last

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
