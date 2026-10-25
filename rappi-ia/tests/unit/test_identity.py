"""Identidad anónima firmada: el token de cada persona (HMAC del id) y el secreto que lo firma."""

import stat

import pytest

from rappi_ia.api import identity

KEY = b"k" * 32


def test_sign_verify_roundtrip():
    token = identity.sign("proto-0123456789abcdef", KEY)

    assert token.startswith("proto-0123456789abcdef.")
    assert identity.verify(token, KEY) == "proto-0123456789abcdef"
    # Con el secreto de la API (el de los tests, API_SECRET en tests/conftest.py)
    assert identity.verify(identity.sign("u1")) == "u1"


def test_tampered_token_is_rejected():
    token = identity.sign("proto-0123456789abcdef", KEY)
    user, signature = token.rsplit(".", 1)
    other = identity.sign("proto-ffffffffffffffff", KEY).rsplit(".", 1)[1]

    assert identity.verify(f"proto-ffffffffffffffff.{signature}", KEY) is None  # otro id con la firma de este
    assert identity.verify(f"{user}.{other}", KEY) is None
    flipped = signature[:-1] + ("B" if signature.endswith("A") else "A")
    assert identity.verify(f"{user}.{flipped}", KEY) is None
    assert identity.verify(token, b"z" * 32) is None  # firmado con otro secreto
    for broken in (None, "", "sin-punto", f".{signature}", "proto-x.ñandú", f"{user}.{signature}\x00"):
        assert identity.verify(broken, KEY) is None


def test_production_requires_api_secret(tmp_path):
    path = tmp_path / "data" / "api-secret"

    with pytest.raises(RuntimeError, match=r"^Falta API_SECRET \(ver docs/despliegue\.md\)\.$"):
        identity.load_secret(None, production=True, path=path)
    with pytest.raises(RuntimeError, match="al menos 32 bytes"):
        identity.load_secret("corto", production=True, path=path)
    assert not path.exists()  # en producción nunca se crea el archivo local
    assert identity.load_secret("x" * 64, production=True, path=path) == b"x" * 64


def test_local_secret_file_is_0600_and_stable(tmp_path):
    path = tmp_path / "data" / "api-secret"

    first = identity.load_secret(None, production=False, path=path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert len(first) >= 32
    assert identity.load_secret(None, production=False, path=path) == first  # se crea una sola vez
    assert identity.load_secret("y" * 32, production=False, path=path) == b"y" * 32  # la variable manda


def test_a_stale_draft_of_the_secret_does_not_stop_the_api(tmp_path, monkeypatch):
    """Un borrador que quedó de otro arranque con el mismo pid (en un contenedor el pid se repite) no impide crearlo."""
    path = tmp_path / "data" / "api-secret"
    path.parent.mkdir()
    monkeypatch.setattr(identity.os, "getpid", lambda: 1)
    (path.parent / ".api-secret.1").write_text("a medio escribir")

    key = identity.load_secret(None, production=False, path=path)

    assert len(key) >= 32 and stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not (path.parent / ".api-secret.1").exists()


def test_a_short_secret_file_is_named_in_the_error(tmp_path):
    path = tmp_path / "api-secret"
    path.write_text("")

    with pytest.raises(RuntimeError, match=f"{path}"):
        identity.load_secret(None, production=False, path=path)


def test_require_user_says_401_without_session_and_403_for_someone_else():
    from fastapi import HTTPException

    identity.require_user("u1", "u1")
    with pytest.raises(HTTPException) as missing:
        identity.require_user("u1", None)
    with pytest.raises(HTTPException) as other:
        identity.require_user("u1", "u2")

    assert (missing.value.status_code, missing.value.detail) == (401, "Falta la sesión")
    assert (other.value.status_code, other.value.detail) == (403, "No autorizado")


def test_cli_token_signs_with_the_api_secret(capsys):
    from rappi_ia import cli

    cli.main(["token", "proto-0123456789abcdef"])

    printed = capsys.readouterr().out.strip()
    assert printed == identity.sign("proto-0123456789abcdef")
    assert identity.verify(printed) == "proto-0123456789abcdef"
