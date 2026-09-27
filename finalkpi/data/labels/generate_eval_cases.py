# IMPLEMENTATION HANDOFF — ground-truth evaluation label generation
# Current: builds data/labels/eval_cases.csv from the six known events in
# data/ground_truth_events.csv (themselves derived from the comments in
# data/fix_dataset.py) plus fixed-seed random negatives. This is NOT the
# "independently reviewed" label path kpi_engine/evaluation.py insists on for
# production calibration; it is a synthetic-dataset ground truth built from
# the generator's own injected events, used only to baseline and regression-
# test this engine against known answers. Never treat it as real-world review.
# Next: once labelled analyst verdicts exist (Stage 9 feedback loop), prefer
# those for calibration and keep this file for regression testing only.
# Check: rerunning this script with the same inputs reproduces byte-identical
# output (fixed seed, sorted iteration order).

"""Deterministically (re)generate data/labels/eval_cases.csv.

Positives: 3-4 dates inside each of the 6 ground-truth event windows, for the
KPIs that event is expected to move (revenue/orders/units for all events, plus
conversion_rate for EVT04's checkout-latency outage).

Negatives: >=150 random quiet slice-days outside every event window (with a
5-day buffer on each side), spread evenly across weekdays, using a fixed RNG
seed so the set is reproducible. Restricted to the three original categories
(Apparel/Electronics/Home) so it does not overlap the separate Beauty
sparse-history scenario.
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EVENTS_CSV = ROOT / "data" / "ground_truth_events.csv"
SALES_CSV = ROOT / "data" / "sales_daily.csv"
OUT_CSV = Path(__file__).resolve().parent / "eval_cases.csv"

SEED = 20260927
NEGATIVE_TARGET = 150
EVENT_BUFFER_DAYS = 5
# Leave enough same-weekday and rolling-window history for every KPI's
# min_history_periods (<=60 days), and enough trailing days for as_of safety.
NEGATIVE_DATE_START = "2023-04-01"
NEGATIVE_DATE_END = "2024-12-20"
NEGATIVE_REGIONS = ["North", "South", "East", "West"]
NEGATIVE_CATEGORIES = ["Apparel", "Electronics", "Home"]
# Emitted for every negative slice-day (not just revenue), so false-alarm rate
# and per-weekday breakdowns can be checked on the other core KPIs too.
NEGATIVE_KPIS = ["net_sales_revenue", "orders", "units_sold"]

CORE_KPIS = ["net_sales_revenue", "orders", "units_sold"]

# event_id -> (kpis, positive dates, dimension slice, true_driver_id, split, is_decoy)
POSITIVE_DATES = {
    "EVT01": ["2023-07-20", "2023-07-24", "2023-07-31", "2023-08-07"],
    "EVT02": ["2023-10-28", "2023-10-30", "2023-11-02", "2023-11-05"],
    "EVT03": ["2024-02-05", "2024-02-07", "2024-02-10", "2024-02-14"],
    "EVT04": ["2024-05-15", "2024-05-16", "2024-05-17", "2024-05-18"],
    "EVT05": ["2024-07-14", "2024-07-18", "2024-07-22", "2024-07-27"],
    "EVT06": ["2023-04-11", "2023-04-14", "2023-04-18", "2023-04-22"],
}
EVENT_SPLIT = {
    "EVT01": "dev", "EVT03": "dev", "EVT04": "dev",
    "EVT02": "holdout", "EVT06": "holdout", "EVT05": "holdout",
}
REVIEWER = "dataset_generator_synthetic_ground_truth"


def load_events() -> pd.DataFrame:
    events = pd.read_csv(EVENTS_CSV, parse_dates=["start_date", "end_date"])
    events["is_decoy"] = events["is_decoy"].astype(str).str.lower() == "true"
    return events


def build_positive_rows(events: pd.DataFrame) -> list[dict]:
    rows = []
    for _, event in events.iterrows():
        event_id = event["event_id"]
        kpis = list(CORE_KPIS)
        if event_id == "EVT04":
            kpis.append("conversion_rate")
        region = "" if event["region"] == "ALL" else event["region"]
        category = "" if event["category"] == "ALL" else event["category"]
        true_driver_id = "" if event["is_decoy"] else event["true_driver_ids"]
        # A decoy event is present (something happened) but never explained by
        # a confident driver; revenue/orders/units are not expected to move
        # materially, so event_present is False for the movement-recall metric.
        event_present = not event["is_decoy"]
        for date in POSITIVE_DATES[event_id]:
            for kpi_id in kpis:
                rows.append(dict(
                    case_id=f"{event_id}-{date}-{kpi_id}",
                    kpi_id=kpi_id,
                    date=date,
                    region=region,
                    category=category,
                    event_present=event_present,
                    true_driver_id=true_driver_id,
                    split=EVENT_SPLIT[event_id],
                    reviewer=REVIEWER,
                    event_id=event_id,
                    is_decoy=bool(event["is_decoy"]),
                ))
    return rows


def excluded_windows(events: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    return [
        (row["start_date"] - pd.Timedelta(days=EVENT_BUFFER_DAYS),
         row["end_date"] + pd.Timedelta(days=EVENT_BUFFER_DAYS))
        for _, row in events.iterrows()
    ]


def is_quiet_date(date: pd.Timestamp, windows: list[tuple[pd.Timestamp, pd.Timestamp]]) -> bool:
    return not any(start <= date <= end for start, end in windows)


def build_negative_rows(events: pd.DataFrame) -> list[dict]:
    windows = excluded_windows(events)
    all_dates = pd.date_range(NEGATIVE_DATE_START, NEGATIVE_DATE_END, freq="D")
    quiet_dates = [d for d in all_dates if is_quiet_date(d, windows)]
    by_weekday: dict[int, list[pd.Timestamp]] = {i: [] for i in range(7)}
    for d in quiet_dates:
        by_weekday[d.dayofweek].append(d)

    rng = np.random.default_rng(SEED)
    per_weekday = -(-NEGATIVE_TARGET // 7)  # ceil
    seen: set[tuple[str, str, str]] = set()
    slice_days: list[tuple[str, str, str]] = []
    for weekday in range(7):
        candidates = list(by_weekday[weekday])
        rng.shuffle(candidates)
        picked = 0
        for date in candidates:
            if picked >= per_weekday:
                break
            region = str(rng.choice(NEGATIVE_REGIONS))
            category = str(rng.choice(NEGATIVE_CATEGORIES))
            key = (date.date().isoformat(), region, category)
            if key in seen:
                continue
            seen.add(key)
            picked += 1
            slice_days.append(key)
    slice_days.sort()

    # Every KPI for a given slice-day shares one split assignment, so the
    # same quiet day is never split dev for one KPI and holdout for another.
    rows = []
    for index, (day, region, category) in enumerate(slice_days):
        split = "dev" if index % 2 == 0 else "holdout"
        for kpi_id in NEGATIVE_KPIS:
            rows.append(dict(
                case_id=f"NEG-{day}-{region}-{category}-{kpi_id}",
                kpi_id=kpi_id,
                date=day,
                region=region,
                category=category,
                event_present=False,
                true_driver_id="",
                split=split,
                reviewer=REVIEWER,
                event_id="",
                is_decoy=False,
            ))
    return rows


def main() -> None:
    events = load_events()
    rows = build_positive_rows(events) + build_negative_rows(events)
    fieldnames = [
        "case_id", "kpi_id", "date", "region", "category", "event_present",
        "true_driver_id", "split", "reviewer", "event_id", "is_decoy",
    ]
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    negatives = [r for r in rows if not r["event_id"]]
    print(f"Wrote {len(rows)} cases ({len(rows) - len(negatives)} positive, "
          f"{len(negatives)} negative) to {OUT_CSV}")


if __name__ == "__main__":
    main()
