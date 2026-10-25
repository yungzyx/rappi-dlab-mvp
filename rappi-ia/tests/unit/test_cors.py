import re

from rappi_ia.api.app import cors_origin_regex


def allowed(origin: str, allow_lan: bool) -> bool:
    return re.fullmatch(cors_origin_regex(allow_lan), origin) is not None


def test_only_this_mac_by_default():
    assert allowed("http://localhost:5174", False)
    assert allowed("http://127.0.0.1:5175", False)
    assert not allowed("http://192.168.1.20:5174", False)
    assert not allowed("http://172.20.10.2:5174", False)


def test_lan_mode_admits_the_iphone_hotspot_and_local_hostnames():
    """Con el hotspot del iPhone el equipo queda en 172.20.10.x; en la red de casa también sirve `nombre.local`."""
    for origin in (
        "http://192.168.1.20:5174",
        "http://10.0.0.7:5175",
        "http://172.20.10.2:5174",
        "http://172.16.0.9:5174",
        "http://mi-mac.local:5174",
    ):
        assert allowed(origin, True), origin


def test_lan_mode_still_rejects_other_hosts_and_ports():
    for origin in (
        "http://172.32.0.1:5174",  # fuera de 172.16.0.0/12
        "http://evil.example.com:5174",
        "http://192.168.1.20:8080",
        "https://localhost:5174",
    ):
        assert not allowed(origin, True), origin


def test_preflight_allows_delete_for_the_profile():
    from fastapi.testclient import TestClient

    from rappi_ia.api.app import app

    reply = TestClient(app).options(
        "/profile/u-1",
        headers={
            "Origin": "http://localhost:5174",
            "Access-Control-Request-Method": "DELETE",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert reply.status_code == 200
    assert "DELETE" in reply.headers["access-control-allow-methods"]
