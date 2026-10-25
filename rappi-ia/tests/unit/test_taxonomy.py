import csv
from collections import defaultdict

import pytest

from rappi_ia.concepts.store import CATEGORY_MAP_CSV, NO_CONCEPT, read_category_map_csv
from rappi_ia.concepts.taxonomy import load_complements, load_taxonomy


def test_taxonomy_loads_with_unique_ids_and_valid_parents():
    taxonomy = load_taxonomy()
    assert len(taxonomy.concepts) >= 100
    assert all(c.parent in taxonomy.groups for c in taxonomy.concepts.values())
    assert not taxonomy.groups.keys() & taxonomy.concepts.keys()


def test_sensitive_and_age_flags():
    concepts = load_taxonomy().concepts
    for concept_id in ("medicamentos", "cigarrillos", "vapeo", "bienestar-sexual", "salud-sexual"):
        assert concepts[concept_id].sensitive, concept_id
    for concept_id in ("cerveza", "vino", "pisco", "cigarrillos", "bienestar-sexual"):
        assert concepts[concept_id].age_restricted, concept_id
    assert not concepts["snacks-salados"].sensitive


def test_curated_complements_reference_existing_concepts():
    edges = load_complements()
    assert ("cerveza", "snacks-salados", 0.9) in edges
    assert all(source != target for source, target, _ in edges)


def test_category_map_csv_uses_known_concepts():
    known = set(load_taxonomy().concepts) | {NO_CONCEPT}
    with CATEGORY_MAP_CSV.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) > 800
    unknown = {r["concept_id"] for r in rows} - known
    assert not unknown
    assert {r["tipo"] for r in rows} == {"categoria", "seccion_menu", "cocina"}
    assert all(0 <= float(r["confianza"]) <= 1 for r in rows)
    assert all(r["metodo"] in {"llm", "curado"} for r in rows)


def test_category_map_csv_has_one_concept_per_key():
    """La clave es el nombre en minúsculas: «Otros medicamentos» y «Otros Medicamentos» son la misma, y la última
    fila pisaba en silencio la decisión del juez (productos de acuario quedaban como medicamentos)."""
    concepts = defaultdict(set)
    with CATEGORY_MAP_CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            concepts[(r["tipo"], r["nombre"].strip().lower())].add(r["concept_id"])
    assert {key: sorted(ids) for key, ids in concepts.items() if len(ids) > 1} == {}


def test_reading_a_category_map_with_conflicting_rows_fails(tmp_path):
    path = tmp_path / "category_map.csv"
    path.write_text(
        "tipo,nombre,concept_id,confianza,metodo,revision,nota,productos\n"
        "categoria,Otros medicamentos,accesorios-mascota,0.8,llm,juez,,3\n"
        "categoria,Otros Medicamentos ,medicamentos,0.75,llm,juez,,1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="otros medicamentos"):
        read_category_map_csv(path)


@pytest.mark.parametrize("method", ["jev", "sugerido"])
def test_reading_a_category_map_rejects_unpromoted_proposals(tmp_path, method):
    """Una propuesta de la máquina (jev, sugerido) no es una revisión: al promoverla, la persona la pasa a «curado»."""
    path = tmp_path / "category_map.csv"
    path.write_text(
        "tipo,nombre,concept_id,confianza,metodo,revision,nota,productos\n"
        "categoria,Vinos,vino,0.95,llm,acuerdo,,10\n"
        f"categoria,Novedades de temporada,cerveza,0.9,{method},pendiente,,3\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=f"novedades de temporada.*{method}.*curado"):
        read_category_map_csv(path)


def test_hunger_occasion_is_always_restaurants():
    assert load_taxonomy().occasions["hambre"].vertical == "restaurantes"
    assert load_taxonomy().occasions["asado"].vertical is None  # las demás: el vertical con más surtido


def test_prepared_flag_comes_from_the_concept_or_its_group():
    """Lo que se pide hecho puede buscarse en restaurantes (agent/verticals.py); se declara en la taxonomía."""
    concepts = load_taxonomy().concepts
    assert concepts["hamburguesa"].prepared  # por su grupo, comida preparada
    assert concepts["postres"].prepared and concepts["cafe"].prepared  # por el concepto
    assert not concepts["chocolates"].prepared and not concepts["gaseosas"].prepared


def test_services_without_catalog_are_loaded_with_their_hooks():
    services = load_taxonomy().services
    assert set(services) == {"rappitravel", "rappifavor"}
    assert services["rappitravel"].route == "travel" and services["rappifavor"].route == "favor"
    assert [h.query for h in services["rappitravel"].hooks] == [
        "protector solar",
        "traje de baño",
        "chaqueta",
        "bufanda",
        "mochila de viaje",
    ]
    assert services["rappitravel"].hooks[-1].when == ()  # la mochila va con cualquier viaje


def test_a_service_hook_must_be_a_known_concept(tmp_path):
    from rappi_ia.concepts.taxonomy import DATA_DIR

    broken = (
        (DATA_DIR / "taxonomy.toml")
        .read_text(encoding="utf-8")
        .replace('concept = "ropa", query', 'concept = "no-existe", query')
    )
    path = tmp_path / "taxonomy.toml"
    path.write_text(broken, encoding="utf-8")
    with pytest.raises(ValueError, match="ganchos inexistentes"):
        load_taxonomy(path)
