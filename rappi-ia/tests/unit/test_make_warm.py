"""`make warm` calienta también el momento `perfil` de /agent/offer, una vez por perfil y sin persona: después de
arrancar, la primera escalera tardaba 4 a 5 s."""

import subprocess
import sys

from rappi_ia.config import PROJECT_ROOT
from rappi_ia.offers.profiles import load_profiles


def test_warm_asks_for_the_ladder_of_every_profile():
    dry_run = subprocess.run(
        ["make", "-n", "-C", str(PROJECT_ROOT), "warm"], capture_output=True, text=True, check=True
    ).stdout

    loop = f"for p in {' '.join(load_profiles())}; do"
    assert loop in dry_run
    calls = dry_run[dry_run.index(loop) :]
    assert "/agent/offer" in calls and '\\"moment\\": \\"perfil\\"' in calls and '\\"perfil\\": \\"$p\\"' in calls


def test_warm_reads_the_catalog_lists_of_the_home():
    """Las listas del catálogo viven en la caché de la API: en frío, /catalog/home tardaba 2,7 s."""
    from rappi_scraper.storage.search import VERTICALS

    # Con el Python de los tests: en el CI no hay `.venv/bin/python`.
    warm = subprocess.run(
        ["make", "-n", "-C", str(PROJECT_ROOT), "warm", f"PY={sys.executable}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    for path in ("/catalog/home", "/catalog/deals", "/catalog/restaurants?sort=rating&limit=6"):
        assert path in warm, path
    assert "/catalog/verticals/{v}/stores" in warm and "VERTICALS" in warm
    listed = subprocess.run(
        ["sh", "-c", warm[warm.index("$(") + 2 : warm.index("); do")]],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert listed == [f"/catalog/verticals/{v}/stores" for v in VERTICALS]
