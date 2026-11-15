#!/bin/bash
# One-time base setup of the Raspberry Pi (phase 1).
# Run on the Pi as root:  sudo bash deploy/setup-pi.sh
# Safe to run again.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run as root (sudo)." >&2
  exit 1
fi

echo "== Packages =="
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get -y install --no-install-recommends \
  python3-picamera2 \
  python3-fastapi \
  python3-uvicorn \
  python3-pil \
  cage \
  chromium \
  fonts-dejavu-core \
  fake-hwclock \
  grim
# fake-hwclock: the Pi has no RTC; restore the last known time at boot so
#               photo timestamps are sane before (or without) NTP.
# grim:         screenshots of the kiosk display for debugging.

echo "== Boot tweaks =="
# Boot as soon as *one* network is up (Wi-Fi or cable), not all of them.
install -d /etc/systemd/system/systemd-networkd-wait-online.service.d
cat > /etc/systemd/system/systemd-networkd-wait-online.service.d/any.conf <<'EOF'
# Photobox: wait for any one network (Wi-Fi or cable), not all of them
[Service]
ExecStart=
ExecStart=/usr/lib/systemd/systemd-networkd-wait-online --any --timeout=30
EOF
# Keep logs across reboots.
install -d -m 2755 -g systemd-journal /var/log/journal

echo "== System user 'photobox' =="
if ! id photobox >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/photobox --no-create-home \
    --shell /usr/sbin/nologin --user-group photobox
fi
# video: camera, input: touchscreen, render: GPU (Chromium/cage)
usermod -aG video,input,render photobox

echo "== Directories =="
install -d -m 755 -o root -g root /opt/photobox                      # application code
install -d -m 750 -o photobox -g photobox /var/lib/photobox           # runtime data
install -d -m 750 -o photobox -g photobox /var/lib/photobox/photos    # photos (never leave the Pi)
install -d -m 755 /etc/photobox                                       # config.toml (see config.example.toml)

echo "== systemd services =="
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install -m 644 "$SCRIPT_DIR/systemd/photobox.service" /etc/systemd/system/
install -m 644 "$SCRIPT_DIR/systemd/photobox-kiosk.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable photobox.service photobox-kiosk.service

echo "Done. Reboot to start the kiosk, or: systemctl start photobox-kiosk"
