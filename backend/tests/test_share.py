"""Phone sharing over the hotspot, and the power-off button."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from photobox.app import create_app
from photobox.config import CameraConfig, Config, HotspotConfig, SystemConfig, load_config
from photobox.share import ShareLinks, pick_language

LOCAL = "http://127.0.0.1:8000"
# TestClient reports the server as ("testserver", 80); pretend that is the hotspot side
PHONE = "http://testserver"


def make_cfg(tmp_path: Path, **kw) -> Config:
    return Config(
        photos_dir=tmp_path / "photos",
        frontend_dir=tmp_path / "no-frontend",
        camera=CameraConfig(driver="mock", preview_size=(320, 240), still_size=(640, 480)),
        hotspot=HotspotConfig(enabled=True, ssid="Photobox", password="secret-pass", address="testserver", port=80),
        **kw,
    )


@pytest.fixture
def local(tmp_path: Path):
    with TestClient(create_app(make_cfg(tmp_path)), base_url=LOCAL) as c:
        yield c


def phone_client(app) -> TestClient:
    return TestClient(app, base_url=PHONE)


def local_and_phone(tmp_path: Path, **kw):
    app = create_app(make_cfg(tmp_path, **kw))
    return TestClient(app, base_url=LOCAL), TestClient(app, base_url=PHONE)


# ---------------------------------------------------------------- links


def test_links_expire():
    now = [1000.0]
    links = ShareLinks(120, clock=lambda: now[0])
    token = links.create("a.jpg")
    assert links.resolve(token) == "a.jpg"
    now[0] += 119
    assert links.resolve(token) == "a.jpg"
    now[0] += 2
    assert links.resolve(token) is None
    assert len(links) == 0  # expired links are dropped, nothing piles up


def test_tokens_are_unique_and_long():
    links = ShareLinks(120)
    tokens = {links.create("a.jpg") for _ in range(100)}
    assert len(tokens) == 100
    assert all(len(t) >= 16 for t in tokens)


@pytest.mark.parametrize(
    "header,lang",
    [(None, "en"), ("de-DE,de;q=0.9,en;q=0.8", "de"), ("en-US,de;q=0.5", "en"), ("fr-FR,de;q=0.7", "de"), ("fr", "en")],
)
def test_pick_language(header, lang):
    assert pick_language(header) == lang


# ---------------------------------------------------------------- API


def test_config_reports_hotspot(local):
    body = local.get("/api/config").json()
    assert body["hotspot"] is True
    assert body["power_off"] is False


def test_hotspot_qr(local):
    body = local.get("/api/hotspot").json()
    assert body["ssid"] == "Photobox"
    assert body["qr_svg"].startswith("<svg")


def test_share_needs_existing_photo(local):
    assert local.post("/api/share/20260101-120000-abcdef.jpg").status_code == 404
    assert local.post("/api/share/..%2Fetc%2Fpasswd").status_code == 404


def test_share_disabled_without_hotspot(tmp_path):
    cfg = Config(photos_dir=tmp_path / "p", frontend_dir=tmp_path / "f", camera=CameraConfig(driver="mock"))
    with TestClient(create_app(cfg)) as c:
        assert c.get("/api/hotspot").status_code == 404
        assert c.post("/api/share/20260101-120000-abcdef.jpg").status_code == 404


def test_phone_download_flow(tmp_path):
    local, phone = local_and_phone(tmp_path)
    with local, phone:
        name = local.post("/api/capture").json()["name"]
        share = local.post(f"/api/share/{name}").json()
        assert share["expires_in"] == 120
        assert share["qr_svg"].startswith("<svg")
        assert share["url"].startswith("http://testserver/d/")
        path = share["url"].removeprefix("http://testserver")

        page = phone.get(path, headers={"Accept-Language": "de-DE"})
        assert page.status_code == 200
        assert "Foto speichern" in page.text
        assert page.headers["cache-control"] == "no-store"

        img = phone.get(f"{path}/photo.jpg")
        assert img.status_code == 200
        assert img.content[:2] == b"\xff\xd8"
        assert img.headers["content-disposition"].startswith("inline")

        dl = phone.get(f"{path}/photo.jpg?download=1")
        assert dl.headers["content-disposition"].startswith("attachment")
        assert f"photobox-{name}" in dl.headers["content-disposition"]


def test_phone_link_expires(tmp_path):
    local, phone = local_and_phone(tmp_path)
    with local, phone:
        name = local.post("/api/capture").json()["name"]
        path = local.post(f"/api/share/{name}").json()["url"].removeprefix("http://testserver")
        # fast-forward the clock of the app's link store past the expiry
        local.app.state.share_links._clock = lambda: time.monotonic() + 121
        r = phone.get(path)
        assert r.status_code == 410
        assert "expired" in r.text
        assert phone.get(f"{path}/photo.jpg").status_code == 410


def test_unknown_token(tmp_path):
    _, phone = local_and_phone(tmp_path)
    with phone:
        assert phone.get("/d/not-a-real-token").status_code == 410
        assert phone.get("/d/not-a-real-token/photo.jpg").status_code == 410


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/photos"),
        ("get", "/api/stream"),
        ("get", "/api/hotspot"),
        ("post", "/api/capture"),
        ("post", "/api/power-off"),
        ("get", "/photos/20260101-120000-abcdef.jpg"),
        ("get", "/thumbs/20260101-120000-abcdef.jpg"),
        ("get", "/index.html"),
    ],
)
def test_phones_cannot_reach_anything_else(tmp_path, method, path):
    _, phone = local_and_phone(tmp_path, system=SystemConfig(power_off_command=("true",)))
    with phone:
        assert getattr(phone, method)(path).status_code == 404


# ---------------------------------------------------------------- captive portal


def via_hotspot(phone: TestClient, url: str):
    """Request `url` the way a phone in the hotspot does: DNS points every name
    to the Pi, so it arrives at the hotspot socket with a foreign Host header."""
    host, _, path = url.removeprefix("http://").partition("/")
    return phone.get("/" + path, headers={"Host": host}, follow_redirects=False)


def test_portal_waits_without_shared_photo(tmp_path):
    _, phone = local_and_phone(tmp_path)
    with phone:
        r = phone.get("/", headers={"Accept-Language": "en"})
        assert r.status_code == 200
        assert "To phone" in r.text
        assert 'http-equiv="refresh"' in r.text


def test_portal_shows_current_photo(tmp_path):
    local, phone = local_and_phone(tmp_path)
    with local, phone:
        name = local.post("/api/capture").json()["name"]
        token = local.post(f"/api/share/{name}").json()["url"].rsplit("/", 1)[1]
        r = phone.get("/")
        assert f"/d/{token}/photo.jpg" in r.text
        assert 'action="/signin"' in r.text
        assert phone.get(f"/d/{token}/photo.jpg").status_code == 200


@pytest.mark.parametrize(
    "url",
    [
        "http://connectivitycheck.gstatic.com/generate_204",
        "http://www.google.com/gen_204",
        "http://captive.apple.com/hotspot-detect.html",
        "http://www.msftconnecttest.com/connecttest.txt",
        "http://detectportal.firefox.com/success.txt",
        "http://example.com/anything",
    ],
)
def test_checks_redirect_to_portal(tmp_path, url):
    _, phone = local_and_phone(tmp_path)
    with phone:
        r = via_hotspot(phone, url)
        assert r.status_code == 302
        assert r.headers["location"] == "http://testserver/"


def test_checks_succeed_after_sign_in(tmp_path):
    _, phone = local_and_phone(tmp_path)
    with phone:
        r = phone.post("/signin")
        assert r.status_code == 200
        assert via_hotspot(phone, "http://connectivitycheck.gstatic.com/generate_204").status_code == 204
        assert "Success" in via_hotspot(phone, "http://captive.apple.com/hotspot-detect.html").text
        # other websites still go to the portal
        assert via_hotspot(phone, "http://example.com/").status_code == 302


# ---------------------------------------------------------------- power off


def test_power_off_disabled_by_default(local):
    assert local.post("/api/power-off").status_code == 404


def test_power_off_runs_command(tmp_path):
    marker = tmp_path / "powered-off"
    cfg = make_cfg(tmp_path, system=SystemConfig(power_off_command=("touch", str(marker))))
    with TestClient(create_app(cfg), base_url=LOCAL) as c:
        assert c.get("/api/config").json()["power_off"] is True
        assert c.post("/api/power-off").status_code == 202
        for _ in range(40):
            if marker.exists():
                break
            time.sleep(0.1)
    assert marker.exists()


# ---------------------------------------------------------------- config


def test_hotspot_config_from_file(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text(
        '[hotspot]\nenabled = true\npassword = "abcdefgh"\nlink_seconds = 120\n'
        '[system]\npower_off_command = ["systemctl", "poweroff"]\n'
    )
    cfg = load_config(f)
    assert cfg.hotspot.enabled and cfg.hotspot.address == "10.42.0.1"
    assert cfg.system.power_off_command == ("systemctl", "poweroff")


def test_hotspot_needs_password(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text("[hotspot]\nenabled = true\npassword = \"short\"\n")
    with pytest.raises(ValueError, match="password"):
        load_config(f)
