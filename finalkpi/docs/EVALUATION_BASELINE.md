# Evaluation baseline: Stage 0 → Stage 1

Recorded by `tests/run_ground_truth_eval.py --split all|dev|holdout`, against
`data/labels/eval_cases.csv` (538 cases: 76 positive across the 6 events in
`data/ground_truth_events.csv`, 462 quiet negatives). Stage 0 numbers were
recorded on `fix/stage-00-ground-truth-eval-harness` (based on
`codex/team-handoff-20260926` HEAD `76f1d57`); Stage 1 numbers are recorded on
`fix/stage-01-data-contract-fixes` after IMPLEMENTATION_PLAN.md §1.1–§1.10
landed. See `IMPLEMENTATION_EVALUATION.md` for the narrative analysis these
numbers confirm, and `IMPLEMENTATION_PLAN.md` for what each stage does.

To reproduce either column: check out the relevant branch and run
`.venv/bin/python tests/run_ground_truth_eval.py --split all`. Full JSON +
markdown for `all`/`dev`/`holdout` splits is reproducible from the committed
script and label file; only the summary is captured below.

## Split sizes (unchanged by Stage 1 — same label file both columns)

| split | cases | positives (event_present) | decoy (EVT05) | negatives |
|---|---|---|---|---|
| all | 538 | 64 | 12 | 462 |
| dev (EVT01, EVT03, EVT04 + half of negatives) | 271 | 40 | 0 | 231 |
| holdout (EVT02, EVT05, EVT06 + other half of negatives) | 267 | 24 | 12 | 231 |

Per the plan's ground rules, thresholds and weights may only ever be tuned on
`dev`; `holdout` numbers are for reporting, never for choosing a threshold.

## Stage 1 at a glance: before → after (`--split all`)

