"""`make schedule-status`, corrido de verdad en una copia del Makefile."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

MAKEFILE = Path(__file__).resolve().parents[2] / "Makefile"
pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="sin make")


def _schedule_status(project: Path) -> str:
    shutil.copy(MAKEFILE, project / "Makefile")
    result = subprocess.run(["make", "-s", "schedule-status"], cwd=project, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_schedule_status_shows_the_newest_backup(tmp_path):
    """Si el respaldo falla semana tras semana quedan los anteriores: la fecha del más nuevo lo delata."""
    backups = tmp_path / "data" / "backups"
    backups.mkdir(parents=True)
    for age, name in enumerate(["rappi_20260927-030000.dump", "rappi_20260920-030000.dump"]):
        (backups / name).write_bytes(b"")
        os.utime(backups / name, (1_700_000_000 - age, 1_700_000_000 - age))

    output = _schedule_status(tmp_path)

    assert "rappi_20260927-030000.dump" in output
    assert "rappi_20260920-030000.dump" not in output


def test_schedule_status_says_when_there_is_no_backup_yet(tmp_path):
    assert "Respaldo más nuevo (data/backups/):\n  ninguno todavía" in _schedule_status(tmp_path)


def _make(project: Path, *args: str) -> subprocess.CompletedProcess:
    shutil.copy(MAKEFILE, project / "Makefile")
    # Nunca el ~/Library/LaunchAgents ni el launchd de verdad, aunque el Makefile se equivoque.
    fakes = project / "fakes"
    fakes.mkdir()
    for tool in ("launchctl", "plutil"):
        (fakes / tool).write_text(f'#!/bin/sh\necho "{tool} $*" >> "{project}/calls.txt"\n')
        (fakes / tool).chmod(0o755)
    env = {**os.environ, "HOME": str(project / "home"), "PATH": f"{fakes}:{os.environ['PATH']}"}
    return subprocess.run(["make", "-s", *args], cwd=project, env=env, capture_output=True, text=True)


def test_schedule_on_linux_points_to_systemd(tmp_path):
    """En el servidor la tarea semanal es un timer de systemd: `make schedule` no intenta launchd y lo dice."""
    result = _make(tmp_path, "schedule", "UNAME=Linux")

    assert result.returncode != 0
    assert "deploy/systemd/" in result.stdout
    assert not (tmp_path / "home").exists()
    assert not (tmp_path / "calls.txt").exists()


def test_schedule_on_macos_is_unchanged(tmp_path):
    result = _make(tmp_path, "-n", "schedule", "UNAME=Darwin")

    assert result.returncode == 0, result.stderr
    assert "scripts/launchd/cl.rappi.refresh.plist.template" in result.stdout
    assert "launchctl bootstrap" in result.stdout
