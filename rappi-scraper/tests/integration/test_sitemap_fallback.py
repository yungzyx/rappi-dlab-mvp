"""Sitemap de restaurantes bloqueado o caído: la corrida usa la lista de la última corrida terminada (18-10-2026)."""

import gzip
from argparse import Namespace

import pytest
import requests

from conftest import FakeClient
from rappi_scraper import cli
from rappi_scraper.pipeline import discover
from rappi_scraper.pipeline.queue import PossibleBlock
from rappi_scraper.pipeline.refresh import refresh
from rappi_scraper.reporting import FALLBACK_LIST, render_markdown
from rappi_scraper.storage import repository

CHAIN_URL = "https://www.rappi.cl/restaurantes/delivery/1833-vapiano"
FORBIDDEN = "403 Client Error: Forbidden for url: https://www.rappi.cl/sitemaps/country/cl/x.xml.gz"


def _forbidden() -> requests.HTTPError:
    response = requests.Response()
    response.status_code = 403
    return requests.HTTPError(FORBIDDEN, response=response)


class SitemapClient(FakeClient):
    """Como FakeClient, y además sirve sitemaps: los de `sitemaps` (URL -> URLs que trae) y 403 a cualquier otro, como
    rappi.cl el 18-10."""

    def __init__(self, *args, sitemaps: dict[str, list[str]] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.sitemaps = sitemaps or {}

    def get_content(self, url: str) -> bytes:
        self.requested.append(url)
        if url not in self.sitemaps:
            raise _forbidden()
        return gzip.compress("".join(f"<url><loc>{u}</loc></url>" for u in self.sitemaps[url]).encode())


REFRESH = {"trigger": "refresh"}  # como las corridas que empieza `refresh` (ensure_run)


def _job(key: str, path: str) -> dict:
    return {
        "job_key": key,
        "job_type": "restaurant",
        "payload": {"verticals": ["restaurantes"], "candidates": [{"store_id": 1, "path": path}]},
    }


def _previous_run(db, jobs: list[tuple[dict, str, dict | None]]) -> int:
    """Una corrida de restaurantes terminada con esos jobs (job, estado, resultado)."""
    run = repository.start_run(db, "restaurants", REFRESH)
    repository.add_jobs(db, run, [job for job, _, _ in jobs])
    for job, status, result in jobs:
        repository.mark_job(db, run, job["job_key"], status, result)
    repository.finish_run(db, run)
    return run


def _keys(db, run: int) -> dict[str, str]:
    return dict(db.execute("SELECT job_key, status FROM scrape_jobs WHERE run_id = %s", (run,)).fetchall())


def _no_stores(conn, run_id):
    return 0


def test_blocked_sitemap_uses_the_list_of_the_last_finished_run(db):
    previous = _previous_run(
        db,
        [
            (_job("rest:384", "/restaurantes/384"), "done", {"store_id": 384}),
            (_job("rest:385", "/restaurantes/385"), "failed", None),  # se descubrió y no se pudo bajar: va igual
            (_job("rest:386", "/restaurantes/386"), "skipped", {"reason": "marca ya scrapeada"}),
            (_job("rest:999", "/restaurantes/999"), "skipped", {"reason": "ya no existe en Rappi"}),
        ],
    )
    failed = repository.start_run(db, "restaurants", {})  # una corrida fallida (sin lista) no sirve de fuente
    repository.finish_run(db, failed, "failed")
    run = repository.start_run(db, "restaurants", {})

    n_jobs = discover.discover_restaurants(db, SitemapClient(), run)

    assert n_jobs == 3
    assert _keys(db, run) == {"rest:384": "pending", "rest:385": "pending", "rest:386": "pending"}
    fallback = repository.run_params(db, run)[FALLBACK_LIST]
    assert fallback["corrida"] == fallback["descubierta_en"] == previous
    assert fallback["restaurantes"] == 3 and "403" in fallback["error"]


def test_a_blocked_partner_sitemap_keeps_the_new_chains_and_adds_the_rest(db):
    """El de cadenas responde (su parte -1 da 403 tras una -0 lejos del tope: es el final) y el de independientes no."""
    previous = _previous_run(
        db,
        [
            (_job("chain:1833", "/restaurantes/viejo"), "done", {}),
            (_job("rest:555", "/restaurantes/555-independiente"), "done", {}),
        ],
    )
    run = repository.start_run(db, "restaurants", {})
    client = SitemapClient(
        {"/restaurantes/delivery/1833-vapiano": "brand_chain"}, sitemaps={discover.CHAIN_SITEMAP.format(0): [CHAIN_URL]}
    )

    n_jobs = discover.discover_restaurants(db, client, run)

    assert n_jobs == 2
    assert set(_keys(db, run)) == {"chain:1833", "rest:555"}
    chain = db.execute("SELECT payload FROM scrape_jobs WHERE run_id = %s AND job_key = 'chain:1833'", (run,))
    assert chain.fetchone()[0]["candidates"][0]["path"] != "/restaurantes/viejo"  # la cadena recién descubierta queda
    assert repository.run_params(db, run)[FALLBACK_LIST]["restaurantes"] == 1
    assert repository.run_params(db, run)[FALLBACK_LIST]["corrida"] == previous


def test_a_working_sitemap_does_not_use_any_previous_list(db):
    _previous_run(db, [(_job("rest:1", "/restaurantes/1"), "done", {})])
    run = repository.start_run(db, "restaurants", {})
    client = SitemapClient(
        sitemaps={
            discover.CHAIN_SITEMAP.format(0): [],
            discover.PARTNER_SITEMAP.format(0): ["https://www.rappi.cl/restaurantes/555-independiente"],
        }
    )

    assert discover.discover_restaurants(db, client, run) == 1
    assert set(_keys(db, run)) == {"rest:555"}
    assert FALLBACK_LIST not in repository.run_params(db, run)


def test_refresh_with_a_blocked_sitemap_updates_the_known_restaurants_and_says_so(db, tmp_path):
    previous = _previous_run(db, [(_job("rest:384", "/restaurantes/384"), "done", {})])
    client = SitemapClient({"/restaurantes/384": "restaurant"})

    reports, _ = refresh(db, client, _no_stores, cli._restaurant_discoverer(client), reports_dir=tmp_path)

    restaurants = reports[1]
    assert restaurants["status"] == "done" and restaurants["jobs"] == {"done": 1}
    assert restaurants["totals"]["platos"] > 0
    assert restaurants["fallback_list"]["corrida"] == previous
    message = f"sitemap bloqueado o caído: se usó la lista de la corrida {previous} (1 restaurantes)"
    assert message in render_markdown(restaurants)
    assert message in (tmp_path / f"run_{restaurants['run_id']}_restaurants.md").read_text(encoding="utf-8")


def test_a_second_fallback_says_where_the_list_was_discovered(db):
    first = _previous_run(db, [(_job("rest:384", "/restaurantes/384"), "done", {})])
    second = repository.start_run(db, "restaurants", REFRESH)
    discover.discover_restaurants(db, SitemapClient(), second)
    repository.finish_run(db, second)
    third = repository.start_run(db, "restaurants", {})

    discover.discover_restaurants(db, SitemapClient(), third)

    fallback = repository.run_params(db, third)[FALLBACK_LIST]
    assert (fallback["corrida"], fallback["descubierta_en"]) == (second, first)
    report = {**_minimal_report(), "fallback_list": fallback}
    assert f"de la corrida {second} (1 restaurantes), descubierta en la corrida {first}" in render_markdown(report)


def _minimal_report() -> dict:
    return {
        "run_id": 1,
        "kind": "restaurants",
        "status": "done",
        "started_at": "x",
        "finished_at": "x",
        "jobs": {},
        "totals": {},
        "verticals": [],
        "checks": [],
        "top_errors": [],
    }


def _cmd_refresh(db, monkeypatch, tmp_path, client) -> int:
    """`rappi refresh` con ese cliente, sin tiendas ni respaldo; devuelve el código de salida (0 si no hubo)."""
    monkeypatch.setattr(cli, "RappiClient", lambda: client)
    monkeypatch.setattr(cli, "_store_discoverer", lambda client, verticals: _with_retry(_no_stores))
    monkeypatch.setattr(cli, "refresh", lambda *args, **kwargs: refresh(*args, reports_dir=tmp_path, **kwargs))
    try:
        cli.cmd_refresh(db, Namespace(no_backup=True, resume_only=False))
    except SystemExit as stop:
        return stop.code
    return 0


def _with_retry(discover_stores):
    discover_stores.retry = lambda conn, run_id: 0
    return discover_stores


def test_refresh_exits_0_when_the_fallback_updated_the_restaurants(db, monkeypatch, tmp_path):
    """Sale con 0, y deja la marca fija que refresh-semanal.sh anota en ultimo-estado.txt."""
    _previous_run(db, [(_job("rest:384", "/restaurantes/384"), "done", {})])
    notes = tmp_path / "avisos.txt"
    monkeypatch.setenv(cli.REFRESH_NOTES_ENV, str(notes))

    assert _cmd_refresh(db, monkeypatch, tmp_path, SitemapClient({"/restaurantes/384": "restaurant"})) == 0
    assert notes.read_text(encoding="utf-8") == f"{cli.FALLBACK_NOTE}\n"


def test_a_normal_refresh_leaves_no_notes(db, monkeypatch, tmp_path):
    notes = tmp_path / "avisos.txt"
    monkeypatch.setenv(cli.REFRESH_NOTES_ENV, str(notes))
    client = SitemapClient(sitemaps={discover.CHAIN_SITEMAP.format(0): [], discover.PARTNER_SITEMAP.format(0): []})

    assert _cmd_refresh(db, monkeypatch, tmp_path, client) == 0
    assert not notes.exists()


def test_blocked_sitemap_without_a_previous_list_still_exits_5_with_a_clear_message(db, monkeypatch, tmp_path):
    assert _cmd_refresh(db, monkeypatch, tmp_path, SitemapClient()) == cli.RESTAURANTS_FAILED_EXIT == 5

    alert, status = db.execute("SELECT report->>'alert', status FROM scrape_runs WHERE kind = 'restaurants'").fetchone()
    assert status == "failed"
    assert alert.startswith("SitemapUnavailable: HTTPError: 403")
    assert "No hay una corrida de restaurantes terminada de la que usar la lista" in alert


def test_a_block_while_downloading_the_fallback_list_exits_4_and_leaves_the_run_open(db, monkeypatch, tmp_path):
    _previous_run(db, [(_job(f"rest:{i}", f"/restaurantes/{i}"), "done", {}) for i in range(12)])
    client = SitemapClient(blocked=True)

    assert _cmd_refresh(db, monkeypatch, tmp_path, client) == cli.POSSIBLE_BLOCK_EXIT == 4

    run = repository.open_run(db, "restaurants")
    assert run is not None  # la próxima actualización la retoma, con la misma lista
    assert _keys(db, run) == {f"rest:{i}": "pending" for i in range(12)}
    assert len([p for p in client.requested if p.startswith("/restaurantes/")]) == 10


@pytest.mark.parametrize("status", ["done", "failed"])
def test_the_fallback_ignores_runs_that_are_not_finished(db, status):
    """Solo una corrida terminada (`done`) da su lista: una abierta o fallida puede tener la cola a medias."""
    run_before = repository.start_run(db, "restaurants", REFRESH)
    repository.add_jobs(db, run_before, [_job("rest:1", "/restaurantes/1")])
    repository.finish_run(db, run_before, status)

    assert repository.last_done_run_with_jobs(db, "restaurants", run_before + 1) == (
        run_before if status == "done" else None
    )


def test_a_manual_discovery_never_becomes_the_fallback_list(db):
    """Un `rappi discover --max-chains 5` a mano, terminado, no reemplaza la lista de la última actualización."""
    weekly = _previous_run(db, [(_job("rest:1", "/restaurantes/1"), "done", {})])
    manual = repository.start_run(db, "restaurants", {})
    repository.add_jobs(db, manual, [_job("rest:2", "/restaurantes/2")])
    repository.finish_run(db, manual)
    run = repository.start_run(db, "restaurants", REFRESH)

    discover.discover_restaurants(db, SitemapClient(), run)

    assert set(_keys(db, run)) == {"rest:1"}
    assert repository.run_params(db, run)[FALLBACK_LIST]["corrida"] == weekly


def test_the_fallback_respects_the_discovery_limits(db):
    _previous_run(
        db,
        [(_job(f"chain:{i}", f"/restaurantes/delivery/{i}"), "done", {}) for i in range(3)]
        + [(_job(f"rest:{i}", f"/restaurantes/{i}"), "done", {}) for i in range(3)],
    )
    run = repository.start_run(db, "restaurants", {})

    n_jobs = discover.discover_restaurants(db, SitemapClient(), run, max_chains=1, max_independents=2)

    assert n_jobs == 3
    assert set(_keys(db, run)) == {"chain:0", "rest:0", "rest:1"}


def test_a_blocked_partner_sitemap_skips_old_independents_that_are_branches_of_todays_chains(db):
    """Vapiano (cadena 1833) lista hoy la sucursal 900021447: su job suelto de la lista anterior no se copia."""
    _previous_run(
        db,
        [
            (_job("rest:900021447", "/restaurantes/900021447-vapiano"), "done", {}),
            (_job("rest:555", "/restaurantes/555-independiente"), "done", {}),
        ],
    )
    run = repository.start_run(db, "restaurants", REFRESH)
    client = SitemapClient(
        {"/restaurantes/delivery/1833-vapiano": "brand_chain"}, sitemaps={discover.CHAIN_SITEMAP.format(0): [CHAIN_URL]}
    )

    assert discover.discover_restaurants(db, client, run) == 2
    assert set(_keys(db, run)) == {"chain:1833", "rest:555"}


def test_a_possible_block_while_reading_a_sitemap_still_exits_4(db, monkeypatch, tmp_path):
    """La lista de respaldo es para un sitemap caído o rechazado, no para un bloqueo: ese sigue deteniendo todo."""
    _previous_run(db, [(_job("rest:384", "/restaurantes/384"), "done", {})])

    class BlockedClient(SitemapClient):
        def get_content(self, url):
            raise PossibleBlock("posible bloqueo: 20 requests seguidos rechazados")

    assert _cmd_refresh(db, monkeypatch, tmp_path, BlockedClient()) == cli.POSSIBLE_BLOCK_EXIT == 4
    [(status, params)] = db.execute(
        "SELECT status, params FROM scrape_runs WHERE kind = 'restaurants' ORDER BY run_id DESC LIMIT 1"
    ).fetchall()
    assert status == "failed" and FALLBACK_LIST not in params


def test_a_stopped_fallback_run_does_not_promise_a_new_discovery(db):
    report = {**_minimal_report(), "alert": "posible bloqueo", "status": "running"}
    report["fallback_list"] = {"corrida": 8, "descubierta_en": 8, "restaurantes": 10, "error": "HTTPError: 403"}

    text = render_markdown(report)

    assert "se usó la lista de la corrida 8 (10 restaurantes)" in text
    assert "vuelve a descubrir" not in text
    assert "vuelve a descubrir" in render_markdown({**report, "alert": None, "status": "done"})


def test_a_notes_file_that_cannot_be_written_only_warns(db, monkeypatch, tmp_path, caplog):
    _previous_run(db, [(_job("rest:384", "/restaurantes/384"), "done", {})])
    monkeypatch.setenv(cli.REFRESH_NOTES_ENV, str(tmp_path))  # un directorio: escribir ahí falla

    assert _cmd_refresh(db, monkeypatch, tmp_path, SitemapClient({"/restaurantes/384": "restaurant"})) == 0
    assert any("No pude escribir los avisos" in r.getMessage() for r in caplog.records)
