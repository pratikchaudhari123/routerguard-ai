# WiFiSense — two-router measurement diagnostic

This branch is configured for the current experiment:

- Main access point: JioAirFiber
- WDS extender: TP-Link TL-WR850N V3
- Development and data-collection computer: macOS MacBook
- Intended goal: determine whether the existing router pair exposes a usable **Jio-to-TP-Link WDS signal measurement** for controlled movement experiments.

## Important: what this version does and does not do

### It does
- Read the MacBook's own Wi-Fi RSSI and, when exposed by macOS, its associated access-point BSSID through local Wi-Fi diagnostics.
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

**The main technical blocker remains access to WDS-link measurements.** The inspected TP-Link web interface shows the upstream wireless network and a Network Map connection, but does not expose a verified telemetry field for the upstream WDS peer's RSSI. CSI is not exposed by the currently installed TP-Link firmware through any method verified in this project. A working WDS bridge does not itself mean its RSSI/CSI is available to the application.

## Mandatory router-link measurement gate and 10-minute baseline

The dashboard now displays a hard measurement gate for the primary JioAirFiber-to-TP-Link sensing path.

**Required before any router-link calibration:** obtain a real, directly measured Jio-to-TP-Link WDS peer RSSI or CSI value from a verified router/driver telemetry source. The TP-Link Statistics value observed as `-48 dBm` is the MacBook wireless-client link, not the WDS peer RSSI. Never relabel MacBook RSSI, client signal strength, router reachability, packet counts, or a Network Map connection as router-to-router telemetry.

The 10-minute empty-room baseline is intentionally marked **BLOCKED** until that source is verified. Once verified:
1. Keep JioAirFiber and TP-Link fixed in their installed positions.
2. Keep the monitored area empty and still for 10 minutes.
3. Store timestamped readings from the verified router-link telemetry source only.
4. Then run repeated labelled person-crossing and non-human disturbance trials and compare them with the empty-room baseline.

The API reports `router_link_telemetry_verified=false`, `calibration_eligible=false`, and the reason while no source has been verified. This is a validation gate, not a claim that the routers currently expose the needed measurement.

## Run on macOS

Run natively, not in Docker, because the MacBook collector uses macOS Wi-Fi interfaces. The recommended launcher checks port 8000, uses the project virtual environment, installs requirements, and preserves the existing SQLite database:

```bash
cd ~/routerguard-ai
git pull --ff-only origin feature/motion-analysis-v2
chmod +x tools/run_local.sh
./tools/run_local.sh
```

Open http://127.0.0.1:8000. If port 8000 is already occupied, the launcher prints the listening process and exits without killing it. Identify and stop only the intended old WiFiSense process, then rerun the launcher.

See [docs/LOCAL_WALKING_EXPERIMENT.md](docs/LOCAL_WALKING_EXPERIMENT.md) for the controlled crossing protocol and interpretation limits.

Open the dashboard:

- On the MacBook: http://127.0.0.1:8000
- For a compatible ESP32 receiver on the same LAN, stop the local-only server and restart with `uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000`; configure the ESP32 with `http://MACBOOK_LAN_IP:8000/api/csi`. Allow access only on your trusted home network.

If the MacBook firewall asks whether Python may accept incoming connections, allow it only on the trusted home network while testing.

## Real CSI receiver workflow\n\nThe dashboard includes a live CSI receiver panel. It polls the CSI and presence-candidate status endpoints, shows receiver freshness, subcarrier count, signal-change score, empty-room calibration progress, and candidate events. The receiver is considered online only if a real CSI packet arrived within the last 10 seconds.\n\n1. Start the MacBook app and identify its current LAN IPv4 address (for example `ipconfig getifaddr en0`).\n2. Confirm the ESP32-S3 and MacBook are on the same LAN; avoid guest Wi-Fi/client isolation.\n3. Run `idf.py menuconfig` in the receiver project and set the Wi-Fi SSID, password, API URL (`http://MACBOOK_LAN_IP:8000/api/csi`) and device ID under **WiFiSense receiver configuration**. Never commit Wi-Fi credentials or `sdkconfig`.\n4. Build and flash with `idf.py build` and `idf.py -p PORT flash monitor`.\n5. Wait for **CSI receiver connected**, a recent packet timestamp, and a non-zero subcarrier count.\n6. Keep the area empty and still, then start **Calibrate empty area (60 real CSI packets)**. Wait for baseline completion.\n7. Walk across the router-to-receiver path and compare repeated trials with empty-room and non-human disturbance trials.\n\nIf the receiver remains offline, check serial logs, MacBook LAN IP, macOS firewall access to port 8000, Wi-Fi credentials, and whether the AP supplies CSI on ping replies. This method is not guaranteed to work with every AP and has not yet been physically validated with your JioAirFiber. The detector requires CSI deviation to persist for at least 5 seconds before opening a presence/movement candidate, and clears the candidate after 5 seconds near baseline. This is a temporal false-spike filter, not a validated human classifier; non-human disturbances can still trigger it. The application does not automatically delete historical samples, CSI records, or movement-candidate events. Back up `data/wifisense.db` before major updates. Multi-receiver localization remains separate and requires at least two CSI receivers.\n\n## Router diagnostics

