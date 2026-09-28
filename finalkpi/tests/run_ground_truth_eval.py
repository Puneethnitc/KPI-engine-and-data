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
# Stage 0 / 0.1 ground rules). Movement recall is scored only where
# event_present is true; EVT05 (a real but non-causal decoy period) is scored
# separately as a decoy false-alarm rate, never folded into recall.

"""Run the full diagnosis pipeline over the ground-truth label set and report
detection, driver-attribution, causal and confidence metrics.

Usage:
    .venv/bin/python tests/run_ground_truth_eval.py --split all
    .venv/bin/python tests/run_ground_truth_eval.py --split dev --fail-under revenue_recall_EVT01=0.7
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from kpi_engine.attribution_confidence import AttributionConfidenceEngine, AttributionConfidenceModel, default_model
from kpi_engine.pipeline import KPIEnginePipeline

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LABELS = ROOT / "data" / "labels" / "eval_cases.csv"
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Plan Stage 1 (§1.3) renames these driver ids (and keeps a LEGACY_DRIVER_IDS
# alias in kpi_engine/contracts/registry.py for saved runs/feedback). Rather
# than editing data/ground_truth_events.csv and data/labels/eval_cases.csv
# again when that rename lands, the harness resolves both spellings here.
LEGACY_DRIVER_ID_ALIASES = {
    "ad_spend_drop": "marketing_spend",
    "checkout_latency_spike": "checkout_latency",
    "competitor_price_cut": "competitor_price_index",
}


def canonical_driver_id(driver_id: str) -> str:
    return LEGACY_DRIVER_ID_ALIASES.get(driver_id, driver_id)


# Expected sign of the driver-vs-KPI relationship (plan §1.2/§1.3), used only
# to flag a "hit" that has the wrong sign (F-R2/F-R3: e.g. ad_spend_drop
# ranked #1 with r=-0.67, the opposite of "more spend -> more revenue"). None
# of this is declared in the registry yet (that's Stage 1), so it is
# hard-coded here purely for evaluation.
EXPECTED_DIRECTION_SIGN = {
    "marketing_spend": "POSITIVE",
    "checkout_latency": "NEGATIVE",
    "competitor_price_index": "POSITIVE",
    "stock_availability": "POSITIVE",
    "price_discount": "POSITIVE",
    "promo_flag": "POSITIVE",
}
# weather_temp's expected direction is scope-dependent (plan §1.2); the only
# ground-truth weather event (EVT06) is category=Apparel.
WEATHER_DIRECTION_BY_CATEGORY = {"Apparel": "NEGATIVE"}
MAX_IS_BETTER_METRICS = {"false_alarm_rate_negatives", "decoy_false_alarm_rate_all_kpis",
                          "decoy_false_alarm_rate_revenue", "decoy_max_ac"}


def expected_direction_sign(driver_id: str, category: str) -> str | None:
    driver_id = canonical_driver_id(driver_id)
    if driver_id == "weather_temp":
        return WEATHER_DIRECTION_BY_CATEGORY.get(category)
    return EXPECTED_DIRECTION_SIGN.get(driver_id)


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


def top_ranked_driver(result: dict[str, Any]) -> dict[str, Any] | None:
    analysis = result.get("driver_analysis") or {}
    ranked = analysis.get("ranked_drivers") or []
    return ranked[0] if ranked else None


def top_driver_ids(result: dict[str, Any], n: int) -> list[str]:
    analysis = result.get("driver_analysis") or {}
    ranked = analysis.get("ranked_drivers") or []
    return [canonical_driver_id(item["driver_id"]) for item in ranked[:n]]


def attribution_confidence_metrics(
    ac_labels: list[tuple[float, int]], decoy_ac_values: list[float],
) -> dict[str, Any]:
    true_acs = [ac for ac, label in ac_labels if label == 1]
    false_acs = [ac for ac, label in ac_labels if label == 0]
    mean_true_ac = round(sum(true_acs) / len(true_acs), 4) if true_acs else None
    mean_false_ac = round(sum(false_acs) / len(false_acs), 4) if false_acs else None
    ac_gap = round(mean_true_ac - mean_false_ac, 4) if mean_true_ac is not None and mean_false_ac is not None else None
    brier = round(sum((ac - label) ** 2 for ac, label in ac_labels) / len(ac_labels), 4) if ac_labels else None
    return {
        "mean_true_driver_ac": mean_true_ac,
        "mean_false_driver_ac": mean_false_ac,
        "ac_gap": ac_gap,
        "decoy_max_ac": round(max(decoy_ac_values), 4) if decoy_ac_values else None,
        "brier_score": brier,
        "n_true_driver_scored": len(true_acs),
        "n_false_driver_scored": len(false_acs),
        "n_decoy_scored": len(decoy_ac_values),
    }


def collect_ac_training_rows(
    cases: list[dict[str, Any]], pipeline: KPIEnginePipeline, model: AttributionConfidenceModel,
) -> list[dict[str, Any]]:
    """One row per ranked, AC-scored driver in an event_present case with a
    labelled true driver: its feature activations (Plan §7.1's evidence
    items, at the same weight-key granularity as the model file) plus the
    1/0 label (is this the labelled true driver?). Used by --calibrate to
    fit new weights by L2-regularised logistic regression (dev split only)."""
    rows: list[dict[str, Any]] = []
    for row in cases:
        if row["is_decoy"] or not (row.get("event_id") and row["event_present"] and row["true_driver_id"]):
            continue
        result = run_case(pipeline, row)
        true_id = canonical_driver_id(row["true_driver_id"])
        source_status = ((result.get("confidence_profile") or {}).get("source") or {}).get("status")
        causal_verification = result.get("causal_verification") or {}
        causal_design_approved = bool(result.get("_causal_design_approved"))
        for driver in (result.get("driver_analysis") or {}).get("ranked_drivers") or []:
            if not driver.get("moved") or driver.get("offsetting"):
                continue
            if (driver.get("sample_size") or 0) < model.thresholds["min_history_periods"]:
                continue
            causal_for_driver = (
                causal_verification if causal_design_approved
                and causal_verification.get("driver_id") == driver.get("driver_id") else None
            )
            features = AttributionConfidenceEngine.feature_activations(
                driver, causal_result=causal_for_driver, corroboration=None,
                source_status=source_status, model=model,
            )
            rows.append({
                "features": features,
                "label": 1 if canonical_driver_id(driver["driver_id"]) == true_id else 0,
            })
    return rows


def fit_logistic_regression(
    rows: list[dict[str, Any]], keys: tuple[str, ...], *, priors: dict[str, float],
    l2: float = 1.0, lr: float = 0.1, iterations: int = 2000,
) -> dict[str, float]:
    """L2-regularised logistic regression by gradient descent, starting from
    the hand-set weights as priors (Plan §7.1's calibration note) -- no
    sklearn dependency is installed in this environment. The L2 penalty is
    centred on the prior, not on zero, so an under-represented feature
    decays toward the hand-set judgement rather than toward "no effect"."""
    n = len(rows)
    if n == 0:
        return dict(priors)
    weights = dict(priors)
    for _ in range(iterations):
        gradients = {key: 0.0 for key in keys}
        for row in rows:
            z = sum(row["features"].get(key, 0.0) * weights[key] for key in keys)
            prediction = 1.0 / (1.0 + math.exp(-z)) if z >= 0 else math.exp(z) / (1.0 + math.exp(z))
            error = prediction - row["label"]
            for key in keys:
                activation = row["features"].get(key, 0.0)
                if activation:
                    gradients[key] += error * activation
        for key in keys:
            grad = gradients[key] / n + l2 * (weights[key] - priors[key]) / n
            weights[key] -= lr * grad
    return weights


def calibrate_attribution_confidence(
    dev_cases: list[dict[str, Any]], holdout_cases: list[dict[str, Any]], pipeline: KPIEnginePipeline,
) -> dict[str, Any]:
    v1 = default_model()
    dev_rows = collect_ac_training_rows(dev_cases, pipeline, v1)
    priors = {key: v1.weights[key] for key in AttributionConfidenceEngine.WEIGHT_KEYS}
    fitted = fit_logistic_regression(dev_rows, AttributionConfidenceEngine.WEIGHT_KEYS, priors=priors)

    v2_data = {
        "version": "attribution-confidence-v2",
        "calibration_status": "CALIBRATED_ON_SYNTHETIC_LABELS",
        "weights": {**{k: v1.weights[k] for k in v1.weights if k not in AttributionConfidenceEngine.WEIGHT_KEYS}, **fitted},
        "caps": dict(v1.caps),
        "bands": {name: dict(spec) for name, spec in v1.bands.items()},
        "thresholds": dict(v1.thresholds),
    }
    v2_path = ROOT / "kpi_engine" / "models" / "attribution_confidence_v2.yaml"
    with open(v2_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(v2_data, handle, sort_keys=False)
    v2_model = AttributionConfidenceModel.load(v2_path)

    holdout_rows = collect_ac_training_rows(holdout_cases, pipeline, v1)
    holdout_labels: list[tuple[float, int]] = []
    for row in holdout_rows:
        logit_ac = math.log(0.5 / 0.5) + sum(
            row["features"].get(key, 0.0) * v2_model.weights[key] for key in AttributionConfidenceEngine.WEIGHT_KEYS
        )
        ac = 1.0 / (1.0 + math.exp(-logit_ac)) if logit_ac >= 0 else math.exp(logit_ac) / (1.0 + math.exp(logit_ac))
        holdout_labels.append((ac, row["label"]))
    brier = (
        round(sum((ac - label) ** 2 for ac, label in holdout_labels) / len(holdout_labels), 4)
        if holdout_labels else None
    )
    log_loss = None
    if holdout_labels:
        eps = 1e-9
        log_loss = round(
            -sum(
                label * math.log(max(ac, eps)) + (1 - label) * math.log(max(1 - ac, eps))
                for ac, label in holdout_labels
            ) / len(holdout_labels), 4,
        )
    bins: dict[str, dict[str, Any]] = {}
    for low in (0.0, 0.2, 0.4, 0.6, 0.8):
        bucket = [(ac, label) for ac, label in holdout_labels if low <= ac < low + 0.2 or (low == 0.8 and ac == 1.0)]
        bins[f"{low:.1f}-{low + 0.2:.1f}"] = {
            "n": len(bucket),
            "mean_predicted": round(sum(ac for ac, _ in bucket) / len(bucket), 4) if bucket else None,
            "observed_rate": round(sum(label for _, label in bucket) / len(bucket), 4) if bucket else None,
        }

    return {
        "v2_path": str(v2_path),
        "n_dev_rows": len(dev_rows),
        "n_holdout_rows": len(holdout_rows),
        "holdout_brier": brier,
        "holdout_log_loss": log_loss,
        "holdout_reliability_bins": bins,
        "note": "Weights are fit on --split dev only, starting from the v1 hand-set weights as an L2 "
                "prior. Holdout Brier/log-loss/reliability above are reported, never used to pick "
                "weights or thresholds (AGENTS.md rule 5). Labels are the synthetic ground-truth "
                "true_driver_id column, not reviewed real-world outcomes -- calibration_status stays "
                "CALIBRATED_ON_SYNTHETIC_LABELS, never 'calibrated on real data'.",
    }


def evaluate(cases: list[dict[str, Any]], pipeline: KPIEnginePipeline) -> dict[str, Any]:
    detection_by_event: dict[str, Counter] = defaultdict(Counter)
    revenue_recall_by_event: dict[str, Counter] = defaultdict(Counter)
    negatives_total = Counter()
    negatives_by_weekday: dict[str, Counter] = defaultdict(Counter)
    negatives_by_kpi = Counter()
    negatives_false_alarms_by_kpi = Counter()

    driver_top1_hits = 0
    driver_top1_direction_hits = 0
    driver_top3_hits = 0
    driver_cases_scored = 0
    driver_by_event: dict[str, Counter] = defaultdict(Counter)
    top1_hit_kpis_by_event: dict[str, set[str]] = defaultdict(set)

    decoy_total = 0
    decoy_false_alarms = 0
    decoy_revenue_total = 0
    decoy_revenue_false_alarms = 0
    decoy_confident_hits = 0

    causal_by_event: dict[str, Counter] = defaultdict(Counter)
    confidence_overall = Counter()
    reconciliation_by_kpi: dict[str, Counter] = defaultdict(Counter)
    ac_labels: list[tuple[float, int]] = []
    decoy_ac_values: list[float] = []

    for row in cases:
        result = run_case(pipeline, row)
        movement = result.get("movement_assessment") or {}
        is_material = bool(movement.get("is_material"))
        weekday = WEEKDAY_NAMES[date.fromisoformat(row["date"]).weekday()]
        event_id = row["event_id"]

        if row["is_decoy"]:
            decoy_total += 1
            if is_material:
                decoy_false_alarms += 1
            if row["kpi_id"] == "net_sales_revenue":
                decoy_revenue_total += 1
                if is_material:
                    decoy_revenue_false_alarms += 1
            if top_ranked_driver(result) is not None:
                decoy_confident_hits += 1
            causal = result.get("causal_verification") or {}
            causal_by_event[event_id][causal.get("verdict") or "NOT_ASSESSED"] += 1
            decoy_ac_values.extend(
                item["attribution_confidence"]
                for item in (result.get("driver_analysis") or {}).get("ranked_drivers") or []
                if item.get("attribution_confidence") is not None
            )

        elif event_id and row["event_present"]:
            bucket = detection_by_event[event_id]
            bucket["positives"] += 1
            if is_material:
                bucket["detected"] += 1
            if row["kpi_id"] == "net_sales_revenue":
                rbucket = revenue_recall_by_event[event_id]
                rbucket["positives"] += 1
                if is_material:
                    rbucket["detected"] += 1

            if row["true_driver_id"]:
                true_id = canonical_driver_id(row["true_driver_id"])
                driver_cases_scored += 1
                event_bucket = driver_by_event[event_id]
                event_bucket["scored"] += 1
                top1 = top_ranked_driver(result)
                top3_ids = top_driver_ids(result, 3)
                hit1 = bool(top1) and canonical_driver_id(top1["driver_id"]) == true_id
                if hit1:
                    driver_top1_hits += 1
                    event_bucket["top1"] += 1
                    top1_hit_kpis_by_event[event_id].add(row["kpi_id"])
                    expected_sign = expected_direction_sign(true_id, row["category"])
                    if expected_sign is not None and top1.get("direction") == expected_sign:
                        driver_top1_direction_hits += 1
                        event_bucket["top1_direction"] += 1
                if true_id in top3_ids:
                    driver_top3_hits += 1
                    event_bucket["top3"] += 1
                for item in (result.get("driver_analysis") or {}).get("ranked_drivers") or []:
                    ac = item.get("attribution_confidence")
                    if ac is None:
                        continue
                    label = 1 if canonical_driver_id(item["driver_id"]) == true_id else 0
                    ac_labels.append((ac, label))

            causal = result.get("causal_verification") or {}
            causal_by_event[event_id][causal.get("verdict") or "NOT_ASSESSED"] += 1

        else:
            negatives_total["total"] += 1
            negatives_by_weekday[weekday]["total"] += 1
            negatives_by_kpi[row["kpi_id"]] += 1
            if is_material:
                negatives_total["false_alarms"] += 1
                negatives_by_weekday[weekday]["false_alarms"] += 1
                negatives_false_alarms_by_kpi[row["kpi_id"]] += 1

        confidence_profile = result.get("confidence_profile") or {}
        confidence_overall[(confidence_profile.get("overall") or {}).get("status") or "UNKNOWN"] += 1

        recon_status = (result.get("reconciliation_verdict") or {}).get("status") or "UNKNOWN"
        reconciliation_by_kpi[row["kpi_id"]][recon_status] += 1

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
    false_alarms_by_kpi = {
        kpi_id: {
            "rate": round(negatives_false_alarms_by_kpi[kpi_id] / total, 3) if total else None,
            "false_alarms": negatives_false_alarms_by_kpi[kpi_id],
            "total": total,
        }
        for kpi_id, total in sorted(negatives_by_kpi.items())
    }
    causal = {
        event_id: dict(counts) for event_id, counts in sorted(causal_by_event.items())
    }
    driver_per_event = {
        event_id: {
            "top1_accuracy": round(counts["top1"] / counts["scored"], 3) if counts["scored"] else None,
            "top1_direction_accuracy": round(counts["top1_direction"] / counts["scored"], 3) if counts["scored"] else None,
            "top3_accuracy": round(counts["top3"] / counts["scored"], 3) if counts["scored"] else None,
            "scored": counts["scored"],
            "top1_hit_kpis": sorted(top1_hit_kpis_by_event.get(event_id, set())),
        }
        for event_id, counts in sorted(driver_by_event.items())
    }
    events_recovered_top1 = sum(1 for row in driver_per_event.values() if (row["top1_accuracy"] or 0) > 0)
    events_recovered_top1_direction = sum(
        1 for row in driver_per_event.values() if (row["top1_direction_accuracy"] or 0) > 0
    )

    reconciliation = {}
    for kpi_id, counts in sorted(reconciliation_by_kpi.items()):
        total = sum(counts.values())
        # NOT_APPLICABLE means no comparator is declared for this KPI at all
        # (a different question from "did the comparison resolve"); exclude
        # it from both sides of the rate so an unreconciled KPI reports None,
        # not a misleading 0.0.
        reconciled_total = total - counts.get("NOT_APPLICABLE", 0)
        resolved = sum(counts[status] for status in ("AGREED", "DRIFT", "CONTRADICTED", "PENDING_CLOSE"))
        reconciliation[kpi_id] = {
            "status_counts": dict(counts),
            "total": total,
            # Stage 4 (F-C3) harness gate: for a reconciled KPI, at least 70%
            # of dates should resolve to AGREED/DRIFT/PENDING_CLOSE rather
            # than NOT_AVAILABLE_FOR_PERIOD (genuinely missing/overdue).
            "resolved_rate": round(resolved / reconciled_total, 3) if reconciled_total else None,
        }

    return {
        "case_count": len(cases),
        "detection": {
            "recall_per_event": detection,
            "revenue_recall_per_event": revenue_recall,
            "false_alarm_rate_negatives": false_alarm_rate,
            "false_alarms_by_weekday": false_alarms_by_weekday,
            "false_alarms_by_kpi": false_alarms_by_kpi,
        },
        "attribution": {
            "driver_cases_scored": driver_cases_scored,
            "top1_accuracy": round(driver_top1_hits / driver_cases_scored, 3) if driver_cases_scored else None,
            "top1_accuracy_direction_aware": (
                round(driver_top1_direction_hits / driver_cases_scored, 3) if driver_cases_scored else None
            ),
            "top3_accuracy": round(driver_top3_hits / driver_cases_scored, 3) if driver_cases_scored else None,
            "per_event": driver_per_event,
            "events_with_any_top1_hit": events_recovered_top1,
            "events_with_any_top1_direction_hit": events_recovered_top1_direction,
            "events_scored": len(driver_per_event),
            "note": "top1_accuracy counts a hit whenever the ranked #1 driver id matches the label, "
                    "regardless of sign; top1_accuracy_direction_aware additionally requires the ranked "
                    "driver's correlation sign to match the expected driver-vs-KPI relationship (plan "
                    "§1.2/§1.3), which is not yet declared in the registry (Stage 1) so is hard-coded here "
                    "for evaluation only. A naive hit that is not a direction-aware hit is a wrong-signed "
                    "association (see docs/EVALUATION_BASELINE.md, e.g. EVT01/ad_spend_drop).",
        },
        "decoy": {
            "cases": decoy_total,
            "false_alarm_rate_all_kpis": round(decoy_false_alarms / decoy_total, 3) if decoy_total else None,
            "revenue_cases": decoy_revenue_total,
            "false_alarm_rate_revenue": (
                round(decoy_revenue_false_alarms / decoy_revenue_total, 3) if decoy_revenue_total else None
            ),
            "confident_driver_rate": round(decoy_confident_hits / decoy_total, 3) if decoy_total else None,
            "note": "EVT05 is a real (non-decoy-labelled-as-quiet) period with no true driver: "
                    "event_present is False for it, so it is scored here, never folded into detection "
                    "recall or driver accuracy. A high confident_driver_rate at Stage 0 is the documented "
                    "flaw (a driver is always surfaced regardless of whether it truly moved); Stage 3/7 "
                    "must bring it down.",
        },
        "causal": {
            "verdict_counts_per_event": causal,
            "note": "NOT_ASSESSED is expected for almost every case until Stage 5 auto-generates designs.",
        },
        "confidence": {
            "overall_status_counts": dict(confidence_overall),
            "attribution_confidence": attribution_confidence_metrics(ac_labels, decoy_ac_values),
            "note": "Attribution Confidence (Stage 7): mean_true_driver_ac/mean_false_driver_ac/ac_gap "
                    "score every ranked driver in an event_present case with a labelled true driver "
                    "(true_driver_id) against every OTHER ranked driver in that case (label 0). "
                    "decoy_max_ac is the max AC seen across the EVT05 decoy cases (never folded into "
                    "the true/false split above). brier_score is over the same true/false pairs.",
        },
        "reconciliation": {
            "by_kpi": reconciliation,
            "note": "Stage 4 (F-C3) gate: a reconciled KPI's resolved_rate "
                    "(AGREED+DRIFT+CONTRADICTED+PENDING_CLOSE, i.e. not "
                    "NOT_AVAILABLE_FOR_PERIOD) should be >= 0.70 for revenue.",
        },
    }


def to_markdown(metrics: dict[str, Any]) -> str:
    lines = ["# Ground-truth evaluation results", ""]
    lines.append(f"Cases evaluated: {metrics['case_count']}")
    lines.append("")
    lines.append("## Detection recall by event (event_present cases only)")
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
    lines.append("## False alarms by KPI")
    lines.append("| kpi | rate | false_alarms/total |")
    lines.append("|---|---|---|")
    for kpi_id, row in metrics["detection"]["false_alarms_by_kpi"].items():
        lines.append(f"| {kpi_id} | {row['rate']} | {row['false_alarms']}/{row['total']} |")
    lines.append("")
    attribution = metrics["attribution"]
    lines.append("## Driver attribution (excludes the EVT05 decoy; see Decoy section)")
    lines.append(f"- Top-1 accuracy (case-level, any sign): {attribution['top1_accuracy']} "
                 f"({attribution['driver_cases_scored']} cases scored)")
    lines.append(f"- Top-1 accuracy (case-level, direction-aware): {attribution['top1_accuracy_direction_aware']}")
    lines.append(f"- Top-3 accuracy (case-level): {attribution['top3_accuracy']}")
    lines.append(f"- Events with the true driver ranked #1 on any day (any sign): "
                 f"{attribution['events_with_any_top1_hit']}/{attribution['events_scored']}")
    lines.append(f"- Events with a direction-consistent #1 hit: "
                 f"{attribution['events_with_any_top1_direction_hit']}/{attribution['events_scored']}")
    lines.append("| event | top1 (any sign) | top1 (direction-aware) | top3 | scored | top1-hit KPIs |")
    lines.append("|---|---|---|---|---|---|")
    for event_id, row in attribution["per_event"].items():
        lines.append(f"| {event_id} | {row['top1_accuracy']} | {row['top1_direction_accuracy']} | "
                     f"{row['top3_accuracy']} | {row['scored']} | {', '.join(row['top1_hit_kpis']) or '-'} |")
    lines.append("")
    decoy = metrics["decoy"]
    lines.append("## Decoy (EVT05) — reported separately, never folded into recall/accuracy")
    lines.append(f"- Cases: {decoy['cases']} (revenue-only: {decoy['revenue_cases']})")
    lines.append(f"- False-alarm rate, all KPIs: {decoy['false_alarm_rate_all_kpis']}")
    lines.append(f"- False-alarm rate, revenue only: {decoy['false_alarm_rate_revenue']}")
    lines.append(f"- Confident-driver rate (a top driver was surfaced regardless of truth): "
                 f"{decoy['confident_driver_rate']}")
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
    ac_metrics = metrics["confidence"]["attribution_confidence"]
    lines.append("## Attribution Confidence (Stage 7)")
    lines.append(f"- Mean AC, true driver: {ac_metrics['mean_true_driver_ac']} "
                 f"({ac_metrics['n_true_driver_scored']} scored)")
    lines.append(f"- Mean AC, false drivers: {ac_metrics['mean_false_driver_ac']} "
                 f"({ac_metrics['n_false_driver_scored']} scored)")
    lines.append(f"- AC gap (true - false, accept >= 0.30): {ac_metrics['ac_gap']}")
    lines.append(f"- Decoy (EVT05) max AC (accept < 0.5): {ac_metrics['decoy_max_ac']} "
                 f"({ac_metrics['n_decoy_scored']} scored)")
    lines.append(f"- Brier score: {ac_metrics['brier_score']}")
    lines.append("")
    lines.append("## Reconciliation status by KPI (Stage 4, F-C3)")
    lines.append("| kpi | resolved rate (target >= 0.70) | status counts |")
    lines.append("|---|---|---|")
    for kpi_id, row in metrics["reconciliation"]["by_kpi"].items():
        lines.append(f"| {kpi_id} | {row['resolved_rate']} | {row['status_counts']} |")
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
        "top1_accuracy_direction_aware": metrics["attribution"]["top1_accuracy_direction_aware"],
        "top3_accuracy": metrics["attribution"]["top3_accuracy"],
        "events_with_any_top1_hit": metrics["attribution"]["events_with_any_top1_hit"],
        "events_with_any_top1_direction_hit": metrics["attribution"]["events_with_any_top1_direction_hit"],
        "decoy_false_alarm_rate_all_kpis": metrics["decoy"]["false_alarm_rate_all_kpis"],
        "decoy_false_alarm_rate_revenue": metrics["decoy"]["false_alarm_rate_revenue"],
        "ac_gap": metrics["confidence"]["attribution_confidence"]["ac_gap"],
        "decoy_max_ac": metrics["confidence"]["attribution_confidence"]["decoy_max_ac"],
    }
    for kpi_id, row in metrics["reconciliation"]["by_kpi"].items():
        flat[f"reconciliation_resolved_rate_{kpi_id}"] = row["resolved_rate"]
    for event_id, row in metrics["detection"]["recall_per_event"].items():
        flat[f"recall_{event_id}"] = row["recall"]
    for event_id, row in metrics["detection"]["revenue_recall_per_event"].items():
        flat[f"revenue_recall_{event_id}"] = row["recall"]
    for event_id, row in metrics["attribution"]["per_event"].items():
        flat[f"driver_top1_{event_id}"] = row["top1_accuracy"]
        flat[f"driver_top1_direction_{event_id}"] = row["top1_direction_accuracy"]
    for key, minimum in thresholds.items():
        value = flat.get(key)
        if value is None:
            failures.append(f"{key}: no value produced (cannot gate)")
        elif key in MAX_IS_BETTER_METRICS:
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
                         help="key=value; recall_EVT01=0.7 (min) or false_alarm_rate_negatives=0.05 "
                              "(max, for keys in MAX_IS_BETTER_METRICS). Repeatable.")
    parser.add_argument("--markdown-out", default=None, help="Optional path to also write the markdown table.")
    parser.add_argument("--calibrate", action="store_true",
                         help="Fit Attribution Confidence weights on --split dev by L2-regularised "
                              "logistic regression, write attribution_confidence_v2.yaml, and report "
                              "Brier/log-loss/reliability on holdout (Plan §7.1). Never changes --split "
                              "used for the main evaluation below.")
    args = parser.parse_args()

    cases = load_cases(Path(args.labels_csv), args.split)
    pipeline = build_pipeline()

    if args.calibrate:
        dev_cases = load_cases(Path(args.labels_csv), "dev")
        holdout_cases = load_cases(Path(args.labels_csv), "holdout")
        calibration = calibrate_attribution_confidence(dev_cases, holdout_cases, pipeline)
        print(json.dumps({"calibration": calibration}, indent=2, allow_nan=False))
        print()

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
