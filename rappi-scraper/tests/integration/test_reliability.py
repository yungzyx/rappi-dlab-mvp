"""Reintentos de jobs y reporte de calidad de corridas, contra `rappi_test`."""

from collections import Counter

import psycopg
import pytest

from conftest import FakeClient, load_page
from rappi_scraper.pipeline import queue
from rappi_scraper.pipeline.queue import PossibleBlock, process_with_retry
from rappi_scraper.pipeline.stores import process_store_jobs
from rappi_scraper.reporting import build_run_report, render_markdown, write_run_report
from rappi_scraper.scraping.restaurant_parser import parse_restaurant
from rappi_scraper.storage import repository


def _job(key, path="/tiendas/900025946-lider"):
    candidate = {"store_id": 1, "path": path, "city": "Santiago", "lat": -33.4, "lng": -70.6}
    return {
        "job_key": key,
        "job_type": "store_group",
        "payload": {"verticals": ["supermercado"], "candidates": [candidate]},
    }


def _status(db, key):
    return db.execute("SELECT status, attempts FROM scrape_jobs WHERE job_key = %s", (key,)).fetchone()


def test_requeue_failed_respects_max_attempts_and_job_keys(db):
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [_job("a"), _job("b"), _job("c")])
    repository.mark_job(db, run, "a", "failed", error="502")  # 1 intento
    for _ in range(3):
        repository.mark_job(db, run, "b", "failed", error="502")  # 3 intentos
    repository.mark_job(db, run, "c", "failed", error="502")

    assert repository.requeue_failed(db, run, max_attempts=2, job_keys=["a", "b"]) == ["a"]
    assert _status(db, "a")[0] == "pending"
    assert _status(db, "b")[0] == "failed"
    assert _status(db, "c")[0] == "failed"  # fuera de job_keys
    assert sorted(repository.requeue_failed(db, run, max_attempts=5)) == ["b", "c"]


def test_latest_and_reopen_run(db):
    run = repository.start_run(db, "stores", {})
    repository.finish_run(db, run)
    assert repository.open_run(db, "stores") is None
    assert repository.latest_run(db, "stores") == run

    repository.reopen_run(db, run)

    assert repository.open_run(db, "stores") == run


def test_transient_failure_is_retried_automatically(db):
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [_job("type:lider")])
    client = FakeClient(failing_once={"/tiendas/900025946-lider"})

    process_store_jobs(db, client, run, max_aisles=1)

    assert _status(db, "type:lider") == ("done", 2)


BLOCKED = ("failed", None, "403 Client Error: Forbidden")


def _job_states(db):
    return dict(db.execute("SELECT status, count(*) FROM scrape_jobs GROUP BY 1").fetchall())


def test_a_block_during_the_retry_pass_sends_the_streak_back_to_the_queue(db):
    """Esos jobs ya llevaban un intento: con el tope de intentos quedaban 'failed' y nadie los volvía a tomar."""
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [_job(f"type:{i:02}") for i in range(30)])
    calls = Counter()

    def handler(job):
        calls[job["job_key"]] += 1
        if calls[job["job_key"]] > 1:  # en la pasada de reintento rappi.cl ya bloquea todo
            return BLOCKED
        if int(job["job_key"][-2:]) % 2:  # en la primera pasada falla uno de cada dos (error transitorio)
            return "failed", None, "HTTP 502"
        return "done", {}, None

    with pytest.raises(PossibleBlock):
        process_with_retry(db, run, repository.pending_jobs(db, run, "store_group"), handler)

    assert _job_states(db) == {"done": 15, "pending": 15}


def test_a_block_two_weeks_in_a_row_leaves_the_jobs_pending(db):
    """La corrida queda abierta y la semana siguiente se retoma: un segundo bloqueo tampoco los da por fallidos."""
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [_job(f"type:{i:02}") for i in range(15)])

    for _ in range(2):
        with pytest.raises(PossibleBlock):
            process_with_retry(db, run, repository.pending_jobs(db, run, "store_group"), lambda job: BLOCKED)

    assert _job_states(db) == {"pending": 15}


def test_a_streak_that_repeats_every_week_ends_up_failed_and_the_run_moves_on(db):
    """Un error fijo (no un bloqueo) en 10 jobs seguidos arma la misma racha cada semana, porque la cola va por
    job_key: sin tope, la corrida de tiendas quedaba detenida para siempre y los jobs sanos no corrían nunca."""
    run = repository.start_run(db, "stores", {})
    turbo = [_job(f"type:turbo_{i:02}") for i in range(10)]
    repository.add_jobs(db, run, turbo + [_job(f"type:unimarc_{i}") for i in range(5)])

    def handler(job):
        if "turbo" in job["job_key"]:
            return "failed", None, "ParseError: sin __NEXT_DATA__"
        return "done", {}, None

    blocked_weeks = 0
    for _ in range(8):  # una actualización por semana, que retoma la corrida abierta
        try:
            process_with_retry(db, run, repository.pending_jobs(db, run, "store_group"), handler)
            break
        except PossibleBlock:
            blocked_weeks += 1

    assert _job_states(db) == {"failed": 10, "done": 5}
    # Tres semanas de vuelta a la cola (cubren un bloqueo real); la cuarta quedan 'failed' y la corrida sigue esa misma
    # semana: antes se detenía igual, sin reencolar nada, y los sanos esperaban una semana más.
    assert blocked_weeks == 3


