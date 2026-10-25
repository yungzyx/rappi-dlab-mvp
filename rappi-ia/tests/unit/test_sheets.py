"""Planillas para juzgar a mano y κ: la estadística con casos de libro, la lectura de planillas con filas malas y la
selección estratificada (sin base de datos)."""

import json
from collections import Counter

import pytest

from rappi_ia.eval import sheets
from rappi_ia.eval.sheets import (
    cohen_kappa,
    read_category_sheet,
    read_search_sheet,
    sample_search_pairs,
    search_ids_document,
    weighted_kappa,
)


def test_kappa_is_one_when_the_raters_always_agree():
    assert cohen_kappa([1, 0, 1, 1, 0], [1, 0, 1, 1, 0]) == 1.0
    assert weighted_kappa([0, 1, 2, 2], [0, 1, 2, 2]) == 1.0


def test_kappa_is_zero_when_agreement_is_what_chance_gives():
    # Cada uno dice «sí» la mitad de las veces y coinciden en la mitad: justo lo esperable por azar.
    assert cohen_kappa([1, 1, 0, 0], [1, 0, 1, 0]) == pytest.approx(0.0)


def test_kappa_matches_the_textbook_two_by_two_example():
    """20 de acuerdo en «sí», 15 en «no», 5 y 10 de desacuerdo (N = 50): acuerdo observado 0,70; esperado por azar
    (25/50)(30/50) + (25/50)(20/50) = 0,50; κ = (0,70 - 0,50) / (1 - 0,50) = 0,4."""
    a = [1] * 20 + [1] * 5 + [0] * 10 + [0] * 15
    b = [1] * 20 + [0] * 5 + [1] * 10 + [0] * 15
    assert cohen_kappa(a, b) == pytest.approx(0.4)


def test_kappa_is_negative_when_the_raters_disagree_systematically():
    assert cohen_kappa([1, 1, 0, 0], [0, 0, 1, 1]) == pytest.approx(-1.0)


def test_kappa_when_both_always_say_the_same_thing_is_perfect_not_a_division_by_zero():
    assert cohen_kappa([1, 1, 1], [1, 1, 1]) == 1.0


def test_linear_weighted_kappa_by_hand():
    """a = [0,1,2,2], b = [0,2,2,1]. Desacuerdo observado: media de |a-b|/2 = (0+1+0+1)/4/2 = 0,25.
    Marginales de ambos: P(0)=0,25, P(1)=0,25, P(2)=0,5. Esperado: suma de p_i q_j |i-j|/2 =
    (2·0,0625·1 + 2·0,125·2 + 2·0,125·1)/2 = 0,4375. κ ponderado = 1 - 0,25/0,4375 = 3/7."""
    assert weighted_kappa([0, 1, 2, 2], [0, 2, 2, 1]) == pytest.approx(3 / 7)


def test_weighted_kappa_with_two_levels_is_cohens_kappa():
    a = [1, 1, 0, 0, 1, 0, 1, 1]
    b = [1, 0, 0, 1, 1, 0, 0, 1]
    assert weighted_kappa(a, b, levels=2) == pytest.approx(cohen_kappa(a, b))


def test_kappa_needs_paired_non_empty_ratings():
    with pytest.raises(ValueError):
        cohen_kappa([1, 0], [1])
    with pytest.raises(ValueError):
        cohen_kappa([], [])
    with pytest.raises(ValueError):
        weighted_kappa([0, 3], [0, 1], levels=3)  # un nivel fuera de 0..2


def _write(path, text, encoding="utf-8"):
    path.write_text(text, encoding=encoding)
    return path


SEARCH_HEADER = "id,consulta,vertical,posicion,nombre,categoria,tienda,juicio\n"


