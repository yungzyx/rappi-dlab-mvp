"""prototipo-app/scripts/demo-photos-gate.py: las fotos de la demo sin conexión se bajan con los candados, el robots.txt
y el User-Agent del scraper. Corrido de verdad con este Python, contra un servidor local (nunca images.rappi.cl)."""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from rappi_scraper import config
from rappi_scraper.lock import file_lock

GATE = Path(__file__).resolve().parents[3] / "prototipo-app" / "scripts" / "demo-photos-gate.py"


@pytest.fixture
def site():
    """Un sitio local cuyo robots.txt no permite /privado; anota los User-Agent que le llegan."""
    agents: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            agents.append(self.headers["User-Agent"])
            body = b"User-agent: *\nDisallow: /privado\n" if self.path == "/robots.txt" else b""
            self.send_response(200 if body else 404)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", agents
    server.shutdown()


def _start(tmp_path: Path, urls: list[str]) -> tuple[subprocess.Popen, dict]:
    env = {**os.environ, "RAPPI_DATA_DIR": str(tmp_path), "DATABASE_URL": ""}
    gate = subprocess.Popen(
        [sys.executable, str(GATE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env, text=True
    )
    gate.stdin.write(json.dumps(urls) + "\n")
    gate.stdin.flush()
    return gate, json.loads(gate.stdout.readline())


def test_it_answers_the_scraper_user_agent_and_holds_the_lock_until_stdin_closes(tmp_path, site):
    base, agents = site
    gate, answer = _start(tmp_path, [f"{base}/fotos/a.png"])
    assert answer == {"user_agent": config.USER_AGENT}
    assert agents == [config.USER_AGENT]  # robots.txt, pedido con el User-Agent del scraper
    second, busy = _start(tmp_path, [f"{base}/fotos/a.png"])
    assert "descarga en curso" in busy["busy"]
    assert second.wait(10) == 1
    gate.stdin.close()
    assert gate.wait(10) == 0
    with file_lock(tmp_path / "scraper.lock"):  # lo soltó
        pass


def test_it_stops_with_7_when_robots_does_not_allow_one(tmp_path, site):
    base, _ = site
    gate, answer = _start(tmp_path, [f"{base}/fotos/a.png", f"{base}/privado/b.png"])
    assert "no permite /privado/b.png" in answer["denial"]
    assert gate.wait(10) == 7


def test_it_says_so_when_another_download_has_the_lock(tmp_path, site):
    base, agents = site
    with file_lock(tmp_path / "scraper.lock"):
        gate, answer = _start(tmp_path, [f"{base}/fotos/a.png"])
    assert "descarga en curso" in answer["busy"]
    assert gate.wait(10) == 1
    assert agents == []  # ni siquiera robots.txt
