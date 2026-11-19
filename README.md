# Photobox Regenbogenhausen

A DIY photo booth for parties, built on a Raspberry Pi with a touchscreen.
Guests tap the screen, see a live preview and a countdown, and get their photo,
which they can download to their phone by scanning a QR code.

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
- **Photos to phones:** a USB Wi-Fi stick runs a small 5 GHz hotspot. The
  touchscreen shows two QR codes: ① join the hotspot, ② open the photo. The
  photo link is random and valid for 5 minutes; several photos can be
  shared at the same time, and the touchscreen stays usable meanwhile
  ("Back" closes the codes, the link keeps working).
- **Settings screen:** a gear button shows the Pi's status over the live
  preview (network, connected devices, SSH, CPU temperature, throttling,
  memory, disk, camera, clock) and holds the buttons for network mode, SSH
  password login, restart and power off (each asks first).
- **Home or standalone:** in *home mode* the built-in Wi-Fi joins the home
  network. In *standalone mode* (parties elsewhere) it opens its own admin
  Wi-Fi `Photobox-Admin` with DHCP in `192.168.73.0/24` (Pi: `192.168.73.1`);
  its QR code is on the settings screen. The booth never waits for a network
  and also starts without a camera (it then says so on screen).
- **Privacy:** photos stay on the Pi (`/var/lib/photobox/photos`). The touch
  UI and API only listen on `127.0.0.1`. Phones in the hotspot can reach
  nothing but the single photo behind their link (firewalled, no routing,
  phones isolated from each other). Photos are never committed to this
  repository.

## Hardware (prototype)

| Part | Used for the prototype |
|---|---|
| Computer | Raspberry Pi 4 (2 GB) |
| OS | Raspberry Pi OS Lite (64-bit, Debian 13 "trixie") |
| Camera | Raspberry Pi Camera Module 3 (IMX708, autofocus); OV5647 also works |
| Display | HDMI touchscreen, 1920×1200 |
| Hotspot | USB Wi-Fi stick with AP mode (tested: Realtek RTL8822BU, `rtw88`) |
| Printer | not yet |

## Repository layout

```
backend/    Python package (FastAPI app, camera drivers)
frontend/   Touch UI served by the backend
deploy/     Deploy script, systemd units, hotspot, network mode (admin/), polkit and udev files
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
| `GET /api/hotspot` | hotspot name and Wi-Fi QR code (SVG) |
| `POST /api/share/{name}` | new 5-minute phone link for a photo, with QR code |
| `GET /api/status` | settings screen: network mode, interfaces, connected devices, SSH, system |
| `POST /api/network-mode` | `{"mode": "home"\|"standalone"}` (if `[system] network_mode_command` is set) |
| `POST /api/ssh-password` | `{"enabled": true\|false}` (if `[system] ssh_password_command` is set) |
| `POST /api/reboot` | restart the Pi (if `[system] reboot_command` is set) |
| `POST /api/power-off` | power off the Pi (if `[system] power_off_command` is set) |

Phones in the hotspot only get `GET /d/{token}` (download page) and
`GET /d/{token}/photo.jpg`; everything else returns 404 there.

### On the Pi

First-time setup (packages, `photobox` user, directories, services):

```bash
sudo bash deploy/setup-pi.sh   # run from a copy of the repo on the Pi
sudo reboot                    # boots straight into the booth (~15 s)
```

Two systemd services run the booth:

| Service | |
|---|---|
| `photobox.service` | backend as user `photobox` (hardened, writes only to `/var/lib/photobox`) |
| `photobox-kiosk.service` | `cage` + Chromium full-screen on `tty1`, waits for the backend |
| `photobox-hotspot.service` | hostapd on the USB stick (named `guestwifi`), runs while it is plugged in |
| `photobox-netmode.service` | applies the saved network mode at boot (`/etc/photobox/network-mode`) |
| `photobox-admin-wifi.service` | hostapd on the built-in Wi-Fi, standalone mode only |

The settings screen switches modes and SSH password login by starting
`photobox-netmode@home|standalone.service` and
`photobox-ssh-password@on|off.service` (scripts in
[`deploy/admin/`](deploy/admin/)); [`deploy/polkit/50-photobox.rules`](deploy/polkit/)
lets the backend start exactly these units, reboot and power off, nothing
else. SSH password login is off by default (keys only); turn it on only
briefly, e.g. to copy a new key with `ssh-copy-id`.

The hotspot pieces live in [`deploy/hotspot/`](deploy/hotspot/): the hostapd
config is generated from the `[hotspot]` section of `config.toml`,
systemd-networkd gives the Pi `10.42.0.1` and hands out addresses, and
`hotspot.nft` only lets phones reach DHCP and the download page.

The USB touch panel reports every tap twice (as touchscreen and as emulated
mouse). [`deploy/udev/70-photobox-touch.rules`](deploy/udev/) makes libinput
ignore the mouse half; the UI also drops clicks that come in right after
another one.

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
deploy/deploy.sh --host=192.168.73.1   # e.g. over the admin Wi-Fi in standalone mode
```

New system pieces (packages, units, config keys) come with
`deploy/setup-pi.sh`; after pulling such a change, run it once on the Pi:
`sudo bash /opt/photobox/deploy/setup-pi.sh` (safe to run again, never
overwrites existing settings).

Only what changed is restarted: frontend changes reload the kiosk browser,
backend changes restart the backend (and the kiosk), changed systemd units are
reinstalled. The deployed git commit is shown in `/api/health` as `build`.

## License

[MIT](LICENSE)
