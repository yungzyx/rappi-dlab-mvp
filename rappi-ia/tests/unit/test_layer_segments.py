import logging
from contextlib import contextmanager

import pytest

from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.layers.attributes import load_attribute_rules
from rappi_ia.layers.segments import (
    CONTENT_PIECES,
    CONTEXT_PIECES,
    EVENT_TYPES,
    FAMILIES,
    LEVELS,
    METRICS,
    SENSITIVE_SEGMENTS,
    load_segment_rules,
    recalculate_user_segments,
)

VERSION, RULES = load_segment_rules()
BY_ID = {r.id: r for r in RULES}


def test_ids_are_unique_and_the_twelve_families_are_all_used():
    assert len(BY_ID) == len(RULES) >= 140
    assert {r.family for r in RULES} == set(FAMILIES) and len(FAMILIES) == 12


def test_exactly_the_fourteen_sensitive_segments_are_flagged():
    """Los 13 de la spec más `higiene-bebe`, que mira lo mismo que `mama-papa-bebe`."""
    assert {r.id for r in RULES if r.sensitive} == SENSITIVE_SEGMENTS
    assert (
        len(SENSITIVE_SEGMENTS) == 14
        and {"compra-sin-gluten", "embarazo", "tabaco", "higiene-bebe"} <= SENSITIVE_SEGMENTS
    )


def test_sensitive_segments_are_named_by_behaviour_never_by_condition():
    names = " ".join(BY_ID[i].name.lower() + " " + BY_ID[i].id for i in SENSITIVE_SEGMENTS)
    for condition in ("celiaco", "celíaco", "diabet", "hipertens", "alérgic", "alergic", "enferm"):
        assert condition not in names


def test_every_rule_has_a_signal_or_a_metric_but_not_both_and_known_pieces_only():
    for r in RULES:
        assert bool(r.signals) != bool(r.metric), r.id
        assert set(r.signals) <= {*CONTENT_PIECES, *CONTEXT_PIECES}, r.id
        assert set(r.exclude) <= {*CONTENT_PIECES, *CONTEXT_PIECES}, r.id
        assert set(r.events) <= EVENT_TYPES, r.id
        if r.signals:
            assert r.events, r.id
        if r.metric:
            assert r.metric["name"] in METRICS, r.id


def test_no_rule_leans_on_occasions_or_on_species_attributes():
    """Una ocasión agrupa conceptos cotidianos (chocolate, café, cerveza) y un producto «para perros y gatos» lleva los
    dos atributos de especie: con ellos «estudiante» y «tiene-gato» alcanzaban a media población simulada."""
    for r in RULES:
        assert "occasions" not in r.signals, r.id
    for rule_id in ("tiene-perro", "tiene-gato"):
        assert "attributes" not in BY_ID[rule_id].signals


def test_levels_are_increasing_and_complete():
    for r in RULES:
        values = [r.levels[level] for level in LEVELS]
        lower = bool(r.metric) and r.metric.get("stronger") == "lower"  # menos es más fuerte: niveles decrecientes
        assert list(r.levels) == list(LEVELS) and values == sorted(set(values), reverse=lower) and min(values) > 0, r.id
        assert r.min_signals >= 1 and r.window_days >= 1 and r.half_life_days > 0, r.id


def test_every_named_concept_group_attribute_occasion_and_service_exists():
    taxonomy = load_taxonomy()
    attributes = {a.attribute_id for a in load_attribute_rules()[1]}
    for r in RULES:
        for pieces in (r.signals, r.exclude):
            assert set(pieces.get("concepts", ())) <= set(taxonomy.concepts), r.id
            assert set(pieces.get("groups", ())) <= set(taxonomy.groups), r.id
            assert set(pieces.get("attributes", ())) <= attributes, r.id
            assert set(pieces.get("occasions", ())) <= set(taxonomy.occasions), r.id
            assert set(pieces.get("services", ())) <= set(taxonomy.services), r.id


def test_relationship_segments_use_metrics_and_the_rest_use_signals():
    assert BY_ID["en-riesgo"].metric == {"name": "dias_sin_pedido", "min": 30, "max": 90}
    assert BY_ID["compra-sin-gluten"].signals["attributes"] == ["sin-gluten"]
    assert BY_ID["nocturno"].signals["hours"] == [21, 1]


def _write(tmp_path, body):
    path = tmp_path / "segments.toml"
    path.write_text('version = "t"\n' + body, encoding="utf-8")
    return path


