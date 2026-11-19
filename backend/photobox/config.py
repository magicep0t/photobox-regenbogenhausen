"""Configuration, loaded from a TOML file with sane defaults.

Lookup order: $PHOTOBOX_CONFIG, then /etc/photobox/config.toml. Missing file
means "use defaults". See config.example.toml in the repository root.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("/etc/photobox/config.toml")
HOTSPOT_CHANNELS = (36, 40, 44, 48)  # 5 GHz channels without DFS/radar detection


@dataclass(frozen=True)
class CameraConfig:
    driver: str = "picamera2"  # "picamera2" or "mock"
    rotation: int = 0  # 0 or 180
    tuning_file: str | None = None  # e.g. "ov5647_noir.json"; None = libcamera's default for the sensor
    preview_size: tuple[int, int] | None = None  # None = 1536 px wide in the sensor's aspect ratio
    preview_fps: int = 24  # more only heats up the Pi
    still_size: tuple[int, int] | None = None  # None = sensor maximum
    jpeg_quality: int = 92


@dataclass(frozen=True)
class UiConfig:
    countdown_seconds: int = 3
    mirror_preview: bool = True  # preview behaves like a mirror; saved photos are not mirrored
    idle_timeout_seconds: int = 60
    default_language: str = "en"


@dataclass(frozen=True)
class HotspotConfig:
    """Wi-Fi hotspot for guests' phones (hostapd, set up by deploy/setup-pi.sh).

    The backend only shows the QR codes and serves single photos to the
    hotspot network via short-lived links; the hotspot itself is run by
    photobox-hotspot.service.
    """

    enabled: bool = False
    ssid: str = "Photobox"
    password: str = ""  # WPA2 passphrase, 8–63 characters
    country: str = "DE"  # regulatory domain for the radio
    channel: int = 36  # 5 GHz only (36, 40, 44, 48): short range, stays in the room
    address: str = "10.42.0.1"  # the Pi's address in the hotspot network (see deploy/hotspot/)
    port: int = 80  # download server for phones, listens on address:port only
    link_seconds: int = 300  # how long a photo link stays valid


@dataclass(frozen=True)
class AdminWifiConfig:
    """Wi-Fi for the operator in standalone mode (built-in Wi-Fi as access point).

    In home mode the built-in Wi-Fi joins the home network instead. The
    settings screen switches between the two (see deploy/admin/netmode.sh).
    """

    enabled: bool = False
    ssid: str = "Photobox-Admin"
    password: str = ""  # WPA2 passphrase, 8–63 characters
    country: str = "DE"
    channel: int = 6  # 2.4 GHz (1–13): reaches a laptop in the next room too
    address: str = "192.168.73.1"  # must match deploy/admin/10-photobox-wlan0-ap.network


@dataclass(frozen=True)
class SystemConfig:
    # Commands behind the buttons on the settings screen; empty = no button
    # (e.g. on a dev laptop). deploy/setup-pi.sh sets them to systemd units that
    # a polkit rule allows the backend to start. {mode} is "home" or
    # "standalone", {state} is "on" or "off".
    power_off_command: tuple[str, ...] = ()
    reboot_command: tuple[str, ...] = ()
    network_mode_command: tuple[str, ...] = ()
    ssh_password_command: tuple[str, ...] = ()
    network_mode_file: Path = Path("/etc/photobox/network-mode")  # written by netmode.sh


@dataclass(frozen=True)
class Config:
    host: str = "127.0.0.1"
    port: int = 8000
    photos_dir: Path = Path("/var/lib/photobox/photos")
    frontend_dir: Path | None = None  # None = ../../frontend relative to this package
    camera: CameraConfig = field(default_factory=CameraConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    hotspot: HotspotConfig = field(default_factory=HotspotConfig)
    admin_wifi: AdminWifiConfig = field(default_factory=AdminWifiConfig)
    system: SystemConfig = field(default_factory=SystemConfig)


def _build(cls, data: dict):
    known = {f.name: f for f in fields(cls)}
    unknown = set(data) - set(known)
    if unknown:
        raise ValueError(f"Unknown config keys in [{cls.__name__}]: {', '.join(sorted(unknown))}")
    kwargs = {}
    for name, value in data.items():
        if isinstance(value, list):
            value = tuple(value)
        kwargs[name] = value
    return cls(**kwargs)


def load_config(path: Path | None = None) -> Config:
    if path is None:
        env = os.environ.get("PHOTOBOX_CONFIG")
        path = Path(env) if env else DEFAULT_CONFIG_PATH
    data: dict = {}
    if path.exists():
        with path.open("rb") as fh:
            data = tomllib.load(fh)

    camera = _build(CameraConfig, data.pop("camera", {}))
    ui = _build(UiConfig, data.pop("ui", {}))
    hotspot = _build(HotspotConfig, data.pop("hotspot", {}))
    admin_wifi = _build(AdminWifiConfig, data.pop("admin_wifi", {}))
    system_data = data.pop("system", {})
    if "network_mode_file" in system_data:
        system_data["network_mode_file"] = Path(system_data["network_mode_file"])
    system = _build(SystemConfig, system_data)
    for key in ("photos_dir", "frontend_dir"):
        if key in data and data[key] is not None:
            data[key] = Path(data[key])
    cfg = _build(Config, data)
    cfg = Config(**{**cfg.__dict__, "camera": camera, "ui": ui, "hotspot": hotspot, "admin_wifi": admin_wifi, "system": system})

    if cfg.camera.rotation not in (0, 180):
        raise ValueError("camera.rotation must be 0 or 180")
    if cfg.ui.default_language not in ("en", "de"):
        raise ValueError("ui.default_language must be 'en' or 'de'")
    if cfg.hotspot.enabled and not 8 <= len(cfg.hotspot.password) <= 63:
        raise ValueError("hotspot.password must be 8 to 63 characters")
    if cfg.hotspot.channel not in HOTSPOT_CHANNELS:
        raise ValueError(f"hotspot.channel must be one of {HOTSPOT_CHANNELS} (5 GHz, no radar detection)")
    if cfg.hotspot.link_seconds < 10:
        raise ValueError("hotspot.link_seconds must be at least 10")
    if cfg.admin_wifi.enabled and not 8 <= len(cfg.admin_wifi.password) <= 63:
        raise ValueError("admin_wifi.password must be 8 to 63 characters")
    if not 1 <= cfg.admin_wifi.channel <= 13:
        raise ValueError("admin_wifi.channel must be 1 to 13 (2.4 GHz)")
    if not 1 <= cfg.camera.preview_fps <= 60:
        raise ValueError("camera.preview_fps must be 1 to 60")
    return cfg
