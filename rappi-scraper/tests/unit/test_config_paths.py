"""Rutas independientes de dónde quedó el código: en un contenedor los datos van en un volumen y el .env en /etc."""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _config_in_subprocess(**env: str) -> list[str]:
    """DATA_DIR y DATABASE_URL tal como los ve un proceso nuevo (la configuración se lee al importarse)."""
    clean = {k: v for k, v in os.environ.items() if k not in ("RAPPI_DATA_DIR", "RAPPI_ENV_FILE", "DATABASE_URL")}
    code = "import os; from rappi_scraper import config; print(config.DATA_DIR); print(os.environ.get('DATABASE_URL'))"
    out = subprocess.run(
        [sys.executable, "-c", code], env={**clean, **env}, capture_output=True, text=True, check=True
    ).stdout
    return out.splitlines()


def test_data_dir_from_env(tmp_path):
    assert _config_in_subprocess()[0] == str(PROJECT_ROOT / "data")  # sin la variable, la de siempre
    assert _config_in_subprocess(RAPPI_DATA_DIR=str(tmp_path / "datos"))[0] == str(tmp_path / "datos")


def test_env_file_from_env(tmp_path):
    env_file = tmp_path / "rappi.env"
    env_file.write_text(f"RAPPI_DATA_DIR={tmp_path / 'volumen'}\nDATABASE_URL=postgresql:///desde_archivo\n")

    data_dir, url = _config_in_subprocess(RAPPI_ENV_FILE=str(env_file))

    assert data_dir == str(tmp_path / "volumen")
    assert url == "postgresql:///desde_archivo"
