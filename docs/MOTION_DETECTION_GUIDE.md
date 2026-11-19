# Motion detection and validation guide

## Current hardware and measurement truth

- Primary router: JioAirFiber.
- Secondary router: TP-Link TL-WR850N V3 / V3.8, WDS mode.
- TP-Link management IP previously observed: 192.168.0.1.
- MacBook RSSI is the MacBook-to-associated-AP link only.
- The Jio-to-TP-Link WDS peer RSSI has not been verified as accessible.
- The ESP32-S3 CSI receiver path is the current experimental CSI input.

## What the application can report

1. **RSSI disturbance:** a signal-strength change at the MacBook receiver. This is not room-wide sensing.
2. **CSI movement candidate:** a sustained change in real CSI amplitude vectors after empty-area calibration. This is a candidate, not a human/object classifier.
3. **Experiment comparison:** manually labelled empty, standing, walking, and object-moving trials can be recorded and compared.
4. **Router diagnostics:** reachability and management-port checks; not WDS RSSI extraction.

## Controlled validation protocol

Keep the routers and receiver fixed for the entire test. Do not move the MacBook between conditions in a single run.

For each zone, collect:
- Empty room: at least 2 minutes.
- Person standing: 3 trials, 30–60 seconds each.
- Person crossing: at least 10 crossings in each direction.
- Non-human object movement: at least 10 trials.
- Empty room again: at least 2 minutes.

Repeat the complete protocol at least three times, preferably on different days. Note doors, fans, people outside the test area, and other Wi-Fi traffic.

Use the experiment recorder to label phases. Export CSV after each session. Analyze it with:

```bash
python tools/analyze_motion_trials.py path/to/exported-experiment.csv --output motion-report.json
```

The analyzer reports sample counts, mean/median RSSI, range, standard deviation, and mean shifts versus the empty-room condition. It does not claim classification accuracy.

## CSI receiver validation

1. Confirm the ESP32-S3 is posting actual packets to `POST /api/csi`.
2. Confirm the dashboard says the receiver is online and shows a recent packet timestamp.
3. Keep the monitored area empty and still.
4. Start the 60-real-packet empty-area calibration.
5. Run the movement and non-human disturbance trials separately.
6. Export/retain trial labels and compare false candidates as well as detected candidates.

The current detector uses temporal persistence to suppress brief spikes. It is not a trained or validated human-vs-object model. CSI changes can also arise from environmental changes and radio interference.

## Do not over-interpret

- A single RSSI drop is not proof of movement.
- A signal change cannot distinguish a person from an object by itself.
- RSSI from the MacBook is not router-to-router WDS RSSI.
- CSI candidate events are not identity, exact position, or guaranteed presence.
- No synthetic measurements should be mixed into real trial data.

## Local launch

```bash
cd ~/routerguard-ai
git fetch origin
git checkout feature/motion-analysis-v2
git pull --ff-only origin feature/motion-analysis-v2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000.


## Specific note for the confirmed installation

The two routers are in the same room, approximately 5 metres apart, with the TP-Link connected to Jio by WDS. This physical arrangement alone does not make the WDS link observable to the MacBook. The current ESP32-S3 firmware associates with a chosen AP and captures CSI from that AP's frames; it does not capture the private Jio-to-TP-Link WDS receiver link. The MacBook BSSID field identifies the AP the MacBook itself is associated with when macOS exposes it. These are separate radio links and must remain separately labelled in data and dashboard displays.
