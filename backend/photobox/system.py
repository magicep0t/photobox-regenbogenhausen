"""System status for the settings screen, and the commands behind its buttons.

Everything here only reads what an unprivileged user may read (``ip``,
``networkctl``, ``iw``, ``/proc``, ``/sys``). Changing things (network mode,
SSH password login, reboot, power off) goes through commands from
``[system]`` in config.toml, which start systemd units allowed by a polkit
rule (see deploy/polkit/). On a laptop most values are simply missing.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

MODES = ("home", "standalone")
# drop-in written by deploy/admin/ssh-password.sh; sshd reads it before 10-*.conf
SSH_PASSWORD_DROPIN = Path("/etc/ssh/sshd_config.d/05-photobox-password.conf")

# what each interface is for (see deploy/)
WIFI, CABLE, GUEST = "wlan0", "end0", "guestwifi"

# vcgencmd get_throttled bits
THROTTLE_FLAGS = {
    0: "undervoltage",
    1: "freq_capped",
    2: "throttled",
    3: "temp_limit",
    16: "undervoltage_past",
    17: "freq_capped_past",
    18: "throttled_past",
    19: "temp_limit_past",
}


def run(args: list[str], timeout: float = 3) -> str | None:
    """stdout of a command, or None if it is missing or fails."""
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return res.stdout if res.returncode == 0 else None


def read(path: str | Path) -> str | None:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


# ---------------------------------------------------------------- parsers (pure, tested)


def parse_stations(text: str) -> dict[str, dict]:
    """``iw dev X station dump`` → {mac: {"signal": dBm, "connected_s": seconds}}."""
    stations: dict[str, dict] = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"Station ([0-9a-f:]{17})", line.strip())
        if m:
            current = stations.setdefault(m.group(1), {})
            continue
        if current is None:
            continue
        key, _, value = line.strip().partition(":")
        value = value.strip()
        if key == "signal":
            num = re.match(r"-?\d+", value)
            if num:
                current["signal"] = int(num.group())
        elif key == "connected time":
            num = re.match(r"\d+", value)
            if num:
                current["connected_s"] = int(num.group())
    return stations


def _ip_from(value) -> str | None:
    if isinstance(value, list) and len(value) == 4:
        return ".".join(str(b) for b in value)
    if isinstance(value, str):
        return value
    return None


def parse_leases(link: dict) -> list[dict]:
    """DHCP leases handed out by networkd, from ``networkctl status X --json=short``."""
    leases = []
    for lease in (link.get("DHCPServer") or {}).get("Leases") or []:
        client_id = lease.get("ClientId") or []
        # client id type 1 = Ethernet: [1, six MAC bytes]
        mac = ":".join(f"{b:02x}" for b in client_id[1:7]) if len(client_id) >= 7 and client_id[0] == 1 else None
        leases.append({"ip": _ip_from(lease.get("Address")), "mac": mac, "name": lease.get("Hostname") or None})
    return leases


def decode_throttled(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = int(raw.split("=")[-1], 16)
    except ValueError:
        return []
    return [name for bit, name in THROTTLE_FLAGS.items() if value & (1 << bit)]


# ---------------------------------------------------------------- collectors


def _interfaces() -> dict[str, dict]:
    out = run(["ip", "-j", "addr", "show"])
    result = {}
    for item in json.loads(out) if out else []:
        result[item["ifname"]] = {
            "up": item.get("operstate") == "UP",
            "mac": item.get("address"),
            "ipv4": [f"{a['local']}/{a['prefixlen']}" for a in item.get("addr_info", []) if a.get("family") == "inet"],
        }
    return result


def _networkd(name: str) -> dict:
    out = run(["networkctl", "status", name, "--json=short"])
    try:
        return json.loads(out) if out else {}
    except ValueError:
        return {}


def _neighbours() -> dict[str, str]:
    """MAC → IPv4 from the kernel's neighbour table."""
    out = run(["ip", "-4", "-j", "neigh", "show"])
    result = {}
    for item in json.loads(out) if out else []:
        if item.get("lladdr") and "FAILED" not in item.get("state", []):
            result[item["lladdr"].lower()] = item["dst"]
    return result


