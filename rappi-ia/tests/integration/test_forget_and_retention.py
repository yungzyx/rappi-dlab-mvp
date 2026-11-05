"""Olvidar, perfil y retención contra `rappi_ia_test` (docs/diseno-ia.md §2)."""

from datetime import UTC, datetime, timedelta

from rappi_ia.analytics import queries
from rappi_ia.concepts.store import seed_taxonomy
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.events import store as events

NOW = datetime(2026, 9, 27, 12, tzinfo=UTC)


def _user_with_beer(db, user="u1"):
    seed_taxonomy(db, load_taxonomy())
    events.record(
        db,
        [
            events.Event(user, "s1", "cart_add", ts=NOW, concept_id="cerveza", cart_id="c1"),
            events.Event(user, "s1", "search", ts=NOW, query="unas chelas bien heladas"),
            events.Event(user, "s1", "search", ts=NOW, concept_id="vino", query="vino tinto"),
        ],
    )
    events.record_order(
        db,
        user,
        "s1",
        "c1",
        "licores",
        [{"entity_type": "catalog_item", "entity_id": "1", "concept_id": "cerveza", "unit_price": 1000}],
    )


def test_a_concept_not_seeded_yet_is_saved_without_concept(db):
    """Un concepto nuevo de taxonomy.toml aún no sembrado en la base (antes de `rappi-ia concepts`) no tumba el
    registro: el evento y la línea se guardan sin concepto, como uno desconocido."""
    seed_taxonomy(db, load_taxonomy())
    db.execute("DELETE FROM concepts WHERE concept_id = 'pollo-preparado'")
    events.record(db, [events.Event("u5", "s1", "chat", ts=NOW, concept_id="pollo-preparado", query="pollo frito")])
    events.record_order(
        db,
        "u5",
        "s1",
        "c1",
        "restaurantes",
        [{"entity_type": "menu_item", "entity_id": "1", "concept_id": "pollo-preparado", "unit_price": 5000}],
    )
    assert db.execute("SELECT concept_id FROM app_events WHERE type = 'chat'").fetchone()[0] is None
    assert db.execute("SELECT concept_id FROM app_order_lines").fetchone()[0] is None


def test_forget_everything_deletes_user_events_and_orders(db):
    _user_with_beer(db)
    assert events.forget(db, "u1") > 0
    for table in ("app_users", "app_events", "app_orders", "app_order_lines"):
        assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table


def test_forget_one_concept_removes_it_everywhere_but_keeps_the_rest(db):
    _user_with_beer(db)
    events.forget(db, "u1", "cerveza")
    assert db.execute("SELECT count(*) FROM app_events WHERE concept_id = 'cerveza'").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM app_order_lines WHERE concept_id = 'cerveza'").fetchone()[0] == 0
    queries_left = [r[0] for r in db.execute("SELECT query FROM app_events WHERE query IS NOT NULL")]
    assert queries_left == ["vino tinto"]  # "chelas" nombraba cerveza: se borró el texto
    assert list(events.profile(db, "u1", now=NOW)) == ["vino"]


def test_forget_a_concept_erases_queries_that_name_it_with_query_only_words(db):
    """ "lubricante" no asigna productos, pero en una consulta pide bienestar sexual: olvidarlo borra la consulta."""
    seed_taxonomy(db, load_taxonomy())
    events.record(db, [events.Event("u4", "s1", "search", ts=NOW, query="lubricante")])
    events.forget(db, "u4", "bienestar-sexual")
    assert db.execute("SELECT count(*) FROM app_events WHERE query IS NOT NULL").fetchone()[0] == 0


def test_profile_learns_only_from_positive_signals(db):
    seed_taxonomy(db, load_taxonomy())
    events.record(
        db,
        [
            events.Event("u2", "s1", "suggestion_shown", ts=NOW, concept_id="cerveza"),
            events.Event("u2", "s1", "suggestion_dismissed", ts=NOW, concept_id="cerveza"),
            events.Event("u2", "s1", "cart_remove", ts=NOW, concept_id="vino"),
            events.Event("u2", "s1", "search", ts=NOW, concept_id="medicamentos", query="paracetamol"),
            events.Event("u2", "s1", "search", ts=NOW, concept_id="pizza", query="pizza"),
        ],
    )
    assert list(events.profile(db, "u2", now=NOW)) == ["pizza"]


def test_old_query_text_is_purged_after_retention(db):
    seed_taxonomy(db, load_taxonomy())
    old = datetime.now(UTC) - timedelta(days=events.QUERY_RETENTION_DAYS + 1)
    events.record(
        db,
        [
            events.Event("u3", "s1", "search", ts=old, concept_id="pizza", query="pizza vieja"),
            events.Event("u3", "s2", "search", concept_id="pizza", query="pizza nueva"),
        ],
    )
    assert events.purge_old_queries(db) == 1
    assert [r[0] for r in db.execute("SELECT query FROM app_events ORDER BY ts")] == [None, "pizza nueva"]
    assert db.execute("SELECT count(*) FROM app_events WHERE concept_id = 'pizza'").fetchone()[0] == 2


