# BusinessIntelligence.ai: Staged Implementation Plan

**For:** the coding agent that will implement the fixes
**Base branch:** `codex/team-handoff-20260926` (HEAD `76f1d57`)
**Companion document:** `IMPLEMENTATION_EVALUATION.md` has the evidence behind every finding. Finding IDs such as `F-R1` refer to that document.
**Requirements source:** `round2_brief.pdf` Problem Track 3 and Round 1 Problem 3 (both PDFs are in the repo root).

---

## 0. How to use this plan

### 0.1 Ground rules for the implementing agent

1. **Work one stage at a time**, in the order in §2. Each stage ends in a working app with all tests green. Do not start stage N+1 until stage N meets its acceptance criteria.
2. **Branching:** make one branch per stage from the previous stage's branch, named `fix/stage-XX-<slug>`. Make one or more commits per stage. Do not force-push the handoff branch.
3. **Keep the good guardrails.** The LLM must never become the source of quantitative truth. Access checks must stay fail-closed. The narrative claim-validation layer (`kpi_engine/narrative.py:validate`) must keep rejecting unsupported claims. Weaken a guardrail only when this plan says so explicitly.
4. **You may change tests, data and contracts.** When a test encodes behaviour this plan says is wrong (for example, "overall is MODERATE" or "traffic_drop ranks first"), update its expected values and say why in the commit message. Do **not** delete a test just to make a stage pass. Replace it with a test of the corrected behaviour.
5. **Bump `ENGINE_VERSION`** (`backend/service.py:51`) in every stage that changes engine output. Diagnosis runs are cached by this string (`find_diagnosis_run`). Without a bump, the UI will serve stale results and you will think your fix did not work. Also delete `backend/runtime/kpi_backend.sqlite3` locally when testing.
6. **Test commands** (all must pass at the end of every stage):
   ```bash
   .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
   .venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'
   (cd frontend && npm test && ./node_modules/.bin/tsc --noEmit --incremental false)
   .venv/bin/python tests/run_ground_truth_eval.py        # created in Stage 0
   ```
7. **Update docs as you go:** `docs/METHODOLOGY_AND_DATASET.md`, `docs/TEAM_HANDOFF.md` (test counts) and the `# IMPLEMENTATION HANDOFF` header comment of every module you touch.
8. **Data is synthetic and yours to fix.** `kpi_dataset.csv` and `ground_truth_events.csv` (the inputs to `data/fix_dataset.py`) are missing, so **do not rerun `fix_dataset.py`**. Make every data change through a new deterministic, idempotent patch script in `data/patches/` and commit both the script and the resulting CSVs.

### 0.2 Stage map

| Stage | Title | Main findings addressed | Depends on |
|---|---|---|---|
| 0 | Ground-truth evaluation harness and baseline | F-C5, housekeeping | none |
| 1 | Data and contract corrections, quick bug fixes | F-R1, F-R2 (part), F-R4, F-R5, F-A2, F-P4, F-C4, F-S4, F-D5 | 0 |
| 2 | Movement detection and prioritisation | F-D1, F-D2, F-D3, F-D4 | 1 |
| 3 | Driver attribution engine (explained movement) | F-R2, F-R3, F-R6, F-R7, F-R8 | 2 |
| 4 | Source reconciliation that actually runs | F-C3 | 1 |
| 5 | Causal verification that can succeed | F-V1 – F-V6 | 3 |
| 6 | Unstructured evidence and RAG pipeline | F-U1, F-U2, F-P3, chat grounding | 3 |
| 7 | Confidence model, including per-driver **attribution confidence** | F-C1, F-C2, F-C4, new requirement | 3, 4, 5, 6 |
| 8 | Persona narratives and action recommendations | F-P1, F-P2, F-A1, F-A2, F-A3 | 7 |
| 9 | Feedback learning that closes the loop | F-L1 | 7, 8 |
| 10 | Frontend integration and UX pass | all UI surfaces | 1–9 (incrementally) |
| 11 | Security, performance, hardening, docs, final evaluation | F-S1 – F-S4, F-SC1, housekeeping | all |

Stages 2 and 4 are independent of each other. Stage 4 can be done any time after Stage 1. Each stage lists its own frontend changes. Stage 10 is a final consistency pass, not the only frontend work.

---

## 1. Target architecture (how it is supposed to work end to end)

```
            ┌──────────────── as-of cutoff applied to every source ───────────────┐
sales_daily ─┐                                                                     │
marketing_wk ┼─► normalize/align ─► reconcile (closed or MTD snapshot) ─► source dim │
finance_mo ──┘         │                                                           │
                       ▼                                                           │
            detect (weekday-aware robust + MSTL) ─► materiality (abs AND rel) ─► movement dim
                       │                                   │
                       │                       scan all slices ─► priority feed
                       ▼
            WHERE: funnel/accounting bridge  (traffic × conversion × AOV; volume/mix/rate)
                       ▼
            WHY:  explained-movement attribution over exogenous/controllable drivers
                  (joint robust regression → β, Δdriver, contribution, share, residual)
                       ▼
            TEST: auto-generated, persisted causal design for top drivers
                  (validated controls / synthetic control, log DiD, placebo)
                       ▼
            CORROBORATE: scoped, as-of-filtered unstructured evidence (tickets/news/promo)
                       ▼
            CONFIDENCE: per-driver Attribution Confidence (0–100 %, band, breakdown)
                        + movement/source/attribution/causal dims → overall = weakest required
                       ▼
            ACT: persona-specific narrative (validated claims) + action cards
                 driver → lever → action → expected impact → owner → confidence → monitoring
                       ▼
            LEARN: analyst verdicts on drivers → labelled store → gated recalibration
```

The user-facing output answers two questions, each with its own confidence:

1. **"Is this movement real and material?"** Movement and source evidence.
2. **"Why did it happen, and how sure are we about each reason?"** Per-driver Attribution Confidence (the new requirement, §Stage 7).

---

## Stage 0: Ground-truth evaluation harness and baseline

### Current status

- There is no committed labelled set. `tests/run_labeled_evaluation.py` expects a CSV that does not exist, and `ground_truth_events.csv` is missing.
- We cannot measure detection recall, false alarms, driver accuracy or calibration, so no stage can prove it helped.

### What to change

1. **Create `data/ground_truth_events.csv`** using the event definitions in `data/fix_dataset.py` (lines 188–240):

   | event_id | region | category | start_date | end_date | true_driver_ids | direction | is_decoy |
   |---|---|---|---|---|---|---|---|
   | EVT01 | North | Electronics | 2023-07-20 | 2023-08-13 | ad_spend_drop | -1 | false |
   | EVT02 | ALL | Home | 2023-10-28 | 2023-11-06 | price_discount | +1 | false |
   | EVT03 | South | Apparel | 2024-02-05 | 2024-02-16 | stock_availability | -1 | false |
   | EVT04 | ALL | ALL | 2024-05-15 | 2024-05-18 | checkout_latency_spike | -1 | false |
   | EVT05 | East | Electronics | 2024-07-14 | 2024-07-29 | (none) | 0 | true |
   | EVT06 | ALL | Apparel | 2023-04-11 | 2023-04-23 | weather_temp | +1 | false |

   The driver IDs `price_discount`, `stock_availability` and `weather_temp` are introduced in Stage 1.

2. **Create `data/labels/eval_cases.csv`** with one row per `(case_id, kpi_id, date, region, category, event_present, true_driver_id, split, reviewer)`:
   - Positives: 3–4 dates inside each event window for the KPIs the event affects (revenue, orders and units for all; conversion_rate for EVT04).
   - Negatives: at least 150 random quiet slice-days outside every window (fixed seed), spread evenly across weekdays.
   - Split: `dev` for EVT01, EVT03, EVT04 and half the negatives; `holdout` for EVT02, EVT06, EVT05 and the other half. Weights and thresholds may only be tuned on `dev`.

3. **(Recommended) Add holdout events that were never seen during tuning.** Write `data/patches/inject_holdout_events.py`. It writes a **separate** dataset to `data/eval_fixtures/holdout_v1/` (a copy of the three source CSVs with 3–4 injected events in unused slice/period combinations, for example a West/Home stockout and a South/Electronics latency spike). Record their labels in `data/eval_fixtures/holdout_v1/labels.csv`. This protects against overfitting to 6 events.

4. **Create `tests/run_ground_truth_eval.py`** (turn the probes from the evaluation into a script). It runs the pipeline over `eval_cases.csv` and prints JSON plus a markdown table with:
   - detection: recall per event, false-alarm rate on negatives, false alarms per weekday
   - attribution: top-1 and top-3 driver accuracy on positives, and the decoy rate (EVT05 must not produce a confident driver)
   - causal: verdict per event (from Stage 5 on)
   - confidence: Brier score and reliability bins for Attribution Confidence (from Stage 7 on)
   - `--split dev|holdout|all` and `--fail-under` thresholds so it can gate CI

5. **Add `tests/test_ground_truth_smoke.py`.** It runs a tiny subset (about 6 cases), asserts the harness runs, and records current baseline numbers. Later stages tighten these assertions.

6. **Housekeeping:** fix the test counts in `docs/TEAM_HANDOFF.md`. Stop tracking the stray root `chroma.sqlite3` (`git rm --cached`, add it to `.gitignore`). Make `kpi_engine/feedback.py` default to a runtime directory rather than `data/feedback_log.jsonl`.

