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


@dataclass(frozen=True)
class CameraConfig:
    driver: str = "picamera2"  # "picamera2" or "mock"
    rotation: int = 0  # 0 or 180
    tuning_file: str | None = None  # e.g. "ov5647_noir.json"
    preview_size: tuple[int, int] = (1280, 960)
    still_size: tuple[int, int] | None = None  # None = sensor maximum
    jpeg_quality: int = 92


@dataclass(frozen=True)
class UiConfig:
    countdown_seconds: int = 3
    mirror_preview: bool = True  # preview behaves like a mirror; saved photos are not mirrored
    idle_timeout_seconds: int = 60
    default_language: str = "en"


@dataclass(frozen=True)
class Config:
    host: str = "127.0.0.1"
    port: int = 8000
    photos_dir: Path = Path("/var/lib/photobox/photos")
    frontend_dir: Path | None = None  # None = ../../frontend relative to this package
    camera: CameraConfig = field(default_factory=CameraConfig)
    ui: UiConfig = field(default_factory=UiConfig)


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
    for key in ("photos_dir", "frontend_dir"):
        if key in data and data[key] is not None:
            data[key] = Path(data[key])
    cfg = _build(Config, data)
    cfg = Config(**{**cfg.__dict__, "camera": camera, "ui": ui})

    if cfg.camera.rotation not in (0, 180):
        raise ValueError("camera.rotation must be 0 or 180")
    if cfg.ui.default_language not in ("en", "de"):
        raise ValueError("ui.default_language must be 'en' or 'de'")
    return cfg
