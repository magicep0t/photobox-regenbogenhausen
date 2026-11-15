"""Camera drivers. Each driver implements :class:`~photobox.camera.base.Camera`."""

from __future__ import annotations

from ..config import CameraConfig
from .base import Camera


def create_camera(cfg: CameraConfig) -> Camera:
    if cfg.driver == "picamera2":
        from .picamera import PicameraCamera

        return PicameraCamera(cfg)
    if cfg.driver == "mock":
        from .mock import MockCamera

        return MockCamera(cfg)
    raise ValueError(f"Unknown camera driver: {cfg.driver!r} (expected 'picamera2' or 'mock')")


__all__ = ["Camera", "create_camera"]