### Acceptance criteria

- `run_ground_truth_eval.py --split all` runs end to end, and the baseline numbers are recorded in `docs/EVALUATION_BASELINE.md`. They should roughly match the evaluation: top-1 driver ≈ 0–1 of 5, Saturday false-alarm spike, revenue recall 0/3 on EVT03 and EVT06.
- The existing test suites still pass.

---

## Stage 1: Data and contract corrections, quick bug fixes

These are small, high-leverage changes. Most are YAML or one-line fixes.

### 1.1 Stockout driver reads a column that is always zero (F-R1)

- **Current:** `stockout → lost_units_stockout`, which is 0 on all 8,880 rows. The driver is always `CONSTANT_SERIES` and DiD returns `NO_EXPOSURE_CONTRAST`.
- **Change:** in every `kpi_engine/registry/*.yaml`, replace `stockout` with:
  ```yaml
  - {id: stock_availability, display_name: Stock availability, unit: share_in_stock, controllability: controllable,
     column: stock_availability, source: sales_daily, grain: daily, aggregation: mean,
     expected_direction: positive, allowed_lags: [0,1,2,3], min_pairs: 14, minimum_coverage: 0.6}
  ```
  Optionally add a data patch (`data/patches/derive_lost_units.py`) that fills `lost_units_stockout` from availability (for example, `baseline_units × (1 − availability)`) so the column means something. Rename the action-catalog key in `kpi_engine/action.py:LEVERS` accordingly.

### 1.2 Missing drivers (F-R4)

Add these to the relevant contracts:

| id | column | applies to | expected_direction | controllability |
|---|---|---|---|---|
| `price_discount` | `price_discount_depth` | units_sold, orders, net_sales_revenue, conversion_rate | positive (units/orders/conv); positive for revenue in this dataset | controllable |
| `promo_flag` | `promo_flag` | same as above | positive | controllable (binary; treat as event indicator) |
| `weather_temp` | `weather_temp_c` | all sales KPIs | **scope-dependent** (see below) | contextual |

- Add optional `expected_direction_by_scope` to the driver schema (parse it in `kpi_engine/contracts/registry.py`, validate it in `contracts/models.py`). Example: `{category: {Apparel: negative}}`, meaning colder weather means more apparel sales. The ranker resolves the effective direction for the requested slice. If there is no scope rule and no default, the direction is `null` and the driver is **flagged, not ranked as confident**.
- Add lever-catalog entries in `action.py` for `price_discount` / `promo_flag` (Pricing/Promotions, `pricing_lead`) and `weather_temp` (contextual: "adjust inventory and merchandising plans", `merchandising_lead`, advisory only).

### 1.3 Declare the expected direction for every driver (F-R5)

| driver | expected_direction (for revenue/orders/units) |
|---|---|
| ad_spend_drop (rename to `marketing_spend`) | positive |
| checkout_latency_spike (rename to `checkout_latency`) | negative |
| competitor_price_cut (rename to `competitor_price_index`) | positive (their price up → our sales up) |
| stock_availability | positive |
| price_discount, promo_flag | positive |

Driver IDs describe **the variable**, not the event. The old IDs (`ad_spend_drop`, …) bake in a direction, which caused sign confusion. Keep a mapping `LEGACY_DRIVER_IDS` in `contracts/registry.py` so saved runs and feedback records still resolve.

### 1.4 Remove funnel components from the driver lists (F-R2, first half)

- **Current:** `traffic_drop` (`traffic_online`) is a candidate driver for revenue, orders and units. It is a mechanical component and wins every ranking.
- **Change:** delete `traffic_drop` from `candidate_drivers` in `net_sales_revenue.yaml`, `orders.yaml` and `units_sold.yaml`. Traffic stays a **KPI** (`traffic_total`) and becomes a **bridge component** in Stage 3. For `traffic_total` itself, add `marketing_spend` (already present), `promo_flag` and `weather_temp` as drivers.
- Add a registry validation rule: a candidate driver's column must not be the KPI's value, numerator, denominator or decomposition component (`quantity_column`), and must not appear in a new contract field `mechanical_components: [...]`. Fail loading the contract if one does.

### 1.5 Action owner mapping (F-A2)

- **Current:** `semantic.py:156` fills each driver's `owner` with the **KPI** owner, and `action.py:_build_card` prefers it. A marketing lever therefore goes to `regional_manager` or `ops_lead`.
- **Change:** in `semantic.py`, only emit a driver `owner` when the YAML driver entry declares one (no fallback to `contract.owner`). In `action.py`, resolve the owner in this order: driver YAML `owner` → lever catalog owner → `"analyst"`. Add `owner` to each driver in the YAMLs (for example, `marketing_spend: marketing_lead`, `checkout_latency: engineering_lead`).

### 1.6 Chat persona default blocks non-CFO users (F-P4)

- **Current:** `backend/app.py:60` sets `persona: str = "CFO"`, so a marketing or regional user who omits `persona` gets a 403.
- **Change:** use `persona: Optional[str] = None`. `_persona()` already resolves the persona from `user_id`.

### 1.7 `verify_event` never marks the design approved (F-C4, bug part)

- In `pipeline.py:verify_event`, add `approved_causal_design: bool = False` and set `result["_causal_design_approved"] = approved_causal_design`, mirroring `run_diagnosis`. The Stage 7 confidence rewrite handles the missing `movement_assessment` in this path.

### 1.8 Fix or retire the broken governed designs (F-V1, first half)

- `verification/registry.py` currently has `ad_spend_drop` with `treatment_start 2023-07-01` (a Saturday and the wrong date) and `traffic_drop` (a driver removed in §1.4).
- **Change for now:** change the marketing design to `driver_id: marketing_spend, pre_start: 2023-06-05, treatment_start: 2023-07-17` (the Monday of the cut week), `post_end: 2023-08-13`, keeping the South control for the moment. Delete the `traffic_drop` design. Stage 5 replaces this registry with auto-generated designs.

### 1.9 Access-control scenario with category restriction (F-S4)

- Add a role to `data/access_control.csv`: `North,category_manager_north_electronics,Electronics`. Add a matching demo identity in `backend/service.py:DEMO_IDENTITIES` and domain entitlements in `backend/domain_policy.py` (`SALES`, `MARKETING`, `KPI_CONTRACT`, `CHAT_EVIDENCE`).
- Add a demo scenario `category-restricted-scope`: this identity requests North/Home and must get `ACCESS_DENIED`.

### 1.10 Demo scenario inside a real event (F-D5)

- `backend/demo_scenarios.py` `non-material-baseline` uses 2023-08-13, the last day of EVT01. Change it to a verified quiet date (pick one from the Stage 0 negatives that returns `NO_MATERIAL_MOVEMENT`, for example a Tuesday in September 2023). Update `backend/tests/test_demo_scenarios.py`.

### Tests to update or add in Stage 1

- Tests referencing `traffic_drop` (listed by our scan): `tests/test_ranking.py`, `test_narrative.py`, `test_verification.py`, `test_confidence.py`, `test_pipeline_regressions.py`, `test_contribute.py`, `test_rag_fallback.py`, `backend/tests/test_feedback_*.py`, `test_offline_learning.py`, and `frontend/tests/driver-analysis.test.js`, `feedback-learning.test.js`. Switch fixtures to the new driver IDs.
- New tests:
  - Registry rejects a mechanical-component driver.
  - `expected_direction_by_scope` resolves correctly.
  - Stockout on 2024-02-07 South/Apparel is **not** excluded as `CONSTANT_SERIES`.
  - Chat without `persona` works for `demo-marketing`.
  - `verify_event` with an approved design produces a causal dimension other than `NOT_ASSESSED`.

### Acceptance criteria

- The harness shows `stock_availability` is eligible during EVT03 and `price_discount` is eligible during EVT02.
- `traffic_drop` no longer appears in any ranking.
- All suites are green, and `ENGINE_VERSION` is bumped.

---

## Stage 2: Movement detection and prioritisation

### Current status (F-D1 – F-D4)

- The primary detector (`detection/robust.py`) uses a 60-day rolling median/MAD that ignores the weekday. Saturdays produced 11 of 42 false alarms on quiet days (other weekdays 0–1), and the wide weekly spread hid a −63% orders drop (EVT03) and a −62% revenue drop (EVT04 North/Electronics).
- Materiality is one absolute number per KPI (500 INR), no matter the slice size.
- Nothing scans across slices; the user must pick a region, category and date.

### How it is supposed to work

- **Expected value:** the median of the **same weekday** over the last `k = 8` weeks, using data available as of the cutoff (as-of safe). If fewer than 4 same-weekday points exist, fall back to a weekday-adjusted median: overall median × weekday factor estimated on the available history.
- **Scale:** robust MAD of the *weekday-adjusted residuals* (`value − same-weekday expectation`) over the last 60–90 days.
- **Point score:** `(actual − expected) / scale`. **Sustained score:** the median of the last `seasonal_period` residuals divided by the scale, as now.
- **Materiality** requires **both**:
  - statistical: `|score| ≥ z_threshold`
  - business: `|delta| ≥ abs_threshold` **and** `|delta| / |expected| ≥ rel_threshold`. Add `rel_threshold` to every contract (for example, 0.10 for revenue/orders/units, 0.10 relative for conversion). `abs_threshold` becomes an optional floor.
