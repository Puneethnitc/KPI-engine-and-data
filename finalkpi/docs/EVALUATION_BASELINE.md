# Evaluation baseline (Stage 0)

Recorded by `tests/run_ground_truth_eval.py --split all|dev|holdout` on branch
`fix/stage-00-ground-truth-eval-harness` (based on `codex/team-handoff-20260926`
HEAD `76f1d57`), against `data/labels/eval_cases.csv` (230 cases: 76 positive
across the 6 events in `data/ground_truth_events.csv`, 154 quiet negatives).

This is the **before** picture: no Stage 1+ fix has been applied yet. Every
number here is expected to move as later stages land; that is the point of
committing it now. See `IMPLEMENTATION_EVALUATION.md` for the narrative
analysis these numbers confirm, and `IMPLEMENTATION_PLAN.md` for what each
stage does about them.

To reproduce: `.venv/bin/python tests/run_ground_truth_eval.py --split all`.
Full JSON + markdown for `all`/`dev`/`holdout` splits is reproducible from the
committed script and label file; only the summary is captured below.

## Split sizes

| split | cases | positives | negatives |
|---|---|---|---|
| all | 230 | 76 | 154 |
| dev (EVT01, EVT03, EVT04 + half of negatives) | 117 | 40 | 77 |
| holdout (EVT02, EVT05, EVT06 + other half of negatives) | 113 | 36 | 77 |

Per the plan's ground rules, thresholds and weights may only ever be tuned on
`dev`; `holdout` numbers are for reporting, never for choosing a threshold.

## Detection recall (`--split all`)

| event | true driver | recall | revenue-only recall |
|---|---|---|---|
| EVT01 (North/Electronics, marketing cut) | ad_spend_drop | 0.333 (4/12) | 0.75 (3/4) |
| EVT02 (ALL/Home, flash discount) | price_discount | 1.0 (12/12) | 1.0 (4/4) |
| EVT03 (South/Apparel, stockout) | stock_availability | 0.25 (3/12) | 0.25 (1/4) |
| EVT04 (ALL/ALL, checkout latency) | checkout_latency_spike | 0.5 (8/16) | 0.5 (2/4) |
| EVT05 (East/Electronics, decoy) | none (abstain expected) | 0.0 (0/12) | 0.0 (0/4) |
| EVT06 (ALL/Apparel, cold snap) | weather_temp | 0.0 (0/12) | 0.0 (0/4) |

False-alarm rate on the 154 quiet negatives: **3.2%** overall (dev 5.2%,
holdout 1.3%). By weekday (`all` split, 22 quiet slice-days each): Mon 0.0,
Tue 4.5%, Wed 0.0, Thu 0.0, Fri 4.5%, Sat 4.5%, Sun 9.1%. This replication
(one KPI, 22 samples/weekday) is smaller than the evaluation's original probe
(120 slice-days x 2 KPIs, which found Sat 11/42 vs 0-1 on other weekdays), so
the skew here is noisier, but it points the same direction: weekend days carry
more false alarms because the primary detector (`kpi_engine/detection/robust.py`)
is not weekday-aware yet (F-D1). Stage 2 fixes this.

EVT03 (a real -63.5% orders drop) and EVT06 (cold-snap revenue lift) are
recalled at or near 0 on revenue, matching the evaluation's finding that the
non-seasonal detector misses genuine large moves inside noisy weekly spread
(F-D2).

## Driver attribution (`--split all`)

- Case-level top-1 accuracy: **15.6%** (10/64 scored cases; excludes the
  decoy). Case-level top-3 accuracy: 25%.
- Event-level: the true driver ranks #1 on at least one labelled day for
  **2 of 5** real (non-decoy) events (EVT01 and EVT04 partially; EVT02, EVT03,
  EVT06 never). This matches the evaluation's "found the true driver as #1 at
  most once in 5 real events" finding (F-R2/F-R3): `stock_availability`
  (EVT03) can't be found because the current registry still maps `stockout`
  to the always-zero `lost_units_stockout` column (F-R1), and `price_discount`
  / `weather_temp` (EVT02/EVT06) aren't declared as candidate drivers at all
  yet (F-R4) — both fixed in Stage 1.
- Decoy confident-driver rate (EVT05): **100%** (12/12) — the ranker always
  surfaces a top driver (usually the mechanical `traffic_drop` component; see
  F-R2) even though nothing about EVT05 should look like a confident cause.
  Stage 3 (explained-movement ranking) and Stage 7 (Attribution Confidence)
  are what bring this down.

## Causal verification (`--split all`)

Every event's causal verdict is `NOT_ASSESSED` or `UNTESTABLE`; `SUPPORTED_CONDITIONAL`
is never produced (F-V1). This is expected until Stage 5 replaces the two
hard-coded designs in `kpi_engine/verification/registry.py` with automatic,
per-driver design generation.

## Confidence (`--split all`)

Overall confidence status distribution: `{"LOW": 215, "MODERATE": 15}`. `HIGH`
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
