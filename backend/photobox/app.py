"""FastAPI application: preview stream, capture, gallery and the touch UI."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .camera import Camera, create_camera
from .config import Config, load_config
from .photos import PhotoStore

log = logging.getLogger(__name__)

BOUNDARY = "frame"
DEFAULT_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def create_app(cfg: Config | None = None, camera: Camera | None = None) -> FastAPI:
    cfg = cfg or load_config()
    cam = camera or create_camera(cfg.camera)
    store = PhotoStore(cfg.photos_dir)
    capture_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cfg.photos_dir.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(cam.start)
        log.info("Camera started: %s", cam.name)
        try:
            yield
        finally:
            await asyncio.to_thread(cam.stop)

    app = FastAPI(title="Photobox", version=__version__, lifespan=lifespan)

    # written by deploy/deploy.sh; read per request, frontend-only deploys don't restart the backend
    build_file = Path(__file__).resolve().parents[2] / "BUILD"

    @app.get("/api/health")
    async def health():
        build = build_file.read_text().strip() if build_file.is_file() else "dev"
        return {"status": "ok", "version": __version__, "build": build, "camera": cam.name}

    @app.get("/api/config")
    async def ui_config():
        return {
            "countdown_seconds": cfg.ui.countdown_seconds,
            "mirror_preview": cfg.ui.mirror_preview,
            "idle_timeout_seconds": cfg.ui.idle_timeout_seconds,
            "default_language": cfg.ui.default_language,
        }

    @app.get("/api/stream")
    async def stream(request: Request):
        async def frames():
            seq = 0
            while not await request.is_disconnected():
                seq, frame = await asyncio.to_thread(cam.preview.wait_for_frame, seq)
                if frame is None:
                    continue  # timeout (e.g. preview paused during a capture); keep waiting
                yield (
                    f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(frame)}\r\n\r\n".encode()
                    + frame
                    + b"\r\n"
                )

        return StreamingResponse(
            frames(),
            media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/snapshot")
    async def snapshot():
        """Latest preview frame as a single JPEG (handy for checks and thumbnails)."""
        _, frame = await asyncio.to_thread(cam.preview.wait_for_frame, -1, 3.0)
        if frame is None:
            raise HTTPException(503, "No preview frame available")
        return StreamingResponse(iter([frame]), media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.post("/api/capture")
    async def capture():
        if capture_lock.locked():
            raise HTTPException(409, "A capture is already in progress")
        async with capture_lock:
            path = store.new_path()
            # write to a temp file first so the gallery never sees half-written photos
            fd, tmp = tempfile.mkstemp(dir=cfg.photos_dir, prefix=".capture-", suffix=".jpg")
            os.close(fd)
            try:
                await asyncio.to_thread(cam.capture, Path(tmp))
                os.chmod(tmp, 0o640)
                os.replace(tmp, path)
            except Exception:
                log.exception("Capture failed")
                Path(tmp).unlink(missing_ok=True)
                raise HTTPException(500, "Capture failed") from None
        photo = store.photo(path)
        log.info("Captured %s", photo.name)
        await asyncio.to_thread(store.thumb, photo.name)
        return photo.to_dict()

    @app.get("/api/photos")
    async def list_photos(limit: int = Query(50, ge=1, le=500)):
        return [p.to_dict() for p in store.list(limit=limit)]

    @app.get("/photos/{name}")
    async def get_photo(name: str):
        path = store.get(name)
        if path is None:
            raise HTTPException(404, "Photo not found")
        return FileResponse(path, media_type="image/jpeg")

    @app.get("/thumbs/{name}")
    async def get_thumb(name: str):
        path = await asyncio.to_thread(store.thumb, name)
        if path is None:
            raise HTTPException(404, "Photo not found")
        return FileResponse(path, media_type="image/jpeg")

    frontend_dir = cfg.frontend_dir or DEFAULT_FRONTEND_DIR
    if (frontend_dir / "index.html").exists():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    else:
        log.warning("No frontend found at %s; serving API only", frontend_dir)

    return app
