"""`refresh`: retoma corridas abiertas o crea nuevas, y deja búsqueda, reportes y respaldo."""

from argparse import Namespace
from contextlib import nullcontext

import pytest

from conftest import FakeClient
from rappi_scraper import cli
from rappi_scraper.pipeline.queue import PossibleBlock
from rappi_scraper.pipeline.refresh import refresh
from rappi_scraper.scraping.client import RobotsDisallowed
from rappi_scraper.storage import repository
from rappi_scraper.storage.db import PendingMigrations, connect, database_url

STORE_JOB = {
    "job_key": "type:lider",
    "job_type": "store_group",
    "payload": {
        "verticals": ["supermercado"],
        "candidates": [
            {"store_id": 1, "path": "/tiendas/900025946-lider", "city": "Santiago", "lat": -33.4, "lng": -70.6}
        ],
    },
}
RESTAURANT_JOB = {
    "job_key": "rest:384",
    "job_type": "restaurant",
    "payload": {"verticals": ["restaurantes"], "candidates": [{"store_id": 384, "path": "/restaurantes/384"}]},
}


def _discoverer(job, calls):
    def discover(conn, run_id):
        calls.append(run_id)
        repository.add_jobs(conn, run_id, [job])
        return 1

    return discover


def _no_discovery(conn, run_id):
    raise AssertionError("no debería descubrir: había una corrida abierta")


def test_refresh_resumes_open_runs_without_rediscovering(db, tmp_path):
    stores_run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, stores_run, [STORE_JOB])
    restaurants_run = repository.start_run(db, "restaurants", {})
    repository.add_jobs(db, restaurants_run, [RESTAURANT_JOB])
    client = FakeClient({"/restaurantes/384": "restaurant"})
    backups = []

    reports, backup_failed = refresh(
        db, client, _no_discovery, _no_discovery, backup=lambda: backups.append("ok"), reports_dir=tmp_path
    )

    assert [r["kind"] for r in reports] == ["stores", "restaurants"]
    assert [r["status"] for r in reports] == ["done", "done"]
    assert {p.name for p in tmp_path.iterdir()} == {
        f"run_{stores_run}_stores.md",
        f"run_{restaurants_run}_restaurants.md",
    }
    assert db.execute("SELECT count(*) FROM search_documents").fetchone()[0] > 0
    assert backups == ["ok"] and not backup_failed


def test_refresh_starts_new_runs_and_discovers_when_none_open(db, tmp_path):
    store_calls, restaurant_calls = [], []
    client = FakeClient({"/restaurantes/384": "restaurant"})

    reports, _ = refresh(
        db,
        client,
        _discoverer(STORE_JOB, store_calls),
        _discoverer(RESTAURANT_JOB, restaurant_calls),
        reports_dir=tmp_path,
    )

    assert len(store_calls) == 1 and len(restaurant_calls) == 1
    assert all(r["jobs"] == {"done": 1} for r in reports)
    params = db.execute("SELECT DISTINCT params->>'trigger' FROM scrape_runs").fetchall()
    assert params == [("refresh",)]


def test_failed_discovery_closes_the_run_so_the_next_refresh_discovers_again(db, tmp_path):
    """Si rappi.cl no responde al descubrir (p. ej. sin red al despertar), la corrida no queda "en curso"."""

    def offline(conn, run_id):
        raise RuntimeError("sin red")

    with pytest.raises(RuntimeError):
        refresh(db, FakeClient(), offline, _no_discovery, reports_dir=tmp_path)
    assert db.execute("SELECT kind, status FROM scrape_runs").fetchall() == [("stores", "failed")]

    calls = []
    refresh(
        db,
        FakeClient({"/restaurantes/384": "restaurant"}),
        _discoverer(STORE_JOB, calls),
        _discoverer(RESTAURANT_JOB, []),
        reports_dir=tmp_path,
    )
    assert len(calls) == 1  # corrida nueva, con descubrimiento


def test_refresh_stops_on_a_block_and_leaves_the_run_open(db, tmp_path):
    """Ante un 403 permanente no sigue job por job: para, deja el reporte y la corrida abierta para retomarla."""
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [{**STORE_JOB, "job_key": f"type:{i:02}"} for i in range(15)])
    client = FakeClient(blocked=True)
    backups = []

    with pytest.raises(PossibleBlock, match="10 fallos consecutivos"):
        refresh(db, client, _no_discovery, _no_discovery, backup=lambda: backups.append("ok"), reports_dir=tmp_path)

    assert len(client.requested) == 10
    # Los 10 que fallaron por el bloqueo vuelven a la cola: la próxima actualización los intenta de nuevo.
    assert db.execute("SELECT status, count(*) FROM scrape_jobs GROUP BY 1").fetchall() == [("pending", 15)]
    assert repository.open_run(db, "stores") == run
    assert "posible bloqueo" in (tmp_path / f"run_{run}_stores.md").read_text(encoding="utf-8")
    assert backups == [] and repository.latest_run(db, "restaurants") is None


