"""La puerta de acceso de deploy/Caddyfile (el servidor) y deploy/macos/Caddyfile (la demo desde un Mac), con un
`caddy` de verdad: sin PANEL_AUTH_*, la misma puerta abre todo el sitio, como antes; con ellas, /panel y /api/analytics
piden la credencial del panel y no la de la puerta. Se salta si `caddy` no está instalado (en el CI lo cubre
deploy/smoke.sh contra el stack, con el panel y su credencial)."""

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from base64 import b64encode
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[3] / "deploy"
CADDY = shutil.which("caddy")
pytestmark = pytest.mark.skipif(CADDY is None, reason="sin caddy")

DEMO = ("demo", "clave-de-la-puerta")
PANEL = ("panel", "clave-del-panel")
PANEL_PATHS = ["/panel", "/panel/", "/api/analytics/kpis", "/api//analytics/kpis", "/api/%61nalytics/kpis"]
APP_PATHS = ["/", "/api/search?q=pan"]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _hash(password: str) -> str:
    return subprocess.run(
        [CADDY, "hash-password", "--plaintext", password, "--algorithm", "bcrypt", "--bcrypt-cost", "4"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _status(port: int, path: str, account: tuple[str, str] | None) -> int:
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    if account:
        request.add_header("Authorization", "Basic " + b64encode(":".join(account).encode()).decode())
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


@pytest.fixture(params=["servidor", "mac"])
def caddy(request, tmp_path):
    """Arranca el Caddyfile pedido (sin la API detrás: lo que pasa la puerta da 502 o 404, nunca 401) y devuelve su
    puerto. El del servidor, adaptado a JSON y sin su API de administración (el :2019 de este equipo)."""

    def start(panel: bool) -> int:
        port = _free_port()
        srv = tmp_path / "srv"
        for app in ("app", "panel"):
            (srv / app).mkdir(parents=True, exist_ok=True)
            (srv / app / "index.html").write_text("<!doctype html>")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("BASIC_AUTH_", "PANEL_AUTH_"))}
        env.update(BASIC_AUTH_USER=DEMO[0], BASIC_AUTH_HASH=_hash(DEMO[1]), HOME=str(tmp_path))
        if panel:
            env.update(PANEL_AUTH_USER=PANEL[0], PANEL_AUTH_HASH=_hash(PANEL[1]))
        if request.param == "mac":
            env.update(SRV_DIR=str(srv), CADDY_PORT=str(port), API_PORT=str(_free_port()))
            config, adapter = DEPLOY / "macos" / "Caddyfile", ["--adapter", "caddyfile"]
        else:
            env.update(DOMAIN=f"http://127.0.0.1:{port}")
            adapted = subprocess.run(
                [CADDY, "adapt", "--config", str(DEPLOY / "Caddyfile"), "--adapter", "caddyfile"],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            settings = json.loads(adapted.stdout)
            settings["admin"] = {"disabled": True}
            config, adapter = tmp_path / "caddy.json", []
            config.write_text(json.dumps(settings))
        command = [CADDY, "run", "--config", str(config), *adapter]
        process = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        started.append(process)
        deadline = time.monotonic() + 15
        while _status_or_none(port) is None:
            assert process.poll() is None, process.stderr.read().decode()
            assert time.monotonic() < deadline, "Caddy no respondió"
            time.sleep(0.1)
        return port

    started: list[subprocess.Popen] = []
    yield start
    for process in started:
        process.terminate()
        process.wait(timeout=10)


def _status_or_none(port: int) -> int | None:
    try:
        return _status(port, "/", None)
    except OSError:
        return None


def test_without_a_panel_credential_the_gate_opens_everything_as_before(caddy):
    port = caddy(panel=False)

    for path in APP_PATHS + PANEL_PATHS:
        assert _status(port, path, None) == 401, path
        assert _status(port, path, DEMO) != 401, path


def test_with_a_panel_credential_only_it_opens_the_panel_and_its_api(caddy):
    """Antes la misma clave de la demo, que se reparte a quienes prueban la app, abría /panel y /api/analytics
    (audiencias con ids por persona y los juicios de la búsqueda, que escriben)."""
    port = caddy(panel=True)

    for path in PANEL_PATHS:
        assert _status(port, path, None) == 401, path
        assert _status(port, path, DEMO) == 401, path
        assert _status(port, path, PANEL) != 401, path
    for path in APP_PATHS:
        assert _status(port, path, DEMO) != 401, path
        assert _status(port, path, PANEL) == 401, path
