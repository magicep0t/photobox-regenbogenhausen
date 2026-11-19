#!/bin/bash
# Allow or forbid SSH logins with a password. Run as root by
# photobox-ssh-password@on|off.service (button on the settings screen).
#
# off (the default): only SSH keys work.
# on:  passwords work too, e.g. to copy a new key with ssh-copy-id.
#      Turn it off again afterwards.
#
# sshd uses the first value it reads, and 05-… comes before the
# system's own 10-local.conf, which says "PasswordAuthentication no".
set -euo pipefail

DROPIN=/etc/ssh/sshd_config.d/05-photobox-password.conf

case "${1:-}" in
  on)
    printf '%s\n' "# written by the photobox settings screen; delete to allow SSH keys only" \
      "PasswordAuthentication yes" > "$DROPIN"
    ;;
  off)
    rm -f "$DROPIN"
    ;;
  *)
    echo "usage: $0 on|off" >&2
    exit 2
    ;;
esac

if ! sshd -t; then
  rm -f "$DROPIN"  # never leave a broken sshd config behind
  echo "sshd config invalid, password login stays off" >&2
  exit 1
fi
systemctl reload ssh.service
echo "SSH password login: $1"
