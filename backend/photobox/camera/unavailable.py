"""Stand-in when the real camera can't be opened (e.g. ribbon cable loose).

The booth still starts: the preview shows a notice instead of a black screen,
the gallery and phone downloads keep working, only taking photos fails.
"""

from __future__ import annotations

import io
import threading
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .base import Camera

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


class CameraUnavailable(RuntimeError):
    pass


def _font(size: int):
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default(size=size)


def notice_frame(lines: list[str], size: tuple[int, int] = (1280, 960)) -> bytes:
    img = Image.new("RGB", size, (14, 14, 16))
    draw = ImageDraw.Draw(img)
    big, small = _font(64), _font(36)
    y = size[1] // 2 - 120
    for i, line in enumerate(lines):
        font = big if i == 0 else small
        draw.text((size[0] // 2, y), line, font=font, fill=(255, 214, 10) if i == 0 else (212, 212, 216), anchor="mm")
        y += 110 if i == 0 else 56
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


class UnavailableCamera(Camera):
    def __init__(self, reason: str) -> None:
        super().__init__()
        self.reason = reason
        self._frame = notice_frame([
            "Kamera nicht gefunden",
            "Camera not found",
            "Flachbandkabel prüfen, dann neu starten.",
            "Check the ribbon cable, then restart.",
        ])
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def name(self) -> str:
        return "unavailable"

    def _loop(self) -> None:
        # a new frame every second, so freshly opened streams get one quickly
        while not self._stop.wait(1.0):
            self.preview.publish(self._frame)

    def start(self) -> None:
        self.preview.publish(self._frame)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="no-camera", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def capture(self, path: Path) -> None:
        raise CameraUnavailable(self.reason)
