"""`rappi-ia dump-entrega` contra `rappi_ia_test`: la entrega lleva la población simulada y nada de las personas del
prototipo, y se niega si aparece una tabla de personas que no sabe filtrar."""

import re
import subprocess
from pathlib import Path

import pytest
from psycopg.types.json import Jsonb
from rappi_scraper.storage.backup import find_pg_dump

from rappi_ia import delivery

SYNTH, PROTO = "u-simulada-1", "proto-0123456789abcdef"


def _people(db) -> None:
    """Una persona simulada y una del prototipo, cada una con lo suyo en las tablas de personas."""
    db.execute(
        "INSERT INTO segment_defs (segment_id, name, family, sensitive, description, rule, rules_version) "
        "VALUES ('prueba', 'Prueba', 'prueba', false, 'x', '{}', 'v1')"
    )
    for user, source in ((SYNTH, "synthetic"), (PROTO, "prototype")):
        db.execute("INSERT INTO app_users (user_id, source) VALUES (%s, %s)", (user, source))
        db.execute(
            "INSERT INTO app_events (user_id, session_id, type, query, source) VALUES (%s, 's', 'search', %s, %s)",
            (user, f"pañales para {user}", source),
        )
        db.execute(
            "INSERT INTO app_orders (order_id, user_id, ts, vertical, total, source) VALUES (%s, %s, now(), "
            "'supermercado', 1000, %s)",
            (f"o-{user}", user, source),
        )
        db.execute(
            "INSERT INTO app_order_lines (order_id, line_no, entity_type, entity_id, qty, unit_price) "
            "VALUES (%s, 1, 'catalog_item', '1', 1, 1000)",
            (f"o-{user}",),
        )
        db.execute(
            "INSERT INTO user_segments (user_id, segment_id, score, level, signals) "
            "VALUES (%s, 'prueba', 1, 'alto', 1)",
            (user,),
        )
        db.execute(
            "INSERT INTO vertical_transitions (data_source, from_vertical, to_vertical, n, prob) "
            "VALUES (%s, 'supermercado', 'farmacia', 1, 1)",
            (source,),
        )
        db.execute(
            "INSERT INTO layer_runs (layer, rules_version, counts) VALUES ('motor', 'v1', %s)",
            (Jsonb({"fuente": source, "pedidos": 1}),),
        )


def test_the_current_schema_has_no_unknown_person_tables(db):
    """Si una migración suma una tabla con `user_id`, `session_id` o `data_source`, o que apunta a una de personas, va
    en PERSON_TABLES."""
    assert delivery.unknown_person_tables(db) == []
    db.execute("CREATE TABLE public.notas_de_personas (user_id text)")
    db.execute("CREATE TABLE public.lineas_extra (order_id text REFERENCES app_orders)")
    assert delivery.unknown_person_tables(db) == ["public.lineas_extra", "public.notas_de_personas"]


def test_the_population_file_has_only_the_simulated_people(db, tmp_path):
    _people(db)
    path = tmp_path / delivery.POPULATION_FILE

    counts = delivery._write_population(db, path, "rappi_ia_test")

    text = path.read_text(encoding="utf-8")
    assert SYNTH in text and f"pañales para {SYNTH}" in text
    assert PROTO not in text and "prototype" not in text
    assert counts["app_users"] == counts["app_events"] == counts["app_order_lines"] == 1
    assert counts["vertical_transitions"] == counts["layer_runs"] == 1
    assert delivery._excluded(db)["app_users"] == delivery._excluded(db)["layer_runs"] == 1


def _pg_tools(db) -> tuple[str, str, str] | None:
    """pg_dump, pg_restore y psql de esta máquina, si sirven para la versión del servidor (en el CI, el cliente puede
    ser más viejo que el Postgres de la imagen)."""
    try:
        pg_dump = find_pg_dump()
    except RuntimeError:
        return None
    version = subprocess.run([pg_dump, "--version"], capture_output=True, text=True).stdout  # «pg_dump (…) 17.11 …»
    major = int(re.search(r"\) (\d+)", version).group(1))
    pg_restore, psql = (str(Path(pg_dump).with_name(name)) for name in ("pg_restore", "psql"))
    if major < db.info.server_version // 10000 or not Path(psql).exists():
        return None
    return pg_dump, pg_restore, psql


def test_the_delivery_restores_without_the_prototype(db, test_url, tmp_path):
    """De punta a punta: el volcado trae el catálogo y las tablas de personas vacías, y el SQL las llena solo con los
    simulados. Restaurado (sobre la misma rappi_ia_test, vaciada), no queda nadie del prototipo."""
    tools = _pg_tools(db)
    if tools is None:
        pytest.skip("pg_dump, pg_restore o psql de esta máquina no sirven para esta versión de Postgres")
    _, pg_restore, psql = tools
    _people(db)
    db.execute("INSERT INTO stores (store_id, name) VALUES (1, 'Tienda de prueba')")
    db.commit()

    target = delivery.build_delivery(test_url, tmp_path)

    files = sorted(p.name for p in target.iterdir())
    assert files == sorted([delivery.README_FILE, delivery.DUMP_FILE, delivery.POPULATION_FILE])
    assert not list(tmp_path.glob("*.part"))
    db.execute("DROP SCHEMA capa CASCADE")
    db.execute("DROP SCHEMA public CASCADE")
    db.execute("CREATE SCHEMA public")
    db.commit()
    # Los tres pasos del LEEME: tablas y catálogo, población, y al final índices, claves foráneas y triggers.
    restore = [pg_restore, "--no-owner", "--no-privileges", "--exit-on-error", f"--dbname={test_url}"]
    dump = str(target / delivery.DUMP_FILE)
    subprocess.run([*restore, "--section=pre-data", "--section=data", dump], check=True)
    assert db.execute("SELECT count(*) FROM app_users").fetchone()[0] == 0  # el volcado solo trae la tabla
    db.rollback()  # sin una transacción abierta: las claves foráneas de post-data esperarían por ella
    subprocess.run([psql, "--quiet", f"--dbname={test_url}", f"--file={target / delivery.POPULATION_FILE}"], check=True)
    subprocess.run([*restore, "--section=post-data", dump], check=True)

    assert db.execute("SELECT array_agg(user_id) FROM app_users").fetchone()[0] == [SYNTH]
    assert db.execute("SELECT count(*), max(query) FROM app_events").fetchone() == (1, f"pañales para {SYNTH}")
    assert db.execute("SELECT array_agg(data_source) FROM vertical_transitions").fetchone()[0] == ["synthetic"]
    assert db.execute("SELECT array_agg(counts->>'fuente') FROM layer_runs").fetchone()[0] == ["synthetic"]
    assert db.execute("SELECT count(*) FROM pg_constraint WHERE conname = 'app_events_user_id_fkey'").fetchone()[0] == 1
    assert db.execute("SELECT name FROM stores").fetchone()[0] == "Tienda de prueba"
    assert "personas: 1, eventos: 1, pedidos: 1" in (target / delivery.README_FILE).read_text(encoding="utf-8")
