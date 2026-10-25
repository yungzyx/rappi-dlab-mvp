"""Rol A: Jev propone conceptos para las categorías sin mapeo revisado (siempre con `FakeJev`, sin red)."""

import csv
import json
from argparse import Namespace

import pytest

from conftest import add_product, add_store
from fakes.jev import FakeJev
from rappi_ia import cli, config, jev
from rappi_ia.concepts import jev_map
from rappi_ia.concepts.jev_map import build_questions, category_state, decide, map_categories
from rappi_ia.concepts.pipeline import build_concepts
from rappi_ia.concepts.report import CATEGORY_MAP_COLUMNS, coverage_report, render_text
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.jev import JevAnswer

TAXONOMY = load_taxonomy()
T_AUTO = 0.85


def jev_says(concept="snacks-salados", conf=0.9, mezcla=0.1, salud=0.05, adultos=0.05) -> dict:
    return {
        "concepto": JevAnswer(choice=concept, confidence=conf, probabilities={concept: conf}),
        "mezcla": JevAnswer(noul=mezcla),
        "salud_sensible": JevAnswer(noul=salud),
        "solo_adultos": JevAnswer(noul=adultos),
    }


# --- preguntas ---------------------------------------------------------------------------------------------------


def test_build_questions_offers_every_leaf_and_none():
    questions = build_questions(TAXONOMY)

    assert set(questions) == {"concepto", "mezcla", "salud_sensible", "solo_adultos"}
    concept = questions["concepto"]
    assert concept["type"] == "choice"
    assert set(concept["criteria"]) == set(TAXONOMY.concepts) | {"ninguno"}
    assert len(concept["criteria"]) == len(TAXONOMY.concepts) + 1 <= 255
    cerveza = concept["criteria"]["cerveza"]
    assert cerveza["what"] == "Cerveza" and cerveza["examples"] == list(TAXONOMY.concepts["cerveza"].keywords[:5])
    assert all(questions[name]["type"] == "noul" for name in ("mezcla", "salud_sensible", "solo_adultos"))


def test_english_variant_translates_instructions_and_keeps_criteria():
    spanish, english = build_questions(TAXONOMY), build_questions(TAXONOMY, "en")

    assert spanish == build_questions(TAXONOMY, "es")
    assert set(english) == set(spanish)
    for name in spanish:
        assert english[name]["type"] == spanish[name]["type"]
        assert english[name].get("criteria") == spanish[name].get("criteria")
        assert english[name]["instructions"] != spanish[name]["instructions"]
    assert english["concepto"]["instructions"].startswith("Which concept")


# --- tabla de decisión -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "kind"),
    [
        (jev_says("ninguno", conf=0.99), "nada"),
        (jev_says(mezcla=0.5, conf=0.99), "nada"),
        (jev_says(conf=0.9), "mapear"),
        (jev_says(conf=0.85), "mapear"),
        (jev_says(conf=0.84), "revisar"),
        (jev_says(conf=0.6), "revisar"),
        (jev_says(conf=0.59), "nada"),
        (jev_says("no-existe", conf=0.99), "nada"),
    ],
    ids=["ninguno", "mezcla", "sobre-t", "justo-t", "bajo-t", "justo-0.6", "bajo-0.6", "concepto-desconocido"],
)
def test_decision_table(answer, kind):
    decision = decide(answer, TAXONOMY, T_AUTO)
    assert decision.kind == kind
    if kind == "mapear":
        assert decision.concept_id == "snacks-salados"
        assert decision.confidence == pytest.approx(answer["concepto"].confidence)


def test_t_auto_comes_from_the_caller():
    assert decide(jev_says(conf=0.9), TAXONOMY, 0.95).kind == "revisar"