| metric | Stage 0 | Stage 1 | moved because |
|---|---|---|---|
| `traffic_drop` appears in any ranking | yes (always #1) | **no — removed** | §1.4: deleted as a candidate driver everywhere; `mechanical_components` now blocks it from ever being re-added |
| `stock_availability` eligible during EVT03 | no (excluded `CONSTANT_SERIES`) | **yes — ranked #1 on 7/12 cases** | §1.1: `stockout` remapped from the always-zero `lost_units_stockout` to the real `stock_availability` column |
| `price_discount` eligible during EVT02 | not declared | **yes — ranked #1 on 12/12 cases** | §1.2: `price_discount`/`promo_flag`/`weather_temp` added as candidate drivers |
| Driver top-1 accuracy, any sign (case-level) | 15.6% (10/64) | **45.3% (29/64)** | net effect of §1.1/§1.2/§1.3 |
| Driver top-1 accuracy, direction-aware | 6.2% (4/64) | **42.2% (27/64)** | most of the Stage 1 gain is correctly signed, not just id-matched |
| Driver top-3 accuracy | 25.0% | **54.7%** | |
| Events with true driver #1 on any day (any sign) | 2 of 5 | **4 of 5** | only EVT06 (weather) still never wins #1 |
| Events with a direction-consistent #1 hit | 1 of 5 | **3 of 5** | |
| Decoy (EVT05) confident-driver rate | 100% (12/12) | 100% (12/12) — **unchanged** | correlational ranking still always surfaces a top "driver" regardless of whether the KPI moved; needs Stage 3/7 |
| Detection recall (all 5 real events) | unchanged | unchanged | Stage 2's job, not touched here |
| False-alarm rate on quiet negatives | 4.1% | 4.1% — **unchanged** | Stage 2's job, not touched here |
| Causal verdicts | `NOT_ASSESSED`/`UNTESTABLE` only | unchanged | Stage 5's job; the harness never supplies a `verification_design` |
| Overall confidence distribution | `{"LOW": 513, "MODERATE": 25}` | unchanged | `ConfidenceEngine.build_profile`'s driver-blind aggregation (F-C1) is Stage 7's job |

**Stage 1 acceptance criteria, verified directly** (see `tests/test_pipeline_regressions.py::test_stockout_driver_is_eligible_not_constant_series`
and the harness run below):
- `stock_availability` is eligible (ranked, not excluded) during EVT03 (South/Apparel, 2024-02-07: `ranked_drivers = ['stock_availability']`, all 6 other drivers excluded for unrelated reasons).
- `price_discount` is eligible during EVT02 (ALL/Home, 2023-10-30: `ranked_drivers = ['price_discount', 'promo_flag']`).
- `traffic_drop` appears in zero rankings (`grep -c traffic_drop` on the full harness JSON output is 0; it no longer exists in any registry YAML).

## Driver attribution, per event (`--split all`, excludes the EVT05 decoy)

| event | true driver (Stage 1 id) | top1 any-sign: before → after | top1 direction-aware: before → after | top3: before → after | top1-hit KPIs (Stage 1) |
|---|---|---|---|---|---|
| EVT01 (marketing cut) | `marketing_spend` | 0.5 → **0.167** | 0.0 → 0.0 | 0.667 → 0.667 | net_sales_revenue |
| EVT02 (flash discount) | `price_discount` | 0.0 → **1.0** | 0.0 → **1.0** | 0.0 → **1.0** | net_sales_revenue, orders, units_sold |
| EVT03 (stockout) | `stock_availability` | 0.0 → **0.583** | 0.0 → **0.583** | 0.0 → **0.583** | net_sales_revenue, orders, units_sold |
| EVT04 (checkout latency) | `checkout_latency` | 0.25 → **0.5** | 0.25 → 0.5 | 0.5 → 0.5 | conversion_rate, net_sales_revenue |
| EVT06 (cold snap) | `weather_temp` | 0.0 → 0.0 | 0.0 → 0.0 | 0.0 → 0.0 | — |

Notes on what moved and what didn't:

- **EVT01 got slightly *worse* on the naive (any-sign) metric (0.5 → 0.167),
  and stayed wrong-signed either way (0.0 direction-aware in both).** This
  is not a regression in the fix — it is `CorrelationalRanker` still ranking
  by raw marginal correlation magnitude (F-R3), now with **7** candidates
  competing instead of 5 (`price_discount`/`promo_flag`/`weather_temp` were
  added). More competing candidates changed which one happens to have the
  largest `|r|` on a given day; the underlying problem — a driver that never
  moved, or moved the wrong way, can still outrank the true cause — is
  exactly what Stage 3's explained-movement ranking (rank by `β × Δdriver`,
  require the driver to have actually moved) is for.
- **EVT02 and EVT03 go from "the true driver isn't even in the candidate
  list / is wrongly excluded" to "found on every labelled day."** These are
  the two events Stage 1 was explicitly scoped to fix (F-R1, F-R4), and nothing
  else about the ranking method changed for them.
- **EVT04 improves but is still incomplete**: `checkout_latency` now also
  wins on `net_sales_revenue` (previously conversion_rate only), but still
  never wins on `orders`/`units_sold`, where a different candidate (still not
  the true cause) has a larger marginal correlation on those specific days.
- **EVT06 (`weather_temp`) still never ranks #1.** `expected_direction_by_scope`
  now resolves correctly (verified directly — see
  `tests/test_ranking.py::test_expected_direction_by_scope_flags_direction_conflict_for_ranked_driver`),
  so a wrong-signed weather association would now be correctly flagged
  (`DIRECTION_CONFLICT`) rather than silently accepted. But that alone
  doesn't make it *win* the ranking — cold-snap Apparel sales still get
  outranked by another candidate's marginal correlation. Same root cause as
  EVT01: Stage 3 is required.

## Detection recall (`--split all`, event_present cases only) — unchanged, Stage 2's job

