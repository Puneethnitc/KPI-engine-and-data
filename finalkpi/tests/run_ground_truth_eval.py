# IMPLEMENTATION HANDOFF — ground-truth evaluation harness
# Current: scores the engine against data/labels/eval_cases.csv, itself built
# from the six known events in data/ground_truth_events.csv. This is a
# synthetic-dataset regression harness, not the "independently reviewed" path
# kpi_engine/evaluation.py requires for production calibration.
# Next: Stage 2 tightens the detection gates, Stage 3 tightens driver-accuracy
# gates, Stage 5 fills in causal verdicts, Stage 7 fills in Attribution
# Confidence (Brier score / reliability bins) which are placeholders here.
# Check: dev-split numbers may be used to tune thresholds; holdout numbers
# must never be used to choose weights or thresholds (see IMPLEMENTATION_PLAN
# Stage 0 / 0.1 ground rules).

"""Run the full diagnosis pipeline over the ground-truth label set and report
detection, driver-attribution, causal and confidence metrics.

Usage:
    .venv/bin/python tests/run_ground_truth_eval.py --split all
    .venv/bin/python tests/run_ground_truth_eval.py --split dev --fail-under revenue_recall=0.7
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from kpi_engine.pipeline import KPIEnginePipeline

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LABELS = ROOT / "data" / "labels" / "eval_cases.csv"
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def load_cases(path: Path, split: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"case_id", "kpi_id", "date", "region", "category",
                    "event_present", "true_driver_id", "split", "reviewer"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"eval_cases.csv requires columns: {', '.join(sorted(required))}")
        for row in reader:
            if split != "all" and row["split"] != split:
                continue
            row["event_present"] = row["event_present"].strip().lower() == "true"
            row["is_decoy"] = str(row.get("is_decoy", "")).strip().lower() == "true"
            rows.append(row)
    if not rows:
        raise ValueError(f"No cases found for split={split!r} in {path}")
    return rows


def build_pipeline() -> KPIEnginePipeline:
    return KPIEnginePipeline(
        registry_dir=str(ROOT / "kpi_engine" / "registry"),
        evidence_csv=str(ROOT / "data" / "unstructured_evidence.csv"),
        access_csv=str(ROOT / "data" / "access_control.csv"),
        feedback_log_path=str(ROOT / "backend" / "runtime" / "ground_truth_eval_feedback.jsonl"),
    )


def run_case(pipeline: KPIEnginePipeline, row: dict[str, Any]) -> dict[str, Any]:
    dimension_slice = {key: row[key] for key in ("region", "category") if row.get(key)}
    return pipeline.run_diagnosis(
        kpi_id=row["kpi_id"],
        target_date=row["date"],
        persona="CFO",
        dimension_slice=dimension_slice or None,
        sales_csv=str(ROOT / "data" / "sales_daily.csv"),
        marketing_csv=str(ROOT / "data" / "marketing_weekly.csv"),
        finance_csv=str(ROOT / "data" / "finance_monthly.csv"),
    )


def top_driver_ids(result: dict[str, Any], n: int) -> list[str]:
    analysis = result.get("driver_analysis") or {}
    ranked = analysis.get("ranked_drivers") or []
    return [item["driver_id"] for item in ranked[:n]]


def evaluate(cases: list[dict[str, Any]], pipeline: KPIEnginePipeline) -> dict[str, Any]:
    detection_by_event: dict[str, Counter] = defaultdict(Counter)
    negatives_total = Counter()
    negatives_by_weekday: dict[str, Counter] = defaultdict(Counter)
    driver_top1_hits = 0
    driver_top3_hits = 0
    driver_cases_scored = 0
    driver_by_event: dict[str, Counter] = defaultdict(Counter)
    decoy_confident_hits = 0
    decoy_cases = 0
    causal_by_event: dict[str, Counter] = defaultdict(Counter)
    confidence_overall = Counter()
    revenue_recall_by_event: dict[str, Counter] = defaultdict(Counter)

    for row in cases:
        result = run_case(pipeline, row)
        movement = result.get("movement_assessment") or {}
        is_material = bool(movement.get("is_material"))
        weekday = WEEKDAY_NAMES[date.fromisoformat(row["date"]).weekday()]

        if row["event_id"]:
            bucket = detection_by_event[row["event_id"]]
            bucket["positives"] += 1
            if is_material:
                bucket["detected"] += 1
            if row["kpi_id"] == "net_sales_revenue":
                rbucket = revenue_recall_by_event[row["event_id"]]
                rbucket["positives"] += 1
                if is_material:
                    rbucket["detected"] += 1

            if row["is_decoy"]:
                decoy_cases += 1
                if top_driver_ids(result, 1):
                    decoy_confident_hits += 1
            elif row["true_driver_id"]:
                driver_cases_scored += 1
                event_bucket = driver_by_event[row["event_id"]]
                event_bucket["scored"] += 1
                top1 = top_driver_ids(result, 1)
                top3 = top_driver_ids(result, 3)
                if top1 and top1[0] == row["true_driver_id"]:
                    driver_top1_hits += 1
                    event_bucket["top1"] += 1
                if row["true_driver_id"] in top3:
                    driver_top3_hits += 1
                    event_bucket["top3"] += 1

            causal = result.get("causal_verification") or {}
            causal_by_event[row["event_id"]][causal.get("verdict") or "NOT_ASSESSED"] += 1
        else:
            negatives_total["total"] += 1
            negatives_by_weekday[weekday]["total"] += 1
            if is_material:
                negatives_total["false_alarms"] += 1
                negatives_by_weekday[weekday]["false_alarms"] += 1

        confidence_profile = result.get("confidence_profile") or {}
        confidence_overall[(confidence_profile.get("overall") or {}).get("status") or "UNKNOWN"] += 1

    detection = {
        event_id: {
            "recall": round(counts["detected"] / counts["positives"], 3),
            "detected": counts["detected"],
            "positives": counts["positives"],
        }
        for event_id, counts in sorted(detection_by_event.items())
    }
    revenue_recall = {
        event_id: {
            "recall": round(counts["detected"] / counts["positives"], 3) if counts["positives"] else None,
            "detected": counts["detected"],
            "positives": counts["positives"],
        }
        for event_id, counts in sorted(revenue_recall_by_event.items())
    }
    false_alarm_rate = (
        round(negatives_total["false_alarms"] / negatives_total["total"], 3)
        if negatives_total["total"] else None
    )
    false_alarms_by_weekday = {
        weekday: {
            "rate": round(counts["false_alarms"] / counts["total"], 3) if counts["total"] else None,
            "false_alarms": counts["false_alarms"],
            "total": counts["total"],
        }
        for weekday, counts in sorted(
            negatives_by_weekday.items(), key=lambda kv: WEEKDAY_NAMES.index(kv[0])
        )
    }
    causal = {
        event_id: dict(counts) for event_id, counts in sorted(causal_by_event.items())
    }
    driver_per_event = {
        event_id: {
            "top1_accuracy": round(counts["top1"] / counts["scored"], 3) if counts["scored"] else None,
            "top3_accuracy": round(counts["top3"] / counts["scored"], 3) if counts["scored"] else None,
            "scored": counts["scored"],
        }
        for event_id, counts in sorted(driver_by_event.items())
    }
    events_recovered_top1 = sum(1 for row in driver_per_event.values() if (row["top1_accuracy"] or 0) > 0)

    return {
        "case_count": len(cases),
        "detection": {
            "recall_per_event": detection,
            "revenue_recall_per_event": revenue_recall,
            "false_alarm_rate_negatives": false_alarm_rate,
            "false_alarms_by_weekday": false_alarms_by_weekday,
        },
        "attribution": {
            "driver_cases_scored": driver_cases_scored,
            "top1_accuracy": round(driver_top1_hits / driver_cases_scored, 3) if driver_cases_scored else None,
            "top3_accuracy": round(driver_top3_hits / driver_cases_scored, 3) if driver_cases_scored else None,
            "per_event": driver_per_event,
            "events_with_any_top1_hit": events_recovered_top1,
            "events_scored": len(driver_per_event),
            "decoy_cases": decoy_cases,
            "decoy_confident_driver_rate": round(decoy_confident_hits / decoy_cases, 3) if decoy_cases else None,
            "note": "A high decoy_confident_driver_rate at Stage 0 is the expected, documented flaw "
                    "(traffic ranks #1 regardless of the true driver); Stage 3/7 must bring it down. "
                    "events_with_any_top1_hit counts a real event as 'recovered' if the true driver ranked "
                    "#1 on at least one labelled in-window day, matching the evaluation's per-event framing.",
        },
        "causal": {
            "verdict_counts_per_event": causal,
            "note": "NOT_ASSESSED is expected for almost every case until Stage 5 auto-generates designs.",
        },
        "confidence": {
            "overall_status_counts": dict(confidence_overall),
            "brier_score": None,
            "reliability_bins": None,
            "note": "Attribution Confidence does not exist until Stage 7; these are placeholders.",
        },
    }


def to_markdown(metrics: dict[str, Any]) -> str:
    lines = ["# Ground-truth evaluation results", ""]
    lines.append(f"Cases evaluated: {metrics['case_count']}")
    lines.append("")
    lines.append("## Detection recall by event")
    lines.append("| event | recall | detected/positives |")
    lines.append("|---|---|---|")
    for event_id, row in metrics["detection"]["recall_per_event"].items():
        lines.append(f"| {event_id} | {row['recall']} | {row['detected']}/{row['positives']} |")
    lines.append("")
    lines.append("## Revenue-only recall by event")
    lines.append("| event | recall | detected/positives |")
    lines.append("|---|---|---|")
    for event_id, row in metrics["detection"]["revenue_recall_per_event"].items():
        lines.append(f"| {event_id} | {row['recall']} | {row['detected']}/{row['positives']} |")
    lines.append("")
    lines.append(f"False-alarm rate on quiet negatives: {metrics['detection']['false_alarm_rate_negatives']}")
    lines.append("")
    lines.append("## False alarms by weekday")
    lines.append("| weekday | rate | false_alarms/total |")
    lines.append("|---|---|---|")
    for weekday, row in metrics["detection"]["false_alarms_by_weekday"].items():
        lines.append(f"| {weekday} | {row['rate']} | {row['false_alarms']}/{row['total']} |")
    lines.append("")
    attribution = metrics["attribution"]
    lines.append("## Driver attribution")
    lines.append(f"- Top-1 accuracy (case-level): {attribution['top1_accuracy']} "
                 f"({attribution['driver_cases_scored']} cases scored)")
    lines.append(f"- Top-3 accuracy (case-level): {attribution['top3_accuracy']}")
    lines.append(f"- Events with the true driver ranked #1 on any day: "
                 f"{attribution['events_with_any_top1_hit']}/{attribution['events_scored']}")
    lines.append("| event | top1_accuracy | top3_accuracy | scored |")
    lines.append("|---|---|---|---|")
    for event_id, row in attribution["per_event"].items():
        lines.append(f"| {event_id} | {row['top1_accuracy']} | {row['top3_accuracy']} | {row['scored']} |")
    lines.append(f"- Decoy confident-driver rate (EVT05): {attribution['decoy_confident_driver_rate']} "
                 f"({attribution['decoy_cases']} cases)")
    lines.append("")
    lines.append("## Causal verdicts per event")
    lines.append("| event | verdict counts |")
    lines.append("|---|---|")
    for event_id, counts in metrics["causal"]["verdict_counts_per_event"].items():
        lines.append(f"| {event_id} | {counts} |")
    lines.append("")
    lines.append("## Overall confidence status distribution")
    lines.append(f"{metrics['confidence']['overall_status_counts']}")
    lines.append("")
    return "\n".join(lines)


def parse_fail_under(pairs: list[str]) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"--fail-under expects key=value, got {pair!r}")
        key, value = pair.split("=", 1)
        thresholds[key.strip()] = float(value)
    return thresholds


def check_thresholds(metrics: dict[str, Any], thresholds: dict[str, float]) -> list[str]:
    failures = []
    flat: dict[str, Any] = {
        "false_alarm_rate_negatives": metrics["detection"]["false_alarm_rate_negatives"],
        "top1_accuracy": metrics["attribution"]["top1_accuracy"],
        "top3_accuracy": metrics["attribution"]["top3_accuracy"],
        "events_with_any_top1_hit": metrics["attribution"]["events_with_any_top1_hit"],
    }
    for event_id, row in metrics["detection"]["recall_per_event"].items():
        flat[f"recall_{event_id}"] = row["recall"]
    for event_id, row in metrics["detection"]["revenue_recall_per_event"].items():
        flat[f"revenue_recall_{event_id}"] = row["recall"]
    for event_id, row in metrics["attribution"]["per_event"].items():
        flat[f"driver_top1_{event_id}"] = row["top1_accuracy"]
    for key, minimum in thresholds.items():
        value = flat.get(key)
        if value is None:
            failures.append(f"{key}: no value produced (cannot gate)")
        elif key == "false_alarm_rate_negatives":
            if value > minimum:
                failures.append(f"{key}: {value} > max allowed {minimum}")
        elif value < minimum:
            failures.append(f"{key}: {value} < required {minimum}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS))
    parser.add_argument("--split", choices=["dev", "holdout", "all"], default="all")
    parser.add_argument("--fail-under", action="append", default=[],
                         help="key=value; recall_EVT01=0.7 or false_alarm_rate_negatives=0.05 (max). Repeatable.")
    parser.add_argument("--markdown-out", default=None, help="Optional path to also write the markdown table.")
    args = parser.parse_args()

    cases = load_cases(Path(args.labels_csv), args.split)
    pipeline = build_pipeline()
    metrics = evaluate(cases, pipeline)
    report = {"split": args.split, "labels_csv": args.labels_csv, "metrics": metrics}
    print(json.dumps(report, indent=2, allow_nan=False))

    markdown = to_markdown(metrics)
    if args.markdown_out:
        Path(args.markdown_out).write_text(markdown, encoding="utf-8")
    else:
        print()
        print(markdown)

    thresholds = parse_fail_under(args.fail_under)
    failures = check_thresholds(metrics, thresholds)
    if failures:
        print("THRESHOLD FAILURES:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
