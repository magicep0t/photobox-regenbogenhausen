#!/bin/bash
# Deploy the photobox from this repository to the Pi.
#
#   deploy/deploy.sh               run tests, sync, restart what changed
#   deploy/deploy.sh --no-tests    skip the local test run
#   deploy/deploy.sh --dry-run     only show what would be copied
#   deploy/deploy.sh --host=ADDR   use another address than in deploy/.env
#                                  (e.g. the Pi's admin Wi-Fi or a direct cable)
#
# Settings come from deploy/.env (git-ignored), see deploy/.env.example.
# The SSH user needs passwordless sudo on the Pi.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

RUN_TESTS=1
DRY_RUN=0
HOST_OVERRIDE=""
for arg in "$@"; do
  case "$arg" in
    --no-tests) RUN_TESTS=0 ;;
    --dry-run) DRY_RUN=1 ;;
    --host=*) HOST_OVERRIDE="${arg#--host=}" ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [ ! -f deploy/.env ]; then
  echo "Missing deploy/.env — copy deploy/.env.example and fill it in." >&2
  exit 1
fi
# shellcheck disable=SC1091
source deploy/.env
[ -n "$HOST_OVERRIDE" ] && PHOTOBOX_HOST="$HOST_OVERRIDE"
: "${PHOTOBOX_HOST:?set PHOTOBOX_HOST in deploy/.env}"
: "${PHOTOBOX_SSH_USER:?set PHOTOBOX_SSH_USER in deploy/.env}"
read -r -a SSH_OPTS <<< "${PHOTOBOX_SSH_OPTS:-}"
SSH_OPTS+=(-o BatchMode=yes -o ConnectTimeout=8)
TARGET="$PHOTOBOX_SSH_USER@$PHOTOBOX_HOST"

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
remote() { ssh "${SSH_OPTS[@]}" "$TARGET" "$@" </dev/null; }

# ---------------------------------------------------------------- checks
BUILD="$(git describe --always --dirty 2>/dev/null || echo unknown)"
if [[ "$BUILD" == *-dirty ]]; then
  echo "Note: deploying uncommitted changes ($BUILD)."
fi

if [ "$RUN_TESTS" = 1 ]; then
  step "Tests"
  if [ -x backend/.venv/bin/python ]; then
    (cd backend && .venv/bin/python -m pytest -q 2>&1 | tail -1)
  else
    echo "No backend/.venv — skipping tests (see README → Development)."
  fi
fi

step "Connection to $TARGET"
remote 'sudo -n true' || { echo "Cannot SSH in or no passwordless sudo." >&2; exit 1; }
echo "ok"

# ---------------------------------------------------------------- sync
step "Sync to /opt/photobox"
RSYNC_FLAGS=(-a --delete --itemize-changes --checksum
  --rsync-path="sudo rsync" --chown=root:root --chmod=D755,F644
  -e "ssh ${SSH_OPTS[*]}"
  --exclude .venv --exclude tests --exclude __pycache__ --exclude '*.egg-info'
  --exclude .pytest_cache --exclude .env --exclude deploy/.env)
[ "$DRY_RUN" = 1 ] && RSYNC_FLAGS+=(--dry-run)

CHANGES="$(rsync "${RSYNC_FLAGS[@]}" backend frontend deploy "$TARGET:/opt/photobox/" | grep -v '^\.d' || true)"
if [ -z "$CHANGES" ]; then
  echo "Nothing changed."
else
  echo "$CHANGES" | sed 's/^/  /'
fi
if [ "$DRY_RUN" = 1 ]; then
  echo; echo "Dry run: nothing was copied or restarted."
  exit 0
fi

# itemized lines look like ">fcsT...... backend/x.py" or "*deleting   frontend/y.js"
changed() { grep -qE "^[^ ]+ +$1" <<< "$CHANGES"; }

# ---------------------------------------------------------------- apply
step "Apply"
remote "echo '$BUILD' | sudo tee /opt/photobox/BUILD >/dev/null"

RESTART_BACKEND=0
RESTART_KIOSK=0
if changed 'deploy/systemd/'; then
  remote 'sudo install -m 644 /opt/photobox/deploy/systemd/*.service /etc/systemd/system/ && sudo systemctl daemon-reload'
  echo "systemd units updated"
  RESTART_BACKEND=1; RESTART_KIOSK=1
fi
if changed 'deploy/systemd/'; then
  remote 'sudo systemctl try-restart photobox-hotspot.service photobox-hotspot-dns.service'
fi
if changed 'deploy/hotspot/'; then
  remote 'sudo install -m 644 /opt/photobox/deploy/hotspot/*.network /etc/systemd/network/ && sudo networkctl reload && sudo systemctl try-restart photobox-hotspot.service'
  echo "hotspot updated"
fi
if changed 'deploy/polkit/'; then
  remote 'sudo rm -f /etc/polkit-1/rules.d/50-photobox-power-off.rules && sudo install -m 644 /opt/photobox/deploy/polkit/*.rules /etc/polkit-1/rules.d/'
  echo "polkit rules updated"
fi
if changed 'deploy/udev/'; then
  remote 'sudo install -m 644 /opt/photobox/deploy/udev/*.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=input --action=change'
  echo "udev rules updated"
  RESTART_KIOSK=1  # the compositor picks up input devices at start
fi
changed 'backend/' && RESTART_BACKEND=1
changed 'frontend/' && RESTART_KIOSK=1   # reload the page in the kiosk browser
[ "$RESTART_BACKEND" = 1 ] && RESTART_KIOSK=1  # the kiosk's stream dies with the backend

if [ "$RESTART_BACKEND" = 1 ]; then
  remote 'sudo systemctl restart photobox.service' && echo "photobox.service restarted"
fi
if [ "$RESTART_KIOSK" = 1 ]; then
  remote 'sudo systemctl restart photobox-kiosk.service' && echo "photobox-kiosk.service restarted"
fi
[ "$RESTART_BACKEND$RESTART_KIOSK" = "00" ] && echo "No restart needed."

# ---------------------------------------------------------------- verify
step "Check"
remote '
  for i in $(seq 1 30); do
    if health=$(curl -sf http://127.0.0.1:8000/api/health); then break; fi
    sleep 1
  done
  [ -n "${health:-}" ] || { echo "backend: NOT responding"; exit 1; }
  echo "backend: $health"
  for i in $(seq 1 20); do
    [ "$(systemctl is-active photobox-kiosk)" = active ] && break; sleep 1
  done
  echo "kiosk:   $(systemctl is-active photobox-kiosk)"
  echo "build:   $(cat /opt/photobox/BUILD)"
'
echo; echo "Deployed $BUILD to $PHOTOBOX_HOST."