_OK = """
[[segment]]
id = "x"
name = "X"
family = "dieta"
description = "d"
signals = { concepts = ["cerveza"] }
events = { order_line = 3.0 }
window_days = 30
half_life_days = 10
min_signals = 1
levels = { bajo = 1.0, medio = 2.0, alto = 3.0 }
"""


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ('signals = { concepts = ["cerveza"] }', 'signals = { concepts = ["no-existe"] }'),
        ('signals = { concepts = ["cerveza"] }', 'signals = { colores = ["rojo"] }'),
        ("events = { order_line = 3.0 }", "events = { clic = 1.0 }"),
        ("levels = { bajo = 1.0, medio = 2.0, alto = 3.0 }", "levels = { bajo = 3.0, medio = 2.0, alto = 1.0 }"),
        ("min_signals = 1", "min_signals = 0"),
        ('family = "dieta"', 'family = "otra"'),
        ('signals = { concepts = ["cerveza"] }', "signals = { hours = [25, 3] }"),
        ('signals = { concepts = ["cerveza"] }', "signals = { metric_misc = 1 }"),
    ],
)
def test_a_bad_rule_fails_naming_the_segment(tmp_path, change, message):
    path = _write(tmp_path, _OK.replace(change, message))
    with pytest.raises(ValueError, match=r"Segmento x"):
        load_segment_rules(path)


def test_duplicate_ids_fail(tmp_path):
    with pytest.raises(ValueError, match="repetido"):
        load_segment_rules(_write(tmp_path, _OK + _OK))


def test_defaults_fill_what_a_segment_omits(tmp_path):
    body = (
        "[defaults]\nwindow_days = 99\nhalf_life_days = 9\nmin_signals = 2\n"
        "levels = { bajo = 1.0, medio = 2.0, alto = 3.0 }\nevents = { search = 1.0 }\n"
    )
    segment = (
        '[[segment]]\nid = "y"\nname = "Y"\nfamily = "dieta"\ndescription = "d"\nsignals = { concepts = ["cerveza"] }\n'
    )
    rule = load_segment_rules(_write(tmp_path, body + segment))[1][0]
    assert (rule.window_days, rule.min_signals, rule.events) == (99, 2, {"search": 1.0})


# ── motor de puntaje ──
from dataclasses import replace  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402

from rappi_ia.layers.segments import Signal, score_user  # noqa: E402

NOW = datetime(2026, 10, 6, 15, 0, tzinfo=UTC)


def _signal(days_ago=1.0, type="order_line", key=None, hour=None, **fields):
    ts = NOW - timedelta(days=days_ago)
    if hour is not None:
        ts = ts.replace(hour=hour)
    base = dict(
        ts=ts, type=type, concept=None, group=None, attributes=frozenset(), vertical=None, brand=None, query=None,
        modality=None, price_percentile=None, discounted=False, basket_items=None, basket_total=None,
        from_suggestion=False, event_key=key or f"{type}-{days_ago}-{hour}-{fields}",
    )  # fmt: skip
    return Signal(**{**base, **fields})


def _rule(**changes):
    base = replace(BY_ID["compra-sin-gluten"], signals={"concepts": ["galletas"]}, events={"order_line": 4.0})
    return replace(base, **changes)


_LOW = {"bajo": 0.5, "medio": 5.0, "alto": 10.0}


def _gluten(days_ago, **fields):
    return _signal(days_ago, concept="galletas", attributes=frozenset({"sin-gluten"}), **fields)


def test_two_gluten_free_purchases_are_not_a_segment_but_three_are():
    rule = BY_ID["compra-sin-gluten"]
    gf = lambda d, k: _signal(d, attributes=frozenset({"sin-gluten"}), concept="galletas", key=k)  # noqa: E731
    assert score_user([gf(1, "a"), gf(2, "b")], {}, [rule], NOW) == []

    found = score_user([gf(1, "a"), gf(2, "b"), gf(3, "c")], {}, [rule], NOW)
    assert [m.segment_id for m in found] == ["compra-sin-gluten"]
    assert found[0].signals == 3 and found[0].level == "medio"  # ≈ 3 × 3.0 × decaimiento ≈ 8,4 (medio ≥ 5, alto ≥ 10)


