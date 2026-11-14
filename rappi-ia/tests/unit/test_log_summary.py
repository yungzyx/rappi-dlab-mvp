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
    assert text[1] == "4 peticiones · 1 errores 5xx · 2 sobre 1 s · 0 personas nuevas (2 siguen en la base)"
    assert text[4] == "  GET /search: 2 · 1.300 ms · 2.500 ms · 1"
    assert text[-1] == "  10:00:00 POST /agent/ask 500 (request_id ddd444)"


def test_an_empty_day_says_so_without_tables():
    text = log_summary.render(log_summary.Summary(date(2026, 11, 3), new_people=0))
    assert text == (
        "Resumen de la API · 03-11-2026\n"
        "0 peticiones · 0 errores 5xx · 0 sobre 1 s · 0 personas nuevas (0 siguen en la base)\n"
    )


UPKEEP = """\
2026-11-03 00:02:27,100 INFO rappi_ia.api.logs [vigilante-1793000000-1] GET /search 200 2504 ms
2026-11-03 00:02:27,200 INFO rappi_ia.api.logs [vigilante-1793000000-2] GET /search 200 40 ms
2026-11-03 09:15:00,250 INFO rappi_ia.api.logs [abc123] GET /search 200 50 ms
"""


def test_the_watchdog_searches_go_apart_from_the_visits():
    """Las dos búsquedas de calentamiento de deploy/macos/vigilante.sh (cada 5 minutos) no son visitas: el 03-11 fueron
    las 574 peticiones del día. Van en su propia línea y no entran a las rutas, los lentos ni los promedios."""
    summary = log_summary.read_log(UPKEEP.splitlines(), date(2026, 11, 3))

    assert (summary.requests, summary.slow, summary.upkeep, summary.upkeep_slow) == (1, 0, 2, 1)
    assert summary.routes["GET /search"].max_ms == 50
    text = log_summary.render(summary).splitlines()
    assert text[1] == "1 peticiones · 0 errores 5xx · 0 sobre 1 s · 0 personas nuevas"
    assert text[2] == "Mantención del vigilante (no cuenta arriba): 2 búsquedas · 1 sobre 1 s"


def test_a_watchdog_5xx_is_still_an_error():
    line = "2026-11-03 00:07:27,000 ERROR rappi_ia.api.logs [vigilante-1793000300-1] GET /search 503 12 ms"

    summary = log_summary.read_log([line], date(2026, 11, 3))

    assert summary.errors == ["00:07:27 GET /search 503 (request_id vigilante-1793000300-1)"]
    assert (summary.requests, summary.upkeep) == (0, 1)


def test_new_people_count_the_sessions_even_after_forget_my_data():
    """ "Borrar mis datos" borra la fila de app_users: el registro todavía dice cuántas sesiones nuevas hubo."""
    lines = [
        "2026-11-03 10:00:00,000 INFO rappi_ia.api.logs [aaa111] POST /session 200 15 ms",
        "2026-11-03 10:30:00,000 INFO rappi_ia.api.logs [bbb222] POST /session 200 12 ms",
        "2026-11-03 10:31:00,000 WARNING rappi_ia.api.logs [ccc333] POST /session 429 2 ms",
    ]

    summary = log_summary.read_log(lines, date(2026, 11, 3))
    summary.new_people = 0

    assert summary.new_sessions == 2
    assert "2 personas nuevas (0 siguen en la base)" in log_summary.render(summary).splitlines()[1]


def test_the_rotated_copy_adds_up_the_watchdog_and_the_sessions(tmp_path):
    session = "2026-11-03 10:00:00,000 INFO rappi_ia.api.logs [aaa111] POST /session 200 15 ms\n"
    (tmp_path / "api.log").write_text(UPKEEP + session, encoding="utf-8")
    (tmp_path / "api.log.1").write_text(UPKEEP.splitlines()[0] + "\n" + session, encoding="utf-8")

    summary = log_summary.read_logs([tmp_path / "api.log", tmp_path / "api.log.1"], date(2026, 11, 3))

    assert (summary.upkeep, summary.upkeep_slow, summary.new_sessions) == (3, 2, 2)


def test_silences_and_hides_go_right_after_what_matters():
    summary = log_summary.Summary(date(2026, 11, 3), new_people=0, silenced=2, hidden=1)
    assert log_summary.render(summary).splitlines()[2] == "Mochi: silenciado por hoy 2 veces · ocultado 1 vez"


def test_the_in_app_question_goes_after_mochi():
    survey = {"mostrada": 3, "si": 1, "en_parte": 1, "no": 0, "cerrada": 1, "p3": 1}
    summary = log_summary.Summary(date(2026, 11, 3), new_people=0, silenced=0, hidden=0, survey=survey)
    assert log_summary.render(summary).splitlines()[3] == (
        'Encuesta: "¿Encontraste lo que buscabas?" mostrada 3 veces · Sí 1 · En parte 1 · No 0'
        ' · cerrada sin responder 1 · "¿Confías en las sugerencias de Mochi?" respondida 1 vez'
    )
