# Photobox Regenbogenhausen

A DIY photo booth for parties, built on a Raspberry Pi with a touchscreen.
Guests tap the screen, see a live preview and a countdown, and get their photo.

**Status:** prototype in progress. See [`docs/PLAN.md`](docs/PLAN.md) for the roadmap.

## How it works

```
┌──────────────── Raspberry Pi ─────────────────┐
│  photobox.service (Python, FastAPI)           │
│   ├─ camera/   picamera2 (now) │ gphoto2 (later)
│   ├─ /stream   live preview (MJPEG)           │
│   ├─ /capture  take a photo                   │
│   ├─ /photos   gallery                        │
│   └─ frontend  touch UI (HTML/CSS/JS)         │
│                                               │
│  photobox-kiosk.service                       │
│   └─ cage (minimal Wayland compositor)        │
│       └─ Chromium --kiosk → localhost:8000    │
└───────────────────────────────────────────────┘
```

- **Backend:** Python + FastAPI. The camera sits behind a small interface, so the
  Pi camera used for the prototype can later be swapped for a DSLR/mirrorless
  camera via gphoto2.
- **Frontend:** plain HTML/CSS/JavaScript, no build step. English UI with a
  button to switch to German.
- **Kiosk:** `cage` runs Chromium full-screen on the touchscreen — no desktop
  environment needed.
- **Privacy:** photos stay on the Pi (`/var/lib/photobox/photos`). The backend
  only listens on `127.0.0.1`; nothing is exposed to the network. Photos are
  never committed to this repository.

## Hardware (prototype)

| Part | Used for the prototype |
|---|---|
| Computer | Raspberry Pi 4 (2 GB) |
| OS | Raspberry Pi OS Lite (64-bit, Debian 13 "trixie") |
| Camera | Raspberry Pi camera module (OV5647 NoIR) |
| Display | HDMI touchscreen, 1920×1200 |
| Printer | not yet |

## Repository layout

```
backend/    Python package (FastAPI app, camera drivers)
frontend/   Touch UI served by the backend
deploy/     Deploy script and systemd units
docs/       Plan and notes
```

## Development

The backend runs on any machine with the `mock` camera driver, which renders
test images instead of using real hardware.

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest

# run locally with the mock camera
printf 'photos_dir = "/tmp/photobox-photos"\n[camera]\ndriver = "mock"\n' > ../config.local.toml
PHOTOBOX_CONFIG=../config.local.toml .venv/bin/python -m photobox
# → http://127.0.0.1:8000/api/stream
```

### API

| Endpoint | |
|---|---|
| `GET /api/health` | status, version, camera model |
| `GET /api/config` | UI settings (countdown, mirroring, idle timeout, language) |
| `GET /api/stream` | live preview as MJPEG |
| `GET /api/snapshot` | latest preview frame as JPEG |
| `POST /api/capture` | take a full-resolution photo |
| `GET /api/photos?limit=50` | newest photos first |
| `GET /photos/{name}` | a photo |
| `GET /thumbs/{name}` | 480 px thumbnail (created on first use) |

### On the Pi

First-time setup (packages, `photobox` user, directories, services):

```bash
sudo bash deploy/setup-pi.sh   # run from a copy of the repo on the Pi
sudo reboot                    # boots straight into the booth (~25 s)
```

Two systemd services run the booth:

| Service | |
|---|---|
| `photobox.service` | backend as user `photobox` (hardened, writes only to `/var/lib/photobox`) |
| `photobox-kiosk.service` | `cage` + Chromium full-screen on `tty1`, waits for the backend |

Screenshot of the touchscreen (for debugging):
`sudo -u photobox env XDG_RUNTIME_DIR=/run/user/$(id -u photobox) WAYLAND_DISPLAY=wayland-0 grim /tmp/screen.png`

Configuration lives in `/etc/photobox/config.toml` (see
[`config.example.toml`](config.example.toml)). The backend only listens on
`127.0.0.1`; to look at it from a laptop, use an SSH tunnel:

```bash
ssh -L 8000:127.0.0.1:8000 <user>@<pi>
# then open http://localhost:8000
```

### Deploying

From the laptop, after creating `deploy/.env` from
[`deploy/.env.example`](deploy/.env.example) (the SSH user needs passwordless
sudo on the Pi):

```bash
deploy/deploy.sh               # run tests, sync to /opt/photobox, restart what changed
deploy/deploy.sh --dry-run     # only show what would change
deploy/deploy.sh --no-tests    # skip the local test run
```

Only what changed is restarted: frontend changes reload the kiosk browser,
backend changes restart the backend (and the kiosk), changed systemd units are
reinstalled. The deployed git commit is shown in `/api/health` as `build`.

## License

[MIT](LICENSE)
