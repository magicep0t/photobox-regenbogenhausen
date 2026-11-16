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
  grim \
  python3-segno \
  hostapd \
  nftables \
  rfkill \
  dnsmasq-base
# python3-segno: QR codes. hostapd, dnsmasq-base, nftables, rfkill: guest
# hotspot for phones (dnsmasq-base has no service of its own).
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG=/etc/photobox/config.toml
touch "$CONFIG"

echo "== Power-off button =="
# polkit lets the 'photobox' user power off the Pi, nothing more
install -m 644 "$SCRIPT_DIR/polkit/50-photobox-power-off.rules" /etc/polkit-1/rules.d/
if ! grep -q '^\[system\]' "$CONFIG"; then
  printf '\n[system]\npower_off_command = ["systemctl", "poweroff"]\n' >> "$CONFIG"
fi

echo "== Guest hotspot (USB Wi-Fi stick) =="
# The built-in Wi-Fi stays in the home network; a USB stick serves the
# 5 GHz hotspot that guests' phones join to download their photos.
STICK=""
for dev in /sys/class/net/*; do
  [ -d "$dev/wireless" ] || [ -d "$dev/phy80211" ] || continue
  [ "$(basename "$dev")" = guestwifi ] && { STICK=guestwifi; break; }
  case "$(readlink -f "$dev/device")" in *usb*) STICK="$(basename "$dev")"; break ;; esac
done
install -m 644 "$SCRIPT_DIR/hotspot/30-photobox-guestwifi.network" /etc/systemd/network/
if [ -n "$STICK" ]; then
  if [ "$STICK" != guestwifi ]; then
    MAC="$(cat "/sys/class/net/$STICK/address")"
    printf '%s\n' \
      "# USB Wi-Fi stick for the photobox guest hotspot (found by setup-pi.sh)" \
      "[Match]" "PermanentMACAddress=$MAC" "" "[Link]" "Name=guestwifi" \
      > /etc/systemd/network/10-photobox-guestwifi.link
    echo "Wi-Fi stick $STICK ($MAC) will be named 'guestwifi' (after replug or reboot)."
  fi
  if ! grep -q '^\[hotspot\]' "$CONFIG"; then
    # random password; guests never type it, it's in the QR code
    PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')"
    printf '\n[hotspot]\nenabled = true\nssid = "Photobox"\npassword = "%s"\n' "$PASSWORD" >> "$CONFIG"
  fi
else
  echo "No USB Wi-Fi stick found: hotspot not enabled (plug one in and run this again)."
fi
# the config now holds the hotspot password: readable for the backend only
chown root:photobox "$CONFIG"
chmod 640 "$CONFIG"
# hostapd is started by photobox-hotspot.service, not by its own unit
systemctl disable --now hostapd.service 2>/dev/null || true

echo "== Touchscreen =="
# ignore the panel's mouse emulation, otherwise every tap arrives twice
install -m 644 "$SCRIPT_DIR"/udev/*.rules /etc/udev/rules.d/
udevadm control --reload
udevadm trigger --subsystem-match=input --action=change

echo "== systemd services =="
install -m 644 "$SCRIPT_DIR"/systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable photobox.service photobox-kiosk.service photobox-hotspot.service photobox-hotspot-dns.service
networkctl reload

echo "Done. Reboot to start the kiosk, or: systemctl start photobox-kiosk"
