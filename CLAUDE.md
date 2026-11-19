# CLAUDE.md – Photobox Regenbogenhausen

DIY touchscreen photo booth on a Raspberry Pi 4 for parties. Public repo
(MIT): `github.com/magicep0t/photobox-regenbogenhausen`. Private details (IPs,
accounts, current state) are in `CLAUDE.local.md`, the German operating manual
for the owner is `HowToPhotobox.md`; both are git-excluded via
`.git/info/exclude` and must never be committed.

## Rules

- **Every 10 user messages in a session, update this file, `CLAUDE.local.md`
  and `HowToPhotobox.md` without being asked** (whatever changed: features,
  files, state, open items). Also update them at the end of any larger change.
- Talk to the user in **English**, unless `CLAUDE.local.md` names another
  language (personal preference, e.g. German); that file wins. Code, comments,
  README, commits are always in **English**.
  UI is English with an EN/DE toggle (`frontend/i18n.js`, keep both languages
  in sync; phone pages in `share.py` too).
- Plan first for bigger changes; the user approves phases.
- Python only on the backend, **no PHP**. Frontend: plain HTML/CSS/JS, no build step.
- **Never commit** photos, real IPs of the home network, passwords, keys,
  `deploy/.env`, `config.local.toml`, `HowToPhotobox.md`, `CLAUDE.local.md`.
  Before committing, scan the staged diff with the grep from `CLAUDE.local.md`.
  (`10.42.0.1` and `192.168.73.x` are fixed design addresses and fine.)
- Commits: `git -c user.name=benton -c user.email=13524431+magicep0t@users.noreply.github.com commit …`,
  ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Push to `main` after committing.
- Never show Wi-Fi passwords in chat (they live in `/etc/photobox/config.toml` on the Pi).
- Laptop shell is zsh: wrap ssh with options in `bash -c '…'`. Don't `pkill -f` a
  pattern that also matches your own command line.

## Architecture

```
Pi 4 (Debian 13 trixie, Raspberry Pi OS Lite 64-bit)
├─ photobox.service        python3 -m photobox (FastAPI/uvicorn, user photobox, hardened)
│    ├─ 127.0.0.1:8000     touch UI + API (never exposed)
│    └─ 10.42.0.1:80       guest phones only: captive portal + photo links
├─ photobox-kiosk.service  cage + Chromium --kiosk → 127.0.0.1:8000/?kiosk=1 on tty1
├─ photobox-hotspot(-dns)  guest Wi-Fi "Photobox" on USB stick `guestwifi` (hostapd, 5 GHz ch 36)
│                          + dnsmasq DNS-only (every name → 10.42.0.1)
├─ photobox-netmode        built-in wlan0: home (wpa_supplicant@wlan0, DHCP client)
│                          or standalone (photobox-admin-wifi: hostapd AP "Photobox-Admin",
│                          2.4 GHz ch 6, 192.168.73.1/24, networkd DHCP .100–.149, no router/DNS)
└─ polkit 50-photobox.rules  user photobox may only: power off, reboot, start
                             photobox-netmode@{home,standalone} and photobox-ssh-password@{on,off}
```

Hardware: Pi 4 2 GB, HDMI touchscreen 1920×1200 with USB touch "CXDIS"
(0416:c168; reports every tap also as mouse), Raspberry Pi Camera Module 3
(IMX708, autofocus; OV5647 also supported), USB Wi-Fi stick RTL8822BU (rtw88).
Later: gphoto2 camera, printer (CUPS), GPIO buzzer, branding.

Screen layout: stage (preview/layers) left, menu column 260 px right.
UI states (`frontend/app.js`):
`live → countdown → result → live`, `live → gallery → viewer`,
`result|viewer → share` (QR ① Wi-Fi, ② photo link), `live → wifi`,
`live → settings → confirm | power1 → power2 → powering | rebooting`.
Tap on the live preview takes a photo. Idle timeout 60 s back to live (share
closes, link stays valid; settings/confirm ×5). A capture-phase click guard drops
clicks within 400 ms after a click or state change (double taps).

## Files

