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
  dnsmasq-base \
  iw
# python3-segno: QR codes. hostapd, dnsmasq-base, nftables, rfkill: guest
# hotspot for phones (dnsmasq-base has no service of its own).
# iw: list of connected devices on the settings screen.
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

# config_default SECTION KEY TOML-VALUE: add KEY to [SECTION] of config.toml
# unless it is already set there (existing values are never changed)
config_default() {
  python3 - "$CONFIG" "$1" "$2" "$3" <<'PY'
import re, sys, tomllib
path, section, key, value = sys.argv[1:]
text = open(path).read()
if key in tomllib.loads(text).get(section, {}):
    sys.exit(0)
header = re.search(rf"^\[{re.escape(section)}\][ \t]*$", text, re.M)
line = f"{key} = {value}\n"
if header:
    end = header.end() + 1
    text = text[:end] + line + text[end:]
else:
    text = text.rstrip("\n") + f"\n\n[{section}]\n{line}"
open(path, "w").write(text)
PY
}
random_password() { python3 -c 'import secrets; print(secrets.token_urlsafe(12))'; }

echo "== Settings screen =="
# polkit lets the 'photobox' user power off, reboot and start the units
# behind the network-mode and SSH buttons, nothing more
rm -f /etc/polkit-1/rules.d/50-photobox-power-off.rules  # old name
install -m 644 "$SCRIPT_DIR/polkit/50-photobox.rules" /etc/polkit-1/rules.d/
config_default system power_off_command '["systemctl", "poweroff"]'
config_default system reboot_command '["systemctl", "reboot"]'
config_default system network_mode_command '["systemctl", "start", "--no-block", "photobox-netmode@{mode}.service"]'
config_default system ssh_password_command '["systemctl", "start", "photobox-ssh-password@{state}.service"]'

echo "== Network mode (home Wi-Fi or own admin Wi-Fi) =="
# The built-in Wi-Fi either joins the home network or, in standalone mode,
# opens its own admin Wi-Fi (deploy/admin/netmode.sh). wpa_supplicant@wlan0
# is then started by photobox-netmode.service instead of at boot by itself.
[ -f /etc/photobox/network-mode ] || echo home > /etc/photobox/network-mode
if ! python3 -c 'import sys, tomllib; sys.exit(0 if "admin_wifi" in tomllib.load(open(sys.argv[1], "rb")) else 1)' "$CONFIG"; then
  config_default admin_wifi password "\"$(random_password)\""
  config_default admin_wifi ssid '"Photobox-Admin"'
  config_default admin_wifi enabled true
fi
systemctl disable wpa_supplicant@wlan0.service 2>/dev/null || true

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
    PASSWORD="$(random_password)"
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
systemctl enable photobox.service photobox-kiosk.service photobox-hotspot.service photobox-hotspot-dns.service \
  photobox-netmode.service
networkctl reload

echo "Done. Reboot to start the kiosk, or: systemctl start photobox-kiosk"