def test_level_is_the_highest_threshold_reached_and_below_the_first_there_is_no_row():
    rule = _rule(min_signals=1, levels={"bajo": 2.0, "medio": 5.0, "alto": 10.0}, half_life_days=1e9)
    one, two, three = ([_gluten(1, key=str(i)) for i in range(n)] for n in (1, 2, 3))  # 4, 8 y 12 puntos
    assert score_user(one, {}, [rule], NOW)[0].level == "bajo"
    assert score_user(two, {}, [rule], NOW)[0].level == "medio"
    assert score_user(three, {}, [rule], NOW)[0].level == "alto"
    weak = _rule(min_signals=1, levels={"bajo": 5.0, "medio": 6.0, "alto": 7.0}, half_life_days=1e9)
    assert score_user(one, {}, [weak], NOW) == []


def test_a_signal_at_half_life_age_is_worth_half():
    rule = _rule(min_signals=1, half_life_days=30.0, window_days=365, levels={"bajo": 0.1, "medio": 5.0, "alto": 10.0})
    fresh = score_user([_gluten(0.0, key="a")], {}, [rule], NOW)[0].score
    old = score_user([_gluten(30.0, key="b")], {}, [rule], NOW)[0].score
    assert fresh == pytest.approx(4.0) and old == pytest.approx(2.0)


def test_signals_outside_the_window_do_not_count():
    rule = _rule(min_signals=1, window_days=30, half_life_days=1e9)
    assert score_user([_gluten(31, key="a")], {}, [rule], NOW) == []
    assert score_user([_gluten(29, key="a")], {}, [rule], NOW) != []


def test_the_same_event_key_counts_once_for_min_signals():
    rule = _rule(min_signals=2)
    assert score_user([_gluten(1, key="x"), _gluten(2, key="x")], {}, [rule], NOW) == []


def test_exclude_drops_the_signals_it_matches():
    rule = _rule(min_signals=1, half_life_days=1e9, exclude={"concepts": ["pizza"]})
    pizza = _signal(1, concept="pizza", key="p")
    assert score_user([_gluten(1, key="a"), pizza], {}, [rule], NOW)[0].signals == 1
    only_excluded = _rule(signals={"groups": ["comida"]}, min_signals=1, exclude={"concepts": ["pizza"]})
    assert score_user([_signal(1, concept="pizza", group="comida", key="p")], {}, [only_excluded], NOW) == []


def test_hours_can_cross_midnight():
    rule = replace(BY_ID["nocturno"], signals={"hours": [22, 4]}, min_signals=1, half_life_days=1e9, levels=_LOW)
    at = lambda hour: score_user([_signal(1, hour=hour, key=str(hour))], {}, [rule], NOW)  # noqa: E731
    assert at(23) and at(3) and at(22) and at(4)
    assert not at(12) and not at(5)


def test_context_pieces_must_all_hold_and_content_pieces_need_only_one():
    rule = _rule(
        signals={"concepts": ["cafe"], "attributes": ["organico"], "weekdays": [1, 2, 3, 4, 5], "discount": True},
        min_signals=1, half_life_days=1e9, levels=_LOW,
    )  # fmt: skip
    monday = NOW - timedelta(days=NOW.weekday())  # lunes de esta semana
    days_ago = (NOW - monday).total_seconds() / 86400
    cafe = _signal(days_ago, concept="cafe", discounted=True, key="a")
    organic = _signal(days_ago, attributes=frozenset({"organico"}), discounted=True, key="b")
    full_price = _signal(days_ago, concept="cafe", discounted=False, key="c")
    assert score_user([cafe], {}, [rule], NOW) and score_user([organic], {}, [rule], NOW)
    assert score_user([full_price], {}, [rule], NOW) == []


def test_query_words_match_whole_words_and_plurals():
    rule = _rule(
        signals={"query_words": ["sin gluten"]}, events={"search": 1.0}, min_signals=1, half_life_days=1e9, levels=_LOW
    )
    search = lambda text: score_user([_signal(1, type="search", query=text, key=text)], {}, [rule], NOW)  # noqa: E731
    assert search("galletas SIN gluten por favor") and not search("singluten") and not search("gluten sin")


def test_query_words_are_normalized_once_per_text():
    """Una corrida compara cada consulta con cada frase de cada regla: cada texto se normaliza una vez (con memoria) y
    calza igual con tildes, mayúsculas y plurales."""
    from rappi_ia.layers import segments

    segments._words.cache_clear()
    for _ in range(3):
        assert segments._has_phrase("Pañales MUJERES talla G", "panal mujer")
        assert not segments._has_phrase("pañales", "panal mujer")
    info = segments._words.cache_info()
    assert info.misses == 3 and info.hits == 9  # «pañales mujeres talla g», «panal mujer» y «pañales»


