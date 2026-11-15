"""Raspberry Pi camera driver (libcamera via picamera2)."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from ..config import CameraConfig
from .base import Camera

log = logging.getLogger(__name__)


class PicameraCamera(Camera):
    def __init__(self, cfg: CameraConfig) -> None:
        super().__init__()
        # Imported here so the package also works on machines without picamera2.
        from libcamera import Transform
        from picamera2 import Picamera2
        from picamera2.encoders import MJPEGEncoder
        from picamera2.outputs import FileOutput

        self._cfg = cfg
        self._lock = threading.Lock()
        self._FileOutput = FileOutput

        tuning = Picamera2.load_tuning_file(cfg.tuning_file) if cfg.tuning_file else None
        self._cam = Picamera2(tuning=tuning)
        transform = Transform(hflip=1, vflip=1) if cfg.rotation == 180 else Transform()

        self._preview_config = self._cam.create_video_configuration(
            main={"size": tuple(cfg.preview_size), "format": "YUV420"},
            transform=transform,
            buffer_count=4,
        )
        still_main = {"size": tuple(cfg.still_size)} if cfg.still_size else {}
        self._still_config = self._cam.create_still_configuration(main=still_main, transform=transform)
        self._encoder = MJPEGEncoder()
        self._model = self._cam.camera_properties.get("Model", "unknown")

    @property
    def name(self) -> str:
        return f"picamera2 ({self._model})"

    def start(self) -> None:
        with self._lock:
            self._cam.configure(self._preview_config)
            self._cam.start_recording(self._encoder, self._FileOutput(self.preview))
            log.info("Preview started: %s, %s", self.name, self._cfg.preview_size)

    def stop(self) -> None:
        with self._lock:
            try:
                self._cam.stop_recording()
            finally:
                self._cam.close()

    def capture(self, path: Path) -> None:
        with self._lock:
            # The hardware encoder can't run across a mode switch, so pause the
            # preview, take the still in full resolution, then resume.
            self._cam.stop_recording()
            try:
                self._cam.options["quality"] = self._cfg.jpeg_quality
                self._cam.configure(self._still_config)
                self._cam.start()
                self._cam.capture_file(str(path))
                self._cam.stop()
            finally:
                self._cam.configure(self._preview_config)
                self._cam.start_recording(self._encoder, self._FileOutput(self.preview))
