# Evaluation baseline (Stage 0)

Recorded by `tests/run_ground_truth_eval.py --split all|dev|holdout` on branch
`fix/stage-00-ground-truth-eval-harness` (based on `codex/team-handoff-20260926`
HEAD `76f1d57`), against `data/labels/eval_cases.csv` (538 cases: 76 positive
across the 6 events in `data/ground_truth_events.csv`, 462 quiet negatives).

This is the **before** picture: no Stage 1+ fix has been applied yet. Every
number here is expected to move as later stages land; that is the point of
committing it now. See `IMPLEMENTATION_EVALUATION.md` for the narrative
analysis these numbers confirm, and `IMPLEMENTATION_PLAN.md` for what each
stage does about them.

To reproduce: `.venv/bin/python tests/run_ground_truth_eval.py --split all`.
Full JSON + markdown for `all`/`dev`/`holdout` splits is reproducible from the
committed script and label file; only the summary is captured below.

## Split sizes

| split | cases | positives (event_present) | decoy (EVT05) | negatives |
|---|---|---|---|---|
| all | 538 | 64 | 12 | 462 |
| dev (EVT01, EVT03, EVT04 + half of negatives) | 271 | 40 | 0 | 231 |
| holdout (EVT02, EVT05, EVT06 + other half of negatives) | 267 | 24 | 12 | 231 |

Per the plan's ground rules, thresholds and weights may only ever be tuned on
`dev`; `holdout` numbers are for reporting, never for choosing a threshold.
Negatives now cover 3 KPIs (`net_sales_revenue`, `orders`, `units_sold`) per
quiet slice-day, 154 slice-days x 3 = 462 rows, up from revenue-only.

## Methodology notes (fixed after the first review pass)

- **Recall is scored only where `event_present` is true.** EVT05 is a real
  period (the dataset generator did run it) but has no true driver and is
  labelled `event_present: false` — it must never count as a detection
  "miss" or a driver-accuracy "miss". It is reported in its own **Decoy**
  section below, never averaged into recall or driver accuracy.
- **Driver identity is resolved through `LEGACY_DRIVER_ID_ALIASES`.** Stage 1
  (plan §1.3) renames `ad_spend_drop`→`marketing_spend`,
  `checkout_latency_spike`→`checkout_latency`,
  `competitor_price_cut`→`competitor_price_index`. Rather than edit
  `ground_truth_events.csv`/`eval_cases.csv` again when that lands, the
  harness canonicalises both the label's `true_driver_id` and the pipeline's
  ranked `driver_id` before comparing, so this file's numbers stay comparable
  across the rename.
- **A "hit" is now split into two metrics.** `top1_accuracy` counts the
  ranked #1 driver id matching the label regardless of sign.
  `top1_accuracy_direction_aware` additionally requires the ranked driver's
  correlation sign (`ranked_drivers[0]["direction"]`) to match the expected
  driver-vs-KPI relationship from plan §1.2/§1.3 (hard-coded in the harness
  as `EXPECTED_DIRECTION_SIGN`, since the registry doesn't declare
  `expected_direction` until Stage 1). A naive hit that is not
  direction-aware is a **wrong-signed association** — exactly the F-R2/F-R3
  failure mode ("found `ad_spend_drop` #1 with r=-0.67, the opposite of the
  hypothesis").

## Detection recall (`--split all`, event_present cases only)

| event | true driver | recall | revenue-only recall |
|---|---|---|---|
| EVT01 (North/Electronics, marketing cut) | ad_spend_drop | 0.333 (4/12) | 0.75 (3/4) |
| EVT02 (ALL/Home, flash discount) | price_discount | 1.0 (12/12) | 1.0 (4/4) |
| EVT03 (South/Apparel, stockout) | stock_availability | 0.25 (3/12) | 0.25 (1/4) |
| EVT04 (ALL/ALL, checkout latency) | checkout_latency_spike | 0.5 (8/16) | 0.5 (2/4) |
| EVT06 (ALL/Apparel, cold snap) | weather_temp | 0.0 (0/12) | 0.0 (0/4) |

(EVT05 is excluded from this table on purpose — see Decoy section.)

False-alarm rate on the 462 quiet negatives (3 KPIs x 154 slice-days):
**4.1%** overall (dev 5.2%, holdout 3.0%). By weekday (`all` split, 66
samples/weekday: 22 slice-days x 3 KPIs): Mon 3.0%, Tue 4.5%, Wed 0.0, Thu
0.0, Fri 7.6%, Sat 4.5%, Sun 9.1%. By KPI: revenue 3.2% (5/154), orders 5.8%
(9/154), units 3.2% (5/154). This replication (154 slice-days, now 3 KPIs) is
still smaller than the evaluation's original probe (120 slice-days x 2 KPIs,
which found Sat 11/42 vs 0-1 on other weekdays), so the skew here is noisier,
but it points the same direction: weekend days (Fri/Sat/Sun) carry more false
alarms than midweek because the primary detector
(`kpi_engine/detection/robust.py`) is not weekday-aware yet (F-D1). Stage 2
fixes this.