| event | true driver | recall | revenue-only recall |
|---|---|---|---|
| EVT01 (North/Electronics, marketing cut) | marketing_spend | 0.333 (4/12) | 0.75 (3/4) |
| EVT02 (ALL/Home, flash discount) | price_discount | 1.0 (12/12) | 1.0 (4/4) |
| EVT03 (South/Apparel, stockout) | stock_availability | 0.25 (3/12) | 0.25 (1/4) |
| EVT04 (ALL/ALL, checkout latency) | checkout_latency | 0.5 (8/16) | 0.5 (2/4) |
| EVT06 (ALL/Apparel, cold snap) | weather_temp | 0.0 (0/12) | 0.0 (0/4) |

(EVT05 is excluded from this table on purpose — see Decoy section.)

False-alarm rate on the 462 quiet negatives (3 KPIs x 154 slice-days):
**4.1%** overall (dev 5.2%, holdout 3.0%), identical to Stage 0 — Stage 1 made
no detection changes. By weekday (`all` split, 66 samples/weekday): Mon 3.0%,
Tue 4.5%, Wed 0.0, Thu 0.0, Fri 7.6%, Sat 4.5%, Sun 9.1%. By KPI: revenue 3.2%
(5/154), orders 5.8% (9/154), units 3.2% (5/154). Weekend days (Fri/Sat/Sun)
still carry more false alarms than midweek because the primary detector
(`kpi_engine/detection/robust.py`) is still not weekday-aware (F-D1) — that is
Stage 2's job. EVT03 (a real -63.5% orders drop) and EVT06 (cold-snap revenue
lift) are still recalled at or near 0 on revenue (F-D2), also Stage 2.

## Decoy (EVT05) — unchanged, still needs Stage 3/7

- 12 cases (4 on revenue). `event_present: false`: nothing about this period
  should look like a confidently-explained real movement.
- False-alarm rate: **0.0** on all 3 KPIs, including revenue-only — unchanged.
- **Confident-driver rate: 100%** (12/12), unchanged — the ranker still
  surfaces a top-ranked "driver" every time regardless of whether the KPI
  moved. Stage 3 (explained-movement ranking, which requires the KPI to have
  actually moved) and Stage 7 (Attribution Confidence, gated on movement
  materiality) are what bring this down.

## Causal verification (`--split all`) — unchanged, Stage 5's job

Every event's causal verdict is still `NOT_ASSESSED` or `UNTESTABLE`;
`SUPPORTED_CONDITIONAL` is never produced (F-V1). The harness calls
`run_diagnosis` without a `verification_design`, so this is expected until
Stage 5 replaces `kpi_engine/verification/registry.py`'s (now corrected, but
still only 1 hard-coded) design with automatic, per-driver design generation.
Stage 1 did fix the registry's one remaining design (§1.8): it now uses
`marketing_spend` with a real Monday treatment start (2023-07-17) and its
`target_date`/`post_end` key moved to 2023-08-13; the broken Saturday-start
`traffic_drop` design was deleted outright rather than repaired.

## Confidence (`--split all`) — unchanged, Stage 7's job

Overall confidence status distribution: `{"LOW": 513, "MODERATE": 25}`,
identical to Stage 0. `HIGH` is never reached (F-C2) and the distribution
barely moves between cases with very different underlying evidence, because
`ConfidenceEngine.build_profile` still does not consult the driver or causal
dimensions in a discriminating way (F-C1) — Stage 1 did not touch
`kpi_engine/confidence.py`. No numeric score or Brier/reliability metric
exists yet (F-C5) — Stage 7 introduces per-driver Attribution Confidence and
the calibration harness (`--calibrate`) that will fill in
`confidence.brier_score` here.

## What Stage 1 actually changed (mechanism, not just numbers)

- **F-R1**: every registry YAML's `stockout` driver (column
  `lost_units_stockout`, constant 0 on all 8,880 rows) is replaced by
  `stock_availability` (column `stock_availability`, real signal down to
  0.15 during EVT03).
- **F-R4**: `price_discount`, `promo_flag` (units_sold/orders/net_sales_revenue/
  conversion_rate) and `weather_temp` (all 5 KPIs) are declared as candidate
  drivers, with corresponding `kpi_engine/query/source_catalog.yaml` field
  entries and `kpi_engine/action.py` lever-catalog entries.
