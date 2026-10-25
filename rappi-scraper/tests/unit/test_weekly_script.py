"""scripts/refresh-semanal.sh (y despues-del-refresh.sh de rappi-ia), corridos de verdad en una copia del proyecto con
un `rappi` falso, con /bin/bash (el 3.2 de macOS; en el CI de Ubuntu, bash 5)."""

import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from rappi_scraper import cli

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
SCRIPT = SCRIPTS / "refresh-semanal.sh"
AFTER_REFRESH = Path(__file__).resolve().parents[3] / "rappi-ia" / "scripts" / "despues-del-refresh.sh"
SHELLS = ["/bin/bash"]
# Lo que usan los scripts, sin caffeinate (no existe en Linux): para probar que no hace falta también en macOS.
TOOLS = [
    "bash",
    "cat",
    "cp",
    "date",
    "dirname",
    "find",
    "grep",
    "mkdir",
    "mv",
    "ps",
    "rm",
    "rmdir",
    "sleep",
    "tee",
    "wc",
]


@pytest.fixture(params=SHELLS)
def shell(request) -> str:
    return request.param


def _write_fake(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/bash\n{body}\n")
    path.chmod(0o755)


def _project(tmp_path: Path, rappi_body: str, other_download_running: bool = False, ai_layer: bool = False) -> Path:
    """Copia mínima del proyecto: el script, un `.venv/bin/rappi` falso, un `pgrep` que responde lo que diga el test (el
    real vería las descargas de verdad que corren en este equipo) y un `make` que anota cómo lo llamaron. Con
    `ai_layer`, un rappi-ia instalado al lado."""
    project = tmp_path / "rappi-scraper"
    (project / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, project / "scripts" / SCRIPT.name)
    _write_fake(project / ".venv" / "bin" / "rappi", rappi_body)
    _write_fake(project / "bin" / "pgrep", f"exit {0 if other_download_running else 1}")
    _write_fake(project / "bin" / "make", 'echo "make $*" >> calls.txt')
    if ai_layer:
        _write_fake(tmp_path / "rappi-ia" / ".venv" / "bin" / "python", "exit 0")
    return project


def _env(project: Path, path: str | None = None, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in {"RAPPI_DATA_DIR", "RAPPI_BIN", "RAPPI_IA_PY", "API_ENV"}}
    return {**env, "PATH": f"{project / 'bin'}:{path or os.environ['PATH']}", **extra}


def _run(project: Path, shell: str, *args: str, path: str | None = None, **extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [shell, project / "scripts" / SCRIPT.name, *args],
        env=_env(project, path, **extra),
        capture_output=True,
        text=True,
    )


def _status_lines(project: Path) -> list[str]:
    return (project / "data" / "logs" / "ultimo-estado.txt").read_text().splitlines()


def _calls(project: Path) -> list[str]:
    return (project / "calls.txt").read_text().splitlines()


def _tools(tmp_path: Path, without: tuple[str, ...] = ()) -> str:
    """Un PATH solo con las herramientas que usa el script (sin caffeinate, y sin lo que diga `without`)."""
    tools = tmp_path / "tools"
    tools.mkdir()
    for tool in TOOLS:
        if tool not in without and (found := shutil.which(tool)):
            (tools / tool).symlink_to(found)
    return str(tools)


def _age(path: Path, seconds: float) -> None:
    then = time.time() - seconds
    os.utime(path, (then, then))


# `migrate` se anota; `refresh` espera a que el test cree `release`.
BLOCKING_REFRESH = (
    '[ "$1" = migrate ] && echo migrate >> calls.txt; '
    '[ "$1" = refresh ] && while [ ! -f release ]; do sleep 0.05; done; exit 0'
)


POST_REFRESH = "make -C ../rappi-ia post-refresh PY=.venv/bin/python"


def test_runs_without_caffeinate_exit0(tmp_path, shell):
    """En Linux (y en el contenedor) no hay caffeinate: el script corre igual, sin él."""
    project = _project(tmp_path, 'echo "$*" >> calls.txt', ai_layer=True)

    result = _run(project, shell, path=_tools(tmp_path))

    assert result.returncode == 0, result.stderr
    assert _calls(project) == ["migrate", "refresh", POST_REFRESH]
    [line] = _status_lines(project)
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d exit=0", line)
    assert not (project / "data" / "refresh-semanal.lock").exists()


@pytest.mark.parametrize("code", [0, 8])
def test_each_run_leaves_its_exit_code(tmp_path, shell, code):
    """Un fallo del domingo no queda solo en launchd.err.log: `make schedule-status` lo muestra."""
    project = _project(tmp_path, f"exit {code}")

    result = _run(project, shell)

    assert result.returncode == code
    [line] = _status_lines(project)
    assert re.fullmatch(rf"\d{{4}}-\d\d-\d\d \d\d:\d\d:\d\d exit={code}", line)
    assert not (project / "data" / "refresh-semanal.lock").exists()


def test_lock_dir_blocks_second_run(tmp_path, shell):
    """Mientras corre una tarea semanal, otra (lanzada a mano o por launchd) se omite sin tocar nada."""
    project = _project(tmp_path, '[ "$1" = refresh ] && while [ ! -f release ]; do sleep 0.05; done; exit 0')
    first = subprocess.Popen(
        [shell, project / "scripts" / SCRIPT.name], env=_env(project), stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        deadline = time.monotonic() + 10
        while not (project / "data" / "refresh-semanal.lock" / "pid").exists():
            assert time.monotonic() < deadline, "la primera ejecución no tomó el candado"
            time.sleep(0.05)

        second = _run(project, shell)

        assert second.returncode == 0
        assert "ya hay una actualización semanal en curso; se omite" in second.stdout
    finally:
        (project / "release").touch()
        first.wait(timeout=10)
    assert first.returncode == 0
    [line] = _status_lines(project)  # solo la primera anota su línea
    assert line.endswith("exit=0")


@pytest.mark.parametrize("pid", ["999999\n", "", None], ids=["pid-muerto", "pid-vacio", "sin-pid"])
def test_stale_lock_is_recovered(tmp_path, shell, pid):
    """Un apagado o un corte de luz no dejan correr el trap: la ejecución siguiente encuentra el candado abandonado, lo
    anota y sigue."""
    project = _project(tmp_path, "exit 0")
    lock = project / "data" / "refresh-semanal.lock"
    lock.mkdir(parents=True)
    if pid is not None:
        (lock / "pid").write_text(pid)
    _age(lock, 600)  # de hace 10 minutos

    result = _run(project, shell)

    assert result.returncode == 0, result.stderr
    interrupted, finished = _status_lines(project)
    assert interrupted.endswith("interrumpida: la ejecución anterior no terminó (apagado o corte de luz)")
    assert finished.endswith("exit=0")
    assert not lock.exists()


@pytest.mark.parametrize("pid", ["", None], ids=["pid-vacio", "sin-pid"])
def test_fresh_lock_without_pid_counts_as_running(tmp_path, shell, pid):
    """Entre el mkdir del candado y escribir su PID pasa un instante: un candado recién creado sin PID es de una
    ejecución que está partiendo, no uno abandonado."""
    project = _project(tmp_path, 'echo "$*" >> calls.txt')
    lock = project / "data" / "refresh-semanal.lock"
    lock.mkdir(parents=True)
    if pid is not None:
        (lock / "pid").write_text(pid)

    result = _run(project, shell)

    assert result.returncode == 0, result.stderr
    assert "ya hay una actualización semanal en curso; se omite" in result.stdout
    assert not (project / "calls.txt").exists()
    assert lock.exists()


@pytest.mark.parametrize("slow_find", [False, True], ids=["find-normal", "find-lento"])
def test_simultaneous_starts_over_a_stale_lock_let_one_through(tmp_path, shell, slow_find):
    """Varias ejecuciones a la vez frente a un candado abandonado: una sola lo recupera y corre; las demás se omiten.
    Con un `find` que tarda al azar (hasta 60 ms), el directorio de recuperación puede desaparecer entre el mkdir que
    falla y la revisión de su edad: eso no debe borrar el de otra ejecución ni hacer fallar a ninguna. Varias rondas,
    porque cada una cruza las ejecuciones de otra manera."""
    project = _project(tmp_path, BLOCKING_REFRESH)
    if slow_find:
        real_find = shutil.which("find")
        _write_fake(project / "bin" / "find", f'sleep "0.$(printf %03d $((RANDOM % 60)))"; exec {real_find} "$@"')
    lock = project / "data" / "refresh-semanal.lock"
    for _ in range(10 if slow_find else 1):
        for leftover in ("release", "calls.txt", "data/logs/ultimo-estado.txt"):
            (project / leftover).unlink(missing_ok=True)
        lock.mkdir(parents=True)
        (lock / "pid").write_text("999999\n")
        _age(lock, 600)
        runs = [
            subprocess.Popen(
                [shell, project / "scripts" / SCRIPT.name],
                env=_env(project),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for _ in range(12)
        ]
        try:
            deadline = time.monotonic() + 30
            while sum(run.poll() is not None for run in runs) < len(runs) - 1 and time.monotonic() < deadline:
                time.sleep(0.05)
        finally:
            (project / "release").touch()
            for run in runs:
                run.wait(timeout=30)

        assert [run.returncode for run in runs] == [0] * len(runs), [run.stderr.read() for run in runs]
        assert _calls(project) == ["migrate"]  # solo una llegó a descargar
        lines = _status_lines(project)
        assert sum("interrumpida" in line for line in lines) == 1
        assert sum("exit=" in line for line in lines) == 1
        assert not lock.exists()
        assert not (project / "data" / "refresh-semanal.lock.recuperando").exists()


def test_recovery_dir_that_vanishes_while_checked_is_not_taken_from_another_start(tmp_path, shell):
    """El directorio de recuperación de otra ejecución desaparece justo mientras se revisa su edad (esa terminó) y otra
    lo vuelve a tomar enseguida: esta ejecución se omite y no lo borra."""
    project = _project(tmp_path, 'echo "$*" >> calls.txt')
    lock = project / "data" / "refresh-semanal.lock"
    recovering = project / "data" / "refresh-semanal.lock.recuperando"
    lock.mkdir(parents=True)
    (lock / "pid").write_text("999999\n")
    _age(lock, 600)
    recovering.mkdir()
    real_find = shutil.which("find")
    _write_fake(
        project / "bin" / "find",
        f'case "$1" in *.recuperando) rmdir "$1"; {real_find} "$@"; rc=$?; mkdir "$1"; exit $rc;; esac\n'
        f'exec {real_find} "$@"',
    )

    result = _run(project, shell)

    assert result.returncode == 0, result.stderr
    assert "ya hay una actualización semanal en curso; se omite" in result.stdout
    assert not (project / "calls.txt").exists()
    assert recovering.is_dir()  # el de la otra ejecución sigue ahí
    assert lock.exists()


def test_abandoned_recovery_dir_is_cleared(tmp_path, shell):
    """Un directorio de recuperación de hace 10 minutos quedó de una ejecución que murió justo ahí: se borra y la
    ejecución sigue."""
    project = _project(tmp_path, 'echo "$*" >> calls.txt')
    lock = project / "data" / "refresh-semanal.lock"
    recovering = project / "data" / "refresh-semanal.lock.recuperando"
    lock.mkdir(parents=True)
    (lock / "pid").write_text("999999\n")
    recovering.mkdir()
    _age(lock, 600)
    _age(recovering, 600)

    result = _run(project, shell)

    assert result.returncode == 0, result.stderr
    assert _calls(project) == ["migrate", "refresh"]
    assert not recovering.exists()
    assert not lock.exists()


def test_finish_keeps_a_lock_it_does_not_own(tmp_path, shell):
    """Al terminar, una ejecución suelta solo su propio candado (con su PID), nunca el de otra."""
    project = _project(tmp_path, BLOCKING_REFRESH)
    lock = project / "data" / "refresh-semanal.lock"
    run = subprocess.Popen(
        [shell, project / "scripts" / SCRIPT.name], env=_env(project), stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        deadline = time.monotonic() + 10
        while not (project / "calls.txt").exists():
            assert time.monotonic() < deadline, "la ejecución no llegó a la descarga"
            time.sleep(0.05)
        (lock / "pid").write_text("424242\n")  # otra ejecución tomó el candado
    finally:
        (project / "release").touch()
        run.wait(timeout=10)

    assert run.returncode == 0
    assert (lock / "pid").read_text() == "424242\n"


def test_live_foreign_pid_without_ps_is_skipped_and_noted(tmp_path, shell):
    """Sin ps (el contenedor) no se puede ver si un PID vivo es la tarea semanal: se omite, pero queda anotado."""
    project = _project(tmp_path, 'echo "$*" >> calls.txt')
    lock = project / "data" / "refresh-semanal.lock"
    lock.mkdir(parents=True)
    other = subprocess.Popen(["sleep", "30"])
    try:
        (lock / "pid").write_text(f"{other.pid}\n")
        _age(lock, 600)

        without_ps = _run(project, shell, path=_tools(tmp_path, without=("ps",)))
        with_ps = _run(project, shell)
    finally:
        other.kill()
        other.wait()

    assert without_ps.returncode == 0, without_ps.stderr
    skipped, interrupted, finished = _status_lines(project)
    assert "se omite" in skipped and str(other.pid) in skipped
    # Con ps se ve que ese PID es otro programa: el candado estaba abandonado.
    assert with_ps.returncode == 0, with_ps.stderr
    assert interrupted.endswith("interrumpida: la ejecución anterior no terminó (apagado o corte de luz)")
    assert finished.endswith("exit=0")


def test_old_pid_lock_of_a_dead_run_is_removed(tmp_path, shell):
    """El candado del script anterior (data/refresh-semanal.pid) de una ejecución muerta se anota y se borra."""
    project = _project(tmp_path, "exit 0")
    (project / "data").mkdir()
    (project / "data" / "refresh-semanal.pid").write_text("999999\n")  # un PID que no es la tarea semanal

    result = _run(project, shell)

    assert result.returncode == 0
    interrupted, finished = _status_lines(project)
    assert interrupted.endswith("interrumpida: la ejecución anterior no terminó (apagado o corte de luz)")
    assert finished.endswith("exit=0")
    assert not (project / "data" / "refresh-semanal.pid").exists()


def test_old_pid_lock_of_a_running_weekly_blocks(tmp_path, shell):
    """Al pasar del script anterior a este, una tarea semanal antigua todavía en curso (con su .pid) no se cruza con la
    nueva."""
    project = _project(tmp_path, 'echo "$*" >> calls.txt')
    (project / "data").mkdir()
    old = subprocess.Popen(["/bin/bash", "-c", "sleep 30; :", "refresh-semanal.sh"])
    try:
        (project / "data" / "refresh-semanal.pid").write_text(f"{old.pid}\n")

        result = _run(project, shell)
    finally:
        old.kill()
        old.wait()

    assert result.returncode == 0
    assert "ya hay una actualización semanal en curso; se omite" in result.stdout
    assert not (project / "calls.txt").exists()
    assert (project / "data" / "refresh-semanal.pid").exists()


def test_a_skipped_run_is_not_reported_as_a_success(tmp_path, shell):
    # Otra descarga en curso, lanzada a mano: el script no debe correr ni anotar «exit=0» a secas.
    project = _project(tmp_path, "exit 0", other_download_running=True)

    result = _run(project, shell)

    assert result.returncode == 0
    [line] = _status_lines(project)
    assert line.endswith("exit=0 (omitida: había una descarga o una actualización en curso)")


def test_migrations_are_applied_before_downloading(tmp_path, shell):
    """Tras un `git pull` con una migración nueva, la descarga de un día no debe reventar al final (p. ej. sin la
    función `clean_html` en build_search_documents) ni repetir el fallo cada domingo."""
    project = _project(tmp_path, 'echo "$*" >> calls.txt')

    result = _run(project, shell)

    assert result.returncode == 0
    assert _calls(project) == ["migrate", "refresh"]


def test_in_production_migrations_are_only_checked(tmp_path, shell):
    """En el servidor (API_ENV=production) la tarea semanal no migra sin respaldo: solo revisa que no falte ninguna. Las
    aplica el despliegue (`docker compose run --rm migrate`), que respalda antes."""
    project = _project(tmp_path, 'echo "$*" >> calls.txt')

    result = _run(project, shell, API_ENV="production")

    assert result.returncode == 0, result.stderr
    assert _calls(project) == ["migrate --solo-revisar", "refresh"]


def test_the_script_passes_its_options_to_refresh(tmp_path, shell):
    """Tras `retry-failed`, `./scripts/refresh-semanal.sh --resume-only` retoma solo lo reencolado."""
    project = _project(tmp_path, 'echo "$*" >> calls.txt')

    result = _run(project, shell, "--resume-only")

    assert result.returncode == 0
    assert _calls(project) == ["migrate", "refresh --resume-only"]


def test_rappi_bin_data_dir_and_ia_python_come_from_the_environment(tmp_path, shell):
    """En el contenedor: `rappi` y `python` en el PATH (sin .venv) y los datos en el volumen (RAPPI_DATA_DIR)."""
    project = _project(tmp_path, "exit 9")
    _write_fake(project / "bin" / "rappi-del-contenedor", 'echo "$*" >> calls.txt')
    data = tmp_path / "volumen"

    result = _run(project, shell, RAPPI_BIN="rappi-del-contenedor", RAPPI_IA_PY="python", RAPPI_DATA_DIR=str(data))

    assert result.returncode == 0, result.stderr
    assert _calls(project) == ["migrate", "refresh", "make -C ../rappi-ia post-refresh PY=python"]
    [line] = (data / "logs" / "ultimo-estado.txt").read_text().splitlines()
    assert line.endswith("exit=0")
    assert not (project / "data").exists()


def test_a_failed_migration_stops_before_downloading(tmp_path, shell):
    project = _project(tmp_path, '[[ $1 == migrate ]] && exit 1; echo "$*" >> calls.txt')

    result = _run(project, shell)

    assert result.returncode == 1
    assert not (project / "calls.txt").exists()
    assert _status_lines(project)[0].endswith("exit=1")


@pytest.mark.parametrize(
    ("code", "exit_code", "ai_layer_runs", "note"),
    [
        # Solo falló el respaldo: la capa de IA corre igual, pero no queda como «exit=0» a secas (quedan los respaldos
        # anteriores y nadie notaría que el más nuevo tiene semanas).
        (3, 0, True, " (respaldo fallido: se conservan los anteriores)"),
        # Posible bloqueo: no es un fallo cualquiera; la línea lo dice y no sigue con la IA.
        (4, 4, False, " (detenida: posible bloqueo)"),
        # robots.txt no permite una página: igual, se detiene y lo dice.
        (7, 7, False, " (detenida: robots.txt no permite una página o no respondió)"),
        # Tiendas, búsqueda y respaldo quedaron; solo los restaurantes no se actualizaron.
        (5, 0, True, " (restaurantes sin actualizar)"),
        (6, 0, True, " (restaurantes sin actualizar; respaldo fallido: se conservan los anteriores)"),
        # Cualquier otro fallo detiene la ejecución, sin capa de IA.
        (8, 8, False, ""),
    ],
)
def test_exit_codes_3_to_7_noted(tmp_path, shell, code, exit_code, ai_layer_runs, note):
    project = _project(tmp_path, f"[[ $1 == refresh ]] && exit {code}; exit 0", ai_layer=True)

    result = _run(project, shell)

    assert result.returncode == exit_code
    if ai_layer_runs:
        assert _calls(project) == [POST_REFRESH]
    else:
        assert not (project / "calls.txt").exists()
    [line] = _status_lines(project)
    assert line.endswith(f"exit={exit_code}{note}")


@pytest.mark.parametrize(
    ("code", "note"),
    [
        (0, " (restaurantes con la lista de la corrida anterior)"),
        (3, " (respaldo fallido: se conservan los anteriores; restaurantes con la lista de la corrida anterior)"),
    ],
)
def test_restaurants_from_the_previous_list_are_noted(tmp_path, shell, code, note):
    """El sitemap de restaurantes no respondió y se bajó la lista de una corrida anterior: sale con 0 (o 3), pero la
    línea de estado lo dice, para que un sitemap bloqueado varias semanas no pase inadvertido."""
    marker = cli.FALLBACK_NOTE
    project = _project(
        tmp_path, f'[[ $1 == refresh ]] && {{ echo {marker} > "${cli.REFRESH_NOTES_ENV}"; exit {code}; }}; exit 0'
    )

    result = _run(project, shell)

    assert result.returncode == 0
    [line] = _status_lines(project)
    assert line.endswith(f"exit=0{note}")


def test_a_previous_weeks_notes_are_not_noted_again(tmp_path, shell):
    project = _project(tmp_path, "exit 0")
    logs = project / "data" / "logs"
    logs.mkdir(parents=True)
    (logs / "refresh-avisos.txt").write_text(f"{cli.FALLBACK_NOTE}\n")

    assert _run(project, shell).returncode == 0
    assert _status_lines(project)[0].endswith("exit=0")


def test_big_launchd_log_rotated(tmp_path, shell):
    """launchd escribe siempre en el mismo archivo: pasados 10 MB, el script lo copia a .1 (y pisa el .1 anterior) y lo
    vacía. Lo de esta misma ejecución, que launchd sigue escribiendo ahí, queda en el archivo vivo."""
    project = _project(tmp_path, 'echo "salida de esta ejecución" >&2; exit 0')
    logs = project / "data" / "logs"
    logs.mkdir(parents=True)
    with (logs / "launchd.err.log").open("wb") as big:
        big.truncate(11 * 1024 * 1024)
    (logs / "launchd.err.log.1").write_text("la anterior\n")
    (logs / "launchd.out.log").write_text("poco\n")

    with (logs / "launchd.err.log").open("ab") as launchd_err:  # como launchd: abierto antes de lanzar el script
        result = subprocess.run(
            [shell, project / "scripts" / SCRIPT.name], env=_env(project), stdout=subprocess.PIPE, stderr=launchd_err
        )

    assert result.returncode == 0
    assert (logs / "launchd.err.log.1").stat().st_size == 11 * 1024 * 1024
    assert "salida de esta ejecución" in (logs / "launchd.err.log").read_text()
    assert (logs / "launchd.err.log").stat().st_size < 1024
    assert (logs / "launchd.out.log").read_text() == "poco\n"
    assert not (logs / "launchd.out.log.1").exists()


def test_old_logs_are_pruned(tmp_path, monkeypatch):
    """Cada comando largo deja su log (refresh_…, backup_…): los de más de LOG_RETENTION_WEEKS semanas se borran. Los de
    launchd y ultimo-estado.txt no son de un comando y no se tocan."""
    logs = tmp_path / "logs"
    logs.mkdir()
    nine_weeks_ago = time.time() - 9 * 7 * 86400
    old = ["refresh_20260801-030000.log", "backup_20260801-030000.log"]
    kept = ["refresh_20261004-030000.log", "launchd.err.log", "launchd.out.log", "ultimo-estado.txt"]
    for name in [*old, *kept]:
        (logs / name).write_text("x\n")
    for name in [*old, *kept[1:]]:
        os.utime(logs / name, (nine_weeks_ago, nine_weeks_ago))
    monkeypatch.setattr(cli, "LOGS_DIR", logs)
    monkeypatch.delenv("LOG_RETENTION_WEEKS", raising=False)
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    root.handlers[:] = []
    try:
        cli._setup_logging("refresh")
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers[:] = handlers
        root.setLevel(level)

    remaining = {p.name for p in logs.iterdir()}
    assert remaining.isdisjoint(old)
    assert set(kept) <= remaining
    assert len(remaining) == len(kept) + 1  # y el log de esta ejecución


def test_log_retention_weeks_from_environment(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    three_weeks_ago = time.time() - 3 * 7 * 86400
    (logs / "refresh_20260920-030000.log").write_text("x\n")
    os.utime(logs / "refresh_20260920-030000.log", (three_weeks_ago, three_weeks_ago))
    monkeypatch.setenv("LOG_RETENTION_WEEKS", "2")

    cli.prune_old_logs(logs)

    assert not (logs / "refresh_20260920-030000.log").exists()


@pytest.mark.parametrize("value", ["muchas", "0"])
def test_bad_log_retention_does_not_break_the_command(tmp_path, monkeypatch, caplog, value):
    """Un LOG_RETENTION_WEEKS mal escrito usa las 8 semanas (y lo avisa); 0 no borra los logs recientes (mínimo 1)."""
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "refresh_de-ayer.log").write_text("x\n")
    _age(logs / "refresh_de-ayer.log", 86400)
    (logs / "refresh_de-hace-diez-semanas.log").write_text("x\n")
    _age(logs / "refresh_de-hace-diez-semanas.log", 10 * 7 * 86400)
    monkeypatch.setenv("LOG_RETENTION_WEEKS", value)

    cli.prune_old_logs(logs)

    assert {p.name for p in logs.iterdir()} == {"refresh_de-ayer.log"}
    if value == "muchas":
        assert "LOG_RETENTION_WEEKS" in caplog.text


def test_a_log_that_vanishes_while_pruning_is_skipped(tmp_path, monkeypatch, caplog):
    """Otro proceso puede borrar un log mientras se poda: el comando sigue."""
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "refresh_viejo.log").write_text("x\n")
    _age(logs / "refresh_viejo.log", 10 * 7 * 86400)
    real_glob = Path.glob
    monkeypatch.setattr(Path, "glob", lambda self, pattern: [logs / "backup_ya-no-esta.log", *real_glob(self, pattern)])

    cli.prune_old_logs(logs)

    assert not (logs / "refresh_viejo.log").exists()


def test_after_refresh_script_runs_post_refresh(tmp_path, shell):
    """despues-del-refresh.sh (rappi-ia): sin caffeinate y con bash, espera que no haya descargas y actualiza la IA."""
    project = tmp_path / "rappi-ia"
    (project / "scripts").mkdir(parents=True)
    shutil.copy(AFTER_REFRESH, project / "scripts" / AFTER_REFRESH.name)
    _write_fake(project / "bin" / "pgrep", "exit 1")
    _write_fake(project / "bin" / "make", 'echo "make $*" >> calls.txt')
    tools = tmp_path / "tools"
    tools.mkdir()
    for tool in TOOLS:
        if found := shutil.which(tool):
            (tools / tool).symlink_to(found)

    result = subprocess.run(
        [shell, project / "scripts" / AFTER_REFRESH.name],
        env=_env(project, str(tools), RAPPI_IA_PY="python"),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert _calls(project) == ["make post-refresh PY=python"]
    assert list((project / "data" / "logs").glob("despues-del-refresh_*.log"))