The dashboard's **Two-router hardware diagnostics** section checks these previously observed addresses:

| Device | Default address |
|---|---|
| JioAirFiber | `192.168.31.1` |
| TP-Link TL-WR850N | `192.168.31.70` |

If the router LAN addresses change, set environment variables before starting the app:

```bash
export ROUTER_JIO_IP=192.168.31.1
export ROUTER_TPLINK_IP=192.168.31.70
```

The endpoint `GET /api/router-diagnostics` performs read-only ping, TCP checks on ports 80 and 443, and a local ARP-cache lookup. A router may be unreachable from the MacBook because the two devices are on different subnets or the router blocks ping. That result is not proof that WDS is down.

### Verify WDS status manually

1. Open `http://192.168.31.70` while connected to the TP-Link network.
2. Open **Settings → Wireless → Connect to Network** to inspect the upstream SSID and connection configuration; do not edit or save it.
3. Open **Network Map** and inspect the wireless connection line between Router and TL-WR850N.
4. The inspected firmware pages do not expose a confirmed WDS peer RSSI or CSI field. A visible wireless connection indicates topology/connectivity only; it is not a radio measurement.
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

- Local database: `data/wifisense.db` (resolved relative to the project directory, not the shell working directory).
- Historical records are preserved; no automatic seven-day deletion runs.
- The app does not capture Wi-Fi payloads, deauthenticate clients, change router settings, or attempt router login.
- Router diagnostics are limited to the two configured IP addresses.
- No router passwords or admin session tokens are needed by the application.

## Firmware warning

Do not flash firmware as part of this experiment. TP-Link warns that firmware must match the exact hardware version and regional variant; an incorrect image can damage the router. The currently observed hardware is TL-WR850N V3.8 / V3 and the installed firmware is Build 210407. Any firmware decision must be checked against the exact device label and TP-Link's local support page first.

## Success criteria for the next stage

We can proceed to an RSSI-based router-link experiment only after identifying a repeatable, documented or directly verified read-only source for the **Jio-to-TP-Link WDS peer RSSI**. If the firmware does not expose it, additional dashboard or Python code cannot create that measurement. At that point, the two-router-only design needs a hardware/firmware capability change before human-crossing sensing can be evaluated.


## Motion trial analysis (added in motion-analysis-v2)

The existing live dashboard already provides the MacBook RSSI disturbance panel and the real-CSI candidate panel. This branch adds an offline analysis utility for exported, manually labelled experiment CSVs:

```bash
python tools/analyze_motion_trials.py path/to/exported-experiment.csv --output motion-report.json
```

The report compares empty-room samples with standing, walking, and object-moving labels by zone. It reports descriptive signal statistics and mean shifts only. It does not classify people versus objects, and it does not turn MacBook RSSI into Jio-to-TP-Link WDS RSSI.

See [docs/MOTION_DETECTION_GUIDE.md](docs/MOTION_DETECTION_GUIDE.md) for the controlled trial protocol and interpretation limits. A unit test is provided at `tests/test_motion_analysis.py`.


## Associated access-point identity

The live collector records the MacBook's associated BSSID when macOS exposes it. This helps identify which access point the MacBook is actually connected to, but it is **not** the Jio-to-TP-Link WDS peer measurement. The BSSID is stored per sample and is migrated into existing SQLite databases without deleting historical rows. If the driver does not expose a BSSID, the field remains empty rather than being guessed.


## Important topology note for the Jio + TP-Link room experiment

The ESP32-S3 firmware joins one selected access point and captures CSI from frames transmitted by that associated AP. If it joins the TP-Link SSID, its CSI describes the **TP-Link-to-ESP32 link**; if it joins the Jio SSID, it describes the **Jio-to-ESP32 link**. It does not passively read the private Jio-to-TP-Link WDS link and does not expose the TP-Link's WDS receive RSSI. Therefore this receiver is a separate CSI sensing link, not a software workaround for unavailable WDS telemetry. Keep the AP identity (BSSID) and receiver position fixed during trials. A single receiver supports experimental movement/presence candidates only; reliable six-zone localization requires multiple spatially separated receivers and labelled validation data.