- **F-R5**: every driver declares `expected_direction` (or, for `weather_temp`,
  `expected_direction_by_scope: {category: {Apparel: negative}}`, resolved by
  `CorrelationalRanker._resolve_expected_direction`). Renamed
  `ad_spend_drop`→`marketing_spend`, `checkout_latency_spike`→`checkout_latency`,
  `competitor_price_cut`→`competitor_price_index`; `LEGACY_DRIVER_IDS` in
  `kpi_engine/contracts/registry.py` resolves the old spelling for historical
  callers (e.g. `quantify_scenario`).
- **F-R2** (first half): `traffic_drop` deleted from every KPI's
  `candidate_drivers`. A new load-time contract validation
  (`KPIContract.mechanical_components`, enforced in
  `kpi_engine/contracts/models.py::validate_grain`) now hard-fails registry
  loading if any candidate driver's column is the KPI's value/numerator/
  denominator/decomposition column, or is listed in `mechanical_components`
  (`traffic_online`/`traffic_instore`/`traffic_wholesale` for the three sales
  KPIs) — so this specific bug cannot silently come back.
- **F-A2**: `kpi_engine/contracts/semantic.py`'s driver projection no longer
  falls back to the KPI's own owner; `kpi_engine/action.py`'s owner
  resolution order (driver YAML owner → lever-catalog owner → `"analyst"`)
  now actually reaches the lever catalog instead of always hitting the
  driver-YAML branch with an inherited KPI owner.
- **F-P4**: `backend/app.py`'s `ChatRequest.persona` now defaults to `None`
  instead of `"CFO"`, so a non-CFO caller that omits `persona` is resolved
  from `user_id` instead of rejected.
- **F-C4** (`verify_event` half): `verify_event` now accepts
  `approved_causal_design` and sets `_causal_design_approved`, mirroring
  `run_diagnosis`, so an approved event verification's causal confidence
  dimension is no longer forced to `NOT_ASSESSED` regardless of what the
  causal test actually found.
- **F-V1** (registry half): the broken `traffic_drop`/Saturday-start designs
  in `kpi_engine/verification/registry.py` are gone; the `marketing_spend`
  design uses a real Monday treatment start and the corrected cut date.
- **F-S4**: a category-restricted demo identity/role
  (`category_manager_north_electronics`, North/Electronics only) is added to
  `data/access_control.csv`, `backend/service.py::DEMO_IDENTITIES` and
  `backend/domain_policy.py`, with a new `category-restricted-scope` demo
  scenario asserting North/Home is denied.
- **F-D5**: the `non-material-baseline` demo scenario moved from
  2023-08-13 (the actual last day of EVT01) to 2023-05-22 (a Monday, verified
  `NO_MATERIAL_MOVEMENT`, well clear of every event window).

## What this baseline is, and is not

- It is a **synthetic-dataset regression baseline**: `data/ground_truth_events.csv`
  and `data/labels/eval_cases.csv` are built from the six events the dataset
  generator (`data/fix_dataset.py`) injected, per Stage 0 of the implementation
  plan — not from independent human review. `kpi_engine/evaluation.py`'s
  stricter "independently reviewed labels" path (`tests/run_labeled_evaluation.py`)
  is unaffected and remains the path for real calibration once analyst
  verdicts exist (Stage 9).
- The recommended holdout-fixture injection (plan Stage 0, item 3) remains
  unimplemented, as noted when Stage 0 shipped; still optional, still future
  work.
- The direction-aware expected-sign map (`EXPECTED_DIRECTION_SIGN` in
  `tests/run_ground_truth_eval.py`) predates and anticipated Stage 1's
  `expected_direction` values; now that the registry declares them for real,
  a future cleanup could read them from `contract_snapshot` instead of
  duplicating them in the harness, but the two are currently kept in sync by
  inspection (both encode plan §1.2/§1.3's table) and this file's direction-aware
  numbers were cross-checked directly against `ranked_drivers[0]["direction"]`
  above.
