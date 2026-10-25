"""La precarga de los índices de la búsqueda (migración 034 y `api/prewarm.py`) contra `rappi_ia_test`: lee los HNSW y
los de texto sin tildes, del más usado al menos usado; sin la extensión, sin permiso o con el tope de tiempo cumplido
solo deja un aviso. La migración no falla en un rol que no puede crear la extensión (en producción migra rappi_owner) y
el rol de la API la puede usar con los permisos de deploy/db/grants.sql."""

import logging

import psycopg
import pytest
from psycopg import errors, sql
from rappi_scraper.storage.db import MIGRATIONS_DIR

from rappi_ia import cli
from rappi_ia.api import prewarm
from rappi_ia.db import connect
from rappi_ia.demo.seed import seed_demo
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents

MIGRATION = MIGRATIONS_DIR / "034_prewarm.sql"


@pytest.fixture
def searchable(db):
    """El catálogo de prueba con sus vectores y un HNSW por vertical."""
    seed_demo(db)
    embed_search_documents(db, HashEmbedder())
    db.commit()
    return db


def _search_indexes(conn) -> dict[str, str]:
    """Nombre → método de los índices de las particiones de search_documents."""
    return dict(
        conn.execute(
            """SELECT c.relname, am.amname
               FROM pg_inherits p
               JOIN pg_index i ON i.indrelid = p.inhrelid
               JOIN pg_class c ON c.oid = i.indexrelid
               JOIN pg_am am ON am.oid = c.relam
               WHERE p.inhparent = 'search_documents'::regclass"""
        ).fetchall()
    )


def test_prewarm_reads_the_hnsw_and_unaccented_text_indexes(searchable, test_url, caplog):
    with caplog.at_level(logging.INFO, logger="rappi_ia.api.prewarm"):
        done = prewarm.prewarm_search_indexes(test_url)

    indexes = _search_indexes(searchable)
    expected = {n for n, am in indexes.items() if am == "hnsw" or (am == "gin" and n.endswith("_tsv_unaccent_idx"))}
    assert set(done) == expected
    assert len(done) == len(expected) == 16  # 8 verticales × (HNSW + tsv_unaccent); ni el tsv con tildes ni la llave
    assert "Precarga" in caplog.text and "WARNING" not in caplog.text


def test_prewarm_goes_from_the_most_used_index_to_the_least(searchable, test_url):
    with connect(test_url) as other:
        other.execute("SET enable_seqscan = off")
        for _ in range(30):  # el índice de texto de farmacia, el más usado
            other.execute("SELECT count(*) FROM search_documents_farmacia WHERE tsv_unaccent @@ 'paracetamol'")
        other.execute("SELECT pg_stat_force_next_flush()")
        other.commit()  # las estadísticas pendientes se publican al quedar libre la sesión

    done = prewarm.prewarm_search_indexes(test_url)

    assert done[0] == "search_documents_farmacia_tsv_unaccent_idx"
    used = dict(
        searchable.execute(
            "SELECT indexrelname, idx_scan FROM pg_stat_user_indexes WHERE indexrelname = ANY(%s)", (done,)
        ).fetchall()
    )
    assert [used[name] for name in done] == sorted(used.values(), reverse=True)


def test_prewarm_without_the_extension_only_warns(searchable, test_url, caplog):
    searchable.execute("DROP EXTENSION pg_prewarm")
    searchable.commit()

    with caplog.at_level(logging.WARNING, logger="rappi_ia.api.prewarm"):
        assert prewarm.prewarm_search_indexes(test_url) == []

    assert "falta la extensión pg_prewarm" in caplog.text


