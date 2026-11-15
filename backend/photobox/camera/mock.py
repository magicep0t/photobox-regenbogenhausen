"""Fake camera for development and tests: renders test images with Pillow."""

from __future__ import annotations

import io
import threading
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw

from ..config import CameraConfig
from .base import Camera

COLORS = [(228, 3, 3), (255, 140, 0), (255, 237, 0), (0, 128, 38), (0, 77, 255), (117, 7, 135)]


class MockCamera(Camera):
    def __init__(self, cfg: CameraConfig, fps: float = 15.0) -> None:
        super().__init__()
        self._cfg = cfg
        self._interval = 1.0 / fps
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame_no = 0

    @property
    def name(self) -> str:
        return "mock"

    def _render(self, size: tuple[int, int], label: str) -> Image.Image:
        w, h = size
        img = Image.new("RGB", size, (20, 20, 20))
        draw = ImageDraw.Draw(img)
        stripe = h // len(COLORS)
        offset = (self._frame_no * 4) % w
        for i, color in enumerate(COLORS):
            draw.rectangle([offset - w, i * stripe, offset + w // 3, (i + 1) * stripe], fill=color)
        draw.text((20, 20), label, fill=(255, 255, 255))
        draw.text((20, 40), datetime.now().strftime("%H:%M:%S.%f")[:-3], fill=(255, 255, 255))
        return img

    def _loop(self) -> None:
        while not self._stop.is_set():
            buf = io.BytesIO()
            self._render(tuple(self._cfg.preview_size), "MOCK PREVIEW").save(buf, "JPEG", quality=70)
            self.preview.publish(buf.getvalue())
            self._frame_no += 1
            time.sleep(self._interval)

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="mock-camera", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def capture(self, path: Path) -> None:
        size = tuple(self._cfg.still_size or (2592, 1944))
        self._render(size, "MOCK PHOTO").save(path, "JPEG", quality=self._cfg.jpeg_quality)
