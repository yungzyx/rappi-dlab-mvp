"""`make post-refresh`: si falla un paso (el motor, al final de `make layers`), igual corre la purga final y el error
no se pierde."""

import os
import subprocess

from rappi_ia.config import PROJECT_ROOT


def test_post_refresh_purges_even_if_the_motor_fails(tmp_path):
    log = tmp_path / "pasos.log"
    fake = tmp_path / "python"  # anota cada `$(PY) -m rappi_ia …` y falla solo en `motor`
    fake.write_text(
        '#!/bin/sh\necho "$*" >> "$PASOS"\ncase "$*" in "-m rappi_ia motor"*) exit 1 ;; esac\n', encoding="utf-8"
    )
    fake.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in ("API_ENV", "MAKEFLAGS", "MFLAGS")} | {"PASOS": str(log)}

    done = subprocess.run(
        ["make", "-s", "-C", str(PROJECT_ROOT), "post-refresh", f"PY={fake}", "API_ENV=local"],
        capture_output=True,
        text=True,
        env=env,
    )

    steps = log.read_text(encoding="utf-8").splitlines()
    assert done.returncode != 0  # el error del motor llega a quien corrió post-refresh (la tarea semanal)
    assert "-m rappi_ia motor" in steps
    assert steps[-1] == "-m rappi_ia purge" and steps.index("-m rappi_ia motor") < len(steps) - 1
