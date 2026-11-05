"""`rappi-ia olvidar` contra `rappi_ia_test`: borrar por id a las personas de una prueba con usuarios, como "Borrar mis
datos" de la app (DELETE /profile/{id}; guion en docs/prueba-usuarios.md §6). Nunca a una simulada."""

from datetime import UTC, datetime

import pytest

from rappi_ia import cli
from rappi_ia.concepts.store import seed_taxonomy
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.events import store as events

NOW = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)
ONCE = events.SessionInfo(app_version="1.0.0", platform="web", mode="propuesta", entry="directa")
LINE = {"entity_type": "catalog_item", "entity_id": "1", "concept_id": "cerveza", "unit_price": 2190}


def _person(db, user, source="prototype"):
    events.ensure_user(db, user, source)
    events.record(
        db,
        [
            events.Event(user, "s1", "search", ts=NOW, query="cervesa", results=5),
            events.Event(user, "s1", "cart_add", ts=NOW, concept_id="cerveza", vertical="licores", cart_id="c1"),
        ],
        source=source,
        session=ONCE if source == "prototype" else None,
    )
    events.record_order(db, user, "s1", f"c-{user}", "licores", [LINE], source=source, ts=NOW)


@pytest.fixture
def seeded(db, test_url, monkeypatch):
    seed_taxonomy(db, load_taxonomy())
    _person(db, "proto-aaaa")
    _person(db, "proto-bbbb")
    _person(db, "syn-0001", "synthetic")
    db.commit()
    monkeypatch.setenv("DATABASE_URL", test_url)  # el comando abre su conexión: a la base de los tests
    return db


def _users(db) -> list[str]:
    db.rollback()  # ver lo que confirmó el comando
    return sorted(row[0] for row in db.execute("SELECT user_id FROM app_users"))


def test_forget_by_id_deletes_the_person_and_says_what(seeded, capsys):
    cli.main(["olvidar", "proto-aaaa", "--si"])

    out = capsys.readouterr().out
    # Dos eventos y el `order_placed` del pedido.
    assert "proto-aaaa: 3 evento(s), 1 pedido(s) y 1 sesión(es)" in out
    assert "proto-aaaa: borrada con 3 evento(s), 1 pedido(s) y 1 sesión(es)" in out
    assert _users(seeded) == ["proto-bbbb", "syn-0001"]
    for table in ("app_events", "app_orders", "app_sessions"):
        left = seeded.execute(f"SELECT count(*) FROM {table} WHERE user_id = 'proto-aaaa'").fetchone()[0]
        assert left == 0, table


def test_a_synthetic_or_unknown_id_deletes_nobody(seeded):
    """Si un id no es del prototipo (simulado o inexistente), no borra a ninguna, tampoco a las que sí lo son."""
    with pytest.raises(SystemExit, match="No son personas del prototipo .*: syn-0001, nadie. No se borró a nadie."):
        cli.main(["olvidar", "proto-aaaa", "syn-0001", "nadie", "--si"])
    assert _users(seeded) == ["proto-aaaa", "proto-bbbb", "syn-0001"]


def test_it_asks_before_deleting(seeded, monkeypatch, capsys):
    """Sin --si pregunta: cualquier cosa que no sea "s" (o no poder preguntar) no borra; "s" borra a las dos."""
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    with pytest.raises(SystemExit, match="No se borró a nadie"):
        cli.main(["olvidar", "proto-aaaa", "proto-bbbb"])
    assert _users(seeded) == ["proto-aaaa", "proto-bbbb", "syn-0001"]

    def no_terminal(prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", no_terminal)
    with pytest.raises(SystemExit, match="No se borró a nadie"):
        cli.main(["olvidar", "proto-aaaa"])
    assert _users(seeded) == ["proto-aaaa", "proto-bbbb", "syn-0001"]

    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "s")
    cli.main(["olvidar", "proto-aaaa", "proto-bbbb"])
    assert prompts == ["¿Borrar a estas 2 personas? [s/N] "]
    assert _users(seeded) == ["syn-0001"]
