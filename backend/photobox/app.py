"""FastAPI application: preview stream, capture, gallery and the touch UI."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .camera import Camera, create_camera
from .config import Config, load_config
from .photos import PhotoStore
from .share import (
    ShareLinks,
    SignedIn,
    expired_page,
    photo_page,
    pick_language,
    probe_success,
    qr_svg,
    signed_in_page,
    waiting_page,
    wifi_qr_svg,
)

log = logging.getLogger(__name__)

BOUNDARY = "frame"
NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
DEFAULT_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def create_app(cfg: Config | None = None, camera: Camera | None = None) -> FastAPI:
    cfg = cfg or load_config()
    cam = camera or create_camera(cfg.camera)
    store = PhotoStore(cfg.photos_dir)
    capture_lock = asyncio.Lock()
    hotspot = cfg.hotspot
    links = ShareLinks(hotspot.link_seconds)
    signed_in = SignedIn()
    background: set[asyncio.Task] = set()

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
    app.state.share_links = links

    if hotspot.enabled:
        # Phones in the hotspot network reach the backend on hotspot.address:port.
        # There they only get the captive portal and single shared photos.
        # How the portal works: see photobox/share.py.
        phone_server = (hotspot.address, hotspot.port)
        portal_url = f"http://{hotspot.address}{'' if hotspot.port == 80 else f':{hotspot.port}'}/"

        @app.middleware("http")
        async def hotspot_guard(request: Request, call_next):
            server = request.scope.get("server")
            if not server or tuple(server) != phone_server:
                return await call_next(request)  # touchscreen side: everything allowed

            path = request.url.path
            host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
            client = request.client.host if request.client else ""
            lang = pick_language(request.headers.get("accept-language"))

            probe = probe_success(path)
            if probe and client in signed_in:
                status, ctype, body = probe
                return Response(body, status_code=status, media_type=ctype, headers=NO_STORE)
            if probe or host != hotspot.address:
                # connectivity check or any other website: send the phone to the portal
                return RedirectResponse(portal_url, status_code=302, headers=NO_STORE)

            if path == "/":
                token = links.latest()
                if token:
                    name = links.resolve(token)
                    return HTMLResponse(photo_page(lang, token, f"photobox-{name}", portal=True), headers=NO_STORE)
                return HTMLResponse(waiting_page(lang), headers=NO_STORE)
            if path == "/signin" and request.method == "POST":
                signed_in.add(client)
                log.info("Phone %s signed in to the hotspot portal", client)
                return HTMLResponse(signed_in_page(lang, hotspot.ssid), headers=NO_STORE)
            if path.startswith("/d/"):
                return await call_next(request)
            return Response("Not found", status_code=404)

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
            "hotspot": hotspot.enabled,
            "power_off": bool(cfg.system.power_off_command),
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

    # ------------------------------------------------------------ phone sharing

    def require_hotspot():
        if not hotspot.enabled:
            raise HTTPException(404, "Hotspot is not enabled")

    @app.get("/api/hotspot")
    async def hotspot_info():
        require_hotspot()
        return {"ssid": hotspot.ssid, "qr_svg": wifi_qr_svg(hotspot.ssid, hotspot.password)}

    @app.post("/api/share/{name}")
    async def share_photo(name: str):
        """New short-lived link to one photo, as URL and QR code."""
        require_hotspot()
        if store.get(name) is None:
            raise HTTPException(404, "Photo not found")
        token = links.create(name)
        port = "" if hotspot.port == 80 else f":{hotspot.port}"
        url = f"http://{hotspot.address}{port}/d/{token}"
        return {"url": url, "expires_in": hotspot.link_seconds, "qr_svg": qr_svg(url)}

    @app.get("/d/{token}")
    async def phone_page(token: str, request: Request):
        lang = pick_language(request.headers.get("accept-language"))
        name = links.resolve(token)
        if name is None or store.get(name) is None:
            return HTMLResponse(expired_page(lang), status_code=410, headers=NO_STORE)
        return HTMLResponse(photo_page(lang, token, f"photobox-{name}"), headers=NO_STORE)

    @app.get("/d/{token}/photo.jpg")
    async def phone_photo(token: str, download: bool = False):
        name = links.resolve(token)
        path = store.get(name) if name else None
        if path is None:
            raise HTTPException(410, "Link expired")
        return FileResponse(
            path,
            media_type="image/jpeg",
            filename=f"photobox-{name}",
            content_disposition_type="attachment" if download else "inline",
            headers=NO_STORE,
        )

    # ------------------------------------------------------------ power off

    @app.post("/api/power-off", status_code=202)
    async def power_off():
        command = cfg.system.power_off_command
        if not command:
            raise HTTPException(404, "Power off is not enabled")

        async def run():
            await asyncio.sleep(1)  # let the UI show its goodbye message first
            log.warning("Powering off: %s", " ".join(command))
            proc = await asyncio.create_subprocess_exec(*command)
            if await proc.wait() != 0:
                log.error("Power off command failed with exit code %s", proc.returncode)

        task = asyncio.create_task(run())
        background.add(task)
        task.add_done_callback(background.discard)
        return {"status": "powering off"}

    frontend_dir = cfg.frontend_dir or DEFAULT_FRONTEND_DIR
    if (frontend_dir / "index.html").exists():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    else:
        log.warning("No frontend found at %s; serving API only", frontend_dir)

    return app
