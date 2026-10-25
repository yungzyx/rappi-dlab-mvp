"""`make serve` y `make serve-lan` pasan por la guardia de migraciones antes de migrar (igual que `make mvp`)."""

import subprocess

import pytest

from rappi_ia.config import PROJECT_ROOT


@pytest.mark.parametrize("target", ["serve", "serve-lan"])
def test_serve_checks_migrations_before_migrating_and_serving(target):
    dry_run = subprocess.run(
        ["make", "-n", "-C", str(PROJECT_ROOT), target], capture_output=True, text=True, check=True
    ).stdout

    assert "rappi_ia check-migrations" in dry_run
    assert dry_run.index("rappi_ia check-migrations") < dry_run.index("rappi_ia migrate") < dry_run.index("uvicorn")
