from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from photobox import system
from photobox.app import create_app
from photobox.config import CameraConfig, Config, SystemConfig

STATION_DUMP = """\
Station 3a:1b:2c:3d:4e:5f (on guestwifi)
\tinactive time:\t120 ms
\tsignal:  \t-48 [-50, -51] dBm
\tconnected time:\t95 seconds
Station aa:bb:cc:dd:ee:01 (on guestwifi)
\tsignal:  \t-71 dBm
\tconnected time:\t3 seconds
"""


def test_parse_stations():
    assert system.parse_stations(STATION_DUMP) == {
        "3a:1b:2c:3d:4e:5f": {"signal": -48, "connected_s": 95},
        "aa:bb:cc:dd:ee:01": {"signal": -71, "connected_s": 3},
    }
    assert system.parse_stations("") == {}


def test_parse_leases():
    link = {
        "DHCPServer": {
            "PoolOffset": 10,
            "Leases": [
                {"ClientId": [1, 58, 27, 44, 61, 78, 95], "Address": [10, 42, 0, 23], "Hostname": "Pixel-8"},
                {"ClientId": [255, 1, 2], "Address": [10, 42, 0, 24]},
            ],
        }
    }
    assert system.parse_leases(link) == [
        {"ip": "10.42.0.23", "mac": "3a:1b:2c:3d:4e:5f", "name": "Pixel-8"},
        {"ip": "10.42.0.24", "mac": None, "name": None},
    ]
    assert system.parse_leases({}) == []


def test_decode_throttled():
    assert system.decode_throttled("throttled=0x0") == []
    assert system.decode_throttled("throttled=0x80008") == ["temp_limit", "temp_limit_past"]
    assert system.decode_throttled(None) == []


def test_network_mode_file(tmp_path):
    f = tmp_path / "mode"
    assert system.network_mode(f) == "home"  # missing file
    f.write_text("standalone\n")
    assert system.network_mode(f) == "standalone"
    f.write_text("nonsense")
    assert system.network_mode(f) == "home"


def test_fill():
    assert system.fill(("systemctl", "start", "x@{mode}.service"), mode="home") == ["systemctl", "start", "x@home.service"]


@pytest.fixture
def make_client(tmp_path: Path):
    def make(**system_cfg):
        cfg = Config(
            photos_dir=tmp_path / "photos",
            frontend_dir=tmp_path / "no-frontend",
            camera=CameraConfig(driver="mock", preview_size=(320, 240), still_size=(640, 480)),
            system=SystemConfig(network_mode_file=tmp_path / "network-mode", **system_cfg),
        )
        return TestClient(create_app(cfg))

    return make


def test_status_works_without_pi_tools(make_client):
    with make_client() as c:
        body = c.get("/api/status").json()
    assert body["mode"] == "home"
    assert body["admin_wifi"] is None
    assert set(body["ssh"]) == {"active", "password", "sessions"}
    assert body["system"]["photos"] == 0
    assert body["system"]["camera"] == "mock"


def test_settings_actions_disabled_by_default(make_client):
    with make_client() as c:
        assert c.post("/api/network-mode", json={"mode": "standalone"}).status_code == 404
        assert c.post("/api/ssh-password", json={"enabled": True}).status_code == 404
        assert c.post("/api/reboot").status_code == 404
        assert c.post("/api/power-off").status_code == 404


def test_network_mode_runs_command(make_client, tmp_path):
    marker = tmp_path / "ran"
    cmd = ("sh", "-c", f"echo {{mode}} > {marker}")
    with make_client(network_mode_command=cmd) as c:
        assert c.post("/api/network-mode", json={"mode": "bogus"}).status_code == 422
        r = c.post("/api/network-mode", json={"mode": "standalone"})
        assert r.status_code == 202
    assert marker.read_text().strip() == "standalone"


def test_ssh_password_runs_command(make_client, tmp_path):
    marker = tmp_path / "ran"
    with make_client(ssh_password_command=("sh", "-c", f"echo {{state}} > {marker}")) as c:
        assert c.post("/api/ssh-password", json={"enabled": False}).status_code == 202
    assert marker.read_text().strip() == "off"


def test_failing_command_is_reported(make_client):
    with make_client(network_mode_command=("false",)) as c:
        assert c.post("/api/network-mode", json={"mode": "home"}).status_code == 500


def test_booth_starts_without_camera(tmp_path):
    # picamera2 isn't installed on a laptop: same as a camera that can't be opened
    cfg = Config(photos_dir=tmp_path / "photos", frontend_dir=tmp_path / "x", camera=CameraConfig(driver="picamera2"))
    with TestClient(create_app(cfg)) as c:
        assert c.get("/api/health").json()["camera"] == "unavailable"
        assert c.get("/api/config").json()["camera"] is False
        snap = c.get("/api/snapshot")
        assert snap.status_code == 200 and snap.content[:2] == b"\xff\xd8"
        assert c.post("/api/capture").status_code == 503
        assert c.get("/api/photos").json() == []
    assert not list((tmp_path / "photos").glob(".capture-*"))
