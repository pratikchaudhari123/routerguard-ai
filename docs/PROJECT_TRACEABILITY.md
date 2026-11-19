# WiFiSense project traceability

## Purpose

This document maps each user-visible measurement to its actual source and records the limits that must be preserved during development. It is a code-review aid, not evidence that a sensor or detector is operational.

## Measurement-source map

| Feature | Source / route | What it measures | Must not be described as |
|---|---|---|---|
| MacBook live RSSI | macOS Wi-Fi collector; `/api/status`, `/api/history` | RSSI reported by the MacBook's associated access point | Jio-to-TP-Link WDS RSSI |
| Router reachability | `backend/router_diagnostics.py`; `/api/router-diagnostics` | Read-only IP reachability, management-port checks and locally cached ARP data | WDS signal strength or CSI |
| Router path probe | `router_link_probe.py` and `router_link_probe.csv`; `/api/router-path-health` when present in the deployed version | Mac-to-router-management-IP ICMP latency and packet loss | RF RSSI, CSI, or proof that packets traversed the WDS radio hop |
| Experiment recorder | `/api/experiment/*` and SQLite experiment tables | Timestamped MacBook RSSI samples with user-applied condition labels | Ground-truth person detection |
| CSI receiver | `/api/csi`, `/api/csi/status` | Only real CSI packets received from a compatible configured receiver | CSI synthesized from RSSI or ping |
| Human/presence candidate | CSI baseline and detector state in `backend/main.py` | Experimental CSI change candidate after real packets and calibration | Validated human identity, exact position, or guaranteed crossing detection |

## Red link indicator rules

A dashboard warning may summarize observed network-path health, but its label must state which measurements triggered it.

- Green: recent management-IP probes are reachable and below configured warning thresholds.
- Amber: latency or packet-loss warning threshold is exceeded.
- Red: the configured path-health rule reports a severe condition or the management endpoint is unreachable.
- Recovered: the path returns to the healthy rule for the required recovery window.

These colors represent **management-path health**, not the physical location of RF interference. A red line between router icons highlights the affected logical link only. It must not be presented as a measured point/area of interference.

## WDS telemetry gate

Do not enable WDS RSSI/CSI calibration unless a source is verified to measure the JioAirFiber-to-TP-Link peer link directly. Record source identity, timestamp, units, peer identity and freshness. MacBook client RSSI, ping latency, packet counts, ARP, and a WDS topology diagram do not satisfy this gate.

## Human sensing gate

Do not show a live person marker unless all of the following are true:

1. Real CSI or another explicitly documented sensing feed is connected and fresh.
2. The feed's receiver identity and measurement path are known.
3. An empty-room baseline has been collected from that same source.
4. The detector reports an active candidate with a timestamp and score.
5. The UI labels the output as an experimental presence/activity candidate unless independently validated.

A single link-quality value cannot determine a person's exact location along the link.

## Local verification

Run from the repository root:

```bash
python -m compileall -q backend tools tests
python -m unittest discover -s tests -v
```

For a running local server, check:

```bash
curl -fsS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/api/router-diagnostics
```

If `/api/router-path-health` is implemented in the checked-out revision, verify it separately. A 404 means that route is not in the running revision; it does not mean the router is offline.

## Release checklist

- [ ] Confirm the branch and commit being tested.
- [ ] Run compile and unit tests.
- [ ] Confirm database files are preserved.
- [ ] Verify each API route exists in the same revision that is running.
- [ ] Verify the probe CSV is fresh before displaying path health.
- [ ] Keep MacBook RSSI, management-path metrics, WDS telemetry and CSI as separate sources.
- [ ] Do not claim exact interference location or human detection without validated sensing data.
