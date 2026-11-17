# WiFiSense — two-router measurement diagnostic

This branch is configured for the current experiment:

- Main access point: JioAirFiber
- WDS extender: TP-Link TL-WR850N V3
- Development and data-collection computer: macOS MacBook
- Intended goal: determine whether the existing router pair exposes a usable **Jio-to-TP-Link WDS signal measurement** for controlled movement experiments.

## Important: what this version does and does not do

### It does
- Read the MacBook's own Wi-Fi RSSI through Apple CoreWLAN when available.
- Store real MacBook RSSI samples in SQLite.
- Verify reachability of the known JioAirFiber and TP-Link management IPs using read-only ping checks.
- Check whether HTTP/HTTPS management ports answer.
- Show MAC addresses only when they are present in the MacBook's local ARP cache.
- Record labelled experiments and export their actual measurements as CSV.

### It does not
- Read the JioAirFiber-to-TP-Link WDS RSSI.
- Read CSI from either router.
- Convert MacBook RSSI into router-to-router RSSI.
- Confirm that a person crossed the signal path.
- Generate synthetic CSI, synthetic RSSI, or simulated detections.

**The main technical blocker remains access to WDS-link measurements.** The TP-Link web interface documents WDS status and connected-client statistics, but the project has not verified an API or telemetry field for the upstream WDS peer's RSSI. CSI is not exposed by the currently installed TP-Link firmware through any method verified in this project. A working WDS bridge does not itself mean its RSSI/CSI is available to the application.

## Run on macOS

Run natively, not in Docker, because the MacBook collector uses macOS Wi-Fi interfaces.

```bash
cd ~/routerguard-ai
git fetch origin
git checkout feature/human-motion-detection
git pull --ff-only origin feature/human-motion-detection
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Open the dashboard:

- On the MacBook: http://127.0.0.1:8000
- From another device on the same LAN: http://MACBOOK_LAN_IP:8000

If the MacBook firewall asks whether Python may accept incoming connections, allow it only on the trusted home network while testing.

## Real CSI receiver workflow\n\nThe dashboard includes a live CSI receiver panel. It polls the CSI and presence-candidate status endpoints, shows receiver freshness, subcarrier count, signal-change score, empty-room calibration progress, and candidate events. The receiver is considered online only if a real CSI packet arrived within the last 10 seconds.\n\n1. Start the MacBook app and identify its current LAN IPv4 address (for example `ipconfig getifaddr en0`).\n2. Confirm the ESP32-S3 and MacBook are on the same LAN; avoid guest Wi-Fi/client isolation.\n3. Run `idf.py menuconfig` in the receiver project and set the Wi-Fi SSID, password, API URL (`http://MACBOOK_LAN_IP:8000/api/csi`) and device ID under **WiFiSense receiver configuration**. Never commit Wi-Fi credentials or `sdkconfig`.\n4. Build and flash with `idf.py build` and `idf.py -p PORT flash monitor`.\n5. Wait for **CSI receiver connected**, a recent packet timestamp, and a non-zero subcarrier count.\n6. Keep the area empty and still, then start **Calibrate empty area (60 real CSI packets)**. Wait for baseline completion.\n7. Walk across the router-to-receiver path and compare repeated trials with empty-room and non-human disturbance trials.\n\nIf the receiver remains offline, check serial logs, MacBook LAN IP, macOS firewall access to port 8000, Wi-Fi credentials, and whether the AP supplies CSI on ping replies. This method is not guaranteed to work with every AP and has not yet been physically validated with your JioAirFiber. The detector is experimental and may react to non-human disturbances; it is not a validated human classifier. Multi-receiver localization remains separate and requires at least two CSI receivers.\n\n## Router diagnostics

The dashboard's **Two-router hardware diagnostics** section checks these previously observed addresses:

| Device | Default address |
|---|---|
| JioAirFiber | `192.168.31.1` |
| TP-Link TL-WR850N | `192.168.0.1` |

If the router LAN addresses change, set environment variables before starting the app:

```bash
export ROUTER_JIO_IP=192.168.31.1
export ROUTER_TPLINK_IP=192.168.0.1
```

The endpoint `GET /api/router-diagnostics` performs read-only ping, TCP checks on ports 80 and 443, and a local ARP-cache lookup. A router may be unreachable from the MacBook because the two devices are on different subnets or the router blocks ping. That result is not proof that WDS is down.

### Verify WDS status manually

1. Open `http://192.168.0.1` while connected to the TP-Link network.
2. Open **Advanced → Status → Wireless**.
3. Read the **WDS Status** field.
4. TP-Link's WDS guidance says `Run` means the bridge is established.
5. Do not change settings during this diagnostic.

The dashboard deliberately does not scrape the router's authenticated admin session, store credentials, or issue undocumented router API calls.

## Controlled MacBook RSSI experiment

This is only a diagnostic of the MacBook-to-associated-access-point link. It is not a substitute for WDS RSSI.

1. Keep the MacBook and its connected access point in fixed positions.
2. Start an experiment and record an empty-room baseline.
3. Record separate walking/crossing trials.
4. Repeat at least three times and export the CSV.
5. Compare measured distributions; do not interpret a single threshold event as a person detection.

The RSSI can change because of people, objects, device movement, walls, multipath, interference, or normal radio behavior.

## Data and privacy

- Local database: `data/wifisense.db`
- The app does not capture Wi-Fi payloads, deauthenticate clients, change router settings, or attempt router login.
- Router diagnostics are limited to the two configured IP addresses.
- No router passwords or admin session tokens are needed by the application.

## Firmware warning

Do not flash firmware as part of this experiment. TP-Link warns that firmware must match the exact hardware version and regional variant; an incorrect image can damage the router. The currently observed hardware is TL-WR850N V3.8 / V3 and the installed firmware is Build 210407. Any firmware decision must be checked against the exact device label and TP-Link's local support page first.

## Success criteria for the next stage

We can proceed to an RSSI-based router-link experiment only after identifying a repeatable, documented or directly verified read-only source for the **Jio-to-TP-Link WDS peer RSSI**. If the firmware does not expose it, additional dashboard or Python code cannot create that measurement. At that point, the two-router-only design needs a hardware/firmware capability change before human-crossing sensing can be evaluated.
