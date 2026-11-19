#!/usr/bin/env python3
"""Analyze WiFiSense experiment CSV exports.

This tool compares measured MacBook RSSI distributions by manually labelled
condition. It does not identify people/objects and does not infer Jio-to-TP-Link
WDS RSSI. It requires real collected CSV rows; it never generates samples.
"""
import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

def summarize(values):
    if not values:
        return None
    return {
        "samples": len(values),
        "mean_dbm": round(statistics.fmean(values), 2),
        "median_dbm": round(statistics.median(values), 2),
        "min_dbm": min(values),
        "max_dbm": max(values),
        "range_db": round(max(values) - min(values), 2),
        "stddev_db": round(statistics.pstdev(values), 2) if len(values) > 1 else 0.0,
    }

def analyze(path):
    groups = defaultdict(list)
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"condition", "rssi_dbm"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("CSV must contain condition and rssi_dbm columns.")
        for row in reader:
            try:
                value = float(row["rssi_dbm"])
            except (TypeError, ValueError):
                continue
            if not -120 <= value <= 0:
                continue
            condition = (row.get("condition") or "unlabelled").strip()
            zone = (row.get("zone") or "unspecified").strip()
            groups[(zone, condition)].append(value)

    results = []
    by_zone = defaultdict(dict)
    for (zone, condition), values in sorted(groups.items()):
        summary = summarize(values)
        by_zone[zone][condition] = summary
        results.append({"zone": zone, "condition": condition, **summary})

    comparisons = []
    for zone, conditions in sorted(by_zone.items()):
        baseline = conditions.get("empty")
        if not baseline:
            continue
        for condition, summary in sorted(conditions.items()):
            if condition == "empty":
                continue
            comparisons.append({
                "zone": zone,
                "baseline_condition": "empty",
                "comparison_condition": condition,
                "baseline_mean_dbm": baseline["mean_dbm"],
                "comparison_mean_dbm": summary["mean_dbm"],
                "mean_shift_db": round(summary["mean_dbm"] - baseline["mean_dbm"], 2),
                "baseline_stddev_db": baseline["stddev_db"],
                "comparison_stddev_db": summary["stddev_db"],
                "baseline_samples": baseline["samples"],
                "comparison_samples": summary["samples"],
            })
    return {
        "source_file": str(path),
        "measurement_scope": "MacBook-to-associated-access-point RSSI only",
        "groups": results,
        "comparisons_vs_empty": comparisons,
        "interpretation": (
            "Descriptive comparison of manually labelled trials. A repeatable shift "
            "may indicate a radio disturbance, but cannot identify a human versus an "
            "object, prove a crossing, or represent Jio-to-TP-Link WDS RSSI."
        ),
    }

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file", help="WiFiSense experiment CSV export")
    parser.add_argument("--output", help="Write JSON report to this path")
    args = parser.parse_args()
    report = analyze(args.csv_file)
    rendered = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(rendered)

if __name__ == "__main__":
    main()
