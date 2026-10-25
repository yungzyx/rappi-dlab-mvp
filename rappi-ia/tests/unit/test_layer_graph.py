from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.layers.attributes import load_attribute_rules
from rappi_ia.layers.graph import KINDS, load_relation_rules

VERSION, RELATIONS, EDGES = load_relation_rules()
TAXONOMY = load_taxonomy()


def _node(ref: str) -> tuple[str, str]:
    kind, _, ident = ref.partition(":")
    return kind, ident


def test_every_relation_is_defined_once_with_known_kinds():
    ids = [r.relation for r in RELATIONS]
    assert len(ids) == len(set(ids)) and {"complementa", "sustituye", "conflicto", "tiene_atributo"} <= set(ids)
    kinds = KINDS
    assert all(set(r.from_kinds) <= kinds and set(r.to_kinds) <= kinds for r in RELATIONS)


def test_curated_edges_point_to_real_nodes_of_the_right_kind_with_a_valid_weight():
    defs = {r.relation: r for r in RELATIONS}
    for edge in EDGES:
        (fk, fid), (tk, tid) = _node(edge.source), _node(edge.target)
        assert edge.relation in defs and fk in defs[edge.relation].from_kinds and tk in defs[edge.relation].to_kinds
        assert 0 <= edge.weight <= 1
        for kind, ident in ((fk, fid), (tk, tid)):
            if kind == "concept":
                assert ident in TAXONOMY.concepts, edge
            elif kind == "group":
                assert ident in TAXONOMY.groups, edge


def test_a_symmetric_relation_is_written_in_one_direction_only():
    symmetric = {r.relation for r in RELATIONS if r.is_symmetric}
    pairs = [frozenset((e.source, e.target)) for e in EDGES if e.relation in symmetric]
    assert len(pairs) == len(set(pairs))


def test_sensitive_groups_conflict_with_baby_items():
    conflicts = {(e.source, e.target) for e in EDGES if e.relation == "conflicto"}
    assert ("group:alcohol", "concept:panales") in conflicts
    assert ("group:tabaco", "concept:alimentacion-bebe") in conflicts
    assert load_attribute_rules()[0]  # el vocabulario de atributos carga junto al de relaciones


def test_no_substitute_leads_into_a_restricted_concept_or_a_different_animal():
    """Un sustituto vale en un solo sentido si el destino restringe (vegano) o es de otra especie (perro ≠ gato)."""
    pairs = {frozenset((e.source, e.target)) for e in EDGES if e.relation == "sustituye"}
    assert not any("concept:vegano" in pair for pair in pairs)
    assert frozenset(("concept:alimento-perro", "concept:alimento-gato")) not in pairs


def test_adult_products_conflict_with_baby_and_kids_items():
    conflicts = {(e.source, e.target) for e in EDGES if e.relation == "conflicto"}
    for kids in ("juguetes-infantiles", "alimentacion-bebe", "articulos-bebe"):
        assert ("group:adultos", f"concept:{kids}") in conflicts