def test_a_failed_backup_does_not_stop_the_weekly_update(db, tmp_path, caplog):
    """Sin respaldo nuevo quedan los anteriores; la capa de IA (post-refresh) igual debe correr. Pero el fallo se
    informa: si solo quedara en el log, la tarea semanal anotaría «exit=0» semana tras semana."""

    def broken_backup():
        raise RuntimeError("pg_dump: disco lleno")

    reports, backup_failed = refresh(
        db,
        FakeClient({"/restaurantes/384": "restaurant"}),
        _discoverer(STORE_JOB, []),
        _discoverer(RESTAURANT_JOB, []),
        backup=broken_backup,
        reports_dir=tmp_path,
    )

    assert [r["status"] for r in reports] == ["done", "done"]
    assert db.execute("SELECT count(*) FROM search_documents").fetchone()[0] > 0
    assert backup_failed
    assert "Respaldo fallido" in caplog.text


def test_an_interrupted_refresh_resumes_restaurants_without_scraping_stores_again(db, tmp_path):
    """Un apagado a mitad de los restaurantes: las tiendas de ese ciclo ya terminaron y no se vuelven a bajar."""
    stores_run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, stores_run, [STORE_JOB])
    repository.mark_job(db, stores_run, STORE_JOB["job_key"], "done", {"store_type": "lider"})
    repository.finish_run(db, stores_run)
    restaurants_run = repository.start_run(db, "restaurants", {})
    repository.add_jobs(db, restaurants_run, [RESTAURANT_JOB])
    client = FakeClient({"/restaurantes/384": "restaurant"})

    reports, _ = refresh(db, client, _no_discovery, _no_discovery, reports_dir=tmp_path)

    assert [(r["kind"], r["run_id"], r["status"]) for r in reports] == [("restaurants", restaurants_run, "done")]
    assert client.requested == ["/restaurantes/384"]
    assert repository.latest_run(db, "stores") == stores_run  # ninguna corrida de tiendas nueva


def test_resuming_after_retry_failed_does_not_start_new_runs(db, tmp_path):
    """`retry-failed` reabrió las tiendas y no los restaurantes (reencoló 0): retomar no vuelve a bajar los ~4.900
    restaurantes (unas 5,5 h) en una corrida nueva."""
    stores_run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, stores_run, [STORE_JOB])
    restaurants_run = repository.start_run(db, "restaurants", {})
    repository.add_jobs(db, restaurants_run, [RESTAURANT_JOB])
    repository.mark_job(db, restaurants_run, RESTAURANT_JOB["job_key"], "done", {})
    repository.finish_run(db, restaurants_run)
    client = FakeClient()

    reports, _ = refresh(db, client, _no_discovery, _no_discovery, reports_dir=tmp_path, resume_only=True)

    assert [(r["kind"], r["run_id"], r["status"]) for r in reports] == [("stores", stores_run, "done")]
    assert all(path.startswith("/tiendas/") for path in client.requested)
    assert repository.latest_run(db, "restaurants") == restaurants_run


def test_resuming_commits_the_search_documents_before_the_backup(db, tmp_path):
    """`pg_dump` corre en otra conexión: tiene que ver los documentos nuevos. Y si el respaldo falla (exit 3, que
    deshace lo pendiente de la conexión), los documentos ya quedaron guardados."""
    stores_run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, stores_run, [STORE_JOB])
    restaurants_run = repository.start_run(db, "restaurants", {})
    repository.finish_run(db, restaurants_run)
    seen_by_backup = []

    def backup():
        with connect(database_url("DATABASE_URL_TEST")) as other:
            seen_by_backup.append(other.execute("SELECT count(*) FROM search_documents").fetchone()[0])
        raise RuntimeError("pg_dump: disco lleno")

    _, backup_failed = refresh(
        db, FakeClient(), _no_discovery, _no_discovery, backup=backup, reports_dir=tmp_path, resume_only=True
    )
    db.rollback()  # como al salir de `with connect()` con SystemExit(3)

    assert backup_failed
    assert seen_by_backup[0] > 0
    assert db.execute("SELECT count(*) FROM search_documents").fetchone()[0] == seen_by_backup[0]