def test_prewarm_without_permission_only_warns(searchable, test_url, monkeypatch, caplog):
    """Simulado: el rol no puede leer los índices (lo que daría una versión de Postgres sin el arreglo de permisos de
    pg_prewarm sobre índices)."""
    real_connect = psycopg.connect

    class Refusing:
        def __init__(self, conn):
            self._conn = conn

        def execute(self, query, *args, **kwargs):
            if "pg_prewarm(" in str(query):
                raise errors.InsufficientPrivilege("permission denied for index search_documents_x")
            return self._conn.execute(query, *args, **kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return self._conn.__exit__(*exc)

    monkeypatch.setattr(prewarm.psycopg, "connect", lambda *a, **kw: Refusing(real_connect(*a, **kw)))

    with caplog.at_level(logging.WARNING, logger="rappi_ia.api.prewarm"):
        assert prewarm.prewarm_search_indexes(test_url) == []

    assert "No se pudo precargar" in caplog.text and "permission denied" in caplog.text


def test_the_time_budget_also_caps_the_first_queries(searchable, test_url, monkeypatch):
    """El tope de tiempo rige desde que conecta: también para revisar la extensión y listar los índices."""
    real_connect = psycopg.connect
    statements = []

    class Recording:
        def __init__(self, conn):
            self._conn = conn

        def execute(self, query, *args, **kwargs):
            statements.append(str(query))
            return self._conn.execute(query, *args, **kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return self._conn.__exit__(*exc)

    monkeypatch.setattr(prewarm.psycopg, "connect", lambda *a, **kw: Recording(real_connect(*a, **kw)))

    assert prewarm.prewarm_search_indexes(test_url)
    assert "statement_timeout" in statements[0]


def test_prewarm_stops_at_its_time_budget(searchable, test_url, caplog):
    with caplog.at_level(logging.WARNING, logger="rappi_ia.api.prewarm"):
        assert prewarm.prewarm_search_indexes(test_url, budget_s=0) == []

    assert "tope" in caplog.text


def test_migration_034_does_not_fail_without_permission_to_create_the_extension(db):
    """En producción migra rappi_owner, que no es superusuario: la extensión la crea init-roles.sh y, si falta, la
    migración solo avisa. Todo en una transacción que se deshace (el rol también)."""
    db.execute("DROP EXTENSION pg_prewarm")
    db.execute("CREATE ROLE migra_sin_superusuario")
    db.execute("GRANT USAGE, CREATE ON SCHEMA public TO migra_sin_superusuario")
    db.execute("SET LOCAL ROLE migra_sin_superusuario")

    db.execute(MIGRATION.read_text(encoding="utf-8"))

    assert db.execute("SELECT count(*) FROM pg_extension WHERE extname = 'pg_prewarm'").fetchone()[0] == 0
    db.rollback()


def test_migration_034_does_not_fail_on_a_postgres_without_the_extension(db):
    """Un Postgres sin contrib no tiene pg_prewarm (undefined_file): la migración solo avisa, como sin permiso. Se
    simula con una extensión que no existe."""
    missing = MIGRATION.read_text(encoding="utf-8").replace("pg_prewarm", "pg_prewarm_que_no_existe")

    db.execute(missing)

    assert db.execute("SELECT count(*) FROM pg_extension WHERE extname = 'pg_prewarm_que_no_existe'").fetchone()[0] == 0
    db.rollback()


def test_migration_034_creates_the_extension(db):
    assert db.execute("SELECT count(*) FROM pg_extension WHERE extname = 'pg_prewarm'").fetchone()[0] == 1


def test_api_role_can_prewarm_with_the_grants_file(searchable):
    """Con los permisos de deploy/db/grants.sql (SELECT sobre las tablas), el rol de la API puede precargar los índices:
    pg_prewarm revisa SELECT sobre la tabla del índice y su EXECUTE es de PUBLIC. No hace falta otro GRANT."""
    conn = searchable
    indexes = [n for n, am in _search_indexes(conn).items() if am in ("hnsw", "gin")]
    role = "rappi_api_precarga"
    for name in ("rappi_owner", role):  # rappi_owner: el dueño de ALTER DEFAULT PRIVILEGES (en el servidor ya existe)
        if conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,)).fetchone() is None:
            conn.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(name)))
    conn.execute(sql.SQL(cli.GRANTS_FILE.read_text(encoding="utf-8")).format(api_role=sql.Identifier(role)))
    conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))

    for index in indexes:
        assert conn.execute("SELECT pg_prewarm(%s::regclass, 'read')", (index,)).fetchone()[0] > 0
    conn.rollback()
