"""Rutas independientes de dónde quedó el código: en un contenedor los datos van en un volumen y el .env en /etc."""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _config_in_subprocess(**env: str) -> list[str]:
    """DATA_DIR y AGENT_LLM_MODEL tal como los ve un proceso nuevo (la configuración se lee al importarse)."""
    names = ("RAPPI_IA_DATA_DIR", "RAPPI_ENV_FILE", "AGENT_LLM_MODEL")
    clean = {k: v for k, v in os.environ.items() if k not in names}
    code = "from rappi_ia import config; print(config.DATA_DIR); print(config.AGENT_LLM_MODEL)"
    out = subprocess.run(
        [sys.executable, "-c", code], env={**clean, **env}, capture_output=True, text=True, check=True
    ).stdout
    return out.splitlines()


def test_data_dir_from_env(tmp_path):
    assert _config_in_subprocess()[0] == str(PROJECT_ROOT / "data")  # sin la variable, la de siempre
    assert _config_in_subprocess(RAPPI_IA_DATA_DIR=str(tmp_path / "ia"))[0] == str(tmp_path / "ia")


def test_env_file_from_env(tmp_path):
    env_file = tmp_path / "rappi.env"
    env_file.write_text(f"RAPPI_IA_DATA_DIR={tmp_path / 'volumen'}\nAGENT_LLM_MODEL=modelo-del-archivo\n")

    data_dir, model = _config_in_subprocess(RAPPI_ENV_FILE=str(env_file))

    assert data_dir == str(tmp_path / "volumen")
    assert model == "modelo-del-archivo"