@pytest.mark.parametrize(
    ("answer", "kind"),
    [
        # Salud: la categoría parece de salud y el concepto no es sensible (laxantes → snacks), o al revés.
        (jev_says("snacks-salados", conf=0.99, salud=0.7), "revisar"),
        (jev_says("medicamentos", conf=0.99, salud=0.1), "revisar"),
        (jev_says("medicamentos", conf=0.99, salud=0.9), "mapear"),
        # +18: alcohol o tabaco a un concepto sin restricción de edad, o un concepto +18 para algo que no lo es.
        (jev_says("gaseosas", conf=0.99, adultos=0.8), "revisar"),
        (jev_says("cerveza", conf=0.99, adultos=0.2), "revisar"),
        (jev_says("cerveza", conf=0.99, adultos=0.9), "mapear"),
        # Tabaco: sensible y +18; basta con que la guardia de adultos lo vea, no es «salud».
        (jev_says("cigarrillos", conf=0.99, salud=0.05, adultos=0.95), "mapear"),
        (jev_says("cigarrillos", conf=0.99, salud=0.05, adultos=0.1), "revisar"),
        # La guardia manda antes que la confianza: un conflicto nunca se aplica ni se descarta solo.
        (jev_says("snacks-salados", conf=0.3, salud=0.9), "revisar"),
    ],
)
def test_guards_send_conflicts_to_review(answer, kind):
    decision = decide(answer, TAXONOMY, T_AUTO)
    assert decision.kind == kind
    if kind == "revisar":
        assert decision.concept_id == answer["concepto"].choice


def test_guard_reason_is_readable():
    decision = decide(jev_says("snacks-salados", conf=0.99, salud=0.7), TAXONOMY, T_AUTO)
    assert "salud" in decision.reason


# --- estado de una categoría -------------------------------------------------------------------------------------


def test_category_state_has_vertical_name_and_the_most_common_examples(db):
    add_store(db, 1, "farmacia", "Farmacia")
    add_store(db, 2, "farmacia", "Farmacia 2")
    add_store(db, 3, "supermercado", "Súper")
    for i in range(10):
        add_product(db, 100 + i, f"Laxante {i:02d}", 1, "Laxantes suaves")
    db.execute("INSERT INTO store_products (store_id, sku, master_product_id) VALUES (2, 'x-109', 109)")
    db.execute("INSERT INTO store_products (store_id, sku, master_product_id) VALUES (3, 'x-108', 108)")

    state = category_state(db, "Laxantes suaves")

    assert state["vertical"] == "farmacia"
    assert state["categoria"] == "Laxantes suaves"
    assert len(state["ejemplos"]) == 8
    assert state["ejemplos"][:2] == ["Laxante 08", "Laxante 09"]  # las que más tiendas venden van primero


# --- map_categories ----------------------------------------------------------------------------------------------

DECISIONS = {
    "Peluches y muñecas": jev_says("juguetes-infantiles", conf=0.95),
    "Laxantes suaves": jev_says("snacks-salados", conf=0.95, salud=0.9),  # guardia: a revisión
    "Snacks de fiesta": jev_says("snacks-salados", conf=0.7),  # confianza media: a revisión
    "Ofertas variadas": jev_says("snacks-salados", conf=0.95, mezcla=0.8),  # mezcla: nada
}


def responder(table):
    def answer(state, questions):
        return table.get(state["categoria"])

    return answer


@pytest.fixture
def catalog(db):
    add_store(db, 1, "supermercado", "Súper")
    add_store(db, 2, "farmacia", "Farmacia")
    add_product(db, 1, "Peluche oso 30 cm", 1, "Peluches y muñecas")
    add_product(db, 2, "Muñeca de trapo", 1, "Peluches y muñecas")
    add_product(db, 3, "Laxante natural 30 cápsulas", 2, "Laxantes suaves")
    add_product(db, 4, "Papas fritas 200 g", 1, "Snacks de fiesta")
    add_product(db, 5, "Pack sorpresa", 1, "Ofertas variadas")
    add_product(db, 6, "Cerveza Escudo 470 cc", 1, "Cervezas")  # mapeada en category_map.csv: no se le pregunta
    db.commit()
    build_concepts(db)  # carga la taxonomía y el CSV versionado
    return db


