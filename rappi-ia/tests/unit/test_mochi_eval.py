"""Las revisiones automáticas de Mochi (eval/mochi_eval.py), con respuestas inventadas: sin base ni modelo."""

import json

from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.eval import mochi_eval
from rappi_ia.eval.mochi_eval import MochiRun, announce_labels, check, claimed_absent, load_cases, summary

TAXONOMY = load_taxonomy()
LABELS = announce_labels(TAXONOMY)


def _product(entity_id: str, concept: str | None, name: str = "Producto") -> dict:
    return {"entity_type": "catalog_item", "entity_id": entity_id, "name": name, "concept": concept}


def _response(text: str, products: list[dict], concepts: list[str] | None = None, query: str = "") -> dict:
    return {"text": text, "products": products, "intent": {"concepts": concepts or [], "query": query}}


def _no_search(vertical, query, concepts):
    raise AssertionError("no debía buscar")


def test_text_that_announces_a_concept_none_of_the_products_has_contradicts_them():
    """El caso del 05-11: "bebida para mezclar con pisco" anunciaba gaseosas y mostraba seis piscos."""
    response = _response(
        "Mira estas opciones de 🥤 bebidas gaseosas en Licores.", [_product(str(i), "pisco") for i in range(6)]
    )

    result = check(response, LABELS, TAXONOMY, _no_search)

    assert result["announced"] == "🥤 bebidas gaseosas" and result["share"] == 0


def test_an_occasion_label_counts_the_products_of_any_of_its_concepts():
    """ "antojo dulce" con cafés: ninguno es de la ocasión; con un chocolate, uno de dos."""
    text = "Mira estas opciones de antojo dulce 🍬 en el súper."
    cafes = [_product("1", "cafe"), _product("2", "cafe")]

    assert check(_response(text, cafes), LABELS, TAXONOMY, _no_search)["share"] == 0
    mixed = [_product("1", "cafe"), _product("2", "chocolates")]
    assert check(_response(text, mixed), LABELS, TAXONOMY, _no_search)["share"] == 0.5


def test_the_longest_label_wins_and_a_price_or_a_prefix_does_not_hide_it():
    text = 'Busqué "pisko". Lo más barato de 🍸 pisco bajo $10.000 en Licores.'

    assert mochi_eval.announced(text, LABELS) == "🍸 pisco"
    assert mochi_eval.announced('No encontré "xyz" en el súper.', LABELS) is None


def test_a_text_without_products_or_without_a_label_is_not_checked():
    assert (
        check(_response("Mira estas opciones de 🍸 pisco en Licores.", []), LABELS, TAXONOMY, _no_search)["share"]
        is None
    )
    assert (
        check(
            _response('Mira estas opciones de "xyz" en Licores.', [_product("1", None)]), LABELS, TAXONOMY, _no_search
        )["share"]
        is None
    )


def test_saying_a_vertical_has_none_of_a_concept_is_false_if_its_search_brings_it():
    asked = []

    def search(vertical, query, concepts):
        asked.append((vertical, query, concepts))
        return [_product("9", "helados", "Helado Chocolate"), _product("8", "chocolates")]

    text = 'En Turbo no hay "helados", pero en el súper sí. Mira estas opciones de 🍦 helados en el súper.'
    result = check(_response(text, [_product("1", "helados")]), LABELS, TAXONOMY, search)

    assert asked == [("turbo", "Helados", ["helados"])]
    assert result["absent"] == '1 de "helados" en turbo'
    assert result["says_absent"]


def test_saying_there_is_no_detail_is_false_if_the_request_brings_products_that_name_it():
    """'En Turbo no hay "dulce"' (el 05-11) y Turbo sí trae cafés del pedido con "dulce" en el nombre."""

    def search(vertical, query, concepts):
        assert (vertical, query, concepts) == ("turbo", "cafe dulce", ["cafe"])
        return [_product("1", "cafe", "Café Dulce de Leche"), _product("2", "cafe", "Café Molido"), _product("3", None)]

    text = 'En Turbo no hay "dulce", pero en el súper sí. Mira estas opciones de ☕ café en el súper.'
    response = _response(text, [_product("4", "cafe")], concepts=["cafe"], query="cafe dulce")

    assert check(response, LABELS, TAXONOMY, search)["absent"] == '1 de "dulce" en turbo'


def test_saying_there_is_none_is_fine_when_the_search_brings_none():
    text = 'En farmacia no hay "vino", pero en Licores sí.'

    assert check(_response(text, []), LABELS, TAXONOMY, lambda v, q, c: [_product("1", "cerveza")])["absent"] is None


def test_almost_none_is_not_a_claim_of_none():
    assert claimed_absent('En Turbo casi no hay "helados"; en el súper hay más.') is None
    assert claimed_absent('En Marte no hay "helados", pero en el súper sí.') is None


def test_the_same_product_twice_is_a_duplicate():
    products = [_product("1", "cafe"), _product("2", "cafe"), _product("1", "cafe")]

    assert check(_response("Hola", products), LABELS, TAXONOMY, _no_search)["duplicates"] == ["catalog_item:1"]


