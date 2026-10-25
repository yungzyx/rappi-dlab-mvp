"""El candado de la base de prueba (`scripts/with-test-db-lock.sh`) vive en la carpeta común de git: los worktrees de un
mismo repositorio comparten rappi_ia_test, así que comparten también el candado. Fuera de git queda en
rappi-ia/.test-db.lock, como antes."""

import os
import shutil
import subprocess
from pathlib import Path

from rappi_ia.config import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "with-test-db-lock.sh"
BUSY = "Otra prueba está usando rappi_ia_test"
# Sin las variables de git de quien corre las pruebas (un hook las pone): cada copia mira solo su carpeta.
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _copy_script(root: Path) -> Path:
    target = root / "rappi-ia" / "scripts" / SCRIPT.name
    target.parent.mkdir(parents=True)
    shutil.copy2(SCRIPT, target)
    return target


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", "-c", "user.name=prueba", "-c", "user.email=prueba@prueba", *args], cwd=cwd, env=ENV,
                   check=True, capture_output=True)  # fmt: skip


def _run(*command: str | Path) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in command], capture_output=True, text=True, env=ENV, timeout=30)


def test_two_worktrees_of_a_repository_share_the_lock(tmp_path):
    repo = tmp_path / "repo"
    script = _copy_script(repo)
    _git("init", "-q", cwd=repo)
    _git("add", ".", cwd=repo)
    _git("commit", "-qm", "candado", cwd=repo)
    _git("worktree", "add", "-q", str(tmp_path / "otro"), cwd=repo)
    other = tmp_path / "otro" / "rappi-ia" / "scripts" / SCRIPT.name

    # Mientras el del repositorio tiene el candado, el del otro worktree lo pide: está ocupado.
    nested = _run(script, other, "true")

    assert nested.returncode == 1, nested.stderr
    lock = (repo / ".git" / "rappi-ia-test-db.lock").resolve()
    assert BUSY in nested.stderr and f"rm -rf {lock}" in nested.stderr
    assert _run(other, "true").returncode == 0  # suelto, ya nadie lo tiene
    assert not lock.exists()


def test_outside_git_the_lock_is_next_to_rappi_ia(tmp_path):
    script = _copy_script(tmp_path)
    lock = tmp_path / "rappi-ia" / ".test-db.lock"

    assert _run(script, "test", "-d", lock).returncode == 0
    assert not lock.exists()