def test_resuming_with_nothing_open_rebuilds_search_and_backup_without_downloading(db, tmp_path):
    """Un corte cuando las dos corridas ya cerraron (durante la búsqueda o el respaldo) no empieza otra descarga."""
    backups = []

    reports, _ = refresh(
        db,
        FakeClient(),
        _no_discovery,
        _no_discovery,
        backup=lambda: backups.append("ok"),
        reports_dir=tmp_path,
        resume_only=True,
    )

    assert reports == [] and backups == ["ok"]
    assert db.execute("SELECT count(*) FROM scrape_runs").fetchone()[0] == 0


def test_refresh_with_pending_migrations_stops_before_downloading(db, tmp_path):
    """El código puede depender de una migración que trajo un `git pull` (la vista de vigencia de la 019): sin ella,
    `refresh` bajaba todo (cerca de un día), cerraba las corridas y fallaba al armar la búsqueda, sin respaldo."""
    db.execute("DELETE FROM schema_migrations WHERE name = '019_store_format_runs.sql'")
    db.commit()
    calls = []
    client = FakeClient({"/restaurantes/384": "restaurant"})

    with pytest.raises(PendingMigrations, match="019_store_format_runs.sql"):
        refresh(db, client, _discoverer(STORE_JOB, calls), _discoverer(RESTAURANT_JOB, calls), reports_dir=tmp_path)

    assert client.requested == [] and calls == []
    assert db.execute("SELECT count(*) FROM scrape_runs").fetchone()[0] == 0


def test_build_search_by_hand_with_pending_migrations_asks_to_migrate(db, monkeypatch):
    db.execute("DELETE FROM schema_migrations WHERE name = '019_store_format_runs.sql'")
    db.commit()
    monkeypatch.setattr(cli, "connect", lambda: nullcontext(db))
    monkeypatch.setattr(cli, "build_search_documents", lambda conn: pytest.fail("no debería armar la búsqueda"))

    with pytest.raises(SystemExit, match="rappi migrate"):
        cli.main(["build-search"])


def test_refresh_retries_failed_listings_after_the_stores_and_scrapes_what_appears(db, tmp_path):
    """Los listados que fallaron al descubrir (botillerías cerradas a las 03:00) se vuelven a pedir cuando termina la
    descarga de tiendas, y lo que aparezca se baja en la misma corrida."""
    late_job = {**STORE_JOB, "job_key": "type:boti"}
    order = []

    def retry(conn, run_id):
        order.append(("retry", len(repository.pending_jobs(conn, run_id, "store_group"))))
        repository.add_jobs(conn, run_id, [late_job])
        return 1

    reports, _ = refresh(
        db,
        FakeClient({"/restaurantes/384": "restaurant"}),
        _discoverer(STORE_JOB, []),
        _discoverer(RESTAURANT_JOB, []),
        reports_dir=tmp_path,
        retry_stores=retry,
    )

    assert order == [("retry", 0)]  # después de bajar las tiendas, no antes
    # el job tardío se procesó en la misma corrida (aquí queda «omitido»: es la misma tienda del primero)
    assert reports[0]["jobs"] == {"done": 1, "skipped": 1} and reports[0]["status"] == "done"


def test_a_block_while_retrying_listings_leaves_the_same_report_and_alert(db, tmp_path):
    """Un posible bloqueo al volver a pedir los listados de las botillerías se trata igual que dentro de la descarga:
    reporte con la alerta, corrida abierta y nada más (ni restaurantes, ni búsqueda, ni respaldo)."""

    def retry(conn, run_id):
        raise PossibleBlock("posible bloqueo: 20 respuestas seguidas de rechazo")

    backups = []
    with pytest.raises(PossibleBlock):
        refresh(
            db,
            FakeClient(),
            _discoverer(STORE_JOB, []),
            _no_discovery,
            backup=lambda: backups.append("ok"),
            reports_dir=tmp_path,
            retry_stores=retry,
        )

    run = repository.open_run(db, "stores")
    assert run is not None
    assert "posible bloqueo" in (tmp_path / f"run_{run}_stores.md").read_text(encoding="utf-8")
    alert = db.execute("SELECT report->>'alert' FROM scrape_runs WHERE run_id = %s", (run,)).fetchone()[0]
    assert "posible bloqueo" in alert
    assert backups == [] and repository.latest_run(db, "restaurants") is None


def _offline(conn, run_id):
    raise RuntimeError("sitemap: sin red")


