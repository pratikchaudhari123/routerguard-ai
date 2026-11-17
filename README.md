# WiFiSense

A local experimental Wi-Fi signal dashboard. It reads the Wi-Fi signal information exposed by the network interface your MacBook is currently using. You do not need to enter router IPs or connect a second router.

## What this MVP does
- Detects the current Wi-Fi interface and connected SSID on macOS.
- Samples RSSI (and noise/channel when the OS exposes them) every 2 seconds.
- Shows a live signal graph and stores samples in SQLite.
- Highlights unusually large RSSI changes as **possible activity**, not confirmed human presence.

## Run on your Mac (recommended)

Run natively rather than in Docker so the app can query macOS Wi-Fi diagnostics.

```bash
git clone https://github.com/pratikchaudhari123/routerguard-ai.git
cd routerguard-ai
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**.

If you already cloned the earlier version, update it first:

```bash
git pull origin main
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Stop the server with Ctrl+C.

## Signal access notes
On macOS the collector tries `wdutil info`, then the legacy Apple `airport -I` utility. macOS versions and hardware differ: Apple may hide RSSI from unprivileged command-line tools. If the dashboard says RSSI is unavailable, the application is running but macOS is not exposing a supported reading through these methods. Do not treat an empty reading as zero.

Linux support uses `iw` if installed and the user has permission to read wireless link data.

## What the signal graph means
RSSI changes can be caused by people, device movement, walls, multipath, interference, access-point power changes, or normal radio variation. This MVP does **not** identify a person, direction, or crossing event. It is a first-stage signal-collection experiment.

Research-grade Wi-Fi sensing generally uses CSI (Channel State Information), which ordinary macOS Wi-Fi APIs do not expose. CSI requires compatible Wi-Fi hardware, firmware, and drivers; a normal phone hotspot plus a dashboard is not sufficient for reliable through-room detection.

## Data and privacy
Samples are stored locally in `data/wifisense.db`. The app does not scan other devices, capture payloads, deauthenticate clients, or change router settings.


## Device-free motion sensing (CSI development branch)

This branch adds the first backend receiver interface for a compatible CSI device.

### Architecture

- Existing JioFiber router: ordinary Wi-Fi transmitter / access point.
- ESP32 CSI receiver: captures channel-state measurements from received Wi-Fi packets.
- MacBook: runs this FastAPI service, stores measurements in SQLite, and hosts the dashboard.
- Future processing stage: calibrated signal processing, movement events, and multi-receiver zone estimation.

Official reference implementation and firmware examples:
- Espressif ESP-CSI: https://github.com/espressif/esp-csi
- ESP-CSI programming guide: https://documentation.espressif.com/esp-csi/master/README.md

Espressif documents a router-as-transmitter setup in which an ESP32 sends ping traffic and captures CSI from router replies. Whether this works depends on the access point's Wi-Fi configuration and compatibility. One receiver can provide experimental motion detection; reliable room/zone localization generally needs additional spatially separated receivers and calibration.

### CSI ingestion API

POST JSON packets to `/api/csi`:

```json
{
  "device_id": "esp32-csi-01",
  "rssi": -54,
  "amplitudes": [12.1, 13.4, 11.8, 14.0, 12.7, 13.1, 11.9, 12.8]
}
```

The current endpoint is an integration scaffold. It accepts amplitude vectors, stores them, and emits an experimental change score after 20 baseline packets. The threshold and feature calculation are placeholders for bench testing, not a validated detector. Do not interpret the score as proof of a person/object or as a position estimate. The ESP32 firmware's native CSI output must be parsed into the API's amplitude-vector format before connecting it.

Check receiver status at `GET /api/csi/status`.

### Calibration protocol (first experiment)

1. Place router and receiver in fixed positions, with the receiver in the target room.
2. Keep the room empty and still while collecting baseline packets.
3. Walk through the intended sensing area, then repeat with a pet or moving object.
4. Record multiple trials and compare signal features against the empty baseline.
5. Only after repeatable results should zone labels and a trained classifier be added.

### Hardware and accuracy boundaries

The current MacBook RSSI collector is retained as a diagnostic only; it is not CSI and cannot provide exact object coordinates. The ESP32 CSI receiver is the next required sensing component unless another compatible CSI-capable receiver is available. A single link can detect channel changes but generally cannot uniquely determine where within a room the movement occurred. Multi-zone localization requires multiple links/receivers, spatial calibration, and validation against false alarms.


## Controlled movement experiment recorder

