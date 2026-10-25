"""deploy/scripts/backup-nightly.sh (el respaldo nocturno del servidor), corrido de verdad con `pg_dump`, `pg_restore` y
`restic` falsos en el PATH."""

import os
import subprocess
from pathlib import Path

BACKUP = Path(__file__).resolve().parents[3] / "deploy" / "scripts" / "backup-nightly.sh"
PASSWORD = "clave-de-prueba"
URL = f"postgresql://rappi_owner:{PASSWORD}@db:5432/rappi"


def _write_fake(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/bash\n{body}\n")
    path.chmod(0o755)


def _fakes(tmp_path: Path, list_ok: bool = True) -> Path:
    """`pg_dump` anota su argv y el archivo de claves (contenido, permisos y ruta) y escribe el volcado; `pg_restore
    --list` lo da por bueno (o no, con `list_ok=False`); `restic` anota cómo lo llamaron."""
    bin_dir = tmp_path / "bin"
    rec = tmp_path / "rec"
    rec.mkdir()
    _write_fake(
        bin_dir / "pg_dump",
        f"""printf '%s\\n' "$@" > {rec}/argv.txt
echo "$PGPASSFILE" > {rec}/passfile-path.txt
cat "$PGPASSFILE" > {rec}/passfile.txt
ls -l "$PGPASSFILE" | cut -c1-10 > {rec}/passfile-mode.txt
for arg in "$@"; do case $arg in --file=*) echo volcado > "${{arg#--file=}}";; esac; done""",
    )
    _write_fake(bin_dir / "pg_restore", f'[ "$1" = --list ] && exit {0 if list_ok else 1}; exit 3')
    _write_fake(bin_dir / "restic", f'echo "$*" >> {rec}/restic.txt')
    return bin_dir


def _run(tmp_path: Path, bin_dir: Path, **extra: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("RESTIC_", "PG"))}
    env.update(
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        DATABASE_URL=URL,
        RAPPI_DATA_DIR=str(tmp_path / "data"),
        RESTIC_REPOSITORY=str(tmp_path / "restic"),
        RESTIC_PASSWORD="otra-clave",
    )
    env.update(extra)
    return subprocess.run(["bash", BACKUP], env=env, capture_output=True, text=True)


def _backups(tmp_path: Path) -> Path:
    return tmp_path / "data" / "backups"


def test_backup_uses_passfile_not_argv(tmp_path):
    """La clave nunca en el argv (`ps` lo muestra durante todo el volcado): en un archivo temporal 0600 que se borra al
    terminar."""
    bin_dir = _fakes(tmp_path)

    result = _run(tmp_path, bin_dir)

    assert result.returncode == 0, result.stderr
    rec = tmp_path / "rec"
    argv = (rec / "argv.txt").read_text()
    assert PASSWORD not in argv
    assert "--dbname=postgresql://rappi_owner@db:5432/rappi" in argv.splitlines()
    assert (rec / "passfile.txt").read_text() == f"*:*:*:*:{PASSWORD}\n"
    assert (rec / "passfile-mode.txt").read_text().strip() == "-rw-------"
    assert not Path((rec / "passfile-path.txt").read_text().strip()).exists()
    assert PASSWORD not in result.stdout + result.stderr
    [dump] = _backups(tmp_path).glob("nocturno_*.dump")
    assert dump.read_text() == "volcado\n"
    restic = (rec / "restic.txt").read_text().splitlines()
    assert restic[0].startswith("backup ") and restic[0].endswith(str(dump))
    assert "forget" in restic[1] and restic[1].endswith("--keep-daily 7 --keep-weekly 4 --prune")


def test_backup_without_restic_warns_and_exits_2(tmp_path):
    """Sin RESTIC_REPOSITORY respalda igual en el volumen, pero el timer queda en rojo: no hay copia afuera."""
    bin_dir = _fakes(tmp_path)

    result = _run(tmp_path, bin_dir, RESTIC_REPOSITORY="")

    assert result.returncode == 2
    assert "Sin copia fuera del equipo: define RESTIC_REPOSITORY (docs/despliegue.md)." in result.stderr
    assert len(list(_backups(tmp_path).glob("nocturno_*.dump"))) == 1
    assert not (tmp_path / "rec" / "restic.txt").exists()


def test_backup_keeps_three_local(tmp_path):
    """Quedan los 3 nocturnos más nuevos; los semanales de `rappi refresh` y los de antes de migrar tienen su propia
    rotación y no se tocan."""
    backups = _backups(tmp_path)
    backups.mkdir(parents=True)
    old = [f"nocturno_2026100{day}-040000.dump" for day in range(1, 6)]
    others = ["rappi_20261004-030000.dump", "pre-migracion_20260901-120000.dump"]
    for age, name in enumerate([*reversed(old), *others]):
        (backups / name).write_text("antiguo\n")
        os.utime(backups / name, (1_700_000_000 - age * 86400, 1_700_000_000 - age * 86400))

    result = _run(tmp_path, _fakes(tmp_path))

    assert result.returncode == 0, result.stderr
    nightly = sorted(p.name for p in backups.glob("nocturno_*.dump"))
    assert len(nightly) == 3
    assert nightly[:2] == old[-2:]  # los dos más nuevos de antes y el de hoy
    assert all((backups / name).exists() for name in others)


