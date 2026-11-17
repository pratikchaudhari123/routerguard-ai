"""Read-only reachability checks for the two-router Wi-Fi sensing experiment.

These checks verify IP reachability only. They do not read WDS RSSI, CSI,
or infer motion.
"""
import os
import platform
import re
import socket
import subprocess
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


def _ping(ip):
    if not ip:
        return False
    cmd = ["ping", "-c", "1", "-W", "1000", ip] if platform.system() == "Darwin" else ["ping", "-c", "1", "-W", "1", ip]
    try:
        return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _open_ports(ip):
    ports = []
    for port in (80, 443):
        try:
            with socket.create_connection((ip, port), timeout=0.4):
                ports.append(port)
        except OSError:
            pass
    return ports


def _arp_map():
    try:
        out = subprocess.run(["arp", "-an"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    found = {}
    for line in out.splitlines():
        ip_match = re.search(r"\\((\\d{1,3}(?:\\.\\d{1,3}){3})\\)", line)
        mac_match = re.search(r" at ((?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2})", line)
        if ip_match and mac_match:
            found[ip_match.group(1)] = mac_match.group(1).upper()
    return found


def router_diagnostics():
    # These are the addresses already observed in this installation.
    # Override with ROUTER_JIO_IP / ROUTER_TPLINK_IP if the LAN changes.
    targets = [
        {"id": "jio", "name": "JioAirFiber", "ip": os.getenv("ROUTER_JIO_IP", "192.168.31.1").strip()},
        {"id": "tplink", "name": "TP-Link TL-WR850N", "ip": os.getenv("ROUTER_TPLINK_IP", "192.168.0.1").strip()},
    ]
    arp = _arp_map()
    routers = []
    for item in targets:
        ip = item["ip"]
        reachable = _ping(ip)
        routers.append({
            **item,
            "reachable": reachable,
            "status": "reachable" if reachable else "not_reachable_from_this_mac",
            "management_ports": _open_ports(ip) if reachable else [],
            "arp_mac": arp.get(ip),
            "checked_at": _now(),
        })
    return {
        "checked_at": _now(),
        "routers": routers,
        "wds_status": {
            "value": "manual_check_required",
            "instruction": "On TP-Link, open Advanced > Status > Wireless and read WDS Status. Run means the bridge is up.",
        },
        "measurement_access": {
            "wds_rssi": "not_exposed_by_this_read_only_probe",
            "csi": "not_available_from_this_router_diagnostics_endpoint",
            "macbook_rssi": "separate_macbook_to_associated_ap_link",
        },
        "safety": "Read-only ping, TCP port checks, and local ARP lookup. No login, settings changes, scans of other subnets, or firmware actions.",
    }
