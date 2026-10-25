"""Respaldo de la base con `pg_dump` (formato custom) y rotación de respaldos antiguos."""

import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict, make_conninfo

from ..config import DATA_DIR

log = logging.getLogger(__name__)

BACKUPS_DIR = DATA_DIR / "backups"
KEEP_BACKUPS = 4  # con corridas semanales: el último mes

# postgresql@17 de Homebrew no queda en el PATH (y launchd no carga el PATH del usuario).
_PG_DUMP_CANDIDATES = (
    "/opt/homebrew/opt/postgresql@17/bin/pg_dump",  # Apple Silicon
    "/usr/local/opt/postgresql@17/bin/pg_dump",  # Intel
)


def find_pg_dump() -> str:
    for candidate in (os.environ.get("PG_DUMP"), shutil.which("pg_dump"), *_PG_DUMP_CANDIDATES):
        if candidate and Path(candidate).exists():
            return candidate
    raise RuntimeError("No se encontró pg_dump (instala postgresql@17 o define PG_DUMP en .env)")


def rotate_backups(backups_dir: Path, keep: int, prefix: str = "rappi") -> list[Path]:
    """Borra los respaldos `<prefix>_*.dump` más antiguos, dejando los `keep` más nuevos. Devuelve los borrados."""
    dumps = sorted(backups_dir.glob(f"{prefix}_*.dump"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = dumps[keep:]
    for path in removed:
        path.unlink()
    return removed


def connection_args(database_url: str) -> tuple[list[str], dict[str, str]]:
    """Argumentos de conexión de `pg_dump` y su entorno. La clave va en PGPASSWORD y nunca en el argv, que `ps` muestra
    durante todo el volcado y que un error dejaba escrito en los logs. Lo que no es host, puerto ni usuario (la base y
    opciones como sslmode) va en `--dbname` como conninfo, sin la clave."""
    params = conninfo_to_dict(database_url)
    password = params.pop("password", None)
    flags = {"host": "--host", "port": "--port", "user": "--username"}
    args = [f"{flag}={params.pop(key)}" for key, flag in flags.items() if params.get(key)]
    args.append(f"--dbname={make_conninfo(**params)}")
    env = {**os.environ, "PGPASSWORD": str(password)} if password else None
    return args, env


def backup_database(
    database_url: str, backups_dir: Path = BACKUPS_DIR, keep: int = KEEP_BACKUPS, prefix: str = "rappi"
) -> Path:
    """Vuelca a `.part`, lo valida con `pg_restore --list` y recién entonces lo renombra y rota: un volcado cortado
    (disco lleno, corte de luz) nunca pasa por el respaldo más nuevo ni expulsa uno sano. Cada `prefix` rota aparte (el
    de antes de migrar, `pre-migracion`, no expulsa a los semanales)."""
    backups_dir.mkdir(parents=True, exist_ok=True)
    target = backups_dir / f"{prefix}_{datetime.now():%Y%m%d-%H%M%S}.dump"
    partial = target.with_name(target.name + ".part")
    pg_dump = find_pg_dump()
    args, env = connection_args(database_url)
    try:
        run_tool("pg_dump", [pg_dump, "--format=custom", "--no-owner", f"--file={partial}", *args], env=env)
        pg_restore = str(Path(pg_dump).with_name("pg_restore"))
        run_tool("pg_restore --list", [pg_restore, "--list", str(partial)], stdout=subprocess.DEVNULL)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    partial.rename(target)
    removed = rotate_backups(backups_dir, keep, prefix)
    log.info("Respaldo en %s (%d antiguos borrados)", target, len(removed))
    return target


def run_tool(name: str, cmd: list[str], **kwargs) -> None:
    """Como `subprocess.run(check=True)`, pero el error dice solo el código: el de subprocess trae el argv entero."""
    try:
        subprocess.run(cmd, check=True, **kwargs)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"{name} falló con código {exc.returncode}") from None