def test_read_search_sheet_maps_the_three_values_and_counts_blank_and_invalid_rows(tmp_path):
    path = _write(
        tmp_path / "planilla-busqueda.csv",
        SEARCH_HEADER
        + "a,pisco,licores,1,Pisco 35,Pisco,Tienda,sirve\n"
        + "b,pisco,licores,2,Ron,Ron,Tienda,a medias\n"
        + "c,pisco,licores,3,Vino,Vino,Tienda,no sirve\n"
        + "d,pisco,licores,4,Otro,Otro,Tienda,\n"  # sin llenar
        + "e,pisco,licores,5,Otro,Otro,Tienda,   \n"  # solo espacios
        + "f,pisco,licores,6,Otro,Otro,Tienda,quizá\n"  # valor que no existe
        + "g,pisco,licores,7,Otro,Otro,Tienda,2\n"  # número en vez de palabra
        + ",pisco,licores,8,Otro,Otro,Tienda,sirve\n",  # sin id
    )
    counts: Counter = Counter()

    judgments = read_search_sheet(path, counts)

    assert judgments == {"a": 2, "b": 1, "c": 0}
    assert counts == {"leidas": 3, "vacias": 2, "invalidas": 3}


def test_read_search_sheet_forgives_case_spaces_accents_in_the_header_and_numbers_style_saves(tmp_path):
    """Excel en español guarda con «;» y sin BOM; Numbers con «,». El valor se escribe a mano: «Sirve », «A MEDIAS»."""
    text = (
        "id;consulta;vertical;posicion;nombre;categoria;tienda;juicio\n"
        "a;pisco;licores;1;Pisco;Pisco;Tienda;  Sirve \n"
        "b;pisco;licores;2;Ron;Ron;Tienda;A MEDIAS\n"
        'c;"pisco; ron";licores;3;Vino;Vino;Tienda;No sirve\n'
    )
    with_bom = _write(tmp_path / "con-bom.csv", text, encoding="utf-8-sig")
    plain = _write(tmp_path / "sin-bom.csv", text)

    expected = {"a": 2, "b": 1, "c": 0}
    assert read_search_sheet(with_bom) == expected
    assert read_search_sheet(plain) == expected


def test_read_search_sheet_ignores_a_repeated_id_with_a_different_answer(tmp_path):
    path = _write(
        tmp_path / "s.csv",
        SEARCH_HEADER + "a,q,v,1,n,c,t,sirve\n" + "a,q,v,1,n,c,t,no sirve\n" + "b,q,v,2,n,c,t,sirve\n",
    )
    counts: Counter = Counter()

    assert read_search_sheet(path, counts) == {"b": 2}  # no se sabe cuál vale: ninguna
    assert counts["invalidas"] == 2


