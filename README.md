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
