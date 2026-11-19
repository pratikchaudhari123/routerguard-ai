#!/usr/bin/env python3
"""Evaluate labelled WiFiSense detection observations.

Input CSV must contain one row per independently labelled observation with:
  ground_truth: presence | absence
  prediction:   presence | absence
Optional timestamp_utc is used to estimate false alarms per observed hour.

This computes empirical metrics only. It cannot establish future or 100% accuracy.
Do not treat correlated CSI packets as independent trials; aggregate into trial
windows before evaluation where possible.
"""
import argparse
import csv
import json
from pathlib import Path


def _label(value, column, row_number):
    normalized = (value or "").strip().lower()
    aliases = {"1": "presence", "true": "presence", "yes": "presence",
               "0": "absence", "false": "absence", "no": "absence"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"presence", "absence"}:
        raise ValueError(
            f"Row {row_number}: {column} must be presence/absence (or 1/0)."
        )
    return normalized


def evaluate(path):
    rows = []
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"ground_truth", "prediction"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("CSV must contain ground_truth and prediction columns.")
        for row_number, row in enumerate(reader, start=2):
            rows.append({
                "truth": _label(row.get("ground_truth"), "ground_truth", row_number),
                "pred": _label(row.get("prediction"), "prediction", row_number),
                "timestamp": (row.get("timestamp_utc") or "").strip(),
            })

    tp = sum(r["truth"] == "presence" and r["pred"] == "presence" for r in rows)
    tn = sum(r["truth"] == "absence" and r["pred"] == "absence" for r in rows)
    fp = sum(r["truth"] == "absence" and r["pred"] == "presence" for r in rows)
    fn = sum(r["truth"] == "presence" and r["pred"] == "absence" for r in rows)

    def ratio(numerator, denominator):
        return round(numerator / denominator, 4) if denominator else None

    accuracy = ratio(tp + tn, len(rows))
    precision = ratio(tp, tp + fp)
    recall = ratio(tp, tp + fn)
    specificity = ratio(tn, tn + fp)
    f1 = ratio(2 * tp, 2 * tp + fp + fn)
    balanced = (
        round((recall + specificity) / 2, 4)
        if recall is not None and specificity is not None else None
    )

    timestamps = []
    if rows and all(r["timestamp"] for r in rows):
        from datetime import datetime
        try:
            timestamps = [datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00"))
                          for r in rows]
        except ValueError:
            timestamps = []
    duration_hours = (
        max((timestamps[-1] - timestamps[0]).total_seconds(), 0) / 3600
        if len(timestamps) >= 2 else None
    )

    return {
        "source_file": str(path),
        "observations": len(rows),
        "confusion_matrix": {"true_positive": tp, "true_negative": tn,
                             "false_positive": fp, "false_negative": fn},
        "metrics": {
            "accuracy": accuracy, "precision": precision, "recall_sensitivity": recall,
            "specificity": specificity, "f1": f1, "balanced_accuracy": balanced,
        },
        "false_alarms_per_hour": (
            round(fp / duration_hours, 3)
            if duration_hours and duration_hours > 0 else None
        ),
        "evaluation_warning": (
            "Empirical results apply only to these labelled observations and this "
            "installation. Use separate training and held-out test sessions, include "
            "non-human disturbances, and report trial-level results. No metric "
            "guarantees 100% accuracy or proves human identity."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file", help="CSV with ground_truth and prediction columns")
    parser.add_argument("--output", help="Optional JSON output path")
    args = parser.parse_args()
    report = evaluate(args.csv_file)
    rendered = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        print(f"Evaluation written to {args.output}")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
