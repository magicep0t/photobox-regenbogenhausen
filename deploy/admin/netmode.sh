#!/bin/bash
# Network mode of the built-in Wi-Fi (wlan0). Run as root by systemd:
#
#   netmode.sh apply             at boot: apply the saved mode (photobox-netmode.service)
#   netmode.sh set home|standalone   save and apply (photobox-netmode@.service,
#                                    started by the settings screen)
#
# home:       wlan0 joins the home Wi-Fi (wpa_supplicant@wlan0, DHCP client).
# standalone: wlan0 opens the admin Wi-Fi (photobox-admin-wifi.service) with
#             its own DHCP server in 192.168.73.0/24, for parties away from home.
#
# The guest hotspot on the USB stick runs the same in both modes. The booth
# itself never waits for any network.
set -euo pipefail

MODE_FILE=/etc/photobox/network-mode
AP_NETWORK=/opt/photobox/deploy/admin/10-photobox-wlan0-ap.network
# /run wins over 20-wlan0.network in /etc (lower number) and is gone after a reboot
RUN_NETWORK=/run/systemd/network/10-photobox-wlan0-ap.network

apply() {
  local mode="$1"
  echo "Network mode: $mode"
  case "$mode" in
    home)
      systemctl stop photobox-admin-wifi.service || true
      rm -f "$RUN_NETWORK"
      networkctl reload
      systemctl start wpa_supplicant@wlan0.service
      networkctl reconfigure wlan0 || true
      ;;
    standalone)
      systemctl stop wpa_supplicant@wlan0.service || true
      install -D -m 644 "$AP_NETWORK" "$RUN_NETWORK"
      networkctl reload
      systemctl start photobox-admin-wifi.service
      networkctl reconfigure wlan0 || true
      ;;
  esac
}

case "${1:-}" in
  apply)
    mode="$(cat "$MODE_FILE" 2>/dev/null || true)"
    [ "$mode" = standalone ] || mode=home
    apply "$mode"
    ;;
  set)
    mode="${2:-}"
    case "$mode" in home|standalone) ;; *) echo "usage: $0 set home|standalone" >&2; exit 2 ;; esac
    printf '%s\n' "$mode" > "$MODE_FILE.tmp"
    mv "$MODE_FILE.tmp" "$MODE_FILE"
    apply "$mode"
    ;;
  *)
    echo "usage: $0 apply | set home|standalone" >&2
    exit 2
    ;;
esac
