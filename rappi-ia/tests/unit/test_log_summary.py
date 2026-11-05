"""El resumen diario de la API (`rappi-ia resumen-api`): lo que se lee del registro y cómo se muestra."""

from datetime import date

from rappi_ia.api import log_summary

LOG = """\
2026-11-02 23:59:59,100 INFO rappi_ia.api.logs [aaa111] GET /search 200 90 ms
2026-11-03 08:00:01,000 INFO rappi_ia.api.prewarm [-] Precarga de la búsqueda: 16 índices en 4.0 s
2026-11-03 09:15:00,250 INFO rappi_ia.api.logs [bbb222] GET /search 200 100 ms
2026-11-03 09:15:02,250 INFO rappi_ia.api.logs [ccc333] GET /search 200 2500 ms
2026-11-03 10:00:00,000 WARNING rappi_ia.api.logs [ddd444] POST /agent/ask 500 1200 ms
2026-11-03 10:00:05,000 INFO rappi_ia.api.logs [eee555] GET <sin ruta> 404 3 ms
2026-11-04 00:00:00,000 INFO rappi_ia.api.logs [fff666] GET /search 200 50 ms
"""


def test_only_the_request_lines_of_that_day_count():
    summary = log_summary.read_log(LOG.splitlines(), date(2026, 11, 3))

    assert summary.requests == 4  # sin la precarga ni las del día anterior y el siguiente
    search = summary.routes["GET /search"]
    assert (search.count, search.total_ms, search.max_ms, search.slow) == (2, 2600, 2500, 1)
    assert summary.routes["GET <sin ruta>"].count == 1  # un 404 no registra la ruta que pidieron
    assert summary.errors == ["10:00:00 POST /agent/ask 500 (request_id ddd444)"]
    assert summary.slow == 2


def test_the_rotated_copy_adds_up_and_a_missing_file_is_skipped(tmp_path):
    (tmp_path / "api.log.1").write_text(LOG.splitlines()[2] + "\n", encoding="utf-8")
    (tmp_path / "api.log").write_text(LOG, encoding="utf-8")
    paths = [tmp_path / "api.log", tmp_path / "api.log.1", tmp_path / "no-existe.log"]

    summary = log_summary.read_logs(paths, date(2026, 11, 3))

    assert summary.routes["GET /search"].count == 3 and summary.requests == 5


def test_the_second_line_says_what_matters_and_routes_go_by_count():
    summary = log_summary.read_log(LOG.splitlines(), date(2026, 11, 3))
    summary.new_people = 2
    text = log_summary.render(summary).splitlines()

    assert text[0] == "Resumen de la API · 03-11-2026"
    assert text[1] == "4 peticiones · 1 errores 5xx · 2 sobre 1 s · 2 personas nuevas"
    assert text[4] == "  GET /search: 2 · 1.300 ms · 2.500 ms · 1"
    assert text[-1] == "  10:00:00 POST /agent/ask 500 (request_id ddd444)"


def test_an_empty_day_says_so_without_tables():
    text = log_summary.render(log_summary.Summary(date(2026, 11, 3), new_people=0))
    assert text == "Resumen de la API · 03-11-2026\n0 peticiones · 0 errores 5xx · 0 sobre 1 s · 0 personas nuevas\n"
