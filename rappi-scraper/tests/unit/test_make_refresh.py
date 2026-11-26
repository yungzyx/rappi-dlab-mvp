"""`make refresh`, corrido de verdad en una copia del Makefile con un `.venv/bin/python` falso (y el de rappi-ia al
lado) que anota cómo lo llamaron."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

MAKEFILE = Path(__file__).resolve().parents[2] / "Makefile"
pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="sin make")


def _fake(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/bash\n{body}\n")
    path.chmod(0o755)


def _project(tmp_path: Path, ai_layer: bool = True) -> Path:
    project = tmp_path / "rappi-scraper"
    project.mkdir()
    shutil.copy(MAKEFILE, project / "Makefile")
    calls = tmp_path / "calls.txt"
    _fake(project / ".venv" / "bin" / "python", f'echo "$*" >> {calls}')
    if ai_layer:  # check-migrations se niega mientras exista `rama-sin-fusionar`
        _fake(
            tmp_path / "rappi-ia" / ".venv" / "bin" / "python",
            f'echo "ia $*" >> {calls}\n[ ! -e {tmp_path}/rama-sin-fusionar ]',
        )
    return project


def _refresh(project: Path, **env: str) -> tuple[subprocess.CompletedProcess, list[str]]:
    clean = {k: v for k, v in os.environ.items() if k not in {"API_ENV", "MAKEFLAGS", "MAKELEVEL"}}
    result = subprocess.run(
        ["make", "-s", "refresh"], cwd=project, env={**clean, **env}, capture_output=True, text=True
    )
    calls = project.parent / "calls.txt"
    return result, calls.read_text().splitlines() if calls.exists() else []


def test_in_production_refresh_only_checks_the_migrations(tmp_path):
    """En el contenedor jobs (API_ENV=production) `make refresh` migraba sin el respaldo del despliegue."""
    result, calls = _refresh(_project(tmp_path), API_ENV="production")

    assert result.returncode == 0, result.stderr
    assert calls == ["-m rappi_scraper migrate --solo-revisar", "-m rappi_scraper refresh"]


def test_refresh_does_not_migrate_the_real_database_from_an_unmerged_branch(tmp_path):
    """Como `make mvp` y `make serve`: con rappi-ia al lado, antes de migrar pasa por `rappi-ia check-migrations`."""
    project = _project(tmp_path)

    result, calls = _refresh(project)

    assert result.returncode == 0, result.stderr
    assert calls == ["ia -m rappi_ia check-migrations", "-m rappi_scraper migrate", "-m rappi_scraper refresh"]

    (tmp_path / "calls.txt").unlink()
    (tmp_path / "rama-sin-fusionar").touch()
    refused, calls = _refresh(project)

    assert refused.returncode != 0
    assert calls == ["ia -m rappi_ia check-migrations"]


def test_without_rappi_ia_refresh_migrates_as_before(tmp_path):
    result, calls = _refresh(_project(tmp_path, ai_layer=False))

    assert result.returncode == 0, result.stderr
    assert calls == ["-m rappi_scraper migrate", "-m rappi_scraper refresh"]
