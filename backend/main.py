import asyncio
import platform
import re
import sqlite3
import subprocess
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

DB_PATH = Path("data/wifisense.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
INTERVAL = 2
lock = Lock()
state = {"connected": False, "ssid": None, "interface": None, "rssi": None,
         "noise": None, "channel": None, "band": None, "channel_width_mhz": None,
         "tx_rate_mbps": None, "cca_percent": None, "phy_mode": None,
         "sniffer_supported": None, "timestamp": None,
         "variation_db": None, "activity": "Waiting for signal samples",
         "activity_level": "neutral", "source": None, "history": []}
samples = deque(maxlen=90)

def run_cmd(args, timeout=4):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.stdout if p.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""

def wifi_interface():
    if platform.system() == "Darwin":
        out = run_cmd(["networksetup", "-listallhardwareports"])
        blocks = re.split(r"\n\s*\n", out)
        for block in blocks:
            if "Hardware Port: Wi-Fi" in block or "Hardware Port: AirPort" in block:
                m = re.search(r"Device: (\S+)", block)
                if m:
                    return m.group(1)
    elif platform.system() == "Linux":
        out = run_cmd(["sh", "-lc", "iw dev | awk '$1==\"Interface\"{print $2; exit}'"])
        return out.strip() or None
    return None

def read_wifi():
    system = platform.system()
    iface = wifi_interface()
    ssid = None
    rssi = noise = channel = channel_width_mhz = tx_rate_mbps = cca_percent = None
    band = phy_mode = None
    sniffer_supported = None
    source = None

    if system == "Darwin":
        if iface:
            ssid_out = run_cmd(["networksetup", "-getairportnetwork", iface])
            if ":" in ssid_out:
                ssid = ssid_out.split(":", 1)[1].strip()
        # wdutil often requires administrator privileges on recent macOS versions.
        # Use a previously-authorized sudo session without prompting the web server.
        info = run_cmd(["sudo", "-n", "wdutil", "info"], timeout=6) or run_cmd(["wdutil", "info"], timeout=6)
        if info:
            source = "macOS wdutil"
            for line in info.splitlines():
                low = line.lower()
                m = re.search(r"(-?\d+)\s*dBm", line, re.I)
                if m and "rssi" in low:
                    rssi = int(m.group(1))
                if m and "noise" in low:
                    noise = int(m.group(1))
                if "channel" in low:
                    cm = re.search(r"(?:5g|2g)?(\d{1,3})", line, re.I)
                    if cm:
                        channel = int(cm.group(1))
                    wm = re.search(r"/(20|40|80|160)(?:\s|$)", line)
                    if wm:
                        channel_width_mhz = int(wm.group(1))
                if "tx rate" in low:
                    rm = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*mbps", line, re.I)
                    if rm:
                        tx_rate_mbps = float(rm.group(1))
                if re.search(r"\bcca\b", low):
                    cm = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", line)
                    if cm:
                        cca_percent = float(cm.group(1))
                if "phy mode" in low:
                    phy_mode = line.split(":", 1)[-1].strip()
                if "sniffer supported" in low:
                    sniffer_supported = "yes" in low
        if rssi is None and iface:
            airport = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
            info = run_cmd([airport, "-I"])
            if info:
                source = "macOS airport utility"
                for line in info.splitlines():
                    if " SSID:" in line:
                        ssid = line.split(":", 1)[1].strip() or ssid
                    m = re.search(r"\bagrCtlRSSI:\s*(-?\d+)", line)
                    if m: rssi = int(m.group(1))
                    m = re.search(r"\bagrCtlNoise:\s*(-?\d+)", line)
                    if m: noise = int(m.group(1))
                    m = re.search(r"\bchannel:\s*(\d+)", line)
                    if m: channel = int(m.group(1))
    elif system == "Linux":
        if iface:
            info = run_cmd(["iw", "dev", iface, "link"])
            for line in info.splitlines():
                m = re.search(r"SSID:\s*(.*)", line)
                if m: ssid = m.group(1).strip()
                m = re.search(r"signal:\s*(-?\d+)\s*dBm", line)
                if m: rssi = int(m.group(1))
            source = "Linux iw"
    if channel is not None:
        band = "2.4 GHz" if channel <= 14 else "5 GHz"
    return {"connected": bool(ssid or rssi is not None), "ssid": ssid,
            "interface": iface, "rssi": rssi, "noise": noise,
            "channel": channel, "band": band, "channel_width_mhz": channel_width_mhz,
            "tx_rate_mbps": tx_rate_mbps, "cca_percent": cca_percent,
            "phy_mode": phy_mode, "sniffer_supported": sniffer_supported,
            "source": source}

def init_db():
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
            ssid TEXT, interface TEXT, rssi INTEGER, noise INTEGER,
            channel INTEGER, variation REAL, activity TEXT,
            band TEXT, channel_width_mhz INTEGER, tx_rate_mbps REAL,
            cca_percent REAL, phy_mode TEXT, sniffer_supported INTEGER)""")
        existing = {row[1] for row in c.execute("PRAGMA table_info(samples)")}
        migrations = {
            "band": "TEXT", "channel_width_mhz": "INTEGER",
            "tx_rate_mbps": "REAL", "cca_percent": "REAL",
            "phy_mode": "TEXT", "sniffer_supported": "INTEGER",
        }
        for column, kind in migrations.items():
            if column not in existing:
                c.execute(f"ALTER TABLE samples ADD COLUMN {column} {kind}")

def take_sample():
    reading = read_wifi()
    timestamp = datetime.now(timezone.utc).isoformat()
    rssi = reading["rssi"]
    variation = None
    activity = "Signal unavailable"
    level = "neutral"
    if rssi is not None:
        samples.append(rssi)
        if len(samples) >= 5:
            recent = list(samples)[-15:]
            variation = round(max(recent) - min(recent), 1)
            if variation >= 8:
                activity, level = "High signal variation — possible activity", "warning"
            elif variation >= 4:
                activity, level = "Signal variation observed", "notice"
            else:
                activity, level = "Signal relatively stable", "good"
        else:
            activity = "Collecting baseline samples"
    result = {**reading, "timestamp": timestamp, "variation_db": variation,
              "activity": activity, "activity_level": level}
    with lock:
        state.update(result)
        state["history"] = list(samples)
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""INSERT INTO samples(timestamp,ssid,interface,rssi,noise,channel,variation,activity,
                     band,channel_width_mhz,tx_rate_mbps,cca_percent,phy_mode,sniffer_supported)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (timestamp, reading["ssid"], reading["interface"], rssi,
                   reading["noise"], reading["channel"], variation, activity,
                   reading["band"], reading["channel_width_mhz"], reading["tx_rate_mbps"],
                   reading["cca_percent"], reading["phy_mode"],
                   None if reading["sniffer_supported"] is None else int(reading["sniffer_supported"])))
    return result

async def sampler_loop():
    while True:
        try:
            await asyncio.to_thread(take_sample)
        except Exception as exc:
            with lock:
                state["activity"] = f"Collector error: {exc}"
                state["activity_level"] = "error"
        await asyncio.sleep(INTERVAL)

@asynccontextmanager
async def lifespan(app):
    init_db()
    task = asyncio.create_task(sampler_loop())
    yield
    task.cancel()

app = FastAPI(title="WiFiSense", version="0.2.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/", response_class=HTMLResponse)
def home():
    return Path("frontend/index.html").read_text()

@app.get("/health")
def health():
    return {"ok": True, "service": "WiFiSense"}

@app.get("/api/status")
def status():
    with lock:
        return dict(state)

@app.get("/api/history")
def history(limit: int = 120):
    limit = max(1, min(limit, 1000))
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("SELECT * FROM samples ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in reversed(rows)]

@app.post("/api/sample")
def sample():
    return take_sample()
