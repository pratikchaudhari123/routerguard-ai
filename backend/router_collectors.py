"""Optional dual-router RSSI polling.

A router is only considered measurable when it exposes an authenticated or
read-only JSON endpoint that returns its own wireless-link RSSI. This module
does not guess undocumented JioFiber URLs or treat missing data as zero.
"""
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

ROUTERS = [
    {
        "id": "main",
        "name": os.getenv("MAIN_ROUTER_NAME", "JioFiber Main"),
        "url": os.getenv("MAIN_ROUTER_RSSI_URL", "").strip(),
        "token": os.getenv("MAIN_ROUTER_RSSI_TOKEN", "").strip(),
        "field": os.getenv("MAIN_ROUTER_RSSI_JSON_FIELD", "rssi").strip(),
    },
    {
        "id": "second",
        "name": os.getenv("SECOND_ROUTER_NAME", "Second Router"),
        "url": os.getenv("SECOND_ROUTER_RSSI_URL", "").strip(),
        "token": os.getenv("SECOND_ROUTER_RSSI_TOKEN", "").strip(),
        "field": os.getenv("SECOND_ROUTER_RSSI_JSON_FIELD", "rssi").strip(),
    },
]

def _fetch_one(router):
    checked_at = datetime.now(timezone.utc).isoformat()
    if not router["url"]:
        return {
            "router_id": router["id"], "router_name": router["name"],
            "rssi": None, "status": "not_configured",
            "source": None, "checked_at": checked_at,
            "message": "No supported RSSI endpoint configured",
        }
    headers = {"Accept": "application/json"}
    if router["token"]:
        headers["Authorization"] = "Bearer " + router["token"]
    request = Request(router["url"], headers=headers, method="GET")
    try:
        with urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        value = payload
        for part in router["field"].split("."):
            value = value[part] if isinstance(value, dict) else None
        rssi = float(value) if value is not None else None
        if rssi is None or not (-120 <= rssi <= 0):
            raise ValueError("Configured JSON field did not contain a valid RSSI in dBm")
        return {
            "router_id": router["id"], "router_name": router["name"],
            "rssi": rssi, "status": "ok", "source": "router_json_endpoint",
            "checked_at": checked_at, "message": None,
        }
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return {
            "router_id": router["id"], "router_name": router["name"],
            "rssi": None, "status": "unavailable", "source": "router_json_endpoint",
            "checked_at": checked_at, "message": str(exc)[:180],
        }

async def read_both_routers():
    """Poll both router endpoints concurrently; timestamps are captured per read."""
    return await asyncio.gather(
        asyncio.to_thread(_fetch_one, ROUTERS[0]),
        asyncio.to_thread(_fetch_one, ROUTERS[1]),
    )
