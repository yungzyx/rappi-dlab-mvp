"""«También en» con un catálogo de tamaño real (≥ 20 ítems), sin base: el resto de los tests baja
MIN_ITEMS_ELSEWHERE a 1 y con eso ninguna vertical alcanza la masa mínima, así que nunca se ejercita el orden por
participación."""

from rappi_ia.agent import verticals

# (vertical, ítems del concepto, ítems de la vertical)
OFFER = [
    ("supermercado", 100, 50_000),  # 0,2 %: la de más productos
    ("chocolateria", 30, 600),  # 5 %: la más típica
    ("conveniencia", 25, 1_000),  # 2,5 %: justo en el piso (max(20, 0,25 × 100) = 25)
    ("mall", 19, 100),  # 19 %: bajo MIN_ITEMS_ELSEWHERE
    ("licores", 60, 8_000),  # la vertical actual
]
STORES = [  # concept_store_assortment, ya ordenado por ítems
    ("supermercado", "Lider", None),
    ("supermercado", "Jumbo", "jumbo.png"),
    ("conveniencia", "Lider", None),  # la misma cadena: solo tiene esa
    ("chocolateria", "Varsovienne", None),
]


class FakeConn:
    def execute(self, sql, params=()):
        rows = []
        if "FROM concept_assortment WHERE concept_id" in sql:
            rows = [(v, items) for v, items, _ in OFFER]
        elif "GROUP BY vertical" in sql:
            rows = OFFER
        elif "FROM concept_store_assortment" in sql:
            rows = [r for r in STORES if r[0] in params[1]]
        return type("Cursor", (), {"fetchall": lambda self: rows})()


def test_rank_counts_the_floor_itself_as_enough_offer():
    contenders, rest = verticals._rank(OFFER)
    assert contenders == ["chocolateria", "conveniencia", "licores", "supermercado"]
    assert rest == ["mall"]


def test_other_verticals_go_by_quantity_with_real_sizes_and_never_without_stores():
    found = verticals.available_elsewhere(FakeConn(), "cerveza", {"licores"}, limit=5)
    assert [v["vertical"] for v in found] == ["supermercado", "chocolateria", "conveniencia"]  # mall: < 20 ítems
    stores = {v["vertical"]: [s["name"] for s in v["stores"]] for v in found}
    assert stores["supermercado"] == ["Lider", "Jumbo"]
    assert stores["conveniencia"] == ["Lider"]  # mejor repetida que sin tiendas
    assert len(verticals.available_elsewhere(FakeConn(), "cerveza", {"licores"}, limit=2)) == 2