def test_read_search_sheet_of_a_missing_file_says_so(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_search_sheet(tmp_path / "no-existe.csv")


CATEGORY_HEADER = "vertical,categoria,ejemplos,concepto_propuesto,concepto_correcto\n"


def test_read_category_sheet_accepts_concepts_and_ninguno_and_counts_the_rest(tmp_path):
    path = _write(
        tmp_path / "planilla-categorias.csv",
        CATEGORY_HEADER
        + "licores,Cervezas,x | y,cerveza,cerveza\n"
        + "licores,  Pisco ,x,pisco,Pisco\n"  # la clave va sin espacios ni mayúsculas
        + "mall,Velas,x,,ninguno\n"
        + "mall,Vacía,x,pisco,\n"
        + "mall,Inventada,x,pisco,concepto-que-no-existe\n",
    )
    counts: Counter = Counter()

    judgments = read_category_sheet(path, counts)

    assert judgments == {"cervezas": "cerveza", "pisco": "pisco", "velas": "ninguno"}
    assert counts == {"leidas": 3, "vacias": 1, "invalidas": 1}


def _pool():
    """Tres verticales × dos tipos × 10 posiciones × 4 consultas, con algunos pares donde juez y posición discrepan."""
    pool = []
    for vertical in ("licores", "mall", "turbo"):
        for tipo in ("exacta", "necesidad"):
            for q in range(4):
                for pos in range(1, 11):
                    pool.append(
                        {
                            "id": f"{vertical}|{tipo}{q}|catalog_item|{pos}",
                            "vertical": vertical,
                            "consulta": f"{tipo}{q}",
                            "tipo": tipo,
                            "entity_type": "catalog_item",
                            "entity_id": str(pos),
                            "posicion": pos,
                            "relevante_auto": (pos + q) % 4 != 0 if pos <= 3 else q > 0 and pos % 7 == 0,
                        }
                    )
    return pool


def test_sample_covers_every_vertical_type_and_position_stratum():
    sample = sample_search_pairs(_pool(), n=60, seed=7)

    assert len(sample) == 60 and len({p["id"] for p in sample}) == 60
    strata = {(p["vertical"], p["tipo"], p["estrato"]) for p in sample}
    assert len(strata) == 3 * 2 * 2  # los 12 estratos existen y todos están
    assert {p["estrato"] for p in sample} == {"top3", "4-10"}
    assert all((p["estrato"] == "top3") == (p["posicion"] <= 3) for p in sample)
    by_stratum = Counter((p["vertical"], p["tipo"], p["estrato"]) for p in sample)
    assert max(by_stratum.values()) - min(by_stratum.values()) <= 3  # parejo: no manda el estrato más grande


def test_sample_oversamples_where_the_concept_judge_and_the_position_disagree():
    pool = _pool()
    disagrees = {p["id"] for p in pool if (p["posicion"] <= 3) != p["relevante_auto"]}
    pool_share = len(disagrees) / len(pool)

    sample = sample_search_pairs(pool, n=60, seed=7)

    chosen = [p for p in sample if p["discrepa"]]
    assert {p["id"] for p in chosen} <= disagrees
    assert len(chosen) / len(sample) > pool_share
    assert all(p["discrepa"] == (p["id"] in disagrees) for p in sample)


def test_sample_is_stable_with_the_same_seed_and_changes_with_another():
    pool = _pool()
    first = [p["id"] for p in sample_search_pairs(pool, n=60, seed=7)]

    assert first == [p["id"] for p in sample_search_pairs(list(reversed(pool)), n=60, seed=7)]
    assert first != [p["id"] for p in sample_search_pairs(pool, n=60, seed=8)]


def test_sample_of_a_small_pool_takes_everything():
    pool = _pool()[:15]
    assert {p["id"] for p in sample_search_pairs(pool, n=200)} == {p["id"] for p in pool}


def test_versioned_ids_document_has_no_catalog_text():
    """En git van solo ids y estrato: nombres, categorías y tiendas viven en data/ (fuera de git)."""
    sample = sample_search_pairs(_pool(), n=20, seed=7)
    for pair in sample:  # lo que traen los resultados de la búsqueda, que sí es texto del catálogo
        pair.update({"texto": "Pisco Alto del Carmen", "nombre": "Pisco", "categoria": "Pisco", "tienda": "Líder"})

    document = search_ids_document(sample, seed=7)

    # entity_type y entity_id son ids (no texto): el piloto los necesita para que Jev juzgue los mismos pares.
    allowed = {"id", "vertical", "consulta", "tipo", "posicion", "estrato", "relevante_auto", "discrepa"}
    allowed |= {"entity_type", "entity_id"}
    assert document["semilla"] == 7
    assert {key for pair in document["pares"] for key in pair} == allowed
    assert "Pisco Alto" not in json.dumps(document, ensure_ascii=False)


def test_the_sheets_live_in_data_and_the_ids_in_the_package():
    assert sheets.SEARCH_IDS_FILE.parent.name == "eval" and sheets.SEARCH_IDS_FILE.parent.parent.name == "rappi_ia"
    assert sheets.CATEGORY_IDS_FILE.parent == sheets.SEARCH_IDS_FILE.parent
    assert "data" in sheets.sheet_dir().parts and "rappi_ia" not in sheets.sheet_dir().parts


def test_pair_id_is_short_ascii_and_stable():
    first = sheets.pair_id("supermercado", "pañales talla g", "catalog_item", "123")

    assert first == sheets.pair_id("supermercado", "pañales talla g", "catalog_item", "123")
    assert first != sheets.pair_id("supermercado", "pañales talla g", "catalog_item", "124")
    assert first.isascii() and len(first) == 11


def test_eval_human_prints_kappa_from_a_filled_sheet(tmp_path, monkeypatch, capsys):
    from rappi_ia import cli

    sample = sample_search_pairs(_pool(), n=8, seed=7)
    ids_file = tmp_path / "ids.json"
    ids_file.write_text(json.dumps(search_ids_document(sample)), encoding="utf-8")
    rows = [{"id": p["id"], "juicio": "sirve" if p["relevante_auto"] else "no sirve"} for p in sample]
    sheet = tmp_path / sheets.SEARCH_SHEET
    sheets.write_csv(sheet, ["id", "juicio"], rows[:6] + [{"id": rows[6]["id"], "juicio": ""}])
    monkeypatch.setattr(sheets, "SEARCH_IDS_FILE", ids_file)
    monkeypatch.setattr(sheets, "sheet_dir", lambda: tmp_path)
    monkeypatch.setattr("rappi_ia.eval.judgments.JUDGMENTS_FILE", tmp_path / "no-hay.json")

    cli.cmd_eval_human(None, None)

    out = capsys.readouterr().out
    assert "6 de 8" in out  # juzgados: la vacía y la que falta no cuentan
    assert "κ 1.0" in out  # las personas coincidieron con el juez por concepto en todo lo que juzgaron
    assert "2 sin juicio" in out


def test_eval_human_without_any_judgment_says_so(tmp_path, monkeypatch):
    from rappi_ia import cli

    monkeypatch.setattr(sheets, "sheet_dir", lambda: tmp_path)
    monkeypatch.setattr("rappi_ia.eval.judgments.JUDGMENTS_FILE", tmp_path / "no-hay.json")

    with pytest.raises(SystemExit, match="Todavía no hay juicios"):
        cli.cmd_eval_human(None, None)


SEARCH_TEXT = (
    "id;consulta;vertical;posicion;nombre;categoria;tienda;juicio\n"
    "a;pañales;supermercado;1;Pañales Talla G;Pañales;Líder;sirve\n"
    "b;café;supermercado;2;Café molido;Café;Líder;no sirve\n"
)


@pytest.mark.parametrize(
    "encoding",
    ["utf-8", "utf-8-sig", "cp1252", "utf-16", "utf-16-le", "latin-1"],
)
def test_search_sheet_is_read_in_any_encoding_excel_or_numbers_may_save(tmp_path, encoding):
    path = tmp_path / "s.csv"
    data = SEARCH_TEXT.encode(encoding)
    if encoding == "utf-16-le":
        data = b"\xff\xfe" + data  # con BOM, como lo guarda Excel («Texto Unicode»)
    path.write_bytes(data)

    assert read_search_sheet(path) == {"a": 2, "b": 0}


def test_macroman_bytes_do_not_crash_the_reader(tmp_path):
    """«CSV (Macintosh)»: bytes que cp1252 no define (0x81, 0x8d, 0x8f, 0x90, 0x9d). Los textos pueden salir mal,
    pero el id y el juicio (ASCII) se leen y no se cae."""
    path = tmp_path / "s.csv"
    path.write_bytes(SEARCH_TEXT.replace(";", ",").encode("mac_roman") + "x,\x81\x8d\x8f\x90\x9d".encode("latin-1"))

    assert read_search_sheet(path) == {"a": 2, "b": 0}


def test_a_header_only_or_empty_file_reads_as_no_judgments(tmp_path):
    header_only = _write(tmp_path / "h.csv", SEARCH_HEADER)
    empty = _write(tmp_path / "e.csv", "")
    counts: Counter = Counter()

    assert read_search_sheet(header_only, counts) == {} and read_search_sheet(empty, counts) == {}
    assert counts["leidas"] == 0


@pytest.mark.parametrize("form", ["NFC", "NFD"])
@pytest.mark.parametrize("encoding", ["utf-8", "cp1252", "utf-16"])
def test_category_sheet_with_semicolons_accents_and_decomposed_accents(tmp_path, encoding, form):
    import unicodedata

    if form == "NFD" and encoding == "cp1252":
        pytest.skip("cp1252 no puede guardar tildes descompuestas")
    text = unicodedata.normalize(
        form,
        "vertical;categoria;ejemplos;concepto_propuesto;concepto_correcto\n"
        "supermercado;Pañales y Toallitas;x | y;panales;Panales\n"
        "licores;Café;x;;cafe\n",
    )
    path = tmp_path / "c.csv"
    path.write_bytes(text.encode(encoding))

    judgments = read_category_sheet(path)

    assert judgments == {"pañales y toallitas": "panales", "café": "cafe"}  # la clave siempre en NFC


def test_shortfalls_warn_when_a_sheet_has_fewer_rows_than_the_target():
    full = {"pares": 200, "categorias": {"sin_mapear": 40, "juez": 30, "acuerdo": 30}}
    short = {"pares": 150, "categorias": {"sin_mapear": 12, "juez": 30}}

    assert sheets.shortfalls(full) == []
    assert sheets.shortfalls(short) == ["búsqueda: 150 de 200 pares", "sin mapear: 12 de 40", "acuerdo: 0 de 30"]


def test_readme_says_how_to_save_as_utf8():
    text = sheets.readme_text()

    assert "Guarda como CSV UTF-8" in text and "Exportar a" in text and "Desde texto/CSV" in text


def test_eval_human_explains_a_sheet_whose_filled_rows_are_all_invalid(tmp_path, monkeypatch, capsys):
    from rappi_ia import cli

    sample = sample_search_pairs(_pool(), n=4, seed=7)
    ids_file = tmp_path / "ids.json"
    ids_file.write_text(json.dumps(search_ids_document(sample)), encoding="utf-8")
    rows = [{"id": p["id"], "juicio": "quizá"} for p in sample[:3]] + [{"id": sample[3]["id"], "juicio": ""}]
    sheets.write_csv(tmp_path / sheets.SEARCH_SHEET, ["id", "juicio"], rows)
    monkeypatch.setattr(sheets, "SEARCH_IDS_FILE", ids_file)
    monkeypatch.setattr(sheets, "sheet_dir", lambda: tmp_path)
    monkeypatch.setattr("rappi_ia.eval.judgments.JUDGMENTS_FILE", tmp_path / "no-hay.json")

    cli.cmd_eval_human(None, None)  # no se cae ni dice «todavía no hay juicios»

    out = capsys.readouterr().out
    assert "3 inválidas" in out and "1 vacías" in out and "valores permitidos" in out


def test_eval_human_counts_judgments_whose_ids_are_not_in_the_sample(tmp_path, monkeypatch, capsys):
    from rappi_ia import cli

    sample = sample_search_pairs(_pool(), n=4, seed=7)
    ids_file = tmp_path / "ids.json"
    ids_file.write_text(json.dumps(search_ids_document(sample)), encoding="utf-8")
    sheets.write_csv(tmp_path / sheets.SEARCH_SHEET, ["id", "juicio"], [{"id": "otro", "juicio": "sirve"}])
    monkeypatch.setattr(sheets, "SEARCH_IDS_FILE", ids_file)
    monkeypatch.setattr(sheets, "sheet_dir", lambda: tmp_path)
    monkeypatch.setattr("rappi_ia.eval.judgments.JUDGMENTS_FILE", tmp_path / "no-hay.json")

    cli.cmd_eval_human(None, None)

    assert "1 desconocidos" in capsys.readouterr().out