def test_broken_dump_is_not_kept(tmp_path):
    """Un volcado que `pg_restore --list` no puede leer no expulsa a los buenos ni sube a restic."""
    backups = _backups(tmp_path)
    backups.mkdir(parents=True)
    for day in range(1, 4):
        (backups / f"nocturno_2026100{day}-040000.dump").write_text("bueno\n")

    result = _run(tmp_path, _fakes(tmp_path, list_ok=False))

    assert result.returncode != 0
    assert sorted(p.name for p in backups.iterdir()) == [f"nocturno_2026100{day}-040000.dump" for day in range(1, 4)]
    assert not (tmp_path / "rec" / "restic.txt").exists()


def test_passfile_decodes_and_escapes_the_password(tmp_path):
    """Una clave con «:» o «\\» llega en la URL como %3A y %5C; en el archivo de claves van escapadas."""
    bin_dir = _fakes(tmp_path)

    result = _run(tmp_path, bin_dir, DATABASE_URL="postgresql://rappi_owner:a%3Ab%5Cc@db:5432/rappi")

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "rec" / "passfile.txt").read_text() == "*:*:*:*:a\\:b\\\\c\n"
    assert "--dbname=postgresql://rappi_owner@db:5432/rappi" in (tmp_path / "rec" / "argv.txt").read_text()


def test_leftover_partial_dumps_are_removed(tmp_path):
    """Un volcado cortado de golpe (SIGKILL, apagado) no corre el trap y deja su .part: el siguiente lo borra. Uno
    reciente puede ser de otro respaldo en curso y queda."""
    backups = _backups(tmp_path)
    backups.mkdir(parents=True)
    (backups / "nocturno_20261001-040000.dump.part").write_text("cortado\n")
    os.utime(backups / "nocturno_20261001-040000.dump.part", (1_700_000_000, 1_700_000_000))
    (backups / "nocturno_20261011-040000.dump.part").write_text("en curso\n")

    result = _run(tmp_path, _fakes(tmp_path))

    assert result.returncode == 0, result.stderr
    assert not (backups / "nocturno_20261001-040000.dump.part").exists()
    assert (backups / "nocturno_20261011-040000.dump.part").exists()


SYSTEMD = BACKUP.parents[1] / "systemd"


def _directives(unit: str) -> list[str]:
    return [line for line in (SYSTEMD / unit).read_text().splitlines() if line and not line.startswith("#")]


def _exec_starts(unit: str) -> list[str]:
    return [line for line in _directives(unit) if line.startswith("ExecStart")]


def test_backup_and_purge_are_independent_units():
    """Un fallo de la purga nunca deja sin respaldo esa noche: cada uno es su propio servicio, con su propio timer."""
    [purge] = _exec_starts("rappi-purge.service")
    [backup] = _exec_starts("rappi-backup.service")
    assert purge.endswith("run --rm jobs rappi-ia purge")
    assert backup.endswith("run --rm jobs bash deploy/scripts/backup-nightly.sh")
    assert not any("rappi-purge" in line for line in _directives("rappi-backup.service"))  # sin Requires ni After
    assert not any("rappi-backup" in line for line in _directives("rappi-purge.service"))
    assert "OnCalendar=*-*-* 04:00 America/Santiago" in (SYSTEMD / "rappi-purge.timer").read_text()
    assert "OnCalendar=*-*-* 04:15 America/Santiago" in (SYSTEMD / "rappi-backup.timer").read_text()
    assert not list(SYSTEMD.glob("rappi-daily.*"))


def test_rotation_keeps_the_newest_by_date_not_by_name(tmp_path):
    """Con otra zona horaria (o un reloj corregido) un respaldo nuevo puede tener un nombre «anterior» a los de antes:
    la rotación va por fecha de modificación y el recién hecho nunca se borra."""
    backups = _backups(tmp_path)
    backups.mkdir(parents=True)
    later_names = [f"nocturno_2099010{day}-040000.dump" for day in range(1, 5)]
    for age, name in enumerate(reversed(later_names)):
        (backups / name).write_text("antiguo\n")
        os.utime(backups / name, (1_700_000_000 - age * 86400, 1_700_000_000 - age * 86400))

    result = _run(tmp_path, _fakes(tmp_path))

    assert result.returncode == 0, result.stderr
    remaining = sorted(p.name for p in backups.glob("nocturno_*.dump"))
    assert len(remaining) == 3
    assert later_names[-2:] == [name for name in remaining if name.startswith("nocturno_2099")]
    [new] = [name for name in remaining if not name.startswith("nocturno_2099")]
    assert (tmp_path / "rec" / "restic.txt").read_text().splitlines()[0].endswith(new)
