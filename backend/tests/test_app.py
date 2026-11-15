from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from photobox.app import create_app
from photobox.config import CameraConfig, Config, load_config


@pytest.fixture
def client(tmp_path: Path):
    cfg = Config(
        photos_dir=tmp_path / "photos",
        frontend_dir=tmp_path / "no-frontend",
        camera=CameraConfig(driver="mock", preview_size=(320, 240), still_size=(640, 480)),
    )
    with TestClient(create_app(cfg)) as c:
        yield c


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["camera"] == "mock"


def test_ui_config_defaults(client):
    body = client.get("/api/config").json()
    assert body == {
        "countdown_seconds": 3,
        "mirror_preview": True,
        "idle_timeout_seconds": 60,
        "default_language": "en",
    }


def test_snapshot_is_jpeg(client):
    r = client.get("/api/snapshot")
    assert r.status_code == 200
    assert r.content[:2] == b"\xff\xd8"


def test_capture_and_gallery(client, tmp_path):
    r = client.post("/api/capture")
    assert r.status_code == 200
    photo = r.json()
    assert photo["url"] == f"/photos/{photo['name']}"

    listed = client.get("/api/photos").json()
    assert [p["name"] for p in listed] == [photo["name"]]

    img = client.get(photo["url"])
    assert img.status_code == 200
    assert Image.open(__import__("io").BytesIO(img.content)).size == (640, 480)

    # no temp files left behind
    assert not list((tmp_path / "photos").glob(".capture-*"))


@pytest.mark.parametrize("name", ["../etc/passwd", "x.jpg", "20260101-120000-abcdef.png", "..%2Fsecret"])
def test_photo_lookup_rejects_bad_names(client, name):
    assert client.get(f"/photos/{name}").status_code == 404


def test_load_config_from_file(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('port = 9000\n[camera]\ndriver = "mock"\nrotation = 180\npreview_size = [640, 480]\n[ui]\ncountdown_seconds = 5\n')
    cfg = load_config(f)
    assert cfg.port == 9000
    assert cfg.camera.rotation == 180
    assert cfg.camera.preview_size == (640, 480)
    assert cfg.ui.countdown_seconds == 5


def test_load_config_rejects_unknown_keys(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text("[camera]\nrotaton = 180\n")
    with pytest.raises(ValueError, match="rotaton"):
        load_config(f)


def test_missing_config_file_gives_defaults(tmp_path):
    cfg = load_config(tmp_path / "missing.toml")
    assert cfg.host == "127.0.0.1"
    assert cfg.camera.driver == "picamera2"