```
backend/photobox/
  __main__.py      binds sockets (hotspot socket with IP_FREEBIND), runs uvicorn
  app.py           create_app(): all routes, hotspot_guard middleware, camera fallback
  config.py        frozen dataclasses from TOML ($PHOTOBOX_CONFIG or /etc/photobox/config.toml);
                   unknown keys = error. Sections: camera, ui, hotspot, admin_wifi, system
  camera/base.py   Camera ABC + FrameBuffer (latest MJPEG frame, wait_for_frame)
  camera/picamera.py  picamera2: preview YUV420 → MJPEGEncoder, auto size (1536 px wide,
                   sensor aspect), FrameRate=preview_fps, AF continuous; capture: keep
                   LensPosition, switch to still config, then back
  camera/mock.py   Pillow test images (dev/tests)
  camera/unavailable.py  UnavailableCamera: notice frame "Kamera nicht gefunden", capture → 503
  photos.py        PhotoStore: names YYYYMMDD-HHMMSS-xxxxxx.jpg, thumbs in .thumbs/ (480 px), count()
  share.py         ShareLinks (random tokens, TTL, active()), SignedIn (portal "Done" per IP),
                   QR SVGs (segno), connectivity-probe answers, phone HTML pages (EN/DE)
  system.py        status collectors (ip -j, networkctl --json, iw station dump, ss, /sys, vcgencmd,
                   timedatectl), parsers, execute() for [system] commands
backend/tests/     test_app.py, test_share.py, test_system.py (pytest, mock camera)
frontend/          index.html (SVG icon symbols, layers), app.js (states/menus), app.css, i18n.js
deploy/
  deploy.sh        laptop → Pi: tests, rsync backend/frontend/deploy to /opt/photobox (root-owned),
                   reinstall changed units/hotspot/polkit/udev, restart what changed, health check.
                   Options: --dry-run --no-tests --host=ADDR. Reads deploy/.env (PHOTOBOX_HOST,
                   PHOTOBOX_SSH_USER, PHOTOBOX_SSH_OPTS)
  setup-pi.sh      idempotent base setup as root: apt packages, user photobox (video,input,render),
                   dirs, polkit, config_default() adds missing config keys (never overwrites),
                   random hotspot/admin passwords, stick rename .link, udev, enable units,
                   disables wpa_supplicant@wlan0 autostart. Re-run after deploys adding system parts
  systemd/         photobox, photobox-kiosk, photobox-hotspot, photobox-hotspot-dns, photobox-netmode,
                   photobox-netmode@, photobox-admin-wifi, photobox-ssh-password@
  hotspot/         hostapd-conf.py guest|admin (writes /run/…/hostapd.conf from config.toml),
                   30-photobox-guestwifi.network (10.42.0.1/24, DHCP, emits router+DNS),
                   hotspot.nft (guests: only DHCP, DNS, :80, ping; no forwarding)
  admin/           netmode.sh apply|set MODE (mode file /etc/photobox/network-mode; standalone copies
                   10-photobox-wlan0-ap.network to /run/systemd/network/), ssh-password.sh on|off
                   (/etc/ssh/sshd_config.d/05-photobox-password.conf, sshd -t, reload)
  polkit/50-photobox.rules   udev/70-photobox-touch.rules (LIBINPUT_IGNORE_DEVICE on the mouse half)
config.example.toml  all keys with defaults/comments
docs/PLAN.md       phases 0–7 (all done) and later ideas
```

## API

Touch side (127.0.0.1:8000): `GET /api/health` (build, camera), `GET /api/config`
(UI flags: hotspot, power_off, reboot, network_mode, ssh_password, camera),
`GET /api/stream` (MJPEG), `GET /api/snapshot`, `POST /api/capture` (503 = no camera),
`GET /api/photos?limit`, `GET /photos/{name}`, `GET /thumbs/{name}`,
`GET /api/hotspot`, `POST /api/share/{name}` (link + QR, `link_seconds`=300),
`GET /api/status`, `POST /api/network-mode {"mode"}`, `POST /api/ssh-password {"enabled"}`,
`POST /api/reboot`, `POST /api/power-off`. Actions return 404 if their
`[system] *_command` is empty; `{mode}`/`{state}` are filled in.

Phone side (10.42.0.1:80): connectivity probes → 302 to portal until "Done"
(`POST /signin`), then success answers; `/` lists all active shared photos
(newest first) or a waiting page; `/d/{token}`, `/d/{token}/photo.jpg[?download=1]`;
anything else 404. Static UI files are served with `Cache-Control: no-cache`.

## Pi paths

Code `/opt/photobox` (+ `BUILD` = deployed git describe), photos
`/var/lib/photobox/photos` (never leave the Pi), config
`/etc/photobox/config.toml` (640 root:photobox), mode
`/etc/photobox/network-mode`. Home Wi-Fi is NOT netplan:
`/etc/wpa_supplicant/wpa_supplicant-wlan0.conf` + `/etc/systemd/network/20-wlan0.network`.
Cable end0 via netplan (DHCP). Kiosk screenshot:
`sudo -u photobox env XDG_RUNTIME_DIR=/run/user/997 WAYLAND_DISPLAY=wayland-0 grim /tmp/s.png`.
`iw` is in `/usr/sbin`. The camera is not hot-pluggable (reboot after reconnecting).

## Development

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q                                   # 62 tests
PHOTOBOX_CONFIG=../config.local.toml .venv/bin/python -m photobox   # mock camera, :8765, portal :8766
```

`config.local.toml` (git-ignored) uses the mock camera and harmless commands
(`["true"]`, mode written to a scratch file). UI flows can be driven headless:
laptop snap Chromium with `--remote-debugging-port` + a small CDP script
(Python `websocket`, in `backend/.venv`); screenshots must go under `~`
(e.g. `~/snap-shots`). Against the real Pi: `ssh -L 8011:127.0.0.1:8000 …`.
