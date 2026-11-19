"""Read-only diagnostics for the JioAirFiber ↔ TP-Link router pair.

The HTTP probe only reads the unauthenticated router landing page. It never
logs in, changes configuration, calls undocumented CGI endpoints, or guesses
that a client RSSI value belongs to the WDS peer.
"""
import os
import platform
import re
import socket
import subprocess
import urllib.error
import urllib.request
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
        ip_match = re.search(r"\((\d{1,3}(?:\.\d{1,3}){3})\)", line)
        mac_match = re.search(r" at ((?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2})", line)
        if ip_match and mac_match:
            found[ip_match.group(1)] = mac_match.group(1).upper()
    return found


def _extract_wds_rssi(html):
    """Return only a dBm value explicitly labelled as WDS/peer RSSI."""
    text = re.sub(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    patterns = (
        r"\bWDS\b.{0,100}?\b(?:RSSI|signal\s+strength)\b.{0,50}?(-\d{1,3})\s*dBm",
        r"\b(?:RSSI|signal\s+strength)\b.{0,50}?(-\d{1,3})\s*dBm.{0,100}?\bWDS\b",
        r"\b(?:peer|upstream|root\s+AP)\b.{0,80}?\bRSSI\b.{0,50}?(-\d{1,3})\s*dBm",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = int(match.group(1))
            if -110 <= value <= -1:
                return value
    return None


def _public_router_signal_probe(ip):
    """Inspect only GET / without credentials; do not scrape private APIs."""
    result = {
        "source": f"http://{ip}/ (unauthenticated landing page)",
        "http_status": None,
        "wds_peer_rssi_dbm": None,
        "measurement_verified": False,
        "status": "not_checked",
        "detail": None,
    }
    request = urllib.request.Request(
        f"http://{ip}/",
        headers={"User-Agent": "WiFiSense-read-only-diagnostics/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=2.5) as response:
            result["http_status"] = response.status
            body = response.read(1024 * 1024).decode("utf-8", errors="replace")
        value = _extract_wds_rssi(body)
        if value is not None:
            result.update({
                "wds_peer_rssi_dbm": value,
                "measurement_verified": True,
                "status": "wds_peer_rssi_found",
                "detail": "Explicit WDS/peer-labelled RSSI field found on the public landing page.",
            })
        else:
            result.update({
                "status": "no_public_wds_rssi_field",
                "detail": "Landing page did not expose an explicitly WDS/peer-labelled RSSI value. Client RSSI is not accepted.",
            })
    except urllib.error.HTTPError as exc:
        result.update({"http_status": exc.code, "status": "authentication_or_http_required",
                       "detail": "Router page requires authentication or returned an HTTP error; no login was attempted."})
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        result.update({"status": "http_probe_unavailable", "detail": f"{type(exc).__name__}: {exc}"})
    return result


def router_diagnostics():
    # These addresses were observed in this installation. Override if LAN changes.
    targets = [
        {"id": "jio", "name": "JioAirFiber", "ip": os.getenv("ROUTER_JIO_IP", "192.168.31.1").strip()},
        {"id": "tplink", "name": "TP-Link TL-WR850N", "ip": os.getenv("ROUTER_TPLINK_IP", "192.168.31.70").strip()},
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
            "public_signal_probe": _public_router_signal_probe(ip) if reachable else {
                "status": "skipped_router_unreachable",
                "wds_peer_rssi_dbm": None,
                "measurement_verified": False,
            },
            "checked_at": _now(),
        })
    wds_values = [
        router["public_signal_probe"].get("wds_peer_rssi_dbm")
        for router in routers
        if router.get("public_signal_probe", {}).get("measurement_verified")
    ]
    return {
        "checked_at": _now(),
        "routers": routers,
        "wds_status": {
            "value": "verified_public_wds_rssi_found" if wds_values else "not_exposed_by_public_router_page",
            "instruction": "Only an explicitly WDS/peer-labelled dBm field is accepted. A generic wireless-client signal value is rejected.",
        },
        "measurement_access": {
            "wds_rssi": "verified_public_router_page" if wds_values else "not_exposed_without_authenticated_or_documented_telemetry",
            "csi": "not_available_from_this_router_diagnostics_endpoint",
            "macbook_rssi": "separate_macbook_to_associated_ap_link",
            "router_link_telemetry_verified": bool(wds_values),
            "router_link_telemetry_source": "unauthenticated router landing page" if wds_values else None,
            "calibration_eligible": bool(wds_values),
            "calibration_block_reason": None if wds_values else (
                "No explicitly WDS-peer-labelled RSSI was found on either router's public landing page. "
                "The application does not use MacBook RSSI, generic client RSSI, ping latency, or packet loss as a substitute. "
                "Authenticated/documented router telemetry would be required if the firmware exposes it only after login."
            ),
            "baseline_plan": {
                "duration_minutes": 10,
                "required_source": "verified Jio-to-TP-Link WDS peer RSSI",
                "protocol": "Keep both routers fixed and the monitored area empty; store timestamped peer RSSI only.",
                "status": "ready_for_source_validation" if wds_values else "blocked_waiting_for_verified_router_link_telemetry",
            },
        },
        "safety": "Read-only ping, TCP port checks, local ARP lookup, and one unauthenticated HTTP GET / per reachable router. No login, undocumented CGI, settings changes, scans, or firmware actions.",
    }