def test_a_relationship_metric_decides_by_its_range():
    rules = [BY_ID[i] for i in ("activo", "en-riesgo", "dormido")]
    ids = lambda days: [m.segment_id for m in score_user([], {"dias_sin_pedido": days}, rules, NOW)]  # noqa: E731
    assert ids(10) == ["activo"] and ids(30) == ["en-riesgo"] and ids(89) == ["en-riesgo"] and ids(90) == ["dormido"]
    assert score_user([], {}, rules, NOW) == []  # sin la métrica no hay segmento
    risk = score_user([], {"dias_sin_pedido": 55}, [BY_ID["en-riesgo"]], NOW)[0]
    assert risk.score == 55 and risk.level == "medio" and risk.evidence == {"metric": "dias_sin_pedido", "value": 55}


def test_evidence_lists_the_three_biggest_contributors_and_the_extreme_dates():
    rule = _rule(signals={"groups": ["comida"]}, min_signals=1, half_life_days=1e9)
    signals = [
        *(_signal(5, group="comida", concept="pizza", key=f"p{i}") for i in range(3)),
        *(_signal(2, group="comida", concept="sushi", key=f"s{i}") for i in range(2)),
        _signal(1, group="comida", concept="empanadas", key="e"),
        _signal(9, group="comida", concept="pastas", key="x"),
    ]
    found = score_user(signals, {}, [rule], NOW)[0]
    assert [t["id"] for t in found.evidence["top"]] == ["pizza", "sushi", "empanadas"]
    assert found.first_seen == NOW - timedelta(days=9) and found.last_signal == NOW - timedelta(days=1)


def test_min_share_needs_the_rule_to_match_enough_of_the_persons_activity():
    rule = _rule(signals={"concepts": ["cafe"]}, min_signals=1, half_life_days=1e9, min_share=0.5, levels=_LOW)
    coffee = [_signal(1, concept="cafe", key=f"c{i}") for i in range(3)]
    other = [_signal(1, concept="pizza", key=f"p{i}") for i in range(6)]
    assert score_user(coffee + other[:2], {}, [rule], NOW)  # 3 de 5 = 60 %
    assert score_user(coffee + other, {}, [rule], NOW) == []  # 3 de 9: es un cafetero ocasional


def test_min_share_is_measured_on_the_event_types_the_rule_counts():
    rule = _rule(signals={"concepts": ["cafe"]}, events={"order_line": 3.0}, min_signals=1, min_share=0.9, levels=_LOW)
    views = [_signal(1, type="view_item", concept="pizza", key=f"v{i}") for i in range(20)]
    assert score_user([_signal(1, concept="cafe", key="o"), *views], {}, [rule], NOW)  # solo cuentan las compras


def test_a_rule_without_min_share_ignores_the_rest_of_the_activity():
    rule = _rule(signals={"concepts": ["cafe"]}, min_signals=1, min_share=0.0, levels=_LOW)
    noise = [_signal(1, concept="pizza", key=f"p{i}") for i in range(50)]
    assert score_user([_signal(1, concept="cafe", key="c"), *noise], {}, [rule], NOW)


def test_every_broad_rule_asks_for_a_share_of_the_activity():
    """Un contexto que cualquiera cumple de vez en cuando (un fin de semana, un precio alto) no es un perfil."""
    for rule_id in ("fin-de-semana", "dia-de-pago", "nocturno", "premium", "sensible-al-precio", "reposicion-rapida"):
        assert 0.2 <= BY_ID[rule_id].min_share <= 1, rule_id


def test_for_metrics_where_lower_is_stronger_the_smaller_value_gets_the_higher_level():
    new = BY_ID["nuevo"]
    level = lambda rule, value, name: score_user([], {name: value}, [rule], NOW)[0].level  # noqa: E731
    assert [level(new, d, "dias_desde_alta") for d in (2.4, 5.0, 13.0)] == ["alto", "medio", "bajo"]
    active = BY_ID["activo"]
    assert [level(active, d, "dias_sin_pedido") for d in (2.0, 12.0, 25.0)] == ["alto", "medio", "bajo"]
    assert level(BY_ID["gasto-bajo"], 0.03, "gasto_90d_percentil") == "alto"
    assert level(BY_ID["gasto-bajo"], 0.18, "gasto_90d_percentil") == "bajo"
    assert level(BY_ID["en-riesgo"], 75, "dias_sin_pedido") == "alto"  # donde más es más fuerte, no cambia


