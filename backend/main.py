import asyncio
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.monitor import perform_scan

load_dotenv()
DB_PATH = Path(os.getenv("DATABASE_PATH", "data/routerguard.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
KNOWN_MACS = {x.strip().upper() for x in os.getenv("KNOWN_MACS", "").split(",") if x.strip()}
INTERVAL = max(10, int(os.getenv("SCAN_INTERVAL_SECONDS", "30")))
lock = Lock()
state = {"timestamp": None, "routers": [], "devices": []}

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL, severity TEXT NOT NULL,
            source TEXT NOT NULL, message TEXT NOT NULL, details TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS devices (
            mac TEXT PRIMARY KEY, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
            last_ip TEXT, approved INTEGER NOT NULL DEFAULT 0
        )""")

def event(severity, source, message, details=""):
    with db() as c:
        c.execute("INSERT INTO events(timestamp,severity,source,message,details) VALUES(datetime('now'),?,?,?,?)",
                  (severity, source, message, details))

def scan_once():
    result = perform_scan(KNOWN_MACS)
    with lock:
        previous = {d["mac"] for d in state.get("devices", [])}
        state.update(result)
    for r in result["routers"]:
        if r["status"] == "unreachable":
            event("warning", r["name"], f"Router {r['ip']} did not respond to ping", "Ping can be blocked; verify via router admin page.")
    for d in result["devices"]:
        with db() as c:
            old = c.execute("SELECT mac FROM devices WHERE mac=?", (d["mac"],)).fetchone()
            c.execute("""INSERT INTO devices(mac,first_seen,last_seen,last_ip,approved)
                         VALUES(?,?,?,?,?) ON CONFLICT(mac) DO UPDATE SET
                         last_seen=excluded.last_seen,last_ip=excluded.last_ip""",
                      (d["mac"], result["timestamp"], result["timestamp"], d["ip"], int(d["known"])))
        if not old:
            event("info" if d["known"] else "warning", d["mac"],
                  "Approved device first observed" if d["known"] else "New/unknown device observed",
                  f"IP={d['ip']} MAC={d['mac']}")
    return result

async def scanner_loop():
    while True:
        try:
            await asyncio.to_thread(scan_once)
        except Exception as exc:
            event("error", "scanner", "Scan failed", str(exc))
        await asyncio.sleep(INTERVAL)

@asynccontextmanager
async def lifespan(app):
    init_db()
    task = asyncio.create_task(scanner_loop())
    yield
    task.cancel()

app = FastAPI(title="RouterGuard AI", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/", response_class=HTMLResponse)
def home():
    return Path("frontend/index.html").read_text()

@app.get("/health")
def health():
    return {"ok": True, "service": "RouterGuard AI"}

@app.get("/api/status")
def status():
    with lock:
        return dict(state)

@app.get("/api/events")
def events(limit: int = 100):
    limit = max(1, min(limit, 500))
    with db() as c:
        rows = c.execute("SELECT id,timestamp,severity,source,message,details FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/scan")
def scan():
    return scan_once()

@app.post("/api/devices/{mac}/approve")
def approve(mac: str):
    mac = mac.upper()
    with db() as c:
        row = c.execute("SELECT mac FROM devices WHERE mac=?", (mac,)).fetchone()
        if not row:
            return {"ok": False, "error": "Device has not been observed yet"}
        c.execute("UPDATE devices SET approved=1 WHERE mac=?", (mac,))
    KNOWN_MACS.add(mac)
    event("info", mac, "Device approved by administrator")
    return {"ok": True, "mac": mac}
