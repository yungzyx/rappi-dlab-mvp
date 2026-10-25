"""Las ofertas de «vertical por probar»: primero las de un concepto típico de la vertical, después las de cualquier otro
concepto y al final las sin concepto; dentro de cada grupo, de mayor a menor descuento (el orden en que llegan)."""

from rappi_ia.offers.engine import _typical_first

TYPICAL = {"cafe": "supermercado", "mantas": "mall", "galletas": "chocolateria"}


def deal(name: str, concept: str | None) -> dict:
    return {"name": name, "concept": concept}


def test_typical_offers_come_first_then_other_concepts_then_the_ones_without_concept():
    found = [
        deal("Spray para auto", None),  # el de mayor descuento
        deal("Manta", "mantas"),
        deal("Galletas", "galletas"),
        deal("Café", "cafe"),
        deal("Otro spray", None),
    ]

    ordered = [d["name"] for d in _typical_first(found, "supermercado", TYPICAL)]

    assert ordered == ["Café", "Manta", "Galletas", "Spray para auto", "Otro spray"]


def test_nothing_is_dropped_when_no_offer_is_typical():
    found = [deal("Manta", "mantas"), deal("Spray para auto", None)]

    assert _typical_first(found, "supermercado", TYPICAL) == found


def test_in_a_food_vertical_what_is_not_food_goes_after_the_food():
    """En la base real, Express partía con una cera para auto: `automotriz` es típico de Express (las tiendas de las
    bencineras). En el súper, Express y Turbo, lo que no se come ni se bebe va después de la comida, aunque sea típico;
    lo sin concepto sigue al final."""
    typical = {"automotriz": "conveniencia", "papeles-desechables": "conveniencia", "verduras": "conveniencia"}
    found = [
        deal("Kit Cera para Auto Aerosol #3 360 CC", "automotriz"),
        deal("Confort Papel Higiénico Rendiplus Doble Hoja 18 m", "papeles-desechables"),
        deal("Sin concepto", None),
        deal("Galletas de agua", "galletas"),
        deal("Clementinas Granel", "verduras"),
    ]

    ordered = [d["name"] for d in _typical_first(found, "conveniencia", typical)]

    assert ordered == [
        "Clementinas Granel",
        "Galletas de agua",
        "Kit Cera para Auto Aerosol #3 360 CC",
        "Confort Papel Higiénico Rendiplus Doble Hoja 18 m",
        "Sin concepto",
    ]


def test_outside_the_food_verticals_the_typical_offers_still_come_first():
    found = [deal("Galletas de agua", "galletas"), deal("Guirnalda de globos", "decoracion")]

    ordered = [d["name"] for d in _typical_first(found, "mall", {"decoracion": "mall"})]

    assert ordered == ["Guirnalda de globos", "Galletas de agua"]
