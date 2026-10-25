from argparse import Namespace

import pytest

from rappi_scraper import cli
from rappi_scraper import keep_awake as keep_awake_module
from rappi_scraper.keep_awake import keep_awake
from rappi_scraper.pipeline.progress import Progress
from rappi_scraper.pipeline.queue import PossibleBlock
from rappi_scraper.reporting import render_markdown


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_progress_estimates_remaining_time_from_average():
    clock = _Clock()
    progress = Progress(10, clock=clock)

    assert progress.label(0) == "[1/10]"
    clock.now = 60  # 1 job en 1 minuto
    assert progress.label(1) == "[2/10 · 1m · faltan ~9m]"
    clock.now = 2 * 3600  # 5 jobs en 2 horas
    assert progress.label(5) == "[6/10 · 2h00m · faltan ~2h00m]"


def test_keep_awake_is_noop_without_caffeinate(monkeypatch):
    monkeypatch.setattr(keep_awake_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(keep_awake_module.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    with keep_awake():
        pass


def test_keep_awake_starts_and_stops_caffeinate(monkeypatch):
    calls = []

    class FakeProcess:
        def __init__(self, cmd):
            calls.append(("start", cmd))

        def terminate(self):
            calls.append(("stop",))

        def wait(self, timeout):
            calls.append(("wait", timeout))

    monkeypatch.setattr(keep_awake_module.shutil, "which", lambda _name: "/usr/bin/caffeinate")
    monkeypatch.setattr(keep_awake_module.subprocess, "Popen", FakeProcess)
    with keep_awake():
        assert calls[0][1][:3] == ["/usr/bin/caffeinate", "-i", "-w"]
    assert calls[-2:] == [("stop",), ("wait", 5)]  # sin quedar como proceso zombi


def _report(checks):
    return {
        "run_id": 7, "kind": "stores", "status": "done", "started_at": "2026-09-26T10:00", "finished_at": None,
        "jobs": {"done": 9, "failed": 1}, "totals": {"ofertas": 120}, "top_errors": [{"error": "HTTP 502", "count": 1}],
        "verticals": [
            {"vertical": "mall", "tiendas": 2, "ofertas": 120, "productos_unicos": 100, "productos_nuevos": 100}
        ],
        "checks": checks,
    }  # fmt: skip


def test_render_markdown_flags_out_of_range_checks():
    checks = [
        {"label": "Productos sin precio (%)", "value": 12.0, "limit": 5, "minimum": False, "ok": False},
        {"label": "Cobertura obtenidos/declarados (%)", "value": 30.0, "limit": 5, "minimum": True, "ok": True},
    ]
    text = render_markdown(_report(checks))

    assert "⚠ 1 validaciones fuera de rango: Productos sin precio (%)" in text
    assert "| Productos sin precio (%) | 12.0 | ≤ 5 | ⚠ |" in text
    assert "| Cobertura obtenidos/declarados (%) | 30.0 | ≥ 5 | ok |" in text
    assert "| mall | 2 | 120 | 100 | 100 |" in text
    assert "- (1) HTTP 502" in text


def test_render_markdown_all_ok():
    ok = [{"label": "Jobs fallidos (%)", "value": 1.0, "limit": 10, "minimum": False, "ok": True}]
    assert "✓ Todas las validaciones dentro de rango" in render_markdown(_report(ok))


def test_refresh_command_exits_with_a_clear_message_on_a_block(monkeypatch, capsys):
    def blocked(*args, **kwargs):
        raise PossibleBlock("posible bloqueo: 10 fallos consecutivos (último: 403)")

    monkeypatch.setattr(cli, "refresh", blocked)
    with pytest.raises(SystemExit) as exit_info:
        cli.cmd_refresh(None, Namespace(no_backup=True, resume_only=False))
    assert exit_info.value.code == 4  # refresh-semanal.sh lo anota como «posible bloqueo»
    assert "Descarga detenida: posible bloqueo" in capsys.readouterr().err


def test_refresh_command_ends_normally_when_everything_worked(monkeypatch, capsys):
    monkeypatch.setattr(cli, "refresh", lambda *args, **kwargs: ([{"kind": "stores", "status": "done"}], False))
    monkeypatch.setattr(cli, "render_markdown", lambda report: f"reporte de {report['kind']}")

    cli.cmd_refresh(None, Namespace(no_backup=False, resume_only=False))

    assert "reporte de stores" in capsys.readouterr().out


def test_refresh_command_exits_with_its_own_code_when_only_the_backup_failed(monkeypatch, capsys):
    """refresh-semanal.sh distingue el código 3: anota «respaldo fallido» y sigue con la capa de IA."""
    monkeypatch.setattr(cli, "refresh", lambda *args, **kwargs: ([{"kind": "stores", "status": "done"}], True))
    monkeypatch.setattr(cli, "render_markdown", lambda report: f"reporte de {report['kind']}")

    with pytest.raises(SystemExit) as exit_info:
        cli.cmd_refresh(None, Namespace(no_backup=False, resume_only=False))

    assert exit_info.value.code == 3
    assert "reporte de stores" in capsys.readouterr().out  # los reportes salen igual


@pytest.mark.parametrize(
    ("restaurants", "backup_failed", "code"), [("failed", False, 5), ("failed", True, 6), ("done", True, 3)]
)
def test_refresh_command_reports_restaurants_and_backup_failures(monkeypatch, restaurants, backup_failed, code):
    """Si fallan los restaurantes y el respaldo, la tarea semanal tiene que poder anotar los dos."""
    reports = [{"kind": "stores", "status": "done"}, {"kind": "restaurants", "status": restaurants}]
    monkeypatch.setattr(cli, "refresh", lambda *args, **kwargs: (reports, backup_failed))
    monkeypatch.setattr(cli, "render_markdown", lambda report: "")

    with pytest.raises(SystemExit) as exit_info:
        cli.cmd_refresh(None, Namespace(no_backup=False, resume_only=False))

    assert exit_info.value.code == code


def test_refresh_command_can_resume_without_starting_new_runs(monkeypatch):
    """Tras `retry-failed`: `rappi refresh --resume-only` (o `refresh-semanal.sh --resume-only`)."""
    calls = []
    monkeypatch.setattr(cli, "refresh", lambda *args, **kwargs: calls.append(kwargs) or ([], False))

    cli.cmd_refresh(None, cli.build_parser().parse_args(["refresh", "--resume-only"]))

    assert calls[0]["resume_only"] is True


@pytest.mark.parametrize(
    ("command", "kind", "processor"),
    [
        ("cmd_scrape_stores", "stores", "process_store_jobs"),
        ("cmd_scrape_restaurants", "restaurants", "process_restaurant_jobs"),
    ],
)
def test_manual_scrape_commands_leave_the_report_and_a_clear_message_on_a_block(monkeypatch, command, kind, processor):
    """Lanzadas a mano, terminaban con una traza y sin el reporte con la alerta (refresh sí lo hacía)."""
    reports = []

    def blocked(*args, **kwargs):
        raise PossibleBlock("posible bloqueo: 10 fallos consecutivos (último: 403)")

    monkeypatch.setattr(cli, processor, blocked)
    monkeypatch.setattr(cli, "RappiClient", lambda: None)
    monkeypatch.setattr(cli.repository, "open_run", lambda conn, k: 7)

    def finish_and_report(conn, run_id, kind, alert=None):
        reports.append((run_id, kind, alert))
        return {}, None

    monkeypatch.setattr(cli, "finish_and_report", finish_and_report)
    monkeypatch.setattr(cli, "render_markdown", lambda report: "")

    args = Namespace(vertical=None, limit=None, max_aisles=None)
    with pytest.raises(SystemExit, match="Descarga detenida: posible bloqueo"):
        getattr(cli, command)(None, args)
    assert reports == [(7, kind, "posible bloqueo: 10 fallos consecutivos (último: 403)")]
