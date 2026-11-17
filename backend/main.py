import asyncio
import platform
import re
import sqlite3
import json
import statistics
import subprocess
import uuid
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse, Response
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
csi_windows = {}
csi_state = {"receiver_connected": False, "device_id": None, "last_seen": None, "subcarriers": 0, "motion_score": None, "motion": "Waiting for CSI receiver", "calibrated": False}

# CSI-only device-free presence candidate detector.
# It compares REAL incoming CSI amplitude vectors against an explicitly collected
# empty-room baseline. It never uses MacBook RSSI as CSI and never fabricates packets.
human_detection = {
    "calibration_active": False, "calibrated": False, "enabled": False,
    "device_id": None, "packets_seen": 0, "baseline_packets": 0,
    "required_baseline_packets": 60, "status": "Waiting for a real CSI receiver",
    "presence_candidate": False, "score": None, "changed_fraction": None,
    "last_seen": None, "events": deque(maxlen=50), "high_count": 0, "low_count": 0
}
human_calibration_vectors = []
human_baseline_mean = []
human_baseline_std = []
HUMAN_Z_THRESHOLD = 3.0
HUMAN_SCORE_THRESHOLD = 2.5
HUMAN_CHANGED_FRACTION_THRESHOLD = 0.25

def human_detector_reset():
    global human_calibration_vectors, human_baseline_mean, human_baseline_std
    human_calibration_vectors = []
    human_baseline_mean = []
    human_baseline_std = []
    human_detection["events"].clear()
    human_detection.update({
        "calibration_active": False, "calibrated": False, "enabled": False,
        "device_id": None, "packets_seen": 0, "baseline_packets": 0,
        "status": "Waiting for a real CSI receiver", "presence_candidate": False,
        "score": None, "changed_fraction": None, "last_seen": None,
        "high_count": 0, "low_count": 0
    })

def human_detector_ingest(device_id, values, timestamp):
    global human_calibration_vectors, human_baseline_mean, human_baseline_std
    if human_detection["calibration_active"]:
        if human_detection["device_id"] not in (None, device_id):
            return {"status": human_detection["status"], "presence_candidate": False,
                    "score": None, "calibrated": False}
        human_detection["device_id"] = device_id
        if human_calibration_vectors and len(values) != len(human_calibration_vectors[0]):
            human_detection["status"] = "CSI vector length changed; reset calibration"
            human_detection["calibration_active"] = False
            return {"status": human_detection["status"], "presence_candidate": False,
                    "score": None, "calibrated": False}
        human_calibration_vectors.append(list(values))
        human_detection["baseline_packets"] = len(human_calibration_vectors)
        human_detection["packets_seen"] += 1
        if len(human_calibration_vectors) >= human_detection["required_baseline_packets"]:
            count = len(human_calibration_vectors)
            width = len(human_calibration_vectors[0])
            human_baseline_mean = [
                statistics.fmean(row[i] for row in human_calibration_vectors)
                for i in range(width)
            ]
            human_baseline_std = [
                max(statistics.pstdev(row[i] for row in human_calibration_vectors), 0.5)
                for i in range(width)
            ]
            human_detection.update({
                "calibration_active": False, "calibrated": True, "enabled": True,
                "status": "Empty-room baseline ready — monitoring CSI changes",
                "presence_candidate": False, "high_count": 0, "low_count": 0
            })
        else:
            human_detection["status"] = (
                f"Collecting empty-room baseline: {len(human_calibration_vectors)}/"
                f"{human_detection['required_baseline_packets']} real CSI packets"
            )
        human_detection["last_seen"] = timestamp
        return {"status": human_detection["status"], "presence_candidate": False,
                "score": None, "calibrated": human_detection["calibrated"]}

    if not human_detection["calibrated"] or not human_detection["enabled"]:
        return {"status": human_detection["status"], "presence_candidate": False,
                "score": None, "calibrated": human_detection["calibrated"]}
    if human_detection["device_id"] != device_id:
        return {"status": "A different CSI receiver is active; recalibrate for this receiver",
                "presence_candidate": False, "score": None, "calibrated": False}
    if len(values) != len(human_baseline_mean):
        human_detection.update({"enabled": False, "calibrated": False,
                                "status": "CSI vector length changed; recalibration required"})
        return {"status": human_detection["status"], "presence_candidate": False,
                "score": None, "calibrated": False}

    z_values = [
        abs(value - mean) / std
        for value, mean, std in zip(values, human_baseline_mean, human_baseline_std)
    ]
    score = round(statistics.fmean(min(z, 10.0) for z in z_values), 3)
    changed_fraction = round(
        sum(1 for z in z_values if z >= HUMAN_Z_THRESHOLD) / len(z_values), 3
    )
    changed = (score >= HUMAN_SCORE_THRESHOLD and
               changed_fraction >= HUMAN_CHANGED_FRACTION_THRESHOLD)
    human_detection["packets_seen"] += 1
    human_detection["last_seen"] = timestamp
    human_detection["score"] = score
    human_detection["changed_fraction"] = changed_fraction
    if changed:
        human_detection["high_count"] += 1
        human_detection["low_count"] = 0
    else:
        human_detection["low_count"] += 1
        human_detection["high_count"] = 0

    previous = human_detection["presence_candidate"]
    if not previous and human_detection["high_count"] >= 3:
        human_detection["presence_candidate"] = True
        human_detection["status"] = "Possible human presence / movement — CSI change sustained"
    elif previous and human_detection["low_count"] >= 10:
        human_detection["presence_candidate"] = False
        human_detection["status"] = "No sustained CSI change observed"
    elif previous:
        human_detection["status"] = "Possible human presence / movement — CSI change sustained"
    else:
        human_detection["status"] = "No sustained CSI change observed"

    current = human_detection["presence_candidate"]
    if current != previous:
        human_detection["events"].appendleft({
            "timestamp": timestamp, "status": human_detection["status"],
            "score": score, "changed_fraction": changed_fraction,
            "source": "real CSI amplitudes", "device_id": device_id
        })
    return {"status": human_detection["status"], "presence_candidate": current,
            "score": score, "changed_fraction": changed_fraction,
            "calibrated": True}


