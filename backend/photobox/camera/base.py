"""Camera interface shared by all drivers."""

from __future__ import annotations

import io
import threading
from abc import ABC, abstractmethod
from pathlib import Path


class FrameBuffer(io.BufferedIOBase):
    """Holds the latest preview JPEG and wakes up waiting stream clients.

    Drivers call ``publish()`` from their own thread; HTTP handlers call
    ``wait_for_frame()`` (in a worker thread) to get the next new frame.
    It is a (write-only) file object so picamera2's FileOutput accepts it.
    """

    def __init__(self) -> None:
        super().__init__()
        self._cond = threading.Condition()
        self._frame: bytes | None = None
        self._seq = 0

    def publish(self, jpeg: bytes) -> None:
        with self._cond:
            self._frame = jpeg
            self._seq += 1
            self._cond.notify_all()

    def wait_for_frame(self, last_seq: int, timeout: float = 2.0) -> tuple[int, bytes | None]:
        """Return (seq, frame) once a frame newer than ``last_seq`` exists, or (last_seq, None) on timeout."""
        with self._cond:
            self._cond.wait_for(lambda: self._seq != last_seq, timeout=timeout)
            if self._seq == last_seq:
                return last_seq, None
            return self._seq, self._frame

    # file interface: picamera2's FileOutput writes one complete JPEG per call
    def writable(self) -> bool:
        return True

    def write(self, data) -> int:
        self.publish(bytes(data))
        return len(data)


class Camera(ABC):
    """A camera that streams a preview and captures full-resolution stills."""

    def __init__(self) -> None:
        self.preview = FrameBuffer()

    @abstractmethod
    def start(self) -> None:
        """Open the camera and start publishing preview frames."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the preview and release the camera."""

    @abstractmethod
    def capture(self, path: Path) -> None:
        """Take a full-resolution photo and write it as JPEG to ``path``.

        Must be safe to call while the preview is running; the preview may
        pause briefly during the capture.
        """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable camera model, for logs and /api/health."""
