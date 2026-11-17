import os
import platform
import re
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

def now():
    return datetime.now(timezone.utc).isoformat()

def ping(ip: str) -> bool:
    if not ip:
        return False
    cmd = ["ping", "-c", "1", "-W", "1000", ip] if platform.system() == "Darwin" else ["ping", "-c", "1", "-W", "1", ip]
    try:
        return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False

def open_ports(ip: str):
    found = []
    for port in (22, 53, 80, 443, 8080, 8443):
        try:
            with socket.create_connection((ip, port), timeout=0.35):
                found.append(port)
        except OSError:
            pass
    return found

def read_arp_table():
    try:
        output = subprocess.run(["arp", "-an"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    devices = []
    # macOS: ? (192.168.1.10) at aa:bb:cc:dd:ee:ff on en0 ...
    for line in output.splitlines():
        ip_match = re.search(r"\((\d{1,3}(?:\.\d{1,3}){3})\)", line)
        mac_match = re.search(r" at ((?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2})", line)
        if ip_match and mac_match:
            ip, mac = ip_match.group(1), mac_match.group(1).upper()
            if mac != "FF:FF:FF:FF:FF:FF":
                devices.append({"ip": ip, "mac": mac})
    return sorted({d["mac"]: d for d in devices}.values(), key=lambda d: d["ip"])

def router_config():
    return [
        {"id": "router_a", "name": os.getenv("ROUTER_A_NAME", "Router A"), "ip": os.getenv("ROUTER_A_IP", "").strip()},
        {"id": "router_b", "name": os.getenv("ROUTER_B_NAME", "Router B"), "ip": os.getenv("ROUTER_B_IP", "").strip()},
    ]

def perform_scan(known_macs):
    routers = []
    for r in router_config():
        ip = r["ip"]
        if not ip:
            routers.append({**r, "status": "not_configured", "ping": False, "open_ports": []})
            continue
        reachable = ping(ip)
        ports = open_ports(ip) if reachable else []
        routers.append({**r, "status": "online" if reachable else "unreachable", "ping": reachable, "open_ports": ports, "checked_at": now()})

    devices = read_arp_table()
    for d in devices:
        d["known"] = d["mac"] in known_macs
        d["classification"] = "known" if d["known"] else "unknown"
    return {"timestamp": now(), "routers": routers, "devices": devices}