def _run(set_name: str, n_products: int, share: float | None = None, absent: str | None = None) -> MochiRun:
    products = [_product(str(i), "cafe") for i in range(n_products)]
    return MochiRun(set_name, None, "q", "", "buscar", "texto", products, share=share, absent=absent)


def test_summary_counts_short_answers_only_among_those_with_products():
    runs = [
        _run("libres", 6, share=1.0),
        _run("libres", 3, share=0.0),
        _run("libres", 0),
        _run("apartado", 2, share=0.3),
    ]

    totals = summary(runs)

    assert totals["libres"] == {
        "casos": 3,
        "con_productos": 2,
        "promedio": 4.5,
        "cortas": 1,
        "anuncia": 2,
        "contradice": 1,
        "menos_de_la_mitad": 0,
        "dice_no_hay": 0,
        "no_hay_falso": 0,
        "duplicados": 0,
    }
    assert totals["total"]["cortas"] == 2 and totals["total"]["menos_de_la_mitad"] == 1


def test_report_lists_what_fails_and_says_the_judged_part_is_an_llm_judgment():
    runs = [_run("necesidades", 6, share=0.0), _run("libres", 2, absent='1 de "dulce" en turbo')]
    scores = {"n": 1, "ndcg": 0.9, "p@3": 0.667, "util@3": 1.0, "mostrados": 6, "sin_juicio": 2, "no_sirve": 0.0}

    mochi_rows = [{"vertical": "turbo", "consulta": "algo para picar", "ndcg": 0.9, "p@3": 0.667}]
    search_rows = [{"vertical": "turbo", "consulta": "algo para picar", "ndcg": 0.8, "p@3": 0.667}]

    report = mochi_eval.render_markdown(
        runs,
        {"total": scores, "completas": scores, "consultas": mochi_rows},
        {"total": scores, "completas": scores, "consultas": search_rows},
    )

    assert "## Revisiones que fallan" in report and 'la búsqueda trae 1 de "dulce" en turbo' in report
    assert "## Respuestas con menos de 4 productos" in report
    assert "juicio LLM, no humano" in report and "nDCG@6" in report
    assert "2 productos de Mochi y 2 de `/search` sin juicio" in report
    assert "Diferencia Mochi − `/search` consulta por consulta (1 consultas" in report
    assert "| nDCG@6 | 1 | 0 | 0 | 0.1 | 0.1 a 0.1 |" in report


def test_paired_difference_pairs_by_query_and_gives_a_reproducible_bootstrap_interval():
    a = [{"vertical": "turbo", "consulta": f"q{i}", "ndcg": 0.5 + i / 20} for i in range(10)]
    b = [{"vertical": "turbo", "consulta": f"q{i}", "ndcg": 0.5} for i in range(10)]
    b.append({"vertical": "turbo", "consulta": "solo en b", "ndcg": 1.0})  # sin pareja: no cuenta

    d = mochi_eval.paired_difference(a, b, "ndcg")

    assert (d["n"], d["sube"], d["empata"], d["baja"], d["diferencia"]) == (10, 9, 1, 0, 0.225)
    low, high = d["ic95"]
    assert low < 0.225 < high and low > 0
    assert mochi_eval.paired_difference(a, b, "ndcg") == d  # semilla fija
    assert mochi_eval.paired_difference([], b, "ndcg")["ic95"] is None


def test_cases_take_needs_free_questions_first_turns_and_the_held_out_set(tmp_path):
    queries = tmp_path / "queries.json"
    queries.write_text(
        json.dumps(
            {
                "queries": [
                    {"vertical": "turbo", "query": "algo para picar", "tipo": "necesidad", "concepts": []},
                    {"vertical": "turbo", "query": "papas fritas", "tipo": "exacta", "concepts": []},
                ]
            }
        )
    )
    free = tmp_path / "libres.txt"
    free.write_text("# título\n¿qué es un poke?\n\n")
    conversations = tmp_path / "conversaciones.txt"
    conversations.write_text("# Ocasiones\nsushi\n+ sin palta\n+ más barato\npizza\n")
    heldout = tmp_path / "apartado.json"
    heldout.write_text(json.dumps({"queries": [{"query": "carbón para el asado", "vertical": None, "tipo": "x"}]}))

    cases = load_cases(queries, free, conversations, heldout)

    assert [(c["set"], c["vertical"], c["query"]) for c in cases] == [
        ("necesidades", "turbo", "algo para picar"),
        ("libres", None, "¿qué es un poke?"),
        ("conversaciones", None, "sushi"),
        ("conversaciones", None, "pizza"),
        ("apartado", None, "carbón para el asado"),
    ]


def test_the_held_out_set_says_it_is_not_for_tuning_and_has_about_forty_phrases():
    document = json.loads(mochi_eval.HELDOUT_FILE.read_text(encoding="utf-8"))

    assert "no se usa para ajustar" in document["nota"]
    assert 35 <= len(document["queries"]) <= 50
    assert all(q["vertical"] in (None, *mochi_eval.VERTICAL_LABELS) for q in document["queries"])