The dashboard now includes a labelled RSSI experiment recorder on the `feature/csi-motion-sensing` branch.

1. Keep the router and MacBook fixed and do not change Wi-Fi band/channel during a session.
2. Enter a manually measured test zone (for example, `Zone A`) and choose `Empty room baseline`.
3. Click **Start recording** and leave the zone empty for about 2 minutes.
4. Change the condition to `Person standing` or `Person walking`, set the zone where the movement occurs, then click **Apply zone / condition**.
5. Repeat the same test several times for each zone. Use **Stop recording** when finished.
6. Compare sample count, average RSSI, min/max, RSSI range, and average variation by zone and condition.

Samples are collected at the normal 2-second interval and stored in a separate `experiment_samples` SQLite table. Existing signal history is not deleted. The comparison is descriptive and does not yet classify human presence, infer a zone, estimate distance, or identify a person. Zone names are manual ground-truth labels for experiments.

API endpoints:
- `POST /api/experiment/start` — start a labelled session.
- `POST /api/experiment/phase` — change zone/condition while recording.
- `POST /api/experiment/stop` — stop recording.
- `GET /api/experiment/status` — current recorder state.
- `GET /api/experiment/summary` — grouped statistics for the current/most recent session.

Allowed phases: `empty`, `standing`, `walking`, `object_moving`.


## Local RSSI signal-change test (no CSI hardware)

The dashboard includes a quick exploratory test at **Quick signal-change test (MacBook RSSI)**:

1. Run the app natively on the MacBook and wait at least 10 seconds for RSSI samples.
2. Keep the router and MacBook fixed. Leave the test area empty.
3. Click **Calibrate empty area & start**.
4. Walk or move an object in different parts of the room, one trial at a time.
5. Watch the change-from-baseline value and event list. Click **Stop test** when finished.

This test compares the RSSI measured at the MacBook with an empty-area baseline. It can show whether a movement coincides with a change at that receiver. It is **not device-free object detection across the entire Wi-Fi coverage area**, does not identify humans versus objects, and cannot estimate position. Small RSSI changes may be missed; unrelated interference or router/client behavior may trigger changes. The threshold is an initial experiment setting, not a validated detection threshold.

For coverage-area sensing, continue with compatible CSI receiver hardware and multiple spatially separated sensing links. The CSI endpoint remains an integration scaffold until real receiver firmware sends correctly parsed CSI amplitudes.


## Multi-receiver CSI area-estimation scaffold

The dashboard now includes a **Multi-receiver area estimation** panel and these endpoints:

- `PUT /api/localization/nodes` — register a CSI receiver with a stable ID, its measured room-map coordinates (0–100), and a zone label.
- `GET /api/localization/nodes` — list registered receivers.
- `POST /api/localization/calibrate` — clear per-receiver history and begin an empty-room baseline.
- `POST /api/localization/csi` — ingest CSI amplitude vectors from each registered receiver.
- `GET /api/localization/status` — receiver status, activity flags, active zones, and an experimental candidate centroid.
- `POST /api/localization/stop` — stop the calibration state.

Each receiver must send at least 30 baseline packets while the monitored area is empty. After that, the scaffold compares the incoming CSI amplitude mean/spread with that receiver's baseline. When at least two receivers report a fresh change at the same time, the dashboard displays a weighted centroid of their installed coordinates.

**Important:** this is an experimental visualization scaffold, not validated triangulation or exact person tracking. The weighted centroid is not a physically derived location estimate; it can be wrong when receiver coverage overlaps unevenly, when reflections dominate, or when multiple people move. The MacBook RSSI collector does not feed this map. Real CSI-capable receiver firmware and labelled multi-zone tests are required before interpreting results as human location.

Example receiver registration:

```bash
curl -X PUT http://127.0.0.1:8002/api/localization/nodes \
  -H 'Content-Type: application/json' \
  -d '{"node_id":"esp32-csi-01","x":15,"y":20,"zone":"North-West"}'
```

Example CSI packet (send from receiver firmware or a test harness):

```bash
curl -X POST http://127.0.0.1:8002/api/localization/csi \
  -H 'Content-Type: application/json' \
  -d '{"node_id":"esp32-csi-01","amplitudes":[12.1,13.4,11.8,14.0,12.7,13.1,11.9,12.8]}'
```

Register at least two receivers at different physical positions, calibrate with the room empty, and have both send packets continuously. Do not send synthetic or copied vectors and interpret them as real detections.
