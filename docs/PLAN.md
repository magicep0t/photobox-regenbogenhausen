# Plan

## Decisions

- **Architecture:** Python/FastAPI backend + HTML/CSS/JS frontend shown in a
  Chromium kiosk under `cage`.
- **Camera abstraction:** one interface, drivers per camera. `picamera2` for the
  prototype, `gphoto2` for a real camera later.
- **Language:** code, docs and commits in English. UI in English with a toggle
  to German; the choice persists until toggled again.
- **Privacy:** photos only on the Pi, backend bound to `127.0.0.1`, no network
  gallery in the prototype. No photos, IPs, passwords or keys in the repo.
- **License:** MIT.

## Touch flow (prototype)

1. **Start screen** — live preview, "Tap to start"
2. **Countdown** — 3 – 2 – 1, white flash
3. **Result** — "Again" / "Done" (print comes later)
4. **Gallery** — recent photos; back to start after a timeout

## Phases

| # | What | Done when |
|---|---|---|
| 0 ✅ | Repository, README, license, skeleton | repo on GitHub |
| 1 ✅ | Pi base (`deploy/setup-pi.sh`): `python3-picamera2`, `cage`, `chromium` (no recommends); system user `photobox` (`video`, `input`); `/opt/photobox`, `/var/lib/photobox` | camera works as user `photobox` |
| 2 ✅ | Backend: camera layer, `GET /stream`, `POST /capture`, `GET /photos`, config file (rotation, resolution, countdown) | preview + capture in a laptop browser via SSH tunnel |
| 3 ✅ | Frontend (menu on the right): start → countdown → flash → result → gallery, idle timeout, EN/DE toggle | full flow in a laptop browser via SSH tunnel |
| 4 | Kiosk: `photobox.service` + `photobox-kiosk.service`, autostart, no screen blanking, touch check | Pi reboots straight into the booth |
| 5 | `deploy/deploy.sh`: rsync laptop → Pi, restart service | one command to deploy |

## Later

- Printer (CUPS)
- Real camera via gphoto2
- Physical buzzer button (GPIO)
- Frames / party branding
- Network gallery with QR-code download