def jev_rows(db):
    return db.execute(
        "SELECT source_key, concept_id, confidence, model_version FROM category_map WHERE method = 'jev' ORDER BY 1"
    ).fetchall()


def read_csv(path):
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_map_categories_applies_the_decision_table(catalog, tmp_path):
    fake = FakeJev(responder=responder(DECISIONS))
    review = tmp_path / "revision-jev.csv"

    summary = map_categories(catalog, fake, TAXONOMY, T_AUTO, review_path=review)

    asked = sorted(state["categoria"] for state, _ in fake.calls)
    assert asked == sorted(DECISIONS)  # «Cervezas» ya tiene mapeo revisado
    assert jev_rows(catalog) == [("peluches y muñecas", "juguetes-infantiles", pytest.approx(0.95), fake.model)]
    rows = read_csv(review)
    assert list(rows[0]) == CATEGORY_MAP_COLUMNS
    assert sorted(r["nombre"] for r in rows) == ["Laxantes suaves", "Snacks de fiesta"]
    laxantes = next(r for r in rows if r["nombre"] == "Laxantes suaves")
    assert laxantes["concept_id"] == "snacks-salados" and laxantes["metodo"] == "jev"
    assert laxantes["revision"] == "pendiente" and laxantes["productos"] == "1" and "salud" in laxantes["nota"]
    assert summary == {"consultadas": 4, "mapear": 1, "revisar": 2, "nada": 1, "sin_respuesta": 0}


def test_map_categories_is_idempotent(catalog, tmp_path):
    review = tmp_path / "revision-jev.csv"
    map_categories(catalog, FakeJev(responder=responder(DECISIONS)), TAXONOMY, T_AUTO, review_path=review)
    first_rows, first_csv = jev_rows(catalog), review.read_text(encoding="utf-8")

    map_categories(catalog, FakeJev(responder=responder(DECISIONS)), TAXONOMY, T_AUTO, review_path=review)

    assert jev_rows(catalog) == first_rows
    assert review.read_text(encoding="utf-8") == first_csv


def test_only_new_skips_categories_jev_already_mapped(catalog, tmp_path):
    review = tmp_path / "revision-jev.csv"
    map_categories(catalog, FakeJev(responder=responder(DECISIONS)), TAXONOMY, T_AUTO, review_path=review)

    fake = FakeJev(responder=responder(DECISIONS))
    map_categories(catalog, fake, TAXONOMY, T_AUTO, only_new=True, review_path=review)

    assert "Peluches y muñecas" not in [state["categoria"] for state, _ in fake.calls]
    assert len(fake.calls) == 3
    assert jev_rows(catalog)[0][:2] == ("peluches y muñecas", "juguetes-infantiles")


def test_a_full_run_drops_a_jev_mapping_that_no_longer_passes(catalog, tmp_path):
    review = tmp_path / "revision-jev.csv"
    map_categories(catalog, FakeJev(responder=responder(DECISIONS)), TAXONOMY, T_AUTO, review_path=review)

    doubtful = DECISIONS | {"Peluches y muñecas": jev_says("juguetes-infantiles", conf=0.7)}
    map_categories(catalog, FakeJev(responder=responder(doubtful)), TAXONOMY, T_AUTO, review_path=review)

    assert jev_rows(catalog) == []
    assert "Peluches y muñecas" in [r["nombre"] for r in read_csv(review)]


def test_a_failed_answer_keeps_what_was_there(catalog, tmp_path):
    review = tmp_path / "revision-jev.csv"
    map_categories(catalog, FakeJev(responder=responder(DECISIONS)), TAXONOMY, T_AUTO, review_path=review)

    failing = FakeJev(
        responder=responder(DECISIONS),
        fail_when=lambda state: state["categoria"] in {"Peluches y muñecas", "Laxantes suaves"},
    )
    summary = map_categories(catalog, failing, TAXONOMY, T_AUTO, review_path=review)

    assert summary["sin_respuesta"] == 2
    assert [row[0] for row in jev_rows(catalog)] == ["peluches y muñecas"]
    assert sorted(r["nombre"] for r in read_csv(review)) == ["Laxantes suaves", "Snacks de fiesta"]