def test_the_corrected_text_is_redacted_like_the_query(db):
    """`corregida` deja tal cual lo que no corrige (un teléfono): se redacta al guardar, sin tocar el del llamador."""
    seed_taxonomy(db, load_taxonomy())
    payload = {"corregida": "llamar 912345678 paracetamol"}
    events.record(
        db, [events.Event("u6", "s1", "search", ts=NOW, query="llamar 912345678 paracetamool", payload=payload)]
    )
    saved = db.execute("SELECT query, payload->>'corregida' FROM app_events").fetchone()
    assert saved == ("llamar [teléfono] paracetamool", "llamar [teléfono] paracetamol")
    assert payload == {"corregida": "llamar 912345678 paracetamol"}


def test_old_corrected_text_is_purged_with_the_query(db):
    seed_taxonomy(db, load_taxonomy())
    old = datetime.now(UTC) - timedelta(days=100)
    events.record(
        db,
        [
            events.Event("u7", "s1", "search", ts=old, query="cervesa", payload={"corregida": "cerveza", "mode": "x"}),
            events.Event("u7", "s2", "ask", ts=old, payload={"corregida": "cerveza"}),  # sin texto: solo la corregida
            events.Event("u7", "s3", "search", query="cervesa", payload={"corregida": "cerveza"}),
        ],
    )
    assert events.purge_old_queries(db) == 2
    rows = db.execute("SELECT query, payload FROM app_events ORDER BY ts, session_id").fetchall()
    assert rows == [(None, {"mode": "x"}), (None, {}), ("cervesa", {"corregida": "cerveza"})]


def test_forget_a_concept_erases_its_corrected_text_too(db):
    """ "test de embaraso" no nombra el concepto, su corrección sí: olvidar salud-sexual borra los dos textos."""
    seed_taxonomy(db, load_taxonomy())
    events.record(
        db,
        [
            events.Event(
                "u8", "s1", "search", ts=NOW, query="test de embaraso", payload={"corregida": "test de embarazo"}
            ),
            events.Event("u8", "s1", "search", ts=NOW, query="pizzza", payload={"corregida": "pizza"}),
        ],
    )
    events.forget(db, "u8", "salud-sexual")
    rows = db.execute("SELECT query, payload FROM app_events ORDER BY query NULLS FIRST").fetchall()
    assert rows == [(None, {}), ("pizzza", {"corregida": "pizza"})]


def test_every_person_table_goes_away_with_forget(db):
    """ "Olvidar" (y la purga de inactivos) borra solo a la persona y deja el resto a las cascadas: toda FK hacia sus
    tablas tiene ON DELETE CASCADE y toda tabla con `user_id` cuelga de `app_users`."""
    fks = db.execute(
        """SELECT conrelid::regclass::text, confrelid::regclass::text, confdeltype FROM pg_constraint
           WHERE contype = 'f' AND confrelid IN ('app_users'::regclass, 'app_events'::regclass,
                                                 'app_orders'::regclass, 'app_sessions'::regclass)"""
    ).fetchall()
    assert fks
    for table, target, action in fks:
        assert action == "c", f"{table} apunta a {target} sin ON DELETE CASCADE: Olvidar la dejaría con datos"
    with_user = [
        r[0]
        for r in db.execute(
            """SELECT c.table_name FROM information_schema.columns c
               JOIN information_schema.tables t USING (table_schema, table_name)
               WHERE c.table_schema = 'public' AND c.column_name = 'user_id' AND t.table_type = 'BASE TABLE'
                 AND c.table_name <> 'app_users'"""
        )
    ]
    assert with_user
    pointing_at_users = {table for table, target, _ in fks if target == "app_users"}
    for table in with_user:
        assert table in pointing_at_users, f"{table} tiene user_id sin FK a app_users: Olvidar la dejaría con datos"


def test_opportunities_never_list_sensitive_concepts(db):
    seed_taxonomy(db, load_taxonomy())
    rows = []
    for i in range(6):
        rows += [
            events.Event(
                f"p{i}", "s", "search", ts=NOW, vertical="supermercado", concept_id="salud-sexual", unmet=True
            ),
            events.Event(f"p{i}", "s", "search", ts=NOW, vertical="restaurantes", concept_id="peruana", unmet=True),
        ]
    events.record(db, rows)
    found = {r["concept_id"] for r in queries.opportunities(db, "prototype")}
    assert found == {"peruana"}


def test_forget_everything_also_deletes_the_users_segments_and_history(db):
    from rappi_ia.layers.segments import build_segments

    _user_with_beer(db)
    for i in range(4):  # cerveza ×4: suficiente para `cervecero`
        events.record(db, [events.Event("u1", f"s{i}", "cart_add", ts=NOW - timedelta(days=i), concept_id="cerveza")])
    build_segments(db, "prototype", now=NOW)
    assert db.execute("SELECT count(*) FROM user_segments WHERE user_id = 'u1'").fetchone()[0] > 0

    events.forget(db, "u1")

    for table in ("user_segments", "user_segment_history"):
        assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table


def test_forget_one_concept_recalculates_the_users_segments(db):
    from rappi_ia.layers.segments import build_segments

    _user_with_beer(db)
    for i in range(4):
        events.record(db, [events.Event("u1", f"s{i}", "cart_add", ts=NOW - timedelta(days=i), concept_id="cerveza")])
    build_segments(db, "prototype", now=NOW)
    before = {r[0] for r in db.execute("SELECT segment_id FROM user_segments WHERE user_id = 'u1'")}
    assert "cervecero" in before

    events.forget(db, "u1", "cerveza")

    after = {r[0] for r in db.execute("SELECT segment_id FROM user_segments WHERE user_id = 'u1'")}
    assert "cervecero" not in after
