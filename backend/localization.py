"""Experimental multi-receiver CSI zone estimation.

This module deliberately reports a coarse candidate region, not a verified
person identity or precise coordinate. Coordinates are receiver installation
coordinates supplied by the operator.
"""
import json
import sqlite3
import statistics
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "wifisense.db"
router = APIRouter(prefix="/api/localization", tags=["localization"])
guard = RLock()
baselines = defaultdict(lambda: deque(maxlen=120))
latest = {}
calibration_active = False
BASELINE_PACKETS = 30
MOTION_THRESHOLD = 18.0
ACTIVE_SECONDS = 6.0


def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def ensure_tables():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS localization_nodes (
            node_id TEXT PRIMARY KEY, x REAL NOT NULL, y REAL NOT NULL,
            zone TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS localization_packets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
            node_id TEXT NOT NULL, feature_mean REAL NOT NULL,
            feature_spread REAL NOT NULL, motion_score REAL NOT NULL,
            motion_active INTEGER NOT NULL)""")


def node_rows():
    ensure_tables()
    with db() as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(
            "SELECT node_id,x,y,zone,updated_at FROM localization_nodes ORDER BY node_id"
        ).fetchall()]


class NodeConfig(BaseModel):
    node_id: str = Field(min_length=1, max_length=80)
    x: float = Field(ge=0, le=100)
    y: float = Field(ge=0, le=100)
    zone: str = Field(min_length=1, max_length=40)


class LocalizationPacket(BaseModel):
    node_id: str = Field(min_length=1, max_length=80)
    amplitudes: list[float] = Field(min_length=8, max_length=512)


@router.put("/nodes")
def register_node(payload: NodeConfig):
    ensure_tables()
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute("""INSERT INTO localization_nodes(node_id,x,y,zone,updated_at)
            VALUES(?,?,?,?,?) ON CONFLICT(node_id) DO UPDATE SET
            x=excluded.x,y=excluded.y,zone=excluded.zone,updated_at=excluded.updated_at""",
            (payload.node_id, payload.x, payload.y, payload.zone, now))
    with guard:
        latest.pop(payload.node_id, None)
        baselines.pop(payload.node_id, None)
    return {"ok": True, "node": payload.model_dump(),
            "note": "Coordinates describe the receiver installation, not a detected person."}


@router.get("/nodes")
def get_nodes():
    return {"nodes": node_rows()}


@router.post("/calibrate")
def calibrate_localization():
    nodes = node_rows()
    if len(nodes) < 2:
        raise HTTPException(status_code=409, detail="Register at least two spatially separated CSI receivers first.")
    with guard:
        baselines.clear()
        latest.clear()
        global calibration_active
        calibration_active = True
    return {"ok": True, "calibration": "collecting_empty_room_baseline",
            "required_packets_per_receiver": BASELINE_PACKETS,
            "registered_receivers": len(nodes),
            "instruction": "Keep the area empty and still. Each receiver must send at least 30 CSI packets."}


@router.post("/stop")
def stop_localization():
    global calibration_active
    with guard:
        calibration_active = False
    return {"ok": True, "status": "stopped"}


@router.post("/csi")
def receive_localization_csi(packet: LocalizationPacket):
    nodes = {n["node_id"]: n for n in node_rows()}
    if packet.node_id not in nodes:
        raise HTTPException(status_code=404, detail="Receiver is not registered. Add it at /api/localization/nodes first.")
    if not all(abs(v) < 1e7 for v in packet.amplitudes):
        raise HTTPException(status_code=422, detail="CSI amplitudes contain invalid values.")

    mean_value = statistics.fmean(packet.amplitudes)
    spread_value = statistics.pstdev(packet.amplitudes)
    now = datetime.now(timezone.utc).isoformat()
    now_epoch = time.time()
    with guard:
        history = baselines[packet.node_id]
        if len(history) < BASELINE_PACKETS:
            history.append((mean_value, spread_value))
            score = 0.0
            active = False
            phase = "baseline_collecting"
        else:
            reference_mean = statistics.fmean(v[0] for v in history)
            reference_spread = statistics.fmean(v[1] for v in history)
            score = round(
                abs(mean_value-reference_mean) / max(abs(reference_mean), 1.0) * 100
                + abs(spread_value-reference_spread) / max(abs(reference_spread), 1.0) * 100, 2
            )
            active = score >= MOTION_THRESHOLD
            phase = "monitoring"
            history.append((mean_value, spread_value))
        latest[packet.node_id] = {
            "node_id": packet.node_id, "x": nodes[packet.node_id]["x"],
            "y": nodes[packet.node_id]["y"], "zone": nodes[packet.node_id]["zone"],
            "score": score, "active": active, "seen_epoch": now_epoch,
            "timestamp": now, "baseline_packets": len(history), "phase": phase
        }
    ensure_tables()
    with db() as conn:
        conn.execute("""INSERT INTO localization_packets(timestamp,node_id,feature_mean,
            feature_spread,motion_score,motion_active) VALUES(?,?,?,?,?,?)""",
            (now, packet.node_id, mean_value, spread_value, score, int(active)))

    return localization_status()


@router.get("/status")
def localization_status():
    nodes = node_rows()
    now = time.time()
    with guard:
        observations = [
            {**v, "fresh": now-v["seen_epoch"] <= ACTIVE_SECONDS}
            for v in latest.values()
        ]
        active = [v for v in observations if v["fresh"] and v["active"]]
        calibrated_nodes = sum(1 for n in nodes if len(baselines[n["node_id"]]) >= BASELINE_PACKETS)
        collecting = calibration_active
    position = None
    if len(active) >= 2:
        total = sum(max(v["score"], 0.1) for v in active)
        position = {
            "x": round(sum(v["x"]*max(v["score"], 0.1) for v in active)/total, 1),
            "y": round(sum(v["y"]*max(v["score"], 0.1) for v in active)/total, 1),
            "method": "weighted receiver-activity centroid",
            "active_receivers": len(active)
        }
    return {
        "registered_receivers": len(nodes), "minimum_receivers": 2,
        "calibrated_receivers": calibrated_nodes,
        "baseline_packets_required": BASELINE_PACKETS,
        "calibration_active": collecting,
        "receivers": [{k: v for k, v in item.items() if k != "seen_epoch"} for item in observations],
        "active_zones": sorted({v["zone"] for v in active}),
        "candidate_position": position,
        "status": ("Candidate activity region" if position else
                   "Waiting for two simultaneous receiver detections"),
        "warning": "Experimental coarse estimate only. A weighted centroid is not triangulation, person identification, or a validated exact location. Use fixed, separated CSI receivers and validate against labelled trials."
    }