def _clients(name: str, link: dict, neighbours: dict[str, str]) -> list[dict]:
    """Devices connected to one of the Pi's access points."""
    stations = parse_stations(run(["iw", "dev", name, "station", "dump"]) or "")
    leases = {lease["mac"]: lease for lease in parse_leases(link) if lease["mac"]}
    clients = []
    for mac, info in stations.items():
        lease = leases.get(mac, {})
        clients.append({
            "mac": mac,
            "ip": lease.get("ip") or neighbours.get(mac),
            "name": lease.get("name"),
            "signal": info.get("signal"),
            "connected_s": info.get("connected_s"),
        })
    return clients


def network_mode(mode_file: Path) -> str:
    mode = read(mode_file)
    return mode if mode in MODES else "home"


def collect_network(mode_file: Path) -> dict:
    ifaces = _interfaces()
    neighbours = _neighbours()
    networks = []
    for name, role in ((WIFI, "wifi"), (CABLE, "cable"), (GUEST, "guest")):
        if name not in ifaces:
            if name == GUEST:
                networks.append({"id": role, "iface": name, "present": False})
            continue
        link = _networkd(name)
        is_ap = link.get("WirelessLanInterfaceTypeString") == "ap"
        dhcp_server = "DHCPServer" in link
        entry = {
            "id": role,
            "iface": name,
            "present": True,
            "up": ifaces[name]["up"] or link.get("OperationalState") in ("routable", "carrier", "degraded"),
            "ipv4": ifaces[name]["ipv4"],
            "ssid": link.get("SSID"),
            "ap": is_ap,
            "dhcp": "server" if dhcp_server else ("client" if ifaces[name]["ipv4"] or link else None),
            "clients": _clients(name, link, neighbours) if is_ap else [],
        }
        if dhcp_server:
            pool = link["DHCPServer"]
            entry["dhcp_leases"] = len(parse_leases(link))
            entry["dhcp_pool"] = pool.get("PoolSize")
        networks.append(entry)
    return {"mode": network_mode(mode_file), "networks": networks}


def collect_ssh() -> dict:
    sessions = []
    out = run(["ss", "-Htn", "state", "established", "( sport = :22 )"])
    for line in (out or "").splitlines():
        parts = line.split()
        if len(parts) >= 4:
            sessions.append(parts[-1].rsplit(":", 1)[0].strip("[]"))
    active = (run(["systemctl", "is-active", "ssh.service"]) or "").strip() == "active"
    return {"active": active, "password": SSH_PASSWORD_DROPIN.exists(), "sessions": sessions}


def collect_system(photos_dir: Path) -> dict:
    temp = read("/sys/class/thermal/thermal_zone0/temp")
    throttled_raw = (run(["vcgencmd", "get_throttled"]) or "").strip() or None
    mem = {}
    for line in (read("/proc/meminfo") or "").splitlines():
        key, _, value = line.partition(":")
        mem[key] = int(value.split()[0]) if value.split() else 0
    try:
        disk = shutil.disk_usage(photos_dir)
    except OSError:
        disk = None
    uptime = read("/proc/uptime")
    ntp = (run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"]) or "").strip()
    return {
        "temp_c": round(int(temp) / 1000, 1) if temp and temp.isdigit() else None,
        "throttled": decode_throttled(throttled_raw),
        "load": [round(x, 2) for x in os.getloadavg()],
        "cpus": os.cpu_count(),
        "mem_total_mb": mem.get("MemTotal", 0) // 1024 or None,
        "mem_used_mb": (mem.get("MemTotal", 0) - mem.get("MemAvailable", 0)) // 1024 if mem else None,
        "disk_free_gb": round(disk.free / 1e9, 1) if disk else None,
        "disk_total_gb": round(disk.total / 1e9, 1) if disk else None,
        "uptime_s": int(float(uptime.split()[0])) if uptime else None,
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "ntp": {"yes": True, "no": False}.get(ntp),
    }


# ---------------------------------------------------------------- actions


def fill(command: tuple[str, ...], **values: str) -> list[str]:
    """Command from config.toml with {mode}/{state} filled in."""
    return [part.format(**values) for part in command]


def execute(command: list[str]) -> bool:
    """Run a command from config.toml; True if it worked (errors are logged)."""
    log.warning("Running: %s", " ".join(command))
    t0 = time.monotonic()
    try:
        res = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as err:
        log.error("Command failed: %s", err)
        return False
    if res.returncode != 0:
        log.error("Command failed (%s, %.1fs): %s", res.returncode, time.monotonic() - t0, res.stderr.strip())
        return False
    return True