def test_a_block_right_after_a_streak_of_exhausted_jobs_still_stops_the_run(db):
    """Si la racha de jobs agotados no detiene la corrida, un bloqueo real justo después sí: al primer fallo más."""
    run = repository.start_run(db, "stores", {})
    turbo = [_job(f"type:turbo_{i:02}") for i in range(10)]
    repository.add_jobs(db, run, turbo + [_job(f"type:unimarc_{i}") for i in range(5)])
    for _ in range(3):  # tres semanas de la misma racha: los turbo llegan a su último intento
        with pytest.raises(PossibleBlock):
            process_with_retry(db, run, repository.pending_jobs(db, run, "store_group"), lambda job: BLOCKED)
    calls = []

    def blocked(job):
        calls.append(job["job_key"])
        return BLOCKED

    with pytest.raises(PossibleBlock):
        process_with_retry(db, run, repository.pending_jobs(db, run, "store_group"), blocked)

    assert [key for key in calls if "unimarc" in key] == ["type:unimarc_0"]
    assert _job_states(db) == {"failed": 10, "pending": 5}


def test_failures_where_rappi_answered_do_not_stop_the_run(db):
    """«Ninguna sucursal disponible» es una respuesta de rappi.cl, no una señal de bloqueo."""
    path = "/tiendas/900025946-lider"
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [_job(f"type:{i:02}", path) for i in range(12)])

    process_store_jobs(db, FakeClient(unavailable={path}), run, max_aisles=1)

    assert db.execute("SELECT status, count(*) FROM scrape_jobs GROUP BY 1").fetchall() == [("failed", 12)]


def test_store_report_counts_jobs_and_flags_missing_prices(db):
    run = repository.start_run(db, "stores", {})
    repository.upsert_store(db, {"store_id": 1, "name": "Lider", "store_type": "lider"})
    repository.upsert_store_vertical(db, 1, "supermercado")
    products = [
        {"product_id": str(i), "master_product_id": 100 + i, "name": f"P{i}", "category_id": 76,
         "category_name": "Arroz", "image_url": "x.png", "price": 0 if i < 3 else 990}
        for i in range(10)
    ]  # fmt: skip
    repository.save_products(db, run, 1, products)
    repository.add_jobs(db, run, [_job("ok"), _job("mal")])
    repository.mark_job(db, run, "ok", "done", {"store_id": 1, "store_type": "lider", "products": 10})
    repository.mark_job(db, run, "mal", "failed", error="HTTP 502")
    db.commit()

    report = build_run_report(db, run)

    assert report["jobs"] == {"done": 1, "failed": 1}
    assert report["top_errors"] == [{"error": "HTTP 502", "count": 1}]
    assert report["verticals"][0]["vertical"] == "supermercado"
    assert report["verticals"][0]["productos_unicos"] == 10
    checks = {c["label"]: c for c in report["checks"]}
    assert checks["Productos sin precio (%)"]["value"] == 30.0
    assert not checks["Productos sin precio (%)"]["ok"]
    assert not checks["Jobs fallidos (%)"]["ok"]  # 50% > 10%
    assert checks["Productos sin categoría (%)"]["ok"]


def _report_with_skips(db, previous_offers=None):
    """1 tienda hecha (1 oferta), 1 fallida y 8 omitidas (marca ya descargada)."""
    if previous_offers is not None:
        prev = repository.start_run(db, "stores", {})
        repository.finish_run(db, prev)
        repository.save_run_report(db, prev, {"totals": {"ofertas": previous_offers}})
    run = repository.start_run(db, "stores", {})
    repository.upsert_store(db, {"store_id": 1, "name": "Lider", "store_type": "lider"})
    repository.upsert_store_vertical(db, 1, "supermercado")
    one = {"product_id": "1", "master_product_id": 101, "name": "P1", "category_id": 76, "category_name": "Arroz",
           "image_url": "x.png", "price": 990}  # fmt: skip
    repository.save_products(db, run, 1, [one])
    keys = ["ok", "mal", *(f"omitida-{i}" for i in range(8))]
    repository.add_jobs(db, run, [_job(k) for k in keys])
    repository.mark_job(db, run, "ok", "done", {"store_id": 1, "store_type": "lider", "products": 1})
    repository.mark_job(db, run, "mal", "failed", error="HTTP 502")
    for k in keys[2:]:
        repository.mark_job(db, run, k, "skipped", {"reason": "marca ya scrapeada"})
    db.commit()
    return {c["label"]: c for c in build_run_report(db, run)["checks"]}