- **The MSTL detector stays as the second opinion.** `detector_agreement` is unchanged. The primary detector is now weekday-aware, so "BOTH" should become common for genuine events.
- **Priority score** for ranking movements: `priority = |delta_in_currency_or_units| × min(|score| / z_threshold, 3) × kpi_weight`, where `kpi_weight` is set in the contract (revenue 1.0, orders 0.8, units 0.6, conversion 0.8 × revenue-per-point, traffic 0.5). Revenue-equivalent impact comes from the contract (`impact_to_revenue: {method: aov|value_per_visit}`) so different units can be compared.

### What to change

- `kpi_engine/detection/robust.py`: implement the weekday-aware expectation and scale. Keep `calculate_robust_dispersion` for the residual scale. Keep the payload fields and add `expected_method: SAME_WEEKDAY_MEDIAN|WEEKDAY_ADJUSTED`, `rel_delta`, `rel_threshold`.
- `kpi_engine/contracts/metrics.py` (`prepare_metric_request` / `ComparisonPlan`): the baseline frame must hold the same-weekday history the detector uses. **The decomposition must use the same baseline** (it currently uses the arithmetic mean of all baseline days). Make `ComparisonPlan` expose `expected_value` and the baseline rows, and have both detection and decomposition consume them.
- Contracts: add `rel_threshold` and `kpi_weight`. Keep the thresholds `PROVISIONAL`, but tune `z_threshold` / `rel_threshold` **on the dev split only**.
- **New service `kpi_engine/scan.py`: `MovementScanner.scan(date, persona, kpis, slices)`.** It runs detection only (fast path, no attribution) for every authorised `(kpi, slice)` on the date, then returns movements sorted by priority with `is_material`, `priority`, `delta`, `rel_delta` and `detector_agreement`. It must respect `AccessController` (only authorised slices) and include ALL-region / ALL-category rollups where the persona is entitled.
- **New route `GET /api/movements?date=&user_id=&kpis=`** (add it to the frontend gateway `ALLOWED_ROOTS`). Also replace `build_marketing_brief`'s 2/1/0 bucket ordering with the priority score.
- **Frontend:** add a "Top movements today" feed on the Overview page (`frontend/app/page.tsx`), sorted by priority. Clicking an item opens that slice's diagnosis.

### Tests

- Unit tests:
  - A synthetic series with strong weekday seasonality: an ordinary Saturday is not material, and a Saturday with a −40% drop is material.
  - `rel_threshold` gating.
  - As-of safety: future rows do not change expectations.
- Update `tests/test_detection.py`, `test_pipeline_regressions.py` and the demo scenarios whose verdict changes. Re-verify each demo scenario's intent and move dates where needed.
- Harness gates, dev and holdout both:
  - quiet-day false alarms no worse than the 4.1% baseline (`--split all`; see docs/EVALUATION_BASELINE.md) — this stage must not regress it, whatever the weekday-aware detector's absolute rate turns out to be
  - the maximum weekday false-alarm rate ≤ 2× the minimum non-zero weekday rate (or ≤ 3 absolute alerts)
  - event-day recall ≥ 70% for revenue/orders/units, **including** EVT03 (stockout) and EVT04
  - EVT03 (stockout, South/Apparel) revenue recall ≥ 70% (Stage 0/1 baseline: 25%, 1/4)
  - EVT06 (cold snap, ALL/Apparel) revenue recall ≥ 70% (Stage 0/1 baseline: 0%, 0/4)
  - the EVT05 decoy may flag `traffic_total` (traffic did rise) but not revenue

---

## Stage 3: Driver attribution engine (explained movement)

This is the core of the "driver rankings" problem.

### Current status (F-R2, F-R3, F-R6, F-R7, F-R8)

- `CorrelationalRanker` ranks by `|r| × coverage × sample × stability`: correlation of first differences over 120 days. It is **independent of what happened on the target day**. `driver_change_pct` is computed but unused.
- Drivers are ranked one at a time; correlated drivers are double-counted.
- The stability check compares nested windows that share 80% of their data, so it is almost always `STABLE`.
- There are no p-values, no multiple-testing correction, and no contribution in KPI units. `ShapleyContributor` is never called.

### How it is supposed to work

The diagnosis first answers **WHERE** (an accounting bridge) and then **WHY** (driver attribution).

**Step A. WHERE: the funnel/accounting bridge (deterministic).**

- Revenue: `revenue = traffic × conversion × AOV` (conversion = orders / traffic, AOV = revenue / orders). Use a 3-factor exact Shapley log-decomposition (or reuse the `DeterministicDecomposer` permutation approach) between the baseline (same-weekday expected components) and the target, plus the existing segment mix bridge when slicing by fewer dimensions.
- Orders: `orders = traffic × conversion`. Units: `units = orders × units_per_order`.
- Output `funnel_bridge: {components: [{name, baseline, actual, effect, share}], identity_held: true}`.
- This replaces the old `traffic_drop` "driver". The narrative says, for example, "Of the −1,364 INR, traffic explains −X, conversion −Y, basket size −Z." It is labelled `ACCOUNTING_NOT_CAUSAL`.

**Step B. WHY: explained-movement attribution (statistical).** Add a new module `kpi_engine/attribution.py` with an `AttributionEngine` class.

1. **Prepare series at the driver's native grain** (reuse the ranker's alignment logic: weekly dedup, complete-week checks, monthly handling, as-of filtering).
2. **Deseasonalise** the KPI and each driver the same way as detection (subtract the same-weekday expectation for daily series; for weekly series, subtract the median of the prior 8 weeks).
3. **Fit a joint model on the history window** (default 180 days, **excluding the target period and the preceding `max_lag` days** so the event cannot fit itself):
   `KPI_residual_t = Σ_d β_d · driver_residual_{d, t−lag_d} + ε`
   - Choose each driver's lag **once**, on the history window (not on the target day), from `allowed_lags`, using the best out-of-sample fit on a time-series split. Report every lag tried and apply a Benjamini–Hochberg correction across drivers × lags for the reported p-values.
   - Use Huber-robust regression, or OLS with HAC standard errors (`statsmodels`, already a dependency), on **standardised** drivers. With more than 4 drivers or collinearity (VIF > 5), use ridge with a small penalty and report `collinearity_warning`.
   - Mixed grains: fit daily drivers on daily data, and weekly drivers in a separate weekly model (the KPI aggregated to weeks). Take the weekly contribution for the target week and pro-rate it to the target day by the KPI's weekday profile, labelling it `grain_adjusted: true`. Monthly drivers are contextual only (not used in contribution) unless the target is a month.