def test_jev_never_overwrites_a_reviewed_mapping(catalog, tmp_path):
    """Aunque se le pregunte por una categoría que ya tiene mapeo curado (p. ej., el CSV cambió en medio)."""
    catalog.execute(
        """INSERT INTO category_map (source_kind, source_key, source_name, concept_id, method, confidence)
           VALUES ('categoria', 'snacks de fiesta', 'Snacks de fiesta', 'galletas', 'curado', 1)"""
    )
    table = DECISIONS | {"Snacks de fiesta": jev_says("snacks-salados", conf=0.99)}
    jev_map.write_decisions(
        catalog,
        {"snacks de fiesta": ("Snacks de fiesta", 1, decide(table["Snacks de fiesta"], TAXONOMY, T_AUTO))},
        "jev-prueba",
    )
    row = catalog.execute("SELECT method, concept_id FROM category_map WHERE source_key = 'snacks de fiesta'")
    assert row.fetchone() == ("curado", "galletas")


def test_a_concept_missing_from_the_database_goes_to_review(catalog, tmp_path):
    """Si la taxonomía cambió y `concepts` aún no corrió, no se rompe la corrida por la clave foránea."""
    catalog.execute("DELETE FROM concepts WHERE concept_id = 'juguetes-infantiles'")
    review = tmp_path / "revision-jev.csv"

    summary = map_categories(catalog, FakeJev(responder=responder(DECISIONS)), TAXONOMY, T_AUTO, review_path=review)

    assert summary["mapear"] == 0 and jev_rows(catalog) == []
    assert "Peluches y muñecas" in [r["nombre"] for r in read_csv(review)]


# --- comando map-categories --jev --------------------------------------------------------------------------------


