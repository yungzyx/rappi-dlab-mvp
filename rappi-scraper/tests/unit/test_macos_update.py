"""deploy/macos/actualizar.sh (la demo desde un Mac se pone al día con origin/main) y los trabajos de launchd que
avisan (vigilante, purga, resumen y respaldo), corridos de verdad con /bin/bash (el 3.2 de macOS; en el CI de Ubuntu,
bash 5) sobre un clon con git real y `make`, `caddy`, `launchctl`, `osascript`, `curl` y `brew` falsos en el PATH."""

import os
import re
import subprocess
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "deploy" / "macos"


def _write_fake(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/bash\n{body}\n")
    path.chmod(0o755)


class Demo:
    """Un origin bare, una copia de trabajo para empujarle commits y el clon que se sirve (REPO_DIR), con TUNEL_DIR y
    los falsos: `make` anota cómo lo llamaron y falla mientras exista `make-falla`; `caddy validate` sale con lo que
    diga `caddy-falla`; `launchctl`, `osascript` y `curl` anotan (`curl` falla con las URL de `curl-falla` y, con
    `-w`, responde 401, lo de la puerta de Caddy); `sleep` no hace nada."""

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.rec = tmp_path / "rec"
        self.rec.mkdir()
        self.tunel = tmp_path / "rappi-tunel"
        self.tunel.mkdir()
        self.repo = tmp_path / "rappi-prod"
        self.work = tmp_path / "work"
        self.bin = tmp_path / "bin"
        (tmp_path / "gitconfig").write_text("[user]\n\tname = Prueba\n\temail = prueba@example.com\n")
        self.env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "HOME": str(tmp_path),
            "TUNEL_DIR": str(self.tunel),
            "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        self.git("init", "-q", "--bare", "-b", "main", str(tmp_path / "origin.git"))
        self.git("clone", "-q", str(tmp_path / "origin.git"), str(self.work))
        self.commit("README.md", "primera versión\n")
        self.git("clone", "-q", str(tmp_path / "origin.git"), str(self.repo))
        _write_fake(self.repo / "rappi-ia" / ".venv" / "bin" / "python", "exit 0")  # sin migraciones pendientes
        (self.tunel / "tunel.env").write_text(f"REPO_DIR='{self.repo}'\nLABEL=test\n")
        (self.tunel / "srv" / "app").mkdir(parents=True)  # lo que ya se servía
        _write_fake(self.bin / "brew", "exit 0")
        _write_fake(self.bin / "launchctl", f'echo "$*" >> {self.rec}/launchctl.txt')
        _write_fake(self.bin / "osascript", f'echo "$*" >> {self.rec}/osascript.txt')
        _write_fake(
            self.bin / "curl",
            f'echo "$*" >> {self.rec}/curl.txt\nfor a in "$@"; do url=$a; done\n'
            f'! grep -qxF "$url" {tmp_path}/curl-falla 2>/dev/null || exit 7\n'
            'case " $* " in *" -w "*) printf 401;; esac',
        )
        _write_fake(self.bin / "sleep", "exit 0")
        _write_fake(self.bin / "caddy", f'echo "$*" >> {self.rec}/caddy.txt; [ ! -e {tmp_path}/caddy-falla ]')
        _write_fake(
            self.bin / "make",
            f'echo "$*" >> {self.rec}/make.txt\n[ ! -e {tmp_path}/make-falla ] || exit 2\n'
            "mkdir -p prototipo-app/dist dashboard-empresa/dist",
        )

    def git(self, *args: str, cwd: Path | None = None) -> str:
        return subprocess.run(
            ["git", *args], cwd=cwd, env=self.env, check=True, capture_output=True, text=True
        ).stdout.strip()

    def commit(self, path: str, text: str) -> str:
        """Un commit nuevo en origin/main que cambia `path`; devuelve su sha."""
        (self.work / path).parent.mkdir(parents=True, exist_ok=True)
        (self.work / path).write_text(text)
        self.git("add", path, cwd=self.work)
        self.git("commit", "-q", "-m", f"cambia {path}", cwd=self.work)
        self.git("push", "-q", "origin", "HEAD:main", cwd=self.work)
        return self.git("rev-parse", "HEAD", cwd=self.work)

    def run(self, script: str = "actualizar.sh", *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["/bin/bash", str(SCRIPTS / script), *args], env=self.env, capture_output=True, text=True)

    def python(self, body: str) -> None:
        """El `.venv/bin/python` de rappi-ia del clon (el que corren purga.sh y resumen.sh)."""
        _write_fake(self.repo / "rappi-ia" / ".venv" / "bin" / "python", body)

    def recorded(self, name: str) -> list[str]:
        path = self.rec / f"{name}.txt"
        return path.read_text().splitlines() if path.exists() else []

    def deployed(self) -> str:
        return (self.tunel / "desplegado.txt").read_text().strip()


@pytest.fixture
def demo(tmp_path) -> Demo:
    return Demo(tmp_path)


def _config_python(demo: Demo) -> None:
    """El `.venv/bin/python` del clon, para el chequeo: responde OFFERS_CONTROL_PCT como `rappi_ia.config` (la variable
    del entorno, que trae tunel.env; si no está, la del .env de rappi-ia, porque load_dotenv no sobreescribe; si no,
    0), solo si lo llaman desde rappi-ia con ese import."""
    demo.python(
        'case "$*" in *"from rappi_ia import config"*"config.OFFERS_CONTROL_PCT"*) ;; *) exit 0;; esac\n'
        f'[ "$PWD" = "{demo.repo}/rappi-ia" ] || exit 1\n'
        'if [ -n "${OFFERS_CONTROL_PCT+x}" ]; then echo "$OFFERS_CONTROL_PCT"; exit 0; fi\n'
        "v=$(sed -n 's/^OFFERS_CONTROL_PCT=//p' .env 2>/dev/null | tail -n 1)\n"
        'echo "${v:-0}"'
    )


def test_a_failed_update_warns_and_the_next_round_retries(demo):
    """Antes, el merge iba primero: si un paso fallaba, la vuelta siguiente veía HEAD == origin/main, anotaba "Al día"
    y no reintentaba nunca. Ahora la referencia es lo que quedó desplegado, y un reintento vuelve a ver las
    dependencias que cambiaron."""
    first = demo.git("rev-parse", "HEAD", cwd=demo.repo)
    new = demo.commit("rappi-ia/requirements.lock.txt", "fastapi==1\n")
    (demo.tmp / "make-falla").touch()

    failed = demo.run()

    assert failed.returncode != 0
    assert demo.recorded("make") == ["-s install"]  # sin install-ml ni build: el fallo de install corta
    assert any("actualizar.sh falló en la línea" in line for line in demo.recorded("osascript"))
    assert demo.deployed() == first != new

    (demo.tmp / "make-falla").unlink()
    retried = demo.run()

    assert retried.returncode == 0, retried.stdout + retried.stderr
    assert "Al día" not in retried.stdout
    assert demo.recorded("make")[1:] == ["-s install", "-s -C rappi-ia install-ml", "-s build"]
    assert demo.deployed() == new == demo.git("rev-parse", "origin/main", cwd=demo.repo)
    assert (demo.tunel / "srv" / "app").is_dir() and (demo.tunel / "srv" / "panel").is_dir()
    assert any("Demo actualizada" in line for line in demo.recorded("osascript"))
    assert demo.recorded("launchctl") == [f"kickstart -k gui/{os.getuid()}/test.api"]

    third = demo.run()

    assert third.returncode == 0 and "Al día" in third.stdout
    assert len(demo.recorded("make")) == 4  # no volvió a construir


def test_a_new_caddyfile_restarts_caddy_after_validating_it(demo):
    demo.commit("deploy/macos/Caddyfile", ":8080 {}\n")

    result = demo.run()

    assert result.returncode == 0, result.stdout + result.stderr
    assert demo.recorded("caddy") == ["validate --config deploy/macos/Caddyfile --adapter caddyfile"]
    uid = os.getuid()
    assert demo.recorded("launchctl") == [f"kickstart -k gui/{uid}/test.caddy", f"kickstart -k gui/{uid}/test.api"]


def test_a_caddyfile_that_does_not_validate_keeps_the_old_one(demo):
    demo.commit("deploy/macos/Caddyfile", "esto no es un Caddyfile\n")
    (demo.tmp / "caddy-falla").touch()

    result = demo.run()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "El Caddyfile nuevo no valida: Caddy sigue con el anterior" in result.stdout
    assert demo.recorded("launchctl") == [f"kickstart -k gui/{os.getuid()}/test.api"]


def test_a_new_tunnel_script_restarts_it_only_with_a_fixed_url(demo):
    """Un túnel rápido cambiaría de URL al reiniciarse: solo avisa."""
    demo.commit("deploy/macos/tunel.sh", "# cambio\n")

    result = demo.run()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Cambió tunel.sh" in result.stdout
    assert not any(line.endswith(".tunel") for line in demo.recorded("launchctl"))

    with (demo.tunel / "tunel.env").open("a") as env:
        env.write("PUBLIC_URL=https://demo.example.com\n")
    demo.commit("deploy/macos/tunel.sh", "# otro cambio\n")
    demo.run()

    assert f"kickstart -k gui/{os.getuid()}/test.tunel" in demo.recorded("launchctl")


def test_a_pause_file_stops_updates_unless_forced(demo):
    """Durante la prueba con usuarios un despliegue reiniciaba la API y recargaba la pestaña del participante: con
    TUNEL_DIR/pausa-actualizar no se despliega nada, salvo con --forzar; al borrarlo, la vuelta siguiente se pone al
    día."""
    first = demo.git("rev-parse", "HEAD", cwd=demo.repo)
    new = demo.commit("rappi-ia/src/app.py", "x = 1\n")
    (demo.tunel / "pausa-actualizar").touch()

    paused = demo.run()

    assert paused.returncode == 0, paused.stdout + paused.stderr
    assert "Pausado" in paused.stdout
    assert demo.recorded("make") == [] and demo.recorded("launchctl") == []
    assert demo.git("rev-parse", "HEAD", cwd=demo.repo) == first != new

    forced = demo.run("actualizar.sh", "--forzar")

    assert forced.returncode == 0, forced.stdout + forced.stderr
    assert demo.recorded("make") == ["-s build"]
    assert demo.deployed() == new

    (demo.tunel / "pausa-actualizar").unlink()
    newer = demo.commit("rappi-ia/src/app.py", "x = 2\n")
    assert demo.run().returncode == 0
    assert demo.deployed() == newer


def test_a_docs_only_change_is_merged_without_building_or_restarting(demo):
    """El #87 solo tocaba 5 archivos .md y aun así construyó y reinició la API: nada se construye desde los .md."""
    docs = demo.commit("docs/guia.md", "# Guía\n")
    demo.commit("deploy/macos/README.md", "# Demo\n")

    result = demo.run()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Solo cambió documentación" in result.stdout
    assert demo.recorded("make") == [] and demo.recorded("launchctl") == []
    head = demo.git("rev-parse", "HEAD", cwd=demo.repo)
    assert demo.deployed() == head == demo.git("rev-parse", "origin/main", cwd=demo.repo) != docs
    assert "Al día" in demo.run().stdout

    demo.commit("docs/guia.md", "# Guía 2\n")
    code = demo.commit("prototipo-app/src/main.js", "x\n")
    assert demo.run().returncode == 0
    assert demo.recorded("make") == ["-s build"]  # un .md junto con código construye
    assert demo.deployed() == code

    assert demo.run("actualizar.sh", "--forzar").returncode == 0
    assert demo.recorded("make") == ["-s build", "-s build"]  # --forzar construye aunque no haya cambios

    # Un .js que pasa a .md: con la detección de renombres el diff solo nombraría el .md.
    demo.git("mv", "prototipo-app/src/main.js", "prototipo-app/src/notas.md", cwd=demo.work)
    demo.git("commit", "-q", "-m", "renombra main.js", cwd=demo.work)
    demo.git("push", "-q", "origin", "HEAD:main", cwd=demo.work)
    assert demo.run().returncode == 0
    assert demo.recorded("make") == ["-s build"] * 3

    # Un .md en public/ se copia a dist y se sirve.
    demo.commit("prototipo-app/public/ayuda.md", "# Ayuda\n")
    assert demo.run().returncode == 0
    assert demo.recorded("make") == ["-s build"] * 4


def test_the_session_check_marks_its_searches_and_warns_about_slow_ones(demo):
    """El chequeo de antes de cada participante solo lee, y sus búsquedas llevan un id con el prefijo que el resumen
    diario (rappi_ia/api/log_summary.py, UPKEEP_PREFIX) deja fuera de las visitas."""
    _write_fake(
        demo.bin / "curl",
        f'echo "$*" >> {demo.rec}/curl.txt\n'
        'case " $* " in\n'
        '  *"/health "*) echo \'{"ok":true,"documentos":3}\';;\n'
        f'  *"q=pizza"*) [ -e {demo.tmp}/lenta ] && printf "200 1.734" || printf "200 0.080";;\n'
        '  *) printf "200 0.120";;\n'
        "esac",
    )
    _write_fake(demo.bin / "psql", 'echo "tiendas 18-10-2026 · restaurantes 05-10-2026"')
    _write_fake(demo.bin / "pgrep", 'case " $* " in *" -P "*) echo 11;; *) echo 10;; esac')  # el proceso de la API
    _write_fake(demo.bin / "ps", 'echo " 51200"')
    _write_fake(demo.bin / "top", 'echo "PID MEM"; echo "1800M"')
    _config_python(demo)
    (demo.tunel / "pausa-actualizar").touch()

    result = demo.run("chequeo-sesion.sh")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "API: lista" in result.stdout and "Despliegues: en pausa" in result.stdout
    assert "Catálogo: tiendas 18-10-2026" in result.stdout
    assert "Proceso 11 de la API: RSS 50 MB, footprint 1800 MB (RSS/footprint 2 %)" in result.stdout
    assert "Máximo: 120 ms" in result.stdout and result.stdout.rstrip().endswith("Listo para la sesión")
    searches = [call for call in demo.recorded("curl") if "/search" in call]
    assert len(searches) == 8
    summary = (SCRIPTS.parents[1] / "rappi-ia" / "src" / "rappi_ia" / "api" / "log_summary.py").read_text()
    prefix = re.search(r'UPKEEP_PREFIX = "([^"]+)"', summary)[1]
    assert all(re.search(rf"-H X-Request-ID: {prefix}chequeo-\d+-[1-8] ", call) for call in searches)
    assert not any(call for call in demo.recorded("curl") if "-X" in call.split() or "--data " in call)

    (demo.tmp / "lenta").touch()
    (demo.tunel / "pausa-actualizar").unlink()
    slow = demo.run("chequeo-sesion.sh")

    assert slow.returncode == 1
    assert "pizza: 1734 ms (más de 1 s)" in slow.stdout and "Máximo: 1734 ms" in slow.stdout
    assert "los despliegues no están en pausa" in slow.stdout
    assert demo.recorded("osascript") == []  # un chequeo con avisos no es un trabajo que falló
    assert "Grupo de control: 0 %" in result.stdout  # sin la variable en tunel.env ni en rappi-ia/.env, apagado


def test_the_session_check_fails_with_the_control_group_on(demo):
    """Con OFFERS_CONTROL_PCT distinto de 0, a un participante se le pueden retener las ofertas: el chequeo lo calcula
    como la API (de tunel.env o, si no lo define, del .env de rappi-ia), lo dice y sale con 1. Si no lo puede calcular,
    tampoco da la sesión por lista. De esos archivos no imprime nada más."""
    _write_fake(
        demo.bin / "curl",
        'case " $* " in *"/health "*) echo \'{"ok":true}\';; *) printf "200 0.100";; esac',
    )
    _write_fake(demo.bin / "psql", "exit 0")
    _config_python(demo)
    (demo.tunel / "pausa-actualizar").touch()
    (demo.repo / "rappi-ia" / ".env").write_text("OFFERS_CONTROL_PCT=10\nAPI_SECRET=no-se-imprime-env\n")

    from_dotenv = demo.run("chequeo-sesion.sh")

    assert from_dotenv.returncode == 1, from_dotenv.stdout + from_dotenv.stderr
    assert "Grupo de control: 10 %" in from_dotenv.stdout
    assert "el grupo de control está en 10 %" in from_dotenv.stdout

    with (demo.tunel / "tunel.env").open("a") as env:
        env.write("OFFERS_CONTROL_PCT=20\nAPI_SECRET=no-se-imprime\n")
    from_tunel = demo.run("chequeo-sesion.sh")  # tunel.env gana: la API lo recibe en su entorno

    assert from_tunel.returncode == 1 and "Grupo de control: 20 %" in from_tunel.stdout
    for result in (from_dotenv, from_tunel):
        assert "no-se-imprime" not in result.stdout + result.stderr

    demo.python("exit 1")  # p. ej. un valor fuera de rango: rappi_ia.config no carga
    unreadable = demo.run("chequeo-sesion.sh")

    assert unreadable.returncode == 1 and "Grupo de control: no pude leerlo" in unreadable.stdout


def test_the_watchdog_marks_its_searches_and_beats_only_when_all_respond(demo):
    """Las búsquedas de calentamiento llevan el id que el resumen diario deja aparte, y el latido de HEARTBEAT_URL sale
    solo si la API, Caddy y el túnel respondieron: si no llega, avisa el monitor externo."""
    with (demo.tunel / "tunel.env").open("a") as env:
        env.write("HEARTBEAT_URL=https://latido.example.com/abc\n")

    assert demo.run("vigilante.sh").returncode == 0

    calls = demo.recorded("curl")
    searches = [call for call in calls if "/search?" in call]
    assert len(searches) == 2
    assert all(re.search(r"-H X-Request-ID: vigilante-\d+-[12] ", call) for call in searches)
    assert calls[-1].endswith(" https://latido.example.com/abc")

    (demo.rec / "curl.txt").unlink()
    (demo.tmp / "curl-falla").write_text("http://127.0.0.1:8080/\n")  # Caddy no responde
    result = demo.run("vigilante.sh")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "caddy no responde (1)" in result.stdout
    assert not any("latido" in call for call in demo.recorded("curl"))
    assert demo.recorded("osascript") == []  # una primera falla no avisa, y el $(curl …) que falla no es un error


def test_the_purge_logs_its_three_lines_and_warns_when_it_fails(demo):
    demo.python("echo 'Consultas borradas: 1'; echo 'Impresiones borradas: 2'; echo 'Usuarios borrados: 3'")

    result = demo.run("purga.sh")

    assert result.returncode == 0, result.stdout + result.stderr
    assert [line.split(" ", 2)[2] for line in result.stdout.splitlines()] == [
        "purga: Consultas borradas: 1",
        "purga: Impresiones borradas: 2",
        "purga: Usuarios borrados: 3",
    ]

    demo.python("echo 'Traceback: sin conexión'; exit 1")
    failed = demo.run("purga.sh")

    assert failed.returncode == 1
    assert "Traceback: sin conexión" in failed.stdout
    [notice] = demo.recorded("osascript")  # un solo aviso, el de la purga
    assert "La purga falló" in notice


def test_the_summary_reads_the_rotated_log_only_when_it_is_recent(demo):
    logs = demo.tunel / "logs"
    logs.mkdir()
    (logs / "api.log").write_text("")
    (logs / "api.log.1").write_text("")
    old = time.time() - 10 * 86400
    os.utime(logs / "api.log.1", (old, old))
    demo.python(f'echo "$*" >> {demo.rec}/python.txt; printf "Resumen\\n3 peticiones\\n"')

    assert demo.run("resumen.sh").returncode == 0
    os.utime(logs / "api.log.1")
    assert demo.run("resumen.sh").returncode == 0

    old_copy, recent_copy = demo.recorded("python")
    assert "api.log.1" not in old_copy and old_copy.endswith(f"--log {logs}/api.log")
    assert recent_copy.endswith(f"--log {logs}/api.log --log {logs}/api.log.1")
    assert "API de ayer: 3 peticiones" in demo.recorded("osascript")[-1]


def test_a_failed_dump_leaves_no_temporary_file(demo):
    _write_fake(demo.bin / "df", 'echo "Filesystem 1K-blocks Used Available"; echo "disco 1 1 999999999"')
    _write_fake(demo.bin / "pg_dump", 'for a in "$@"; do out=$a; done; echo parcial > "$out"; exit 1')

    result = demo.run("respaldo.sh")

    assert result.returncode != 0
    assert list((demo.tunel / "respaldos").iterdir()) == []
    assert any("respaldo.sh falló en la línea" in line for line in demo.recorded("osascript"))


def test_an_unreadable_deployed_file_falls_back_to_head(demo):
    """Un desplegado.txt vacío (una escritura que falló con el disco lleno) hacía morir cada vuelta en el git diff."""
    (demo.tunel / "desplegado.txt").write_text("")
    new = demo.commit("README.md", "segunda versión\n")

    result = demo.run()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "desplegado.txt no es un commit: comparo con HEAD" in result.stdout
    assert demo.deployed() == new
    assert not (demo.tunel / "desplegado.txt.tmp").exists()


def test_a_failed_migration_is_retried_without_a_new_backup(demo):
    """Un reintento no vuelve a respaldar: con RESPALDOS_A_GUARDAR=3, tres reintentos borraban el respaldo de antes del
    primer intento. Un despliegue nuevo, una vez que el anterior quedó bien, sí respalda."""
    _write_fake(demo.bin / "df", 'echo "Filesystem 1K-blocks Used Available"; echo "disco 1 1 999999999"')
    _write_fake(
        demo.bin / "pg_dump",
        f'echo "$*" >> {demo.rec}/pg_dump.txt; for a in "$@"; do out=$a; done; echo respaldo > "$out"',
    )
    _write_fake(demo.bin / "pg_restore", "exit 0")
    demo.python(f'case "$*" in *--solo-revisar*) exit 1;; esac; [ ! -e {demo.tmp}/migrate-falla ]')
    (demo.tmp / "migrate-falla").touch()
    first = demo.commit("rappi-scraper/src/rappi_scraper/storage/migrations/099_a.sql", "select 1;\n")

    assert demo.run().returncode != 0
    retried = demo.run()

    assert retried.returncode != 0
    assert "ya hay un respaldo de este despliegue" in retried.stdout
    assert len(demo.recorded("pg_dump")) == 1

    (demo.tmp / "migrate-falla").unlink()
    assert demo.run().returncode == 0
    assert demo.deployed() == first
    assert len(demo.recorded("pg_dump")) == 1

    demo.commit("rappi-scraper/src/rappi_scraper/storage/migrations/100_b.sql", "select 2;\n")
    assert demo.run().returncode == 0
    assert len(demo.recorded("pg_dump")) == 2