4. **Measure each driver's movement on the target period at its lag:** `Δd = driver_value(t − lag) − driver_expected(t − lag)` and `z_Δd = Δd / driver_scale`.
5. **Contribution:** `c_d = β_d · Δd` (in KPI units), with interval `[β_lo · Δd, β_hi · Δd]` (95% interval).
6. **Explained share:** `s_d = c_d / ΔKPI`, where ΔKPI = actual − expected from detection. `residual = ΔKPI − Σ c_d`, reported explicitly.
7. **Ranking:** order by `c_d` in the direction of ΔKPI (drivers pushing the same way as the movement, largest first). Drivers pushing the opposite way are listed as **offsetting drivers**. Drivers that did not move (`|z_Δd| < 1.5`) are listed as **"did not move"** exclusions. This is the key behaviour change: a driver that did not change cannot explain the change.
8. **Diagnostics per driver:**
   - `direction_consistent` (the sign of β against the contract's `expected_direction`)
   - `temporal_precedence` (the driver's residual crossed its threshold before or on the KPI's onset date)
   - `stability`: β estimated on two **disjoint** halves of the history window. STABLE if the signs agree and the ratio is within [0.5, 2].
   - `p_value_adj`, sample size, coverage
9. **Keep backward-compatible payload keys** (`driver_analysis.ranked_drivers[*]` with `rank`, `driver_id`, `display_name`, …) and add: `contribution`, `contribution_interval`, `explained_share`, `driver_change`, `driver_change_z`, `beta`, `beta_ci`, `p_value_adj`, `offsetting: bool`, `moved: bool`, `method: "JOINT_ROBUST_REGRESSION_EXPLAINED_MOVEMENT"`. Keep `claim_boundary` text, updated to: *"Statistical attribution of observed movement; causal status is shown separately."*
10. **Wire Shapley properly (F-R8):** when the model has interactions or is non-linear (optional), compute the per-driver allocation with `ShapleyContributor`, using coalition values from the fitted model (drivers set to baseline vs actual). For the linear model, the Shapley values equal `c_d`, so assert that equality in a test. Document it.
11. **Retire `CorrelationalRanker` as the primary method.** Keep it as a diagnostic (`driver_analysis.association_diagnostics`) or delete it along with its tests. Either is fine; update `processing_transparency` to name the new method.

**Step C. Edge cases (explicit statuses, never silent):**

- Sparse history: fewer than `min_history_periods` points in the fit window → `INSUFFICIENT_HISTORY` for attribution (the movement can still be reported).
- Driver missing on the target period at its lag → `SOURCE_UNAVAILABLE` (this already exists; keep it).
- ΔKPI not material → attribution still runs but is labelled `EXPLORATORY_NON_MATERIAL`, and the narrative does not present drivers as explanations.
- Reconciliation `CONTRADICTED` → `BLOCKED` (keep).

### Files

`kpi_engine/attribution.py` (new), `kpi_engine/decompose.py` (funnel bridge), `kpi_engine/pipeline.py` (call the bridge and the attribution engine and replace the `ranker.evaluate_candidates` calls in both `run_diagnosis` and `verify_event`), `kpi_engine/contribute.py` (Shapley hook), `kpi_engine/processing_transparency.py`, `kpi_engine/narrative.py` (new claim types `FUNNEL_BRIDGE` and `ATTRIBUTED_DRIVER`, validated; see Stage 8), `kpi_engine/action.py` (read the new fields).

### Frontend (part of this stage)

- `frontend/lib/driver-analysis.ts` and `components/driver-analysis-workspace.tsx`: rename the card to "What explains the change". Show per driver: contribution (KPI units, with interval), explained share %, driver change (value and %), lag, direction check, stability, adjusted p-value. Show the residual ("unexplained"), and list offsetting and "did not move" drivers.
- A new component `components/funnel-bridge.tsx`: a waterfall of traffic, conversion and AOV effects, plus mix. Use the `dataviz` guidance if the implementer has it.
- Update `frontend/tests/driver-analysis.test.js`.

### Tests

- Synthetic unit test (`tests/test_attribution.py`) with known β: KPI = 2·A − 3·B + noise. The event moves A only. A must rank first, B must be "did not move", the contributions must sum to ≈ ΔKPI, and the residual must be small.
- Collinearity test: A and A' are nearly identical. Expect a warning, no double counting, and a stable total.
- Future-row invariance: appending rows after the cutoff changes nothing.
- Linear-model Shapley equals `c_d`.
- Harness gates:
  - **top-1 driver accuracy ≥ 4 of 5 real events** (EVT01 marketing_spend, EVT02 price_discount or promo_flag, EVT03 stock_availability, EVT04 checkout_latency, EVT06 weather_temp) on revenue or units, on at least one in-window day each
  - EVT05 decoy: no driver's explained share ≥ 50% with a same-direction contribution on revenue

---

## Stage 4: Source reconciliation that actually runs

### Current status (F-C3)

- Closed-period mode needs `target_date == month_end` **and** `as_of ≥ month_end + 5 days`. The default `as_of` is target + 1.5 days, so the comparison returned `NOT_AVAILABLE_FOR_PERIOD` on 96 of 96 weekly dates. That status lowers the source dimension to LOW, so revenue, the only reconciled KPI, is almost always LOW, while unreconciled KPIs are "HIGH".
- The `snapshot` (MTD) mode exists but is unused, and finance rows carry no coverage-end date for the provisional month.

### How it is supposed to work

- **Status semantics:**
  - `PENDING_CLOSE`: new. The comparator exists but its period is not yet due as of the cutoff. **Neutral** for confidence, the same as `NOT_APPLICABLE`.
  - `NOT_AVAILABLE_FOR_PERIOD`: the comparator is overdue or missing (for example, as_of > closes_at and still no row). Lowers confidence.
  - `AGREED`, `DRIFT`, `CONTRADICTED`: unchanged.
- **MTD snapshot mode (default for mid-month dates):** use the latest finance row available at the cutoff for the target month (closed or provisional). Compare it with sales summed from the month start through the finance row's **coverage end date**, not through the target date. Tolerance: the contract's `tolerance_pct` for closed rows and a separate `provisional_tolerance_pct` (for example, 5%) for provisional rows.
- **Closed-period mode** is still used when the month is closed at the cutoff.

### What to change

- Data patch `data/patches/add_finance_coverage.py`: add `coverage_end` and `available_at` to `finance_monthly.csv`. Closed rows: `coverage_end = month_end`, `available_at = closes_at`. Provisional rows: `coverage_end = snapshot_date − 6 days` (per the data README), `available_at = snapshot_date`. Add **monthly provisional snapshots for every historical month** (for example, a snapshot on day 15 covering through day 9, with `revision` 1 and the closed row as revision 2) so MTD reconciliation has data mid-month across history. Keep the rows deterministic, and make them match sales exactly (or within a small realistic timing gap).
- `kpi_engine/reconcile.py`: implement the status logic and MTD comparison above. Use `_select_latest_revision` at the cutoff (it already exists).
- `kpi_engine/normalize.py`: keep the finance `available_at` filter and carry `coverage_end` and `revision` through.
- Contract `net_sales_revenue.yaml`: `mode: auto` (closed if available, else MTD snapshot), `provisional_tolerance_pct: 5.0`. Add a reconciliation block to `units_sold.yaml` too (finance has `units_sold`), so a second KPI is reconciled.
- Keep the `contradictory-sources` demo fixture working. Its manifest should now also demonstrate MTD contradiction if needed.
- Frontend: `frontend/lib/evidence-helpers.js` / source evidence panel: show `PENDING_CLOSE` as neutral ("Finance close not due until <date>"), and show the MTD comparison window and snapshot revision.

### Tests

- Update `tests/test_reconciliation_semantics.py`, `backend/tests/test_source_evidence.py` and `frontend/tests/source-evidence.test.js`.
- New tests:
  - A mid-month date returns `AGREED` via MTD using a provisional snapshot.
  - A mid-month date with no snapshot yet returns `PENDING_CLOSE`.
  - A date overdue with no row returns `NOT_AVAILABLE_FOR_PERIOD`.
  - A revised snapshot uses the latest revision at the cutoff.
- Harness: for revenue, at least 70% of dates return `AGREED` / `DRIFT` / `PENDING_CLOSE` rather than `NOT_AVAILABLE_FOR_PERIOD`.

---

## Stage 5: Causal verification that can succeed

### Current status (F-V1 – F-V6)

- There are only 2 hard-coded designs keyed by exact date. One is always `UNTESTABLE` (a Saturday start) and the other is `INCONCLUSIVE`. `SUPPORTED_CONDITIONAL` is never produced on real data.
- A correct EVT01 design is `REJECTED`, because the control region (South) ran its own campaign and DiD compares levels.
- Weekly-driver designs are `UNTESTABLE` at the default as-of (the last post week is not yet published).
- Causal tests only run on material alert days, are not linked to the ranked drivers, and `verify_sensitivity()` is unused.

### How it is supposed to work

**5.1 Automatic, persisted design generation (`kpi_engine/verification/designer.py`, new)**

For each of the top-K (default 2) attributed drivers with explained share ≥ 20% from Stage 3:

1. **Treatment onset:** the first date in a 42-day lookback where the driver's deseasonalised residual crosses `1.5 × scale` in the driver's own movement direction and stays there for at least 3 of the next 5 periods. For weekly drivers, the onset is the week start, and the outcome's treatment start is the same Monday. If no onset is found, return `UNTESTABLE / NO_ONSET_DETECTED`.
2. **Pre period:** `[onset − 42 days, onset − 1]` (minimum 21 days). **Post period:** `[onset, min(target_date, onset + 27 days)]`.
3. **Candidate controls:** every other slice the persona is authorised to see (other regions in the same category first, then the same region in other categories).
4. **Control validity gates** (a control is kept only if all pass):
   - Driver stability: the control's own driver change over the same pre/post windows is ≤ 25% of the treated change, in relative terms.
   - Pre-period fit: the correlation of log outcomes in the pre period is ≥ 0.6.
   - No labelled event: no `ground_truth_events` row or detected material driver movement in the control during the window. (Use only detection outputs at run time; the labels file is for evaluation, never runtime.)
5. **Estimator:** DiD on **log outcome** against the average of valid controls. If 3 or more controls are valid, use a **synthetic control** (non-negative weights summing to 1, fitted on the pre period with `scipy.optimize.nnls` or simple constrained least squares; add `scipy` to `pyproject.toml` if needed). Keep HAC standard errors.
6. **Placebo:**
   - In time: rerun the **same estimator** with a fake onset in 2–3 quiet pre windows.
   - In space: treat each valid control as the "treated" unit.
   - Placebo p-value = the rank of |treated effect| among all placebo effects.
7. **Verdict:**
   - `SUPPORTED_CONDITIONAL`: CI excludes 0 **and** the effect has the expected sign **and** placebo p ≤ 0.1 **and** the pretrend test passes.
   - `REJECTED`: the estimate has the opposite sign and its CI excludes 0.
   - `INCONCLUSIVE`: otherwise.
   - `UNTESTABLE`: when no valid control, onset or coverage exists, with a reason code.
8. **Persist the design before running** (this makes it predeclared). Add a table `verification_designs` in `backend/storage.py` holding `design_id`, `created_at`, `generator_version` and a hash of the design. The result references `design_id`. A design with the same hash is reused, never regenerated with different windows (this prevents p-hacking).
9. **Sensitivity:** run `verify_sensitivity()` across the valid-control subsets and 2 pre-window lengths. Report `CONSISTENT_CONDITIONAL` / `SENSITIVE`. A `SUPPORTED` verdict that is `SENSITIVE` is downgraded to `INCONCLUSIVE` in the confidence model.

**5.2 Fix the verifier plumbing**

- `did.py`: add a log-outcome option (the default for additive KPIs; ratio KPIs use logit or level). The `min_*` policies come from the contract's `verification_policy` block.
- **As-of buffer for weekly drivers:** exposure uses the latest **available** complete weeks. The post period ends at the last published week, and the outcome post window is truncated to match (`post_end_effective`). Report `truncated_for_availability: true` instead of returning `INCOMPLETE_DRIVER_EXPOSURE`.
- Run causal verification for **any date inside a detected sustained movement**, not only on single-day material alerts. In `pipeline.py`, run the designer when `assessment.is_material` **or** `assessment.pattern == "SUSTAINED"`.
- `registry.py`: keep it only as an **override** list of human-declared designs (validated the same way). The designer is the default.
- Every result carries `design_id`, `driver_id` (from the attributed ranking), `controls_used`, `control_weights`, `controls_rejected` (with reasons) and `placebo_p_value`.

**5.3 Authorisation:** controls are chosen only from slices the persona is allowed to see (this matches the current `CONTROL_NOT_AUTHORIZED` rule). If none are allowed, return `UNTESTABLE / NO_AUTHORIZED_CONTROL`, and the narrative says a wider-scope analyst could run the test.

### Frontend

- `components/confidence-workspace.tsx` (or a new `causal-test-card.tsx`): per tested driver, show the design (onset, windows, controls with weights, rejected controls and why), the effect with CI (as %), the placebo p-value, the sensitivity status and the verdict with plain-language meaning.

### Tests

- Update `tests/test_verification.py`, which encodes `COARSE_TREATMENT_TIME` for the old design.
- Synthetic test: a treated unit with a known step effect and 3 clean controls → `SUPPORTED`. A contaminated control is rejected by the gate. A no-effect case → `INCONCLUSIVE` with a high placebo p. A wrong-direction case → `REJECTED`.
- Harness gates:
  - EVT01 (marketing_spend, North/Electronics) → `SUPPORTED_CONDITIONAL` (South must be rejected as a control by the driver-stability gate; East or West used instead)
  - EVT03 (stock_availability) → `SUPPORTED_CONDITIONAL`
  - EVT05 decoy → not `SUPPORTED`
  - a wrong-driver design (competitor price on EVT01) → not `SUPPORTED`
  - EVT04 (ALL/ALL) → `UNTESTABLE / NO_VALID_CONTROL` is acceptable (all regions were treated); the narrative must say why

---

## Stage 6: Unstructured evidence and RAG pipeline

### Current status (F-U1, F-U2, F-P3)

- `unstructured_evidence.csv` is never ingested. `retrieval.ingest_documents()` and `retrieve_relevant_documents()` are never called, and `corroborate.py` is dead code.
- `ingest_kb()` writes to `backend/data/chroma` but `ContextBuilder` reads `CHROMA_DIR` (`backend/runtime/chroma`), so the chat's collection is empty. The indexed contract text uses keys that do not exist.
- Vector retrieval has no region/category filter, and its as-of filter reads a field (`timestamp`) that the evidence rows do not set, so scope and future-time leaks are latent.
- Chat LLM answers are not validated (numbers or causal words could be invented). The no-LLM fallback does not answer "why", and "next month" questions are not declined.

### How it is supposed to work

**6.1 One evidence store, one path**

- A single config `CHROMA_DIR` used by **both** ingest and retrieval (`backend/ingest.py` must honour `config.CHROMA_DIR`). One collection per corpus: `kb_contracts`, `kb_methodology`, `kb_evidence`.
- Ingest `unstructured_evidence.csv` into `kb_evidence` with metadata: `doc_id`, `date` (ISO), `available_at` (add the column through a data patch: the same day, 18:00), `region`, `category`, `source_type`, `access_tags` (for example, `sales`, `marketing`, `operations`, `finance`; add a column), and `driver_tags` (add a column mapping each doc to driver IDs, for example TCK-1001 → `marketing_spend`).
- Fix contract ingestion to read the real YAML keys (`display_name`, `definition`, `formula`, `aggregation`, `materiality`, `candidate_drivers`, `owner`).
- Ingest runs at startup **and** is idempotent (upsert by `doc_id`). `/health` reports real `retrieval_ready` and document counts.
- **Enlarge the corpus** (data patch): add about 20 more docs, including **distractors** (irrelevant notes, a doc from another region on the same date, a future-dated doc that must never appear, and a doc containing a prompt-injection string). This lets the scope, as-of and injection tests mean something.

**6.2 Engine corroboration (deterministic, part of diagnosis)**

- Rewrite `kpi_engine/corroborate.py` as `EvidenceCorroborator`:
  - Retrieval filters (mandatory): `available_at ≤ as_of`; `date ∈ [target − 21 days, target]` (no future docs); `region ∈ {slice region, ALL}`; `category ∈ {slice category, ALL}`; `access_tags ⊆ persona entitlements`.
  - Matching: by `driver_tags` first, then keyword/semantic similarity to the driver's `evidence_keywords` (a new optional contract field per driver, for example `marketing_spend: [budget, campaign, paid search, spend]`).
  - Output per driver: `corroboration: {status: CORROBORATED|CONTRADICTED|NONE, documents: [{doc_id, date, source_type, snippet, match_reason}]}`. `CONTRADICTED` applies when a doc explicitly says the driver was not the issue (for example "not a tracking issue" for instrumentation). Keep it simple: a per-doc `stance` column in the data patch (`supports` / `refutes` / `neutral`).
  - Document text is **untrusted**. It is fenced and never interpreted as instructions, and it never changes numbers or statuses. It only feeds the corroboration evidence item in Stage 7.
- Pipeline: run it after attribution, attach it to each ranked driver, and cite it in the narrative (new claim type `CORROBORATION`, validated against `doc_id` existence).

**6.3 Chat (RAG) fixes (`backend/rag_pipeline.py`, `backend/retrieval.py`)**

- `retrieve_vector_chunks`: apply the same mandatory filters (scope, as-of, access tags), using Chroma `where` for exact fields and post-filtering for date comparisons.
- **Answer validator** (new `backend/answer_guard.py`), applied to every LLM answer before it is returned:
  - Every number in the answer must appear in the context (diagnosis JSON values or retrieved snippets), within rounding tolerance.
  - Causal verbs (`caused`, `due to`, `because of`, …) are allowed only when the cited driver's Attribution Confidence band is ≥ MODERATE, or its causal verdict is `SUPPORTED_CONDITIONAL`. Otherwise, rewrite the answer to hedged wording or fall back.
  - Citations must reference IDs actually present in the context (this is partly done; keep it).
  - On failure, return the deterministic fallback with `limitations` explaining why.
- **Deterministic fallback improvements:**
  - "Why…" questions answer with the funnel bridge plus the top attributed drivers, each with its contribution, share and Attribution Confidence %, plus corroborating documents.
  - Forecast or future questions ("next month", "will", "forecast") are declined explicitly: "This engine explains observed movements; it does not forecast."
  - Detected prompt-injection or out-of-scope requests (a small regex/keyword list plus the router intent) get an explicit refusal, not the full narrative.
- Persona-aware answer depth (reuse the Stage 8 persona config).

### Frontend

- A new evidence panel `components/corroboration-panel.tsx` under each driver: document cards (type icon, date, source, snippet, "supports / refutes").
- Chat: render citations for evidence docs (doc_id, date, type), and show "Declined: forecasting is out of scope" styling.

### Tests

- `backend/tests/test_rag_scope.py`:
  - A North user never receives South docs.
  - A 2023 diagnosis never receives a 2024 doc.
  - A marketing persona does not receive `finance`-tagged docs.
  - An injection doc's instructions are not followed.
- `tests/test_corroboration.py`: EVT01 North/Electronics 2023-07-24 → `marketing_spend` CORROBORATED by TCK-1001. EVT03 → `stock_availability` CORROBORATED by TCK-3001. The EVT05 decoy's doc (PROMO-5001) is found, but the attribution does not support the driver (checked in Stage 7).
- Answer-guard tests: an invented number is rejected, and causal wording is rejected at LOW confidence.
- Update `tests/test_rag_fallback.py`.

---

## Stage 7: Confidence model, including per-driver Attribution Confidence

### Current status (F-C1, F-C2, F-C4, and the new requirement)

- The overall status is **MODERATE in all 96 tested combinations** once movement and source pass. The driver dimension is never consulted, a causal `REJECTED` does not lower it, and `HIGH` is unreachable dead code (`confidence.py:356–370`).
- `verify_event` results always show causal `NOT_ASSESSED` and overall `INSUFFICIENT_EVIDENCE`.
- No numeric score is produced anywhere.
- **New requirement:** confidence must say *how confident we are that this particular driver caused the KPI change*.

### 7.1 Per-driver Attribution Confidence (AC): design

**Definition:** for each attributed driver *d* of a movement, **AC_d is the estimated probability that *d* is a genuine cause of a material share of this movement**. "Material share" means at least 20% of ΔKPI in the movement's direction. AC is a number in [0, 1], shown as a %, with a band and a full breakdown.

**Model:** a transparent evidence-weighted log-odds model (naive-Bayes style), later calibrated on labelled data.

```
logit(AC_d) = logit(prior_d) + Σ_i w_i · e_i(d)        then clamp by hard caps
```

| # | Evidence item e_i | Computation (from earlier stages) | Initial weight / values (tune on dev split) |
|---|---|---|---|
| E0 | Prior | `prior_d = 1 / (number of eligible moved drivers + 1)` (the +1 is "other/unknown cause"). A contract may override it per driver (`attribution_prior`). | n/a |
| E1 | Explained share | `s_d = c_d / ΔKPI`, clipped to [0, 1.5] | +2.0 × min(s_d, 1) ; −1.5 if s_d < 0.1 |
| E2 | Driver actually moved | `|z_Δd|` | +0.8 if ≥ 3 ; +0.4 if ≥ 2 ; −2.0 if < 1.5 (normally excluded already) |
| E3 | Direction consistent with contract | β sign against `expected_direction` | +0.5 consistent ; −2.5 conflict ; 0 if undeclared (and cap 0.6) |
| E4 | Temporal precedence | driver onset ≤ KPI onset | +0.5 before ; 0 coincident ; −1.5 driver moved **after** the KPI |
| E5 | Stability (disjoint halves) | Stage 3 | +0.3 STABLE ; −0.7 SENSITIVE |
| E6 | Statistical support | `p_value_adj` of β | +0.5 if < 0.01 ; +0.2 if < 0.05 ; −0.5 if ≥ 0.2 |
| E7 | Causal test (Stage 5) | verdict × sensitivity | SUPPORTED & CONSISTENT: +2.0 ; SUPPORTED & SENSITIVE: +0.8 ; INCONCLUSIVE: −0.3 ; REJECTED: −3.0 ; UNTESTABLE / not run: 0 |
| E8 | Unstructured corroboration (Stage 6) | status | CORROBORATED: +1.0 ; CONTRADICTED: −1.5 ; NONE: 0 |
| E9 | Data quality | coverage ratio and source dimension | −0.5 if coverage < 0.8 ; −1.0 if source dimension LOW |

**Hard caps and gates** (applied after the sigmoid, recorded as `caps_applied`):

- Source reconciliation `CONTRADICTED` → AC not computed; status `BLOCKED`.
- Movement not material → AC capped at 0.5 and labelled `EXPLORATORY`.
- **No causal test result (E7 = 0)** → AC capped at **0.75**. Without an experimental or quasi-experimental check, we never claim "very likely".
- Causal `REJECTED` → AC capped at **0.20**.
- Direction undeclared → AC capped at 0.60.
- Sparse history (< `min_history_periods`) → AC not computed; status `INSUFFICIENT_HISTORY`.

**Bands:**

| AC | Band | Plain-language label |
|---|---|---|
| ≥ 0.80 | HIGH | "Very likely a cause" |
| 0.60 – 0.79 | MODERATE | "Likely a contributing cause" |
| 0.35 – 0.59 | LOW | "Possible; needs verification" |
| < 0.35 | VERY_LOW | "Unlikely to explain this change" |

**Output per driver** (add to each `driver_analysis.ranked_drivers[*]`, **and** a new top-level `attribution_confidence` list):

```json
{
  "driver_id": "marketing_spend",
  "attribution_confidence": 0.74,
  "band": "MODERATE",
  "label": "Likely a contributing cause",
  "prior": 0.25,
  "evidence": [
    {"id": "E1", "name": "explained_share", "value": 0.62, "weight_contribution": 1.24, "note": "Explains 62% of the −1,364 INR drop"},
    {"id": "E7", "name": "causal_test", "value": "SUPPORTED_CONDITIONAL/CONSISTENT", "weight_contribution": 2.0},
    {"id": "E8", "name": "corroboration", "value": "CORROBORATED", "weight_contribution": 1.0, "doc_ids": ["TCK-1001"]}
  ],
  "caps_applied": [],
  "model_version": "attribution-confidence-v1",
  "calibration": {"status": "CALIBRATED_ON_SYNTHETIC_LABELS", "n_cases": 0, "brier": null, "split": "dev"}
}
```

- The **unexplained residual** also gets a row: `driver_id: "unexplained"`, AC = `1 − max(AC_d)` share-weighted. This makes the ambiguity visible when nothing explains the change.
- **Ambiguity rule (brief R2-5, "abstain when contradictory"):** if the top two drivers have AC within 0.1 of each other and both are ≥ 0.5, or if the top driver's AC < 0.35, set `attribution_status = AMBIGUOUS` or `NO_CONFIDENT_DRIVER`. The narrative then **asks a clarifying question** (for example, "Was there a pricing change or a stock issue in South/Apparel that week?") and captures the answer as feedback in Stage 9. This also satisfies "requests clarification or abstains".

**Calibration:**

- `kpi_engine/attribution_confidence.py` holds the weights in a versioned file `kpi_engine/models/attribution_confidence_v1.yaml` (weights, caps, bands, version).
- `tests/run_ground_truth_eval.py --calibrate` fits the weights by L2-regularised logistic regression on the **dev** split (a label is 1 when the driver is the event's true driver, 0 for other drivers and for decoy/negative cases). Starting from the hand weights above as priors, it writes `attribution_confidence_v2.yaml` with the Brier score, log-loss, and reliability bins on **holdout**.
- The UI shows the calibration status. It must never say "calibrated on real data".

### 7.2 Overall confidence: fix the aggregation (F-C1, F-C2)

Replace `ConfidenceEngine.build_profile`'s overall logic with a **weakest-required-dimension** rule over an ordered scale:

`CONFLICTING_EVIDENCE < INSUFFICIENT_EVIDENCE < LOW < MODERATE < HIGH`

- The dimensions become:
  - `movement` (unchanged logic, with Stage 2 inputs)
  - `source` (Stage 4 semantics; `PENDING_CLOSE` and `NOT_APPLICABLE` are neutral)
  - **`attribution`** (replaces `driver`): the band of the top driver's AC, mapped HIGH → HIGH, MODERATE → MODERATE, LOW → LOW, VERY_LOW / NO_CONFIDENT_DRIVER → INSUFFICIENT_EVIDENCE, AMBIGUOUS → LOW
  - `causal`: the top driver's test verdict. SUPPORTED & CONSISTENT → HIGH; SUPPORTED & SENSITIVE → MODERATE; INCONCLUSIVE → LOW; REJECTED → CONFLICTING_EVIDENCE; not run or UNTESTABLE → `NOT_ASSESSED` (not required)
- Present **two headline answers**:
  - `overall.movement_conclusion = min(movement, source)`: "Is the change real?"
  - `overall.explanation_conclusion = min(movement, source, attribution, causal_if_assessed)`: "Do we know why?"
  - `overall.status = explanation_conclusion` when the movement is material, else `movement_conclusion`.
- `HIGH` must be reachable: movement HIGH, source HIGH, attribution HIGH (which needs a supported causal test, because of the cap).
- `CONFLICTING_EVIDENCE` if the source is contradicted **or** the top driver's causal test is REJECTED and there is no other driver with AC ≥ 0.6.
- Keep `pipeline.py:240`, which clears action cards on `CONFLICTING_EVIDENCE`. It now fires correctly.
- `verify_event` path: movement is `NOT_ASSESSED` there (event mode), so the overall status = `explanation_conclusion` computed without the movement dimension.
- **Keep the old `confidence` key** (`EvidenceQualityAssessment`) for compatibility, but mark it deprecated in the payload (this is already done via `confidence_deprecated`).

### Files

`kpi_engine/attribution_confidence.py` (new), `kpi_engine/models/attribution_confidence_v1.yaml` (new), `kpi_engine/confidence.py` (rewrite `build_profile`), `kpi_engine/pipeline.py` (call order: attribution → causal → corroboration → AC → profile), `kpi_engine/narrative.py` (claims cite AC), `backend/response_projection.py` (AC evidence is visible to all personas entitled to the diagnosis; hide `doc_ids` from personas without the doc's access tag), `kpi_engine/processing_transparency.py` (add a stage `attribution_confidence`, type `STATISTICAL_MODEL`).

### Frontend

- `lib/confidence-profile.ts` and `components/confidence-workspace.tsx`:
  - Headline: two answers ("Is the change real?" and "Do we know why?").
  - A **per-driver confidence bar** (0–100%) with band colour, plain label, and an expandable evidence breakdown. Use a horizontal "tug-of-war" view: which evidence items pushed the value up or down, and which caps applied.
  - Show the calibration status text.
  - Remove the "Not calibrated / score null" copy for AC; keep it for dimensions that remain categorical.
- Update `frontend/tests/confidence-profile.test.js`.

### Tests

- `tests/test_confidence.py`: rewrite.
  - A table-driven test proving that **each of the 5 overall statuses is reachable**.
  - A REJECTED top driver with no alternative → CONFLICTING_EVIDENCE.
  - No driver → INSUFFICIENT_EVIDENCE.
  - A cap at 0.75 without a causal test.
  - A cap at 0.20 when REJECTED.
  - Monotonicity: adding corroboration never lowers AC.
- `tests/test_attribution_confidence.py`: the arithmetic of the log-odds sum, caps and bands; loading a model version; `AMBIGUOUS` and `NO_CONFIDENT_DRIVER` rules.
- Update tests asserting `MODERATE` (listed by our scan: `test_action.py`, `test_chat_storage.py`, `backend/tests/test_domain_projection.py`, `test_demo_scenarios.py`, `test_offline_learning.py`, `test_feedback_api.py`, `test_feedback_proposals.py`, and `frontend/tests/confidence-profile.test.js`, `feedback-learning.test.js`).
- Harness gates:
  - mean AC of true drivers minus mean AC of false drivers ≥ 0.30 on holdout
  - EVT05 decoy: max AC < 0.5
  - Brier score on holdout reported and ≤ 0.20
  - the `low-confidence-abstention` demo scenario still abstains (now through `NO_CONFIDENT_DRIVER` / `AMBIGUOUS` plus a clarifying question)

---

## Stage 8: Persona narratives and action recommendations

### Current status (F-P1, F-P2, F-A1, F-A2, F-A3)

- The narrative is identical for the CFO, marketing manager and regional manager. Persona only affects field redaction and a "Financial review:" prefix. The UI persona selector only offers CFO and marketing.
- The LLM only selects between 1–2 pre-written variants.
- Action cards: at most 1 per run, `expected_impact` is always `null`, owners are wrong (fixed in Stage 1), and evidence refs are mislabelled.

### How it is supposed to work

**8.1 Persona configuration.** A new directory `kpi_engine/personas/` with one YAML per persona (`cfo.yaml`, `marketing_manager.yaml`, `regional_manager.yaml`, `category_manager.yaml`). Each defines:

- `claim_order` and `claim_depth` (which claim types to include and in what order). For example:
  - CFO: movement, **revenue-equivalent impact**, reconciliation, funnel bridge, top drivers with AC, actions requiring budget approval.
  - Marketing: movement, funnel bridge (traffic/conversion), marketing, promo and pricing drivers first, campaign actions.
  - Regional: movement, stock, latency and ops drivers first, region-specific actions.
- `driver_priority` (which lever families to surface first)
- `units_display` (currency vs operational units)
- `allowed_action_levers`, and `approval_threshold` (the impact above which approval is required)
- `delivery_channel` (dashboard, `email_digest` or `alert`)
- `summary_length` (short/long)

**8.2 Narrative engine (`kpi_engine/narrative.py`).**

- `_claims(payload, persona_cfg)` builds claims from the persona config. Every claim is still validated by `validate()`, so persona changes **ordering, selection and wording templates**, never facts.
- New claim types:
  - `FUNNEL_BRIDGE`
  - `ATTRIBUTED_DRIVER` ("{driver} explains about {share}% ({contribution} {unit}); attribution confidence {AC}% ({label})")
  - `CAUSAL_TEST`
  - `CORROBORATION` ("Supported by {doc_type} {doc_id} on {date}")
  - `CLARIFICATION_REQUEST`
  - `IMPACT` (revenue-equivalent, CFO only)
- Causal-language control: wording like "likely caused by" is allowed **only** for drivers with AC band ≥ MODERATE **and** a causal verdict of SUPPORTED. Wording like "associated with" is used otherwise. Enforce this in `validate()`.
- **LLM role (F-P2):** when a key is configured, the LLM rewrites the validated claim list into fluent persona-appropriate prose, via the `rewrite` method. The output then passes a **round-trip check**:
  - every number in the prose must match a number in the claims
  - no new entities
  - causal verbs obey the AC rule
  - every claim's key fact appears
  If any check fails, fall back to the deterministic template text. Record `llm_status` and tokens (telemetry already exists).
- A deterministic persona template set exists for every claim type, so the demo works without a key.

**8.3 Action recommendations (`kpi_engine/action.py`).** The full chain is: driver → lever → action → expected impact → owner → confidence → monitoring.

- One card per attributed driver with `AC ≥ 0.35` and `controllability == controllable`, up to 3. Contextual drivers (weather, competitor) produce **advisory** cards (for example, "adjust inventory plans") with `kind: ADVISORY`.
- `kind`:
  - `ACTION_PROPOSAL` when AC ≥ 0.6 and causal is SUPPORTED
  - `VERIFY_THEN_ACT` when AC ≥ 0.6 without a causal test
  - `NEXT_CHECK` when AC is between 0.35 and 0.6
  - no card below 0.35. Instead, one `EVIDENCE_COLLECTION` card, plus the clarification question.
- **Expected impact (F-A1):** `recoverable_impact = −c_d` over the review window (the per-day contribution × the remaining days of the driver's deviation, or 7 days by default), with an interval from the β CI. Label it `impact_method: "ATTRIBUTED_CONTRIBUTION_X_WINDOW"`, carry `impact_confidence = AC_d`, and add a revenue-equivalent figure for the CFO. If AC < 0.6, show the impact as a range with the note "not validated".
- Owner from Stage 1. `decision_right` and `approval_required` come from the persona config (`approval_threshold`).
- `monitoring_plan`: `{metric: driver column and KPI, success_criterion: "driver back within 1 scale of expected and KPI residual > −X", review_date, stop_conditions}`.
- Fix the evidence-reference labels: `evidence_type` must match the path.
- Persona filters: `allowed_action_levers` decides which cards each persona sees (for example, the CFO sees all cards, with budget cards flagged for approval).

**8.4 Backend.**

- `SUPPORTED_PERSONAS` = `CFO`, `marketing_manager`, `regional_manager_*` (resolved by identity), `category_manager_north_electronics`. `/api/filters` returns the personas available to the current identity.
- `build_marketing_brief` → rename it to `build_persona_brief(persona)`. Stories and summary come from the persona config, and ordering comes from the Stage 2 priority.

### Frontend

- Persona selector: add Regional manager (North) and Category manager. Header copy per persona (`app/page.tsx:444`, `:510` are hard-coded to CFO/marketing).
- `components/action-workspace.tsx`: multiple cards, impact with range, AC chip, kind badge, owner, approval badge, monitoring plan, stop conditions.
- Narrative block: render claims with inline citation chips (evidence path / doc_id).

### Tests

- `tests/test_narrative.py`:
  - The same payload yields **different claim sets and order** for CFO vs marketing vs regional.
  - All claim sets pass `validate()`.
  - Causal wording is rejected when AC is LOW.
  - The LLM rewrite round-trip rejects a changed number (use the existing injectable `llm_client`).
- `tests/test_action.py`: impact computation, kinds by AC thresholds, persona lever filtering, owner resolution.
- `backend/tests`: the persona brief differs by persona, and the regional persona is visible in filters only to its identity.

---

## Stage 9: Feedback learning that closes the loop

### Current status (F-L1)

There is a solid governance workflow (capture → aggregate → proposal → accept → candidate → evaluate → rollback), but everything is `evaluation_only` and `deployed: False`. The only supported candidate types are `EVALUATION_CASE_ADDITION` and `NARRATIVE_TEMPLATE_CHANGE`. Nothing changes engine behaviour.

### How it is supposed to work

1. **Driver verdict feedback (new, first-class):** on each attributed driver, an analyst can mark "confirmed cause / not the cause / partially / unsure", with an optional comment and an optional pointer to another driver. Store it in a new table `driver_verdicts` (`run_id`, `driver_id`, `verdict`, `user_id`, `persona`, `created_at`). This produces **real labels** for AC calibration, merged with the synthetic labels and weighted.
2. **Clarification answers** (from the Stage 7 `CLARIFICATION_REQUEST`) are stored as feedback and, when confirmed by a CFO/reviewer, become `driver_verdicts`.
3. **New proposal types** in `backend/feedback_learning.py` and `offline_learning.py`:
   - `THRESHOLD_CHANGE`: z/rel thresholds for a KPI, triggered when false-alarm or missed-event feedback aggregates.
   - `DRIVER_PRIOR_CHANGE`: the per-driver `attribution_prior` in the contract, from verdict statistics.
   - `ATTRIBUTION_MODEL_RECALIBRATION`: refit the AC weights on the dev labels plus reviewed verdicts.
   - `DRIVER_ADDITION` (proposal only; a human edits the YAML).
4. **Gate:** each candidate is evaluated with `run_ground_truth_eval.py` logic on the holdout split plus the saved runs. It is accepted only if metrics do not regress (detection F1, top-1 accuracy, Brier) and every guardrail test passes.
5. **Deploy (new):** `POST /api/improvement-proposals/{id}/deploy` (CFO only, after the state is `VERIFIED`). It writes a **new contract version** (`version: N+1`, which changes the contract hash, so the cache invalidates automatically) or a new `attribution_confidence_vN.yaml`, and records it in an append-only `deployments` table with a rollback pointer. Rollback restores the previous version. The live engine loads the latest deployed version.
6. **UI:** the feedback review workspace shows metric deltas before and after, with a Deploy / Rollback control.

### Tests

- End-to-end backend test: submit 5 "not the cause" verdicts for driver X in a slice → a DRIVER_PRIOR_CHANGE proposal → accept → evaluate (gate passes) → deploy → the next diagnosis shows the new contract version and a lower AC for X → rollback restores it.
- A gate-failure test: a candidate that worsens holdout Brier cannot be deployed.

---

## Stage 10: Frontend integration and UX pass

By now each stage has shipped its own UI pieces. This stage makes them coherent. Target layout of the diagnosis view, in order:

1. **Headline:** what changed (value, delta, % vs same-weekday expected), with two confidence answers: "Is it real?" and "Do we know why?".
2. **Where it changed:** the funnel/accounting bridge waterfall, and the mix by segment.
3. **Why it changed:** attributed drivers, each with contribution, share, **Attribution Confidence bar**, causal test chip, corroborating docs, plus an "Unexplained" row and offsetting drivers.
4. **What to do:** action cards (persona-filtered) with impact range, owner, approval and monitoring.
5. **Evidence and lineage:** source freshness, reconciliation (MTD / closed / pending), processing transparency (LLM vs non-LLM), telemetry.
6. **Assistant:** chat with citations, and the clarification prompt when attribution is ambiguous.
7. **Overview page:** the "Top movements today" priority feed (Stage 2).

Also:

- Accessibility: colour plus a text label for every band, keyboard navigation for expandable evidence.
- Remove stale copy that says "Association only - not contribution or causation" where it is no longer true. Replace it with accurate boundary text per section.
- `frontend/app/jury/page.tsx` and `tests/run_jury_review.py`: update the jury walkthrough so each Round 2 minimum expectation maps to a screen (use the checklist in `IMPLEMENTATION_EVALUATION.md` §7).
- Run `npm test`, `tsc` and `next build` (build in CI or a temp clone, not committed).
- Gateway `frontend/app/api/backend/[...path]/route.ts`: add the new roots (`movements`, `driver-verdicts`, the deploy route under `improvement-proposals`), and add `DELETE` only if a route needs it.

---

## Stage 11: Security, performance, hardening, docs, final evaluation

### Security

- **F-S1:** keep demo identities, but put them behind a single `IdentityProvider` interface (`backend/identity.py`): `DemoIdentityProvider` (the current behaviour, clearly labelled `DEMO_SIMULATED` in every response) and a documented stub `JwtIdentityProvider` (verifies a bearer token, maps claims to persona and scope). Read identity from the `Authorization` header when present. The Next gateway forwards that header (currently it forwards only Content-Type).
- **F-S2:** hide reconciliation gap and totals from personas without the FINANCE domain (show status only). Update `response_projection.project_diagnosis` and its tests.
- **F-S3:** optionally return 403 for `ACCESS_DENIED` diagnoses on the API, with the same body. Coordinate with the frontend, which currently expects 200. If you change it, update `test_row_authorization.py`.
- Scope, as-of and injection tests from Stage 6 must be part of the default suite.
- Audit: log `DRIVER_VERDICT`, `PROPOSAL_DEPLOY` and `DESIGN_CREATE` events in the security audit chain.

### Performance and cost (R2-8)

- Cache the `KPIEnginePipeline` object and the parsed source frames per `source_data_version` (an LRU keyed by file hash and mtime). Avoid re-reading the CSVs for each KPI in `diagnose_scope`. Use the existing `QueryService` / DuckDB path for loading.
- Trim the `/api/diagnoses` response: it is currently about 385 KB for 5 KPIs. Move large diagnostics (lag trials, raw inputs) behind `/api/diagnoses/{run_id}/evidence` and return summaries by default.
- Telemetry: add stages for `attribution`, `causal_design`, `corroboration`, `attribution_confidence`, and a per-insight cost roll-up (`cost_per_insight_usd`). Record one run with an LLM key and save the telemetry JSON as a jury artefact (`docs/telemetry_sample.json`).
- Latency budget: at most 2 s per 5-KPI diagnosis without the LLM, and at most 5 s with it (the causal designer may run async or only for the top 2 drivers). Add a simple timing test with a generous bound.

### Docs and final evaluation

- Update `README.md`, `docs/METHODOLOGY_AND_DATASET.md` (new methods: weekday detection, funnel bridge, attribution regression, auto-designed DiD/synthetic control, Attribution Confidence model and calibration, MTD reconciliation), `docs/JURY_GUIDE_PLAIN_LANGUAGE.md` and `docs/TEAM_HANDOFF.md`.
- Regenerate `IMPLEMENTATION_EVALUATION.md` §2–§7 numbers with `run_ground_truth_eval.py --split all` and `--split holdout`, and add a before/after table.
- Final gate: every harness threshold from Stages 2, 3, 5 and 7 passes on **holdout**.

---

## Appendix A: Consolidated flaw register (status and owning stage)

| ID | Flaw (short) | Current status | Stage |
|---|---|---|---|
| F-R1 | Stockout driver column always 0 | Driver can never rank or be tested | 1 |
| F-R2 | Traffic (mechanical component) ranked as a driver | Wins every ranking | 1 (remove), 3 (bridge) |
| F-R3 | Ranking ignores the target-day movement | `driver_change_pct` unused | 3 |
| F-R4 | Discount/promo and weather drivers missing | 2 of 6 events unexplainable | 1 |
| F-R5 | No expected direction declared | Wrong-sign drivers ranked normally | 1, 3 |
| F-R6 | Nested stability window (80% overlap) | Almost always STABLE | 3 |
| F-R7 | No p-values or correction; marginal ranking; lag caps | Exploratory only | 3 |
| F-R8 | Shapley contributor unwired | No contributions | 3 |
| F-C1 | Overall confidence ignores driver and causal evidence | MODERATE in 96/96 combos | 7 |
| F-C2 | HIGH unreachable | Dead code | 7 |
| F-C3 | Reconciliation never runs; revenue always LOW | 96/96 NOT_AVAILABLE | 4, 7 |
| F-C4 | `verify_event` causal always NOT_ASSESSED | Flag not set | 1, 7 |
| F-C5 | No labels, no calibration | No numeric scores | 0, 7 |
| NEW | Per-driver "how sure is this driver the cause" | Missing | 7 |
| F-V1 | Two hard-coded designs, both unable to succeed | Never SUPPORTED | 1, 5 |
| F-V2 | Contaminated control; level DiD | EVT01 REJECTED | 5 |
| F-V3 | Weekly driver untestable at default as-of | INCOMPLETE_DRIVER_EXPOSURE | 5 |
| F-V4 | Causal only on material-alert days | Missed sustained events | 5 |
| F-V5 | Causal result not linked to ranking or actions | Inconsistent cards | 5, 8 |
| F-V6 | Weak placebo/pretrend, single control | Low power | 5 |
| F-D1 | Weekday seasonality ignored | Saturday false alarms 11/42 | 2 |
| F-D2 | Large real drops missed | EVT03 −63% not material | 2 |
| F-D3 | Absolute-only materiality | Not slice-aware | 2 |
| F-D4 | No cross-slice prioritisation | Manual slice picking | 2 |
| F-D5 | Demo "quiet" date inside a real event | Misleading demo | 1 |
| F-U1 | Unstructured evidence never used | Round 1 requirement unmet | 6 |
| F-U2 | Retrieval lacks scope/as-of filters | Latent leak | 6 |
| F-P1 | Identical narrative across personas | Brief minimum unmet | 8 |
| F-P2 | LLM adds almost nothing; 0 tokens in demo | Weak LLM story | 8, 11 |
| F-P3 | Chat fallback does not answer "why"; no forecast refusal | Weak chat | 6 |
| F-P4 | Chat persona defaults to CFO → 403 | Bug | 1 |
| F-A1 | Expected impact always null | Action chain incomplete | 8 |
| F-A2 | Wrong action owners | KPI owner used | 1 |
| F-A3 | One card; mislabelled evidence refs | Thin actions | 8 |
| F-L1 | Feedback never reaches the live engine | Evaluation-only | 9 |
| F-S1 | Spoofable demo identity | Demo only | 11 |
| F-S2 | Marketing sees finance reconciliation details | Minor leak | 11 |
| F-S3 | ACCESS_DENIED returned as HTTP 200 | Convention | 11 |
| F-S4 | Category-level security not demonstrated | Missing scenario | 1 |
| F-SC1 | CSV re-read and new pipeline per request; 385 KB responses | Scale story weak | 11 |
| RAG-1 | Ingest and retrieval use different Chroma dirs; empty KB | Chat has no KB | 6 |
| RAG-2 | Contract ingest uses non-existent YAML keys | Empty chunks | 6 |
| RAG-3 | LLM chat answers not validated for numbers or causal words | Hallucination risk | 6 |
| OPS-1 | `ENGINE_VERSION` hard-coded; cache serves stale runs | Dev trap | every stage |
| OPS-2 | Missing `ground_truth_events.csv` / `kpi_dataset.csv`; stray `chroma.sqlite3`; stale docs | Housekeeping | 0, 11 |

## Appendix B: Round 2 requirement → stage traceability

| Round 2 objective / minimum expectation | Delivered by stage |
|---|---|
| 1. Detect and prioritise material movements | 2 |
| 2. Reconcile heterogeneous sources | 4 (plus existing alignment) |
| 3. Identify and rank drivers with appropriate methods | 3, 5 |
| 4. Persona-specific narratives with traceable evidence | 6, 8 |
| 5. Communicate uncertainty; abstain or clarify when insufficient | 7 (AC, AMBIGUOUS, clarification) |
| 6. Actions grounded in levers, constraints, decision rights | 8 |
| 7. Learn from analyst and business-user feedback | 9 |
| 8. Security, cost, latency, scalability | 11 (plus existing) |
| LLM vs non-LLM breakdown; LLM not the source of truth | existing, extended in 7, 8, 11 |
| ≥ 2 personas with different narratives or actions | 8 |
| Multi-factor movement with known drivers | 0 (labels), 3, 7 |
| Low-confidence scenario (clarify or abstain) | 7 |
| Sparse-history scenario | existing (keep passing) |
| Role-based security scenario | existing plus the Stage 1 category role |
| Evidence: freshness, method, contribution, confidence, lineage | 3 (contribution), 4, 7 |
| Runtime telemetry: latency, calls, tokens, cost | existing, extended in 11 |
| Round 1: structured **and** unstructured data | 6 |
