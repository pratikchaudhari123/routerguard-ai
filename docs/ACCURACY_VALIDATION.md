# WiFiSense accuracy validation

## Accuracy target and honest limits

No Wi-Fi-only detector can be promised 100% accurate in advance. Human movement, moving objects, multipath changes, interference, doors, fans, and device movement can produce overlapping radio changes. The current JioAirFiber + TL-WR850N V3 installation has not exposed verified WDS-link RSSI/CSI. MacBook readings are from the MacBook-to-associated-AP link; they are not measurements of the Jio-to-TP-Link WDS path.

The present CSI candidate detector is experimental. A candidate is not proof of a person, identity, exact location, or guaranteed crossing. Do not use it for safety, security, or emergency decisions.

## Current installation

- JioAirFiber: 192.168.31.1 (first floor)
- TP-Link TL-WR850N V3: 192.168.31.70 (first floor, WDS extender)
- MacBook: 192.168.31.214 (second floor, associated Wi-Fi client)
- The MacBook is not physically in the first-floor router-to-router test zone. Its RSSI/CCA and ping results are useful diagnostics, not direct measurements of that zone.

## Required experiment

1. Fix both routers and every receiver in place. Record receiver identity, BSSID, channel, band, channel width, location, and firmware.
2. Collect at least 10 minutes of empty-area baseline.
3. Collect separate trial windows for: person crossing each direction, person standing still, no movement, object movement, door movement, fan/airflow, and ordinary Wi-Fi traffic.
4. Repeat each condition across multiple sessions and days. Keep a trial log with ground truth, start/end timestamps, zone, direction, and environmental notes.
5. Split data by complete sessions/days into development and held-out test sets. Never randomly split adjacent packets from the same trial across both sets.
6. Tune thresholds only on development sessions. Run the final evaluation once on held-out sessions.
7. Report false positives, false negatives, precision, recall, specificity, F1, balanced accuracy, and false alarms per hour. Also report the number of independent trials and conditions.

## Evaluate labelled observations

Create a CSV with one row per independently reviewed observation window:

```csv
timestamp_utc,ground_truth,prediction
2026-11-20T10:00:00+00:00,presence,presence
2026-11-20T10:01:00+00:00,absence,absence
2026-11-20T10:02:00+00:00,absence,presence
2026-11-20T10:03:00+00:00,presence,absence
```

Labels are `presence` or `absence` (also accepts 1/0). Run:

```bash
python tools/evaluate_detection.py labelled-observations.csv --output evaluation.json
```

This reports a confusion matrix and empirical metrics. It does not manufacture accuracy data. Use one row per trial/window, not every highly correlated CSI packet, unless the evaluation explicitly accounts for packet dependence.

## Hardware gate

The two-router WDS link must not be treated as observable until a documented, directly measured WDS peer RSSI/CSI source is found. The ESP32 CSI receiver associates with one AP and observes that AP-to-receiver link; it does not passively reveal the private Jio-to-TP-Link WDS link. A receiver placed on the first floor can test its own AP-to-receiver CSI path, but that is a separate sensing path.

## Completion criteria

The project is ready for a stated experimental performance level only after:
- real receiver telemetry is flowing and its source is identified;
- the intended sensing zone and receiver geometry are fixed;
- labelled human and non-human trials are collected;
- a held-out test set is evaluated;
- false-alarm and missed-detection rates are reported;
- results repeat across sessions.

Do not advertise 100% accuracy unless a sufficiently large, independent test programme actually demonstrates it—and even then describe the tested conditions and confidence intervals rather than promising universal performance.