def test_failed_jobs_are_counted_over_attempted_jobs_not_skipped_ones(db):
    """Corrida 4: 8,4 % «ok» con los omitidos en el denominador; sobre los intentados era 11,5 % (> 10 %)."""
    checks = _report_with_skips(db)
    assert checks["Jobs fallidos (%)"]["value"] == 50.0


def test_a_big_drop_versus_the_previous_run_is_flagged(db):
    """Las validaciones eran absolutas: una corrida con la mitad de ofertas pasaba sin aviso."""
    checks = _report_with_skips(db, previous_offers=100)
    drop = next(c for label, c in checks.items() if label.startswith("Ofertas vs corrida"))
    assert drop["value"] == -99.0 and not drop["ok"]


def test_store_report_sums_skipped_pages(db):
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [_job("a"), _job("b"), _job("c")])
    repository.mark_job(db, run, "a", "done", {"products": 5, "paginas_omitidas": 2})
    repository.mark_job(db, run, "b", "done", {"products": 5, "paginas_omitidas": 1})
    repository.mark_job(db, run, "c", "done", {"products": 5})  # jobs anteriores no traen el conteo

    assert build_run_report(db, run)["totals"]["paginas_omitidas"] == 3


def test_store_report_flags_the_share_of_skipped_pages(db):
    """Las omitidas como % de las intentadas (también en los jobs que fallaron por omitir demasiadas)."""
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [_job("a"), _job("b")])
    repository.mark_job(db, run, "a", "done", {"products": 5, "paginas_omitidas": 1, "paginas_intentadas": 100})
    repository.mark_job(db, run, "b", "failed", {"paginas_omitidas": 9, "paginas_intentadas": 20}, "demasiadas")

    check = next(c for c in build_run_report(db, run)["checks"] if c["label"] == "Páginas omitidas (%)")

    assert (check["value"], check["limit"], check["ok"]) == (8.3, 5.0, False)


def test_restaurant_report_and_written_files(db, tmp_path):
    run = repository.start_run(db, "restaurants", {})
    repository.save_restaurant(db, run, parse_restaurant(load_page("restaurant")))
    db.commit()

    report, path = write_run_report(db, run, reports_dir=tmp_path)

    assert report["totals"] == {"restaurantes": 1, "platos": 61, "platos_nuevos": 61}
    assert all(c["ok"] for c in report["checks"])
    assert path == tmp_path / f"run_{run}_restaurants.md"
    assert "✓ Todas las validaciones" in path.read_text(encoding="utf-8")
    stored = db.execute("SELECT report->>'kind' FROM scrape_runs WHERE run_id = %s", (run,)).fetchone()[0]
    assert stored == "restaurants"


def test_store_report_warns_about_listings_that_failed_at_discovery(db):
    """El 04-10 el listado de licores falló en 13 de 14 ciudades y el reporte decía «ok»: no había jobs fallidos,
    simplemente nunca se crearon."""
    run = repository.start_run(db, "stores", {})
    repository.set_run_param(db, run, "listados_fallidos", [["Viña del Mar", "licores"], ["Temuco", "licores"]])

    report = build_run_report(db, run)

    check = next(c for c in report["checks"] if c["label"] == "Listados fallidos al descubrir")
    assert check["value"] == 2 and not check["ok"]
    assert "licores: Temuco, Viña del Mar" in render_markdown(report)


def test_mark_job_is_retried_once_after_a_database_error(db, monkeypatch):
    """Un error pasajero de la base al anotar el job (p. ej. un timeout) no tumba una corrida de días."""
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [_job("a")])
    real_mark_job = repository.mark_job
    calls = []

    def flaky(*args, **kwargs):
        calls.append(args[2])
        if len(calls) == 1:
            raise psycopg.errors.QueryCanceled("canceling statement due to statement timeout")
        real_mark_job(*args, **kwargs)

    monkeypatch.setattr(queue.repository, "mark_job", flaky)

    process_with_retry(db, run, repository.pending_jobs(db, run, "store_group"), lambda job: ("done", {}, None))

    assert calls == ["a", "a"]
    assert _status(db, "a") == ("done", 1)


def test_a_lost_connection_stops_with_a_clear_message(db):
    """Con la conexión caída (Postgres reiniciado) el rollback del `except` reventaba con una traza confusa."""
    run = repository.start_run(db, "stores", {})
    repository.add_jobs(db, run, [_job("a")])
    jobs = repository.pending_jobs(db, run, "store_group")
    db.commit()

    def handler(job):
        db.close()  # como un pg_terminate_backend a mitad del job
        raise psycopg.OperationalError("server closed the connection unexpectedly")

    with pytest.raises(psycopg.OperationalError, match="Se perdió la conexión con la base"):
        process_with_retry(db, run, jobs, handler)
