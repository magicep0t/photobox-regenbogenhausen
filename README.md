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

Setup, running and deploying are documented as each phase lands
(see [`docs/PLAN.md`](docs/PLAN.md)).

## License

[MIT](LICENSE)
