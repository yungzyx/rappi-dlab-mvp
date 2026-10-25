import psycopg
import pytest

TABLES = (
    *("user_vertical_affinity", "vertical_transitions", "combo_stats", "combo_steps"),
    *("cross_sell_rules", "trends", "replenishment"),
)
EVENT = "INSERT INTO app_events (user_id, session_id, type, source) VALUES ('u1', 's', %s, 'prototype')"
STEP = (
    "INSERT INTO combo_steps (data_source, from_combo, to_combo, users, prob) VALUES (%s, 'rest', 'rest+turbo', 1, 0.5)"
)


def test_motor_tables_and_capa_views_exist(db):
    tables = {r[0] for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    views = dict(
        db.execute(
            """SELECT c.relname, obj_description(c.oid, 'pg_class') FROM pg_class c
               JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'capa' AND c.relkind = 'v'"""
        ).fetchall()
    )
    for name in TABLES:
        assert name in tables, name
        assert views.get(name), f"capa.{name} sin comentario"


def test_vertical_open_is_a_valid_event(db):
    db.execute("INSERT INTO app_users (user_id, source) VALUES ('u1', 'prototype')")
    db.execute(EVENT, ("vertical_open",))
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(EVENT, ("tipo_inventado",))


def test_layer_runs_accepts_motor(db):
    db.execute("INSERT INTO layer_runs (layer, rules_version) VALUES ('motor', 'v1')")
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("INSERT INTO layer_runs (layer, rules_version) VALUES ('otra', 'v1')")
    comment = db.execute(
        """SELECT col_description('capa.layer_runs'::regclass, attnum) FROM pg_attribute
           WHERE attrelid = 'capa.layer_runs'::regclass AND attname = 'layer'"""
    ).fetchone()[0]
    assert "motor" in comment


def test_affinity_rows_go_with_the_person(db):
    db.execute("INSERT INTO app_users (user_id, source) VALUES ('u1', 'prototype')")
    db.execute(
        "INSERT INTO user_vertical_affinity (user_id, vertical, score, orders, signals)"
        " VALUES ('u1', 'turbo', 1.5, 2, 3)"
    )
    db.execute("INSERT INTO concepts (concept_id, name, taxonomy_version) VALUES ('cafe', 'Café', 'v1')")
    db.execute("INSERT INTO replenishment (user_id, concept_id, vertical) VALUES ('u1', 'cafe', 'turbo')")
    db.execute("DELETE FROM app_users WHERE user_id = 'u1'")
    assert db.execute("SELECT count(*) FROM user_vertical_affinity").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM replenishment").fetchone()[0] == 0


def test_personal_capa_views_carry_the_source_and_hide_sensitive_concepts(db):
    db.execute("INSERT INTO app_users (user_id, source) VALUES ('u1', 'prototype'), ('u2', 'synthetic')")
    for user in ("u1", "u2"):
        db.execute(
            "INSERT INTO user_vertical_affinity (user_id, vertical, score, orders, signals)"
            " VALUES (%s, 'turbo', 1, 1, 1)",
            (user,),
        )
    db.execute(
        "INSERT INTO concepts (concept_id, name, taxonomy_version, sensitive)"
        " VALUES ('cafe', 'Café', 'v1', false), ('pañal', 'Pañal', 'v1', true)"
    )
    for concept in ("cafe", "pañal"):
        db.execute("INSERT INTO replenishment (user_id, concept_id, vertical) VALUES ('u1', %s, 'turbo')", (concept,))
    assert dict(db.execute("SELECT user_id, source FROM capa.user_vertical_affinity").fetchall()) == {
        "u1": "prototype",
        "u2": "synthetic",
    }
    assert db.execute("SELECT concept_id, source FROM capa.replenishment").fetchall() == [("cafe", "prototype")]
    for view in ("user_vertical_affinity", "replenishment"):
        comment = db.execute(
            f"""SELECT col_description('capa.{view}'::regclass, attnum) FROM pg_attribute
                WHERE attrelid = 'capa.{view}'::regclass AND attname = 'source'"""
        ).fetchone()[0]
        assert comment, f"capa.{view}.source sin comentario"


def test_population_tables_keep_synthetic_and_prototype_apart(db):
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(STEP, ("mezcla",))
    db.execute(STEP, ("synthetic",))
    db.execute(STEP, ("prototype",))


def test_combo_tables_keep_coarse_and_fine_apart(db):
    """Migración 037: la misma combinación puede estar en los dos niveles; sin nivel, la fila es gruesa."""
    stats = "INSERT INTO combo_stats (data_source, nivel, combo, user_months) VALUES ('synthetic', %s, 'turbo', 1)"
    db.execute(stats, ("grueso",))
    db.execute(stats, ("fino",))
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(stats, ("medio",))
    with pytest.raises(psycopg.errors.UniqueViolation), db.transaction():
        db.execute(stats, ("fino",))
    db.execute(STEP, ("synthetic",))
    db.execute(
        "INSERT INTO combo_steps (data_source, nivel, from_combo, to_combo, users, prob)"
        " VALUES ('synthetic', 'fino', 'rest', 'rest+turbo', 1, 0.5)"
    )
    assert db.execute("SELECT nivel FROM combo_steps ORDER BY nivel").fetchall() == [("fino",), ("grueso",)]
    for view in ("combo_stats", "combo_steps"):
        assert db.execute(f"SELECT count(*) FROM capa.{view} WHERE nivel = 'fino'").fetchone()[0] == 1
        comment = db.execute(
            f"""SELECT col_description('capa.{view}'::regclass, attnum) FROM pg_attribute
                WHERE attrelid = 'capa.{view}'::regclass AND attname = 'nivel'"""
        ).fetchone()[0]
        assert comment and "fino" in comment, f"capa.{view}.nivel sin comentario"