experiment_state = {"active": False, "session_id": None, "label": None, "zone": None, "phase": None, "started_at": None}

# RSSI-only exploratory monitor. It measures changes at the MacBook receiver,
# not CSI, object identity, or whole-room coverage.
rssi_sensing = {"enabled": False, "calibrated": False, "baseline_rssi": None,
    "threshold_db": 4.0, "last_delta_db": None, "status": "Not calibrated",
    "last_event_at": None, "events": deque(maxlen=30), "last_event_state": None}

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
        helper = Path("tools/macos_wifi_signal")
        if helper.exists():
            try:
                raw = subprocess.run([str(helper)], capture_output=True, text=True, timeout=4)
                if raw.returncode == 0 and raw.stdout.strip():
                    native = json.loads(raw.stdout)
                    return {
                        "connected": bool(native.get("connected")),
                        "ssid": native.get("ssid") or None,
                        "interface": native.get("interface") or iface,
                        "rssi": native.get("rssi") if isinstance(native.get("rssi"), int) and native.get("rssi") < 0 else None,
                        "noise": native.get("noise") if isinstance(native.get("noise"), int) and native.get("noise") < 0 else None,
                        "channel": native.get("channel") if isinstance(native.get("channel"), int) else None,
                        "band": ("2.4 GHz" if native.get("channel", 0) <= 14 else "5 GHz") if native.get("channel") else None,
                        "channel_width_mhz": None,
                        "tx_rate_mbps": native.get("tx_rate_mbps"),
                        "cca_percent": None, "phy_mode": None,
                        "sniffer_supported": None, "source": native.get("source", "Apple CoreWLAN")
                    }
            except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
                pass
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
        c.execute("""CREATE TABLE IF NOT EXISTS experiment_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
            timestamp TEXT NOT NULL, phase TEXT NOT NULL, zone TEXT NOT NULL,
            label TEXT, rssi INTEGER, noise INTEGER, variation REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS human_detection_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
            device_id TEXT NOT NULL, status TEXT NOT NULL, score REAL,
            changed_fraction REAL, presence_candidate INTEGER NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS csi_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
            device_id TEXT NOT NULL, rssi INTEGER, amplitudes_json TEXT NOT NULL,
            motion_score REAL NOT NULL, motion TEXT NOT NULL, zone TEXT)""")

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
    with lock:
        if rssi_sensing["enabled"] and rssi_sensing["calibrated"] and rssi is not None:
            delta = round(abs(rssi - rssi_sensing["baseline_rssi"]), 1)
            changed = delta >= rssi_sensing["threshold_db"]
            rssi_sensing["last_delta_db"] = delta
            new_status = "Signal change observed near receiver" if changed else "Near baseline"
            rssi_sensing["status"] = new_status
            event_state = "change" if changed else "baseline"
            if event_state != rssi_sensing["last_event_state"]:
                rssi_sensing["events"].appendleft({
                    "timestamp": timestamp, "status": new_status,
                    "rssi": rssi, "delta_db": delta
                })
                rssi_sensing["last_event_at"] = timestamp
                rssi_sensing["last_event_state"] = event_state
    with lock:
        exp = dict(experiment_state)
    if exp["active"] and rssi is not None:
        with sqlite3.connect(DB_PATH) as c:
            c.execute("""INSERT INTO experiment_samples(session_id,timestamp,phase,zone,label,rssi,noise,variation)
                         VALUES(?,?,?,?,?,?,?,?)""",
                      (exp["session_id"], timestamp, exp["phase"], exp["zone"], exp["label"],
                       rssi, reading["noise"], variation))
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