def test_restaurant_discovery_error_still_builds_search_and_backup(db, tmp_path):
    """Tras tres días de tiendas, un error al descubrir restaurantes (sitemap caído) se saltaba la búsqueda, el
    respaldo y la capa de IA: las tiendas nuevas recién llegaban a la app la semana siguiente."""
    backups = []

    reports, backup_failed = refresh(
        db,
        FakeClient(),
        _discoverer(STORE_JOB, []),
        _offline,
        backup=lambda: backups.append("ok"),
        reports_dir=tmp_path,
    )

    assert [(r["kind"], r["status"]) for r in reports] == [("stores", "done"), ("restaurants", "failed")]
    assert "sin red" in reports[1]["alert"]
    assert db.execute("SELECT count(*) FROM search_documents").fetchone()[0] > 0
    assert backups == ["ok"] and not backup_failed
    assert repository.open_run(db, "restaurants") is None  # la próxima actualización descubre de nuevo
    failed_run = db.execute("SELECT run_id FROM scrape_runs WHERE kind = 'restaurants'").fetchone()[0]
    assert reports[1]["run_id"] == failed_run
    restaurants_md = next(tmp_path.glob("run_*_restaurants.md")).read_text(encoding="utf-8")
    assert "sin red" in restaurants_md and "Quedó abierta" not in restaurants_md


def _cmd_refresh(db, monkeypatch, tmp_path, discover_restaurants) -> int:
    """`rappi refresh` con un cliente falso, sin respaldo y con reportes en tmp_path; devuelve el código de salida."""
    monkeypatch.setattr(cli, "RappiClient", FakeClient)
    monkeypatch.setattr(cli, "_store_discoverer", lambda client, verticals: _with_retry(_discoverer(STORE_JOB, [])))
    monkeypatch.setattr(cli, "_restaurant_discoverer", lambda client: discover_restaurants)
    monkeypatch.setattr(cli, "refresh", lambda *args, **kwargs: refresh(*args, reports_dir=tmp_path, **kwargs))
    with pytest.raises(SystemExit) as stop:
        cli.cmd_refresh(db, Namespace(no_backup=True, resume_only=False))
    return stop.value.code


def _with_retry(discover):
    discover.retry = lambda conn, run_id: 0
    return discover


def test_refresh_exits_5_when_restaurants_were_not_updated(db, monkeypatch, tmp_path):
    assert _cmd_refresh(db, monkeypatch, tmp_path, _offline) == cli.RESTAURANTS_FAILED_EXIT == 5


def test_refresh_exits_4_on_a_possible_block(db, monkeypatch, tmp_path, capsys):
    """El código 1 de cualquier caída no dejaba distinguir un bloqueo en la línea de estado de la tarea semanal. Un
    bloqueo al descubrir cierra la corrida como fallida: el mensaje no puede decir que quedó abierta."""

    def blocked(conn, run_id):
        raise PossibleBlock("posible bloqueo: 20 respuestas seguidas de rechazo")

    assert _cmd_refresh(db, monkeypatch, tmp_path, blocked) == cli.POSSIBLE_BLOCK_EXIT == 4
    message = capsys.readouterr().err
    assert "quedó abierta" not in message
    assert "cerró como fallida" in message
    assert repository.open_run(db, "restaurants") is None


def test_refresh_stops_with_7_when_robots_txt_forbids_a_page(db, monkeypatch, tmp_path, capsys):
    """robots.txt no permite una página: no se la salta ni sigue con las demás. Se detiene, lo dice y la corrida de
    tiendas queda abierta, con el motivo en su reporte."""
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [{**STORE_JOB, "job_key": f"type:{i:02}"} for i in range(3)])

    class Forbidden(FakeClient):
        def get_next_data(self, path):
            self.requested.append(path)
            raise RobotsDisallowed(f"robots.txt de www.rappi.cl no permite {path} a rappi-dlab-scraper")

    monkeypatch.setattr(cli, "RappiClient", Forbidden)
    monkeypatch.setattr(cli, "refresh", lambda *args, **kwargs: refresh(*args, reports_dir=tmp_path, **kwargs))
    with pytest.raises(SystemExit) as stop:
        cli.cmd_refresh(db, Namespace(no_backup=True, resume_only=False))

    assert stop.value.code == cli.ROBOTS_EXIT == 7
    assert "robots.txt de www.rappi.cl no permite" in capsys.readouterr().err
    assert db.execute("SELECT status, count(*) FROM scrape_jobs GROUP BY 1").fetchall() == [("pending", 3)]
    assert repository.open_run(db, "stores") == run
    assert "robots.txt" in (tmp_path / f"run_{run}_stores.md").read_text(encoding="utf-8")