EVT03 (a real -63.5% orders drop) and EVT06 (cold-snap revenue lift) are
recalled at or near 0 on revenue, matching the evaluation's finding that the
non-seasonal detector misses genuine large moves inside noisy weekly spread
(F-D2).

## Driver attribution (`--split all`, excludes the EVT05 decoy)

- Case-level top-1 accuracy (any sign): **15.6%** (10/64 scored cases).
  Direction-aware top-1 accuracy: **6.2%** (4/64) — most of the naive hits
  disappear once the sign is checked. Case-level top-3 accuracy: 25%.
- Event-level: the true driver ranks #1 (any sign) on at least one labelled
  day for **2 of 5** real events (EVT01, EVT04); **only 1 of 5** once the sign
  is checked (EVT04). This matches the evaluation's "found the true driver as
  #1 at most once in 5 real events" finding (F-R2/F-R3), and sharpens it:
  - **EVT01 (`ad_spend_drop`): the 4 naive hits (across
    net_sales_revenue/orders/units_sold) are all wrong-signed** — top-1
    accuracy 0.5 (any sign) drops to **0.0** direction-aware. This reproduces
    F-R2's specific finding (ranked #1 with r=-0.67, opposite of "less spend
    -> less revenue").
  - **EVT04 (`checkout_latency_spike`): the only KPI where the true driver
    ever ranks #1 is `conversion_rate`** (top1-hit KPIs: conversion_rate
    only); it never wins on net_sales_revenue, orders or units_sold, where
    `traffic_drop` still dominates (F-R2/F-R3). Its 0.25 top-1 accuracy is
    correctly signed (0.25 direction-aware too), but it only "finds" the
    driver via the one KPI closest to where checkout latency mechanically
    acts.
  - EVT02, EVT03, EVT06 never rank their true driver #1 at all: `stock_availability`
    (EVT03) can't be found because the current registry still maps `stockout`
    to the always-zero `lost_units_stockout` column (F-R1), and
    `price_discount` / `weather_temp` (EVT02/EVT06) aren't declared as
    candidate drivers at all yet (F-R4) — all fixed in Stage 1.

## Decoy (EVT05) — reported separately, never folded into recall/accuracy

- 12 cases (4 on revenue). `event_present: false` in the label file: nothing
  about this period should look like a confidently-explained real movement.
- False-alarm rate: **0.0** on all 3 KPIs, including revenue-only. The
  movement detector correctly does not flag EVT05 as material on these KPIs
  (consistent with the evaluation's expectation that only `traffic_total`
  might rise here, which is not one of the KPIs in this label set).
- **Confident-driver rate: 100%** (12/12) — even though the KPI itself never
  moves materially, the driver ranker still surfaces a top-ranked "driver"
  every time (typically the mechanical `traffic_drop` component; F-R2). Stage
  3 (explained-movement ranking, which requires the KPI to have actually
  moved) and Stage 7 (Attribution Confidence, which gates on movement
  materiality) are what bring this down.

## Causal verification (`--split all`)

Every event's causal verdict is `NOT_ASSESSED` or `UNTESTABLE`; `SUPPORTED_CONDITIONAL`
is never produced (F-V1). This is expected until Stage 5 replaces the two
hard-coded designs in `kpi_engine/verification/registry.py` with automatic,
per-driver design generation.

## Confidence (`--split all`)

Overall confidence status distribution: `{"LOW": 513, "MODERATE": 25}`. `HIGH`
is never reached (F-C2) and the distribution barely moves between cases with
very different underlying evidence, because the driver and causal dimensions
are not yet consulted by `ConfidenceEngine.build_profile` (F-C1). No numeric
score or Brier/reliability metric exists yet (F-C5) — Stage 7 introduces
per-driver Attribution Confidence and the calibration harness (`--calibrate`)
that will fill in `confidence.brier_score` here.

## What this baseline is, and is not

- It is a **synthetic-dataset regression baseline**: `data/ground_truth_events.csv`
  and `data/labels/eval_cases.csv` are built from the six events the dataset
  generator (`data/fix_dataset.py`) injected, per Stage 0 of the implementation
  plan — not from independent human review. `kpi_engine/evaluation.py`'s
  stricter "independently reviewed labels" path (`tests/run_labeled_evaluation.py`)
  is unaffected and remains the path for real calibration once analyst
  verdicts exist (Stage 9).
- The recommended holdout-fixture injection (plan Stage 0, item 3 — new events
  written to a separate `data/eval_fixtures/holdout_v1/` dataset copy, never
  seen while tuning) was **not** implemented in this pass; it is optional per
  the plan and not required by Stage 0's acceptance criteria. It remains
  future work if stronger overfitting protection is wanted beyond the
  dev/holdout split of the existing 6 events.
- The direction-aware expected-sign map (`EXPECTED_DIRECTION_SIGN` in
  `tests/run_ground_truth_eval.py`) is an evaluation-only convenience that
  anticipates plan §1.3's `expected_direction` values. It is not read from
  the registry and must not be treated as a substitute for Stage 1 actually
  declaring `expected_direction` (and `expected_direction_by_scope` for
  weather) in the YAML contracts.
