"""deploy/smoke.sh contra un sitio y un stack falsos (un `curl` y un `docker compose` de mentira): revisa el aviso de
demo no oficial en la app y el entorno de cada servicio, también el de jobs (que no corre), y un `exec` que falla no
cuenta como bien."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from rappi_ia.config import PROJECT_ROOT

SMOKE = PROJECT_ROOT.parent / "deploy" / "smoke.sh"
NOTICE = "Demo no oficial · prototipo independiente, no afiliado a Rappi"
CSP = "default-src 'self'; img-src 'self' https://images.rappi.cl data:; connect-src 'self'; frame-ancestors 'none'"
SITE_HEADERS = [
    "strict-transport-security: max-age=31536000",
    f"content-security-policy: {CSP}",
    "x-content-type-options: nosniff",
    "referrer-policy: no-referrer",
    "x-robots-tag: noindex, nofollow",
    "permissions-policy: camera=(), microphone=(), geolocation=()",
    "cache-control: no-cache",
]

FAKE_CURL = """
import json, os, sys
site = json.load(open(os.environ["FAKE_SITE"]))
args, out, fmt, dump, authed, url, i = sys.argv[1:], None, None, False, False, None, 0
while i < len(args):
    arg = args[i]
    if arg in ("-o", "-w", "-D", "-K"):
        value = args[i + 1]
        if arg == "-o": out = value
        if arg == "-w": fmt = value
        if arg == "-D": dump = True
        if arg == "-K": authed = "user" in sys.stdin.read()
        i += 2
        continue
    if not arg.startswith("-"): url = arg
    i += 1
path = "/" + url.split("://", 1)[1].partition("/")[2]
page = site.get(path, {"body": "", "headers": []}) if authed else {"body": "", "headers": [], "code": 401}
code = str(page.get("code", 200))
if dump: sys.stdout.write("HTTP/2 " + code + "\\r\\n" + "".join(h + "\\r\\n" for h in page["headers"]) + "\\r\\n")
if out is None: sys.stdout.write(page["body"])
if fmt: sys.stdout.write(fmt.replace("\\\\n", "\\n").replace("%{http_code}", code))
"""

FAKE_COMPOSE = """
import json, os, sys
stack = json.load(open(os.environ["FAKE_STACK"]))
args = sys.argv[1:]
if args[0] == "ps":
    with_status = args[args.index("--format") + 1] != "{{.Service}}"
    for service in stack["running"]:
        print(f"{service} Up 2 minutes (healthy)" if with_status else service)
    sys.exit(0)
service = next(a for a in args[1:] if not a.startswith("-"))
script = args[-1]
if (args[0] == "exec" and service not in stack["running"]) or service in stack.get("broken", []):
    print(f"service {service!r} is not running", file=sys.stderr)
    sys.exit(1)
if "DROP TABLE" in script:
    print("ERROR:  must be owner of table app_events")
    sys.exit(3)
if "psql -U postgres" in script:
    print("0\\nf")
    sys.exit(0)
if "cambiar-esto" in script:
    print(stack.get("left", {}).get(service, ""), end="")
    sys.exit(0)
sys.exit(f"falso: no sé qué hacer con {args}")
"""


def _fake(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(0o755)
    return path


def _site(entry_js: str) -> dict:
    index = (
        '<!doctype html><html><head><meta name="description" content="Demo no oficial: prototipo independiente.">'
        '<script type="module" crossorigin src="/assets/index-abc.js"></script>'
        '<link rel="stylesheet" crossorigin href="/assets/index-abc.css"></head><body></body></html>'
    )
    asset_headers = ["cache-control: private, max-age=31536000, immutable"]
    return {
        "/": {"body": index, "headers": SITE_HEADERS},
        "/api/health": {"body": '{"ok":true,"busqueda_semantica":true}', "headers": []},
        "/api/live": {"body": "{}", "headers": [f"content-security-policy: {CSP}"]},
        "/assets/index-abc.js": {"body": entry_js, "headers": asset_headers},
        "/assets/index-abc.css": {"body": "body{}", "headers": asset_headers},
    }


def _smoke(tmp_path: Path, entry_js: str = f'x("{NOTICE}")', **stack) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake(bin_dir / "curl", FAKE_CURL)
    compose = _fake(tmp_path / "fake-compose", FAKE_COMPOSE)
    (tmp_path / "site.json").write_text(json.dumps(_site(entry_js)), encoding="utf-8")
    (tmp_path / "stack.json").write_text(json.dumps({"running": ["api", "db", "web"], **stack}), encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "COMPOSE": str(compose),
        "FAKE_SITE": str(tmp_path / "site.json"),
        "FAKE_STACK": str(tmp_path / "stack.json"),
        "BASIC_AUTH_USER": "demo",
        "BASIC_AUTH_PASSWORD": "clave-de-prueba",
    }
    return subprocess.run(["bash", str(SMOKE), "https://ejemplo.test"], env=env, capture_output=True, text=True)


def test_a_healthy_stack_passes(tmp_path):
    result = _smoke(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "el aviso «Demo no oficial» está en la app" in result.stdout
    assert "jobs sin «cambiar-esto»" in result.stdout


def test_a_build_without_the_demo_notice_fails(tmp_path):
    result = _smoke(tmp_path, entry_js='x("Hola")')

    assert result.returncode == 1
    assert "falta el aviso «Demo no oficial»" in result.stderr


@pytest.mark.parametrize("service", ["api", "jobs"])
def test_an_example_value_left_in_a_service_fails(tmp_path, service):
    result = _smoke(tmp_path, left={service: "API_SECRET "})

    assert result.returncode == 1
    assert f"{service} tiene «cambiar-esto» en: API_SECRET" in result.stderr


@pytest.mark.parametrize("service", ["api", "jobs"])
def test_an_environment_that_cannot_be_read_fails(tmp_path, service):
    result = _smoke(tmp_path, broken=[service])

    assert result.returncode == 1
    assert f"no se pudo leer el entorno de {service}" in result.stderr
