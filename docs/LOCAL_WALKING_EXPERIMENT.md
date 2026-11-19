# Local walking experiment — WiFiSense

## Purpose

This procedure tests whether repeatable changes appear in the **MacBook's own Wi-Fi RSSI** while a person crosses the space between the fixed JioAirFiber and TP-Link routers. It is an exploratory radio-disturbance experiment, not validated human detection.

## Fixed setup

- Keep JioAirFiber at `192.168.31.1` and TP-Link at `192.168.31.70` in their normal WDS configuration.
- Keep the MacBook stationary for the entire experiment. Prefer a safe fixed position near the middle of the router-to-router path, with its Wi-Fi connection and BSSID unchanged.
- Keep the MacBook connected to the same access point throughout all trials. Do not move it or switch Wi-Fi networks between empty and walking phases.
- Do not change router channels, transmit power, WDS settings, or firmware during a test.
- Record environmental changes such as doors, fans, other people, and heavy Wi-Fi use.

The MacBook samples its associated AP link. Even when the MacBook is positioned between the routers, this is **not** a measurement of the private Jio-to-TP-Link WDS link. A person's crossing may or may not produce a measurable change on the MacBook link.

## Start locally

Recommended one-command launcher on macOS:

```bash
cd ~/routerguard-ai
git pull --ff-only origin feature/motion-analysis-v2
chmod +x tools/run_local.sh
./tools/run_local.sh
```

Open `http://127.0.0.1:8000`. The launcher creates `.venv` only if missing, installs the pinned requirements, preserves `data/wifisense.db`, and refuses to start if port 8000 is already occupied. It does not kill an existing process.

Manual alternative:

```bash
cd ~/routerguard-ai
source .venv/bin/activate
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

## Controlled trial protocol

Use the **Movement experiment recorder**. Sampling is every two seconds.

1. Wait until the dashboard shows fresh samples and the same connected network/BSSID for at least one minute.
2. Select **Empty room baseline**, label it `empty-1`, and start recording. Leave the monitored path empty for 2 minutes.
3. Select **Person walking / crossing**, label it `walk-1`, and apply the new phase without stopping the session. Walk through the router-to-router space 10 times at a normal pace. Keep the routers and MacBook fixed.
4. Change back to **Empty room baseline**, label it `empty-2`, and record another 2 minutes.
5. Repeat the walking and empty phases at least three times. Add separate trials for standing still and moving an object if useful.
6. Stop recording and export the session CSV.

For every trial, note the direction, number of crossings, approximate pace, and any environmental changes. Do not move the MacBook to mark zones during the same session.

## Interpreting results

Compare each walking phase with the empty phases from the same session. Look for repeatable shifts and ranges across multiple trials, not a single RSSI spike. A result is only a **radio disturbance correlated with the manually labelled walking interval**. It cannot distinguish a person from an object, interference, multipath, or normal network variation, and it cannot confirm that the person crossed the direct Jio-to-TP-Link radio path.

The dashboard's `High signal variation` status is a rolling RSSI-range indicator, not a movement detector. Do not report it as a confirmed detection.

## What is needed for actual router-link sensing

The JioAirFiber-to-TP-Link WDS RSSI/CSI source is still unverified on the current firmware. The TP-Link Statistics value previously observed (`-48 dBm`) is the MacBook client signal, not WDS peer RSSI. The ESP32-S3 receiver workflow is separate: it can only provide CSI for a supported AP-to-receiver link when compatible hardware, firmware, and AP frame support are confirmed. It does not passively read the private WDS link.

Do not enable the 10-minute **router-link** baseline until a real WDS telemetry source is independently verified. Never substitute MacBook RSSI, ping, packet counters, or synthetic values.
