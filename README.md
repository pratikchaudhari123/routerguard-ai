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


## Dual-router RSSI experiment (feature branch)

The `feature/dual-router-rssi-collection` branch adds a concurrent collector for two
router-provided JSON RSSI endpoints. It polls the configured main router (named
JioFiber by default) and second router in parallel every 2 seconds, stores each
reading and status in `data/wifisense.db`, and exposes:

- `GET /api/routers/status` — latest reading/status for both routers.
- `GET /api/routers/history?limit=120` — timestamped router readings.

Copy `.env.example` to `.env` and configure
`MAIN_ROUTER_RSSI_URL` and `SECOND_ROUTER_RSSI_URL` only after confirming
that each router exposes a read-only JSON endpoint containing its own RSSI in dBm.
The JSON field defaults to `rssi`; nested fields can be configured, for example
`radio.signal.rssi`. If an endpoint requires a bearer token, set its matching
`*_RSSI_TOKEN` variable. Do not commit real tokens or passwords.

**JioFiber compatibility is not yet verified.** JioFiber firmware does not have
a universal documented RSSI endpoint. An empty endpoint is reported as
`not_configured`; failed requests are reported as `unavailable`. The app never
fabricates readings or substitutes zero. The MacBook's own RSSI is a separate
measurement and is not mislabeled as either router's RSSI.

This branch adds the collection interface and synchronized storage, not a
confirmed JioFiber adapter. We need the exact JioFiber model/firmware and
second-router model, or a sanitized read-only API response, to implement and
validate their actual RSSI access.