class CSIPacket(BaseModel):
    device_id: str = Field(min_length=1, max_length=80)
    amplitudes: list[float] = Field(min_length=8, max_length=512)
    rssi: int | None = Field(default=None, ge=-120, le=0)
    zone: str | None = Field(default=None, max_length=40)

@app.post("/api/csi")
def receive_csi(packet: CSIPacket):
    """Receive CSI subcarrier amplitudes from a compatible ESP32 receiver."""
    now = datetime.now(timezone.utc).isoformat()
    values = packet.amplitudes

    if not all(abs(v) < 1e7 for v in values):
        raise HTTPException(status_code=422, detail="CSI amplitudes contain invalid values")
    human_result = human_detector_ingest(packet.device_id, values, now)
    if human_result.get("calibrated"):
        with sqlite3.connect(DB_PATH) as c:
            c.execute("""INSERT INTO human_detection_events(timestamp,device_id,status,score,
                         changed_fraction,presence_candidate) VALUES(?,?,?,?,?,?)""",
                      (now, packet.device_id, human_result["status"],
                       human_result.get("score"), human_result.get("changed_fraction"),
                       int(human_result.get("presence_candidate", False))))
    baseline = csi_windows.setdefault(packet.device_id, deque(maxlen=150))
    vector_mean = statistics.fmean(values)
    vector_spread = statistics.pstdev(values)
    if len(baseline) < 20:
        baseline.append((vector_mean, vector_spread))
        score = 0.0
        motion = "Calibrating empty-room baseline"
    else:
        ref_mean = statistics.fmean(x[0] for x in list(baseline)[-100:])
        ref_spread = statistics.fmean(x[1] for x in list(baseline)[-100:])
        score = round(abs(vector_mean-ref_mean) / max(abs(ref_mean), 1.0) * 100
                      + abs(vector_spread-ref_spread) / max(abs(ref_spread), 1.0) * 100, 2)
        motion = "Possible movement" if score >= 18 else "No significant change"
        baseline.append((vector_mean, vector_spread))
    with lock:
        csi_state.update({"receiver_connected": True, "device_id": packet.device_id,
                          "last_seen": now, "subcarriers": len(values),
                          "motion_score": score, "motion": motion,
                          "calibrated": len(baseline) >= 20})
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""INSERT INTO csi_samples(timestamp,device_id,rssi,amplitudes_json,
                     motion_score,motion,zone) VALUES(?,?,?,?,?,?,?)""",
                  (now, packet.device_id, packet.rssi, json.dumps(values),
                   score, motion, packet.zone))
    return {"ok": True, "timestamp": now, "device_id": packet.device_id,
            "subcarriers": len(values), "motion_score": score, "motion": motion,
            "calibrated": len(baseline) >= 20,
            "human_detection": human_result,
            "note": "Human-presence candidate is inferred only from real CSI packets after empty-room calibration. It is experimental, can false-trigger on non-human changes, and is not a validated human classifier."}


@app.post("/api/human-detection/calibrate")
def human_detection_calibrate():
    human_detector_reset()
    human_detection["calibration_active"] = True
    human_detection["status"] = (
        "Calibration started — keep the monitored area empty and still; "
        "waiting for 60 real CSI packets"
    )
    return human_detection_status()

@app.post("/api/human-detection/stop")
def human_detection_stop():
    human_detection["enabled"] = False
    human_detection["calibration_active"] = False
    human_detection["status"] = "Human-presence candidate monitoring stopped"
    return human_detection_status()

@app.get("/api/human-detection/status")
def human_detection_status():
    return {
        **{k: v for k, v in human_detection.items() if k != "events"},
        "events": list(human_detection["events"]),
        "measurement_source": "CSI amplitude vectors received from configured CSI receiver",
        "rssi_used_for_human_detection": False,
        "interpretation": "Possible presence/movement candidate only; not a validated human-vs-object classifier."
    }

@app.get("/api/sensing/status")
def sensing_status():
    with lock:
        return {**{k: v for k, v in rssi_sensing.items() if k != "events"},
                "events": list(rssi_sensing["events"]),
                "measurement": "MacBook RSSI only",
                "scope_warning": "Changes are measured only at the MacBook receiver; this is not whole-room object detection."}

@app.post("/api/sensing/calibrate")
def sensing_calibrate():
    values = [v for v in list(samples)[-30:] if isinstance(v, (int, float))]
    if len(values) < 5:
        raise HTTPException(status_code=409, detail="Need at least 5 RSSI samples. Wait 10 seconds and retry.")
    baseline = statistics.fmean(values)
    spread = statistics.pstdev(values) if len(values) > 1 else 0.0
    threshold = round(max(4.0, spread * 3.0), 1)
    with lock:
        rssi_sensing.update({"enabled": True, "calibrated": True,
            "baseline_rssi": round(baseline, 1), "threshold_db": threshold,
            "last_delta_db": 0.0, "status": "Calibrated — monitoring signal changes",
            "last_event_at": None, "last_event_state": "baseline"})
        rssi_sensing["events"].clear()
    return sensing_status()

@app.post("/api/sensing/stop")
def sensing_stop():
    with lock:
        rssi_sensing.update({"enabled": False, "status": "Monitoring stopped",
                             "last_event_state": None})
    return sensing_status()

@app.get("/api/sensing/events")
def sensing_events():
    with lock:
        return list(rssi_sensing["events"])

@app.get("/api/csi/status")
def csi_status():
    with lock:
        return dict(csi_state)

class ExperimentStart(BaseModel):
    zone: str = Field(min_length=1, max_length=40)
    phase: str = Field(pattern="^(empty|standing|walking|object_moving)$")
    label: str | None = Field(default=None, max_length=100)

class ExperimentPhase(BaseModel):
    zone: str = Field(min_length=1, max_length=40)
    phase: str = Field(pattern="^(empty|standing|walking|object_moving)$")
    label: str | None = Field(default=None, max_length=100)

@app.post("/api/experiment/start")
def start_experiment(payload: ExperimentStart):
    with lock:
        if experiment_state["active"]:
            raise HTTPException(status_code=409, detail="An experiment is already active")
        experiment_state.update({"active": True, "session_id": str(uuid.uuid4()),
                                 "label": payload.label, "zone": payload.zone,
                                 "phase": payload.phase,
                                 "started_at": datetime.now(timezone.utc).isoformat()})
        return dict(experiment_state)

@app.post("/api/experiment/phase")
def set_experiment_phase(payload: ExperimentPhase):
    with lock:
        if not experiment_state["active"]:
            raise HTTPException(status_code=409, detail="Start an experiment first")
        experiment_state.update({"zone": payload.zone, "phase": payload.phase, "label": payload.label})
        return dict(experiment_state)

@app.post("/api/experiment/stop")
def stop_experiment():
    with lock:
        session_id = experiment_state["session_id"]
        experiment_state.update({"active": False})
        return {"ok": True, "session_id": session_id}

@app.get("/api/experiment/status")
def experiment_status():
    with lock:
        return dict(experiment_state)

@app.get("/api/experiment/summary")
def experiment_summary():
    with lock:
        session_id = experiment_state["session_id"]
    if not session_id:
        return {"session_id": None, "groups": []}
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("""SELECT phase,zone,COUNT(*) AS samples,ROUND(AVG(rssi),2) AS avg_rssi,
            MIN(rssi) AS min_rssi,MAX(rssi) AS max_rssi,ROUND(MAX(rssi)-MIN(rssi),2) AS rssi_range,
            ROUND(AVG(variation),2) AS avg_variation
            FROM experiment_samples WHERE session_id=? GROUP BY phase,zone ORDER BY zone,phase""",
            (session_id,)).fetchall()
    return {"session_id": session_id, "groups": [dict(r) for r in rows],
            "note": "Descriptive RSSI statistics only; not validated person detection or distance estimation."}

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


@app.get("/api/diagnostics")
def diagnostics():
    """Report collector and database health; never infer person presence."""
    now = datetime.now(timezone.utc)
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        total = c.execute("SELECT COUNT(*) AS n FROM samples").fetchone()["n"]
        recent = c.execute(
            "SELECT timestamp,rssi FROM samples ORDER BY id DESC LIMIT 31"
        ).fetchall()
        exp = dict(experiment_state)
        exp_count = 0
        if exp["session_id"]:
            exp_count = c.execute(
                "SELECT COUNT(*) FROM experiment_samples WHERE session_id=?",
                (exp["session_id"],)
            ).fetchone()[0]
    last_timestamp = recent[0]["timestamp"] if recent else None
    age_seconds = None
    if last_timestamp:
        try:
            age_seconds = round((now - datetime.fromisoformat(last_timestamp)).total_seconds(), 1)
        except ValueError:
            pass
    recent_times = []
    for row in recent:
        try:
            recent_times.append(datetime.fromisoformat(row["timestamp"]))
        except ValueError:
            continue
    recent_times.sort()
    intervals = [
        (recent_times[i] - recent_times[i-1]).total_seconds()
        for i in range(1, len(recent_times))
    ]
    avg_interval = round(statistics.fmean(intervals), 2) if intervals else None
    return {
        "ok": bool(last_timestamp and age_seconds is not None and age_seconds <= 8),
        "collector_interval_seconds_configured": INTERVAL,
        "average_interval_seconds_recent": avg_interval,
        "samples_in_last_60_seconds": sum(
            1 for row in recent_times if (now-row).total_seconds() <= 60
        ),
        "expected_samples_per_minute_approx": round(60 / INTERVAL),
        "database_total_samples": total,
        "last_sample_at": last_timestamp,
        "last_sample_age_seconds": age_seconds,
        "latest_rssi": recent[0]["rssi"] if recent else None,
        "experiment_active": exp["active"],
        "experiment_session_id": exp["session_id"],
        "experiment_samples_current_session": exp_count,
        "warning": "Collector health and RSSI sampling only; this endpoint does not verify human/object detection."
    }


@app.get("/api/experiment/export.csv")
def export_experiment_csv():
    from csv import writer
    from io import StringIO
    with lock:
        session_id = experiment_state["session_id"]
    if not session_id:
        raise HTTPException(status_code=404, detail="No experiment session is available to export.")
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute(
            """SELECT timestamp,zone,phase,label,rssi,noise,variation
               FROM experiment_samples WHERE session_id=? ORDER BY id""",
            (session_id,)
        ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="No samples recorded in the current session.")
    output = StringIO()
    csv_writer = writer(output)
    csv_writer.writerow(["timestamp_utc","zone","condition","trial_label","rssi_dbm","noise_dbm","rolling_rssi_range_db"])
    csv_writer.writerows(rows)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="wifisense-experiment-{session_id}.csv"'}
    )


class CoveragePoint(BaseModel):
    x: float = Field(ge=0, le=1000)
    y: float = Field(ge=0, le=1000)
    room_width: float = Field(gt=0, le=1000)
    room_height: float = Field(gt=0, le=1000)
    zone: str | None = Field(default=None, max_length=40)


@app.post("/api/coverage/point")
def record_coverage_point(payload: CoveragePoint):
    with lock:
        reading = dict(state)
    if reading.get("rssi") is None:
        raise HTTPException(status_code=409, detail="No valid MacBook RSSI reading is available right now.")
    if payload.x > payload.room_width or payload.y > payload.room_height:
        raise HTTPException(status_code=422, detail="Survey point must be inside the room dimensions.")
    timestamp = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS coverage_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
            x REAL NOT NULL, y REAL NOT NULL, rssi INTEGER NOT NULL,
            room_width REAL NOT NULL, room_height REAL NOT NULL, zone TEXT)""")
        c.execute("""INSERT INTO coverage_points(timestamp,x,y,rssi,room_width,room_height,zone)
                     VALUES(?,?,?,?,?,?,?)""",
                  (timestamp,payload.x,payload.y,reading["rssi"],
                   payload.room_width,payload.room_height,payload.zone))
    return {"ok": True, "point": {"timestamp":timestamp,"x":payload.x,"y":payload.y,
            "rssi":reading["rssi"],"zone":payload.zone},
            "note":"RSSI measured at the MacBook at the time of recording; map interpolation is an estimate between surveyed points."}


@app.get("/api/coverage/status")
def coverage_status():
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        exists = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='coverage_points'").fetchone()
        rows = c.execute("SELECT * FROM coverage_points ORDER BY id").fetchall() if exists else []
    return {"points":[dict(row) for row in rows],
            "count":len(rows),
            "warning":"Only manually surveyed points contain measured RSSI. Colours between points are interpolation, not directly measured radio coverage."}


from backend.localization import router as localization_router
app.include_router(localization_router)
