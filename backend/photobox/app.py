"""FastAPI application: preview stream, capture, gallery and the touch UI."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, system
from .camera import Camera, create_camera
from .camera.unavailable import CameraUnavailable, UnavailableCamera
from .config import Config, load_config
from .photos import PhotoStore
from .share import (
    ShareLinks,
    SignedIn,
    expired_page,
    photo_page,
    pick_language,
    portal_page,
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


class RevalidatedStaticFiles(StaticFiles):
    """UI files that the browser must re-check on every load (cheap 304 if unchanged).

    Without this the kiosk browser may keep running old JavaScript after a deploy.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(cfg: Config | None = None, camera: Camera | None = None) -> FastAPI:
    cfg = cfg or load_config()
    try:
        cam = camera or create_camera(cfg.camera)
    except Exception as err:  # no camera must not mean no photobox
        log.exception("Camera not available")
        cam = UnavailableCamera(str(err))
    store = PhotoStore(cfg.photos_dir)
    capture_lock = asyncio.Lock()
    hotspot = cfg.hotspot
    links = ShareLinks(hotspot.link_seconds)
    signed_in = SignedIn()
    background: set[asyncio.Task] = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal cam
        cfg.photos_dir.mkdir(parents=True, exist_ok=True)
        try:
            await asyncio.to_thread(cam.start)
        except Exception as err:
            log.exception("Camera failed to start")
            cam = UnavailableCamera(str(err))
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
                shared = [(token, f"photobox-{name}") for token, name in links.active() if store.get(name)]
                page = portal_page(lang, shared) if shared else waiting_page(lang)
                return HTMLResponse(page, headers=NO_STORE)
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
            "reboot": bool(cfg.system.reboot_command),
            "network_mode": bool(cfg.system.network_mode_command),
            "ssh_password": bool(cfg.system.ssh_password_command),
            "camera": not isinstance(cam, UnavailableCamera),
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
            except CameraUnavailable:
                Path(tmp).unlink(missing_ok=True)
                raise HTTPException(503, "Camera not available") from None
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

    # ------------------------------------------------------------ settings screen

    @app.get("/api/status")
    async def status():
        """Everything the settings screen shows: network, connected devices, SSH, system."""

        def collect():
            data = system.collect_network(cfg.system.network_mode_file)
            data["ssh"] = system.collect_ssh()
            data["system"] = system.collect_system(cfg.photos_dir)
            data["system"]["photos"] = store.count()
            data["system"]["camera"] = cam.name
            data["system"]["build"] = build_file.read_text().strip() if build_file.is_file() else "dev"
            admin = cfg.admin_wifi
            data["admin_wifi"] = (
                {
                    "ssid": admin.ssid,
                    "address": admin.address,
                    "qr_svg": wifi_qr_svg(admin.ssid, admin.password),
                }
                if admin.enabled and data["mode"] == "standalone"
                else None
            )
            return data

        return await asyncio.to_thread(collect)

    def command_or_404(command: tuple[str, ...], what: str) -> tuple[str, ...]:
        if not command:
            raise HTTPException(404, f"{what} is not enabled")
        return command

    async def execute(command: list[str]) -> None:
        if not await asyncio.to_thread(system.execute, command):
            raise HTTPException(500, "Command failed")

    def later(command: list[str]) -> None:
        """Run after a second, so the UI can show its goodbye message first."""

        async def run():
            await asyncio.sleep(1)
            await asyncio.to_thread(system.execute, command)

        task = asyncio.create_task(run())
        background.add(task)
        task.add_done_callback(background.discard)

    @app.post("/api/network-mode", status_code=202)
    async def set_network_mode(mode: str = Body(..., embed=True)):
        command = command_or_404(cfg.system.network_mode_command, "Network mode switching")
        if mode not in system.MODES:
            raise HTTPException(422, f"mode must be one of {system.MODES}")
        await execute(system.fill(command, mode=mode))
        return {"mode": mode}

    @app.post("/api/ssh-password", status_code=202)
    async def set_ssh_password(enabled: bool = Body(..., embed=True)):
        command = command_or_404(cfg.system.ssh_password_command, "SSH settings")
        await execute(system.fill(command, state="on" if enabled else "off"))
        return {"password": enabled}

    @app.post("/api/reboot", status_code=202)
    async def reboot():
        later(list(command_or_404(cfg.system.reboot_command, "Reboot")))
        return {"status": "rebooting"}

    @app.post("/api/power-off", status_code=202)
    async def power_off():
        later(list(command_or_404(cfg.system.power_off_command, "Power off")))
        return {"status": "powering off"}

    frontend_dir = cfg.frontend_dir or DEFAULT_FRONTEND_DIR
    if (frontend_dir / "index.html").exists():
        app.mount("/", RevalidatedStaticFiles(directory=frontend_dir, html=True), name="frontend")
    else:
        log.warning("No frontend found at %s; serving API only", frontend_dir)

    return app