@pytest.fixture
def cli_env(catalog, tmp_path, monkeypatch):
    """Datos en tmp_path, adopción y cliente controlados por cada test."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(jev, "ADOPTION_FILE", tmp_path / "jev-adopcion.json")
    fake = FakeJev(responder=responder(DECISIONS))
    monkeypatch.setattr(jev, "client_or_none", lambda: fake)
    return Namespace(db=catalog, tmp=tmp_path, fake=fake, review=tmp_path / "data" / "concepts" / "revision-jev.csv")


def adopt(env, **values):
    document = {"categorias": True, "juez": False, "t_auto": 0.85, "model_version": env.fake.model} | values
    (env.tmp / "jev-adopcion.json").write_text(json.dumps(document), encoding="utf-8")


def args(**flags):
    return Namespace(**({"jev": True, "solo_nuevas": False, "exportar": False} | flags))


def test_without_adoption_jev_does_nothing_even_with_a_key(cli_env, capsys):
    cli.cmd_map_categories(cli_env.db, args())

    assert "no está adoptado" in capsys.readouterr().out
    assert cli_env.fake.calls == [] and jev_rows(cli_env.db) == [] and not cli_env.review.exists()


def test_adoption_that_says_no_does_nothing(cli_env, capsys):
    adopt(cli_env, categorias=False)
    cli.cmd_map_categories(cli_env.db, args())
    assert "no está adoptado" in capsys.readouterr().out
    assert cli_env.fake.calls == []


def test_without_key_jev_writes_nothing(cli_env, monkeypatch, capsys):
    adopt(cli_env)
    monkeypatch.setattr(jev, "client_or_none", lambda: None)

    cli.cmd_map_categories(cli_env.db, args())

    assert "TYPESAFE_API_KEY" in capsys.readouterr().out
    assert jev_rows(cli_env.db) == [] and not cli_env.review.exists()


def test_adoption_for_another_model_does_nothing(cli_env, capsys):
    adopt(cli_env, model_version="jev-0.1")
    cli.cmd_map_categories(cli_env.db, args())
    assert "jev-0.1" in capsys.readouterr().out
    assert cli_env.fake.calls == [] and jev_rows(cli_env.db) == []


def test_with_key_and_adoption_jev_maps_and_writes_the_review_queue(cli_env, capsys):
    adopt(cli_env, t_auto=0.9)

    cli.cmd_map_categories(cli_env.db, args(solo_nuevas=True))

    out = capsys.readouterr().out
    assert "mapeó 1" in out and "2 a revisión" in out
    assert [row[0] for row in jev_rows(cli_env.db)] == ["peluches y muñecas"]
    assert len(read_csv(cli_env.review)) == 2
    cli_env.db.rollback()  # el comando confirmó su transacción
    assert [row[0] for row in jev_rows(cli_env.db)] == ["peluches y muñecas"]


def test_map_categories_uses_the_adopted_instruction_variant(cli_env):
    adopt(cli_env, variante="en")

    cli.cmd_map_categories(cli_env.db, args())

    english = build_questions(TAXONOMY, "en")
    assert cli_env.fake.calls and all(questions == english for _, questions in cli_env.fake.calls)


def test_export_lists_jev_mappings_and_the_review_queue_without_calling_jev(cli_env, capsys):
    adopt(cli_env)
    cli.cmd_map_categories(cli_env.db, args())
    calls = len(cli_env.fake.calls)

    cli.cmd_map_categories(cli_env.db, args(exportar=True))

    assert len(cli_env.fake.calls) == calls
    rows = read_csv(cli_env.tmp / "data" / "concepts" / "categorias-jev.csv")
    assert list(rows[0]) == CATEGORY_MAP_COLUMNS
    by_name = {r["nombre"]: r for r in rows}
    assert set(by_name) == {"Peluches y muñecas", "Laxantes suaves", "Snacks de fiesta"}
    mapped = by_name["Peluches y muñecas"]
    assert (mapped["concept_id"], mapped["confianza"], mapped["metodo"]) == ("juguetes-infantiles", "0.95", "jev")
    assert cli_env.fake.model in mapped["nota"] and mapped["productos"] == "2"
    assert by_name["Laxantes suaves"]["revision"] == "pendiente"
    assert "category_map.csv" in capsys.readouterr().out


def test_solo_nuevas_and_exportar_need_jev(cli_env):
    with pytest.raises(SystemExit):
        cli.cmd_map_categories(cli_env.db, args(jev=False, solo_nuevas=True))


def test_parser_accepts_the_jev_flags():
    parsed = cli.build_parser().parse_args(["map-categories", "--jev", "--solo-nuevas"])
    assert parsed.jev and parsed.solo_nuevas and not parsed.exportar


# --- reporte de cobertura ----------------------------------------------------------------------------------------


def test_coverage_report_counts_the_review_queue_and_names_the_export_command(cli_env):
    adopt(cli_env)
    cli.cmd_map_categories(cli_env.db, args())

    report = coverage_report(cli_env.db)
    assert report["mapeos_jev"] == 1 and report["revision_jev"] == 2
    text = render_text(report)
    assert "rappi-ia map-categories --jev --exportar" in text
    assert "1 categorías mapeadas" in text and "2 en revisión" in text


def test_a_jev_mapping_rejected_in_review_goes_away_with_concepts(catalog):
    """Al revisar, la persona puede decir «ninguno» (fila del CSV): esa respuesta también gana sobre la de Jev."""
    catalog.execute(
        """INSERT INTO category_map (source_kind, source_key, source_name, concept_id, method, confidence)
           VALUES ('categoria', 'accesorios', 'Accesorios', 'juguetes-infantiles', 'jev', 0.9)"""
    )

    build_concepts(catalog)

    assert jev_rows(catalog) == []
