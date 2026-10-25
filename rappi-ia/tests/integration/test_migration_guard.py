"""`rappi-ia check-migrations`: `make mvp` y `make serve` no migran la base real desde una rama sin fusionar.

`migrate` registra cada migración por el nombre de su archivo: una de rama que se aplica y después se edita nunca se
vuelve a aplicar. Por eso, con migraciones pendientes en la base `rappi` y un código que no está en origin/main, se
niega y dice cómo seguir. El nombre de la base protegida se cambia a la de tests: los tests nunca tocan `rappi`.
"""

import subprocess

import pytest

from rappi_ia import cli
from rappi_ia.demo import doctor
from rappi_ia.demo.doctor import check_pending_migrations, head_is_merged

UNMERGED = lambda: False  # noqa: E731
MERGED = lambda: True  # noqa: E731


@pytest.fixture
def protected(monkeypatch):
    """La base de tests hace el papel de `rappi`."""
    monkeypatch.setattr(doctor, "PROTECTED_DATABASE", "rappi_ia_test")


@pytest.fixture
def pending(db):
    """Las dos últimas migraciones sin aplicar (solo el registro: el esquema queda como está)."""
    names = [row[0] for row in db.execute("SELECT name FROM schema_migrations ORDER BY name DESC LIMIT 2")]
    db.execute("DELETE FROM schema_migrations WHERE name = ANY(%s)", (names,))
    db.commit()
    return sorted(names)


def test_no_pending_migrations_changes_nothing(db, test_url, protected):
    allowed, message = check_pending_migrations(test_url, merged=UNMERGED)

    assert allowed is True
    assert message == ""


def test_refuses_pending_migrations_of_the_real_database_from_an_unmerged_branch(test_url, protected, pending):
    allowed, message = check_pending_migrations(test_url, merged=UNMERGED)

    assert allowed is False
    assert "rappi_ia_test" in message
    for name in pending:
        assert name in message
    assert "createdb -T rappi rappi_staging" in message
    assert "DATABASE_URL=postgresql:///rappi_staging make mvp" in message
    assert "MIGRATE=1" in message


def test_accepts_pending_migrations_when_the_code_is_in_main(test_url, protected, pending):
    allowed, message = check_pending_migrations(test_url, merged=MERGED)

    assert allowed is True
    assert all(name in message for name in pending)  # avisa qué va a aplicar


def test_accepts_when_git_cannot_tell(test_url, protected, pending):
    """Sin repositorio o sin origin/main no hay cómo saber si es una rama: no se frena a quien no la usa."""
    allowed, _ = check_pending_migrations(test_url, merged=lambda: None)

    assert allowed is True


def test_migrate_1_forces_the_migration(test_url, protected, pending):
    allowed, message = check_pending_migrations(test_url, force=True, merged=UNMERGED)

    assert allowed is True
    assert all(name in message for name in pending)


def test_another_database_migrates_without_asking(test_url, pending):
    """rappi_ia_test no es `rappi` (sin la fixture `protected`): una copia como rappi_staging tampoco lo es."""
    allowed, message = check_pending_migrations(test_url, merged=UNMERGED)

    assert allowed is True
    assert "rappi_ia_test" in message


def test_never_writes_to_the_database(db, test_url, protected, pending):
    check_pending_migrations(test_url, merged=UNMERGED)

    applied = {row[0] for row in db.execute("SELECT name FROM schema_migrations")}
    assert not applied & set(pending)


def test_command_exits_1_and_lists_the_pending_migrations(test_url, protected, pending, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", test_url)
    monkeypatch.delenv("MIGRATE", raising=False)
    monkeypatch.setattr(doctor, "head_is_merged", UNMERGED)

    with pytest.raises(SystemExit) as refused:
        cli.main(["check-migrations"])

    assert refused.value.code == 1
    error = capsys.readouterr().err
    assert all(name in error for name in pending)


def test_command_with_migrate_1_goes_ahead(test_url, protected, pending, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", test_url)
    monkeypatch.setenv("MIGRATE", "1")
    monkeypatch.setattr(doctor, "head_is_merged", UNMERGED)

    cli.main(["check-migrations"])  # termina sin SystemExit

    out = capsys.readouterr().out
    assert all(name in out for name in pending)


def test_command_is_silent_when_there_is_nothing_to_migrate(db, test_url, protected, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", test_url)
    monkeypatch.setattr(doctor, "head_is_merged", UNMERGED)

    cli.main(["check-migrations"])

    assert capsys.readouterr().out == ""


def test_command_warns_about_a_migration_edited_after_applying(db, test_url, protected, monkeypatch, capsys):
    """Se registran por nombre: una editada después de aplicarse no se vuelve a correr. El md5 lo deja a la vista."""
    first = db.execute("SELECT min(name) FROM schema_migrations").fetchone()[0]
    db.execute("UPDATE schema_migrations SET checksum = 'otro' WHERE name = %s", (first,))
    db.commit()
    monkeypatch.setenv("DATABASE_URL", test_url)
    monkeypatch.setattr(doctor, "head_is_merged", UNMERGED)

    cli.main(["check-migrations"])  # avisa, pero no frena

    assert f"La migración {first} cambió después de aplicarse" in capsys.readouterr().out


def test_command_explains_unreachable_postgres(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost:1/nada")

    with pytest.raises(SystemExit) as refused:
        cli.main(["check-migrations"])

    assert refused.value.code == 1
    assert "No puedo conectar con Postgres" in capsys.readouterr().err


def git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "uno")
    git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    return tmp_path


def test_head_is_merged_when_it_is_origin_main(repo):
    assert head_is_merged(repo) is True


def test_head_is_not_merged_when_it_has_commits_origin_main_lacks(repo):
    git(repo, "commit", "-q", "--allow-empty", "-m", "dos")

    assert head_is_merged(repo) is False


def test_head_is_merged_when_origin_main_is_ahead(repo):
    git(repo, "commit", "-q", "--allow-empty", "-m", "dos")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "reset", "-q", "--hard", "HEAD~1")

    assert head_is_merged(repo) is True


def test_head_is_unknown_without_origin_main(repo):
    git(repo, "update-ref", "-d", "refs/remotes/origin/main")

    assert head_is_merged(repo) is None


def test_head_is_unknown_outside_a_repository(tmp_path):
    assert head_is_merged(tmp_path) is None
