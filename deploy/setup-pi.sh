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
  fonts-dejavu-core

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

echo "Done."