def test_a_lower_is_stronger_metric_needs_decreasing_levels(tmp_path):
    body = """
[[segment]]
id = "x"
name = "X"
family = "relacion"
description = "d"
metric = { name = "dias_sin_pedido", min = 0, max = 30, stronger = "lower" }
window_days = 30
half_life_days = 10
min_signals = 1
levels = { bajo = 5.0, medio = 10.0, alto = 20.0 }
"""
    with pytest.raises(ValueError, match=r"Segmento x.*decrecientes"):
        load_segment_rules(_write(tmp_path, body))


def test_no_plain_segment_shares_what_it_looks_at_with_a_sensitive_one():
    """Un segmento común que mira lo mismo que uno sensible es el mismo dato sin sus protecciones (sin filas por persona
    en `capa`, k ≥ 5): `higiene-bebe` era `mama-papa-bebe` con otro nombre."""
    taxonomy = load_taxonomy()

    def looked_at(rule):
        pieces = rule.signals
        concepts = set(pieces.get("concepts", ()))
        for group in pieces.get("groups", ()):
            concepts |= {c.id for c in taxonomy.concepts.values() if c.parent == group}
        return concepts, set(pieces.get("attributes", ())), set(pieces.get("verticals", ()))

    sensitive = [looked_at(r) for r in RULES if r.sensitive]
    for r in RULES:
        if r.sensitive or not r.signals:
            continue
        concepts, attributes, verticals = looked_at(r)
        for s_concepts, s_attributes, s_verticals in sensitive:
            assert not (concepts & s_concepts or attributes & s_attributes or verticals & s_verticals), r.id


def test_evidence_of_a_plain_segment_never_names_what_a_sensitive_segment_looks_at():
    """`capa.user_segments` oculta los segmentos sensibles, pero la evidencia de uno común (cazaofertas) listaba lo que
    la persona compró, pañales incluidos: el mismo dato por otra puerta."""
    rule = BY_ID["cazaofertas"]
    signals = [
        *(_signal(2, concept="panales", discounted=True, key=f"p{i}", price_percentile=0.5) for i in range(4)),
        *(_signal(3, concept="galletas", discounted=True, key=f"g{i}", price_percentile=0.5) for i in range(3)),
    ]
    found = score_user(signals, {}, [replace(rule, min_signals=1, min_share=0.0, levels=_LOW)], NOW)[0]
    assert [t["id"] for t in found.evidence["top"]] == ["galletas"]

    sensitive = score_user(
        [_signal(2, concept="panales", key=f"b{i}") for i in range(4)], {}, [BY_ID["mama-papa-bebe"]], NOW
    )[0]
    assert [t["id"] for t in sensitive.evidence["top"]] == ["panales"]  # la propia evidencia del sensible se conserva


def test_evidence_also_drops_taxonomy_sensitive_concepts():
    sensitive_concept = min(c.id for c in load_taxonomy().concepts.values() if c.sensitive)
    rule = replace(BY_ID["cazaofertas"], min_signals=1, min_share=0.0, levels=_LOW)
    found = score_user([_signal(2, concept=sensitive_concept, discounted=True, price_percentile=0.5)], {}, [rule], NOW)
    assert found and found[0].evidence["top"] == []


def test_a_failed_recalculation_is_logged_without_the_user_id(caplog):
    """El aviso de un recálculo fallido queda en el registro, pero sin el id de la persona."""

    @contextmanager
    def broken():
        raise RuntimeError("sin base")
        yield

    with caplog.at_level(logging.INFO, logger="rappi_ia.layers.segments"):
        recalculate_user_segments(broken, "persona-123")

    assert "No se pudieron recalcular los segmentos" in caplog.text
    assert "persona-123" not in caplog.text


def test_failed_recalculation_never_logs_the_persons_id(caplog):
    """Un error de Postgres trae la fila en su texto (`Key (user_id)=(…)`): el aviso lleva su clase y su sqlstate,
    sin el texto ni la traza."""
    from contextlib import contextmanager

    import psycopg

    from rappi_ia.layers import segments

    @contextmanager
    def failing_connector():
        raise psycopg.errors.ForeignKeyViolation("Key (user_id)=(proto-0123456789abcdef) is not present")
        yield  # pragma: no cover

    with caplog.at_level(logging.WARNING, logger=segments.__name__):
        segments.recalculate_user_segments(failing_connector, "proto-0123456789abcdef")

    [record] = [r for r in caplog.records if r.name == segments.__name__]
    assert "proto-0123456789abcdef" not in record.getMessage()
    assert record.exc_info is None
    assert "ForeignKeyViolation" in record.getMessage()
