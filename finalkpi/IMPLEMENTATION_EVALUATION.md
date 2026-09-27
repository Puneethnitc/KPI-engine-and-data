# BusinessIntelligence.ai: Implementation Evaluation

**Branch evaluated:** `codex/team-handoff-20260926` (HEAD `76f1d57`)
**Evaluated on:** 2026-09-27
**Measured against:** *Accenture Innovation Challenge – Round 1 Problem Statements* (Problem 3) and *round2_brief.pdf* (Problem Track 3)
**Scope:** Read-only evaluation. No source code was changed. This file is the only thing added to the repo.

Each finding has two parts:

- **In simple terms:** what is wrong and why it matters, for anyone on the team.
- **Technical:** the exact file and line, the mechanism, and the evidence from our own test runs.

---

## 1. Executive summary

### In simple terms

The project is well built. It is careful, honest about uncertainty and heavily tested. All 458 existing tests pass. It rarely claims things it cannot prove. Access control, audit trails, telemetry, the semantic contracts and the "abstain when unsure" behaviour are strong, and they match what the Round 2 brief asks for.

But the three areas you were worried about really are broken. We checked them against the six real events hidden in the dataset (a marketing cut, a flash discount, a stockout, a checkout outage, a fake marketing "decoy" and a cold snap):

1. **Driver ranking almost never names the real cause.** In 5 real events it found the true driver as #1 at most once. "Online traffic" comes out on top nearly every time, because traffic is part of how revenue is calculated, so it always moves with revenue. The stockout driver reads a data column that is always zero, so it can never be found. Discounts and weather are the real causes of two events, but they are not in the list of drivers at all.
2. **Causal verification never confirms anything with the real data.** Only two causal tests exist, and both are hard-coded. One can never run because its start date is a Saturday and the check requires a Monday. The other comes back "inconclusive". When we set up a correct test of the real marketing cut, the engine *rejected* it, because the comparison region (South) was running its own big campaign at the same time and nothing checks for that.
3. **The overall confidence label is effectively constant.** Whenever the movement and the data sources pass their checks, the overall label is "MODERATE" in every case we tried (96 out of 96). It does not change when the causal test passes, when it fails, or when no driver is found. The "HIGH" label cannot be reached. For revenue, the flagship KPI, the finance cross-check never runs in normal use, so revenue is almost always shown as "LOW" confidence.

Other important gaps:

- The unstructured data (support tickets, news and promo calendars) is never used. The brief requires both structured and unstructured data.
- The CFO, the marketing manager and the regional manager all get the same narrative.
- Recommended actions never estimate impact.
- The anomaly detector ignores the day of the week, so most false alarms fall on Saturdays. It also missed a 63% drop in orders during the stockout.

### Technical

| Area | Verdict |
|---|---|
| Engineering quality, guardrails, tests | **Strong.** 187 engine, 111 backend and 160 frontend tests pass. `tsc` is clean. |
| R2-1 Detect and prioritise material movements | **Partial.** Detects single slices. No weekly seasonality in the primary detector. No cross-slice/KPI prioritisation. |
| R2-2 Reconcile heterogeneous sources | **Partial.** Grain and as-of alignment is good. Reconciliation is unreachable in the default path. |
| R2-3 Identify and **rank** drivers | **Weak.** Marginal, movement-agnostic correlation ranking dominated by a mechanical component. One driver maps to the wrong column. Key drivers are missing. |
| R2-4 Persona-specific narratives with evidence | **Weak.** Evidence binding is excellent. Narratives are identical across personas. |
| R2-5 Uncertainty and abstention | **Partial.** Abstention works well. The overall confidence aggregation is flawed (see §4). |
| R2-6 Actions (driver → lever → action → impact → owner → confidence → monitoring) | **Partial.** Impact is always `null`. Owners are wrong. One card per run. |
| R2-7 Learn from feedback | **Partial.** A full governance workflow exists, but nothing ever reaches the live engine. |
| R2-8 Security, cost, latency, scale | **Good for a prototype.** Identity is spoofable (demo mode). Everything is CSV-per-request. |
| Round 1: structured **and unstructured** data | **Not met in practice.** Unstructured evidence is never ingested or used. |

---

## 2. What we ran

| Check | Result |
|---|---|
| `python -m unittest discover -s tests` | 187 tests, **OK** (the handoff doc still says 123) |
| `python -m unittest discover -s backend/tests` | 111 tests, **OK** (the handoff doc still says 12) |
| `frontend: npm test` | 160 tests, **OK** |
| `frontend: tsc --noEmit` | **Clean** |
| `next build` | Not run, to avoid writing build artefacts into the repo |
| Live API (`uvicorn` on a test port, isolated runtime dir) | Tested identity, row security, persona outputs, telemetry, chat/RAG and all 6 demo scenarios |
| **Our own ground-truth probe** | 95 pipeline runs across the 6 events in `data/fix_dataset.py` × 5 KPIs × 3–4 dates each |
| **Our own causal probe** | 10 hand-built `VerificationDesign`s: correct, wrong-driver, decoy, null period |
| **Our own confidence probe** | Every combination (96) of movement, source, driver and causal inputs to `ConfidenceEngine.build_profile` |
| **Our own false-alarm probe** | 120 random quiet slice-days (outside every event window) × 2 KPIs |

All 6 governed demo scenarios (`/api/demo-scenarios`) return their expected outcome. The engine behaves correctly on the paths it was hand-tuned for. The problems below appear as soon as you leave those paths.

Ground-truth events used (from the comments in `data/fix_dataset.py`; `ground_truth_events.csv` itself is **not in the repo**):

| Event | Slice | Window | True driver |
|---|---|---|---|
| EVT01 | North/Electronics | 2023-07-20 → 08-13 | Marketing (paid-search) cut |
| EVT02 | ALL/Home | 2023-10-28 → 11-06 | 30% flash discount |
| EVT03 | South/Apparel | 2024-02-05 → 02-16 | Stockout (stock availability 15%) |
| EVT04 | ALL/ALL | 2024-05-15 → 05-18 | Checkout latency spike |
| EVT05 | East/Electronics | 2024-07-14 → 07-29 | Decoy: marketing burst with no real effect (should abstain) |
| EVT06 | ALL/Apparel | 2023-04-11 → 04-23 | Cold snap (weather) |

---

## 3. Driver ranking (deep dive)

### 3.1 Scoreboard against ground truth

**In simple terms:** We asked, "when a real event happened, did the engine put the right cause at #1?" Almost never.

| Event (revenue) | Engine's #1 driver | Correct? |
|---|---|---|
| EVT01 marketing cut | `ad_spend_drop` on day 1 (with the **wrong sign**, r = −0.67), then `traffic_drop` on later days | Partly, and the sign contradicts the hypothesis |
| EVT02 flash discount | `traffic_drop`, and the card says "check traffic instrumentation" for a revenue **increase** | ✗ (discount is not a declared driver) |
| EVT03 stockout | `traffic_drop` (r = 0.80). `stockout` was excluded as `CONSTANT_SERIES` | ✗ |
| EVT04 latency spike | `traffic_drop` #1, `checkout_latency_spike` #2 even though latency rose **+391%** that day | ✗ (true driver ranked 2nd) |
| EVT06 cold snap | `traffic_drop` | ✗ (weather is not a declared driver) |

`traffic_drop` was ranked #1 in **every** revenue, orders and units run we made, with r between 0.50 and 0.93, whatever the event.

### 3.2 Root causes

**F-R1. The stockout driver reads a column that is always zero. (Critical)**
- *Simple:* The engine looks at "lost units due to stockout". That field is 0 on every row, including during the real stockout. The real signal (stock availability dropping to 15%) is in a different column, so the stockout driver can never fire.
- *Technical:* Every registry YAML maps `stockout` → `column: lost_units_stockout`. In `data/sales_daily.csv`, `lost_units_stockout > 0` on **0 of 8,880 rows**. During EVT03, `stock_availability` falls from 1.00 to 0.15. The ranker excludes the driver as `CONSTANT_SERIES` (`kpi_engine/rank.py:482`). The DiD verifier returns `NO_EXPOSURE_CONTRAST` (`kpi_engine/verification/did.py:205`).
- *Fix:* Map `stockout` to `stock_availability` with `expected_direction: positive`, or regenerate `lost_units_stockout`.

**F-R2. "Traffic" is a mechanical part of revenue, not an explanation. (Critical)**
- *Simple:* Revenue equals traffic × conversion × basket size. Traffic will always move with revenue, so ranking it by correlation is like saying "revenue fell because revenue fell". It crowds out the real causes.
- *Technical:* `traffic_drop` uses `traffic_online` (a component of `traffic_total`), which sits upstream of `orders` in the accounting identity. It is ranked as a free "driver" for `net_sales_revenue`, `orders` and `units_sold`. The target-leakage guard (`rank.py:302`) only catches the KPI's own column, not identity components.
- *Fix:* Treat funnel components as **decomposition** (a traffic × conversion × AOV bridge), not as candidate drivers. Restrict candidate drivers to exogenous or controllable levers: spend, price or discount, stock, latency, competitor index, weather.

**F-R3. Ranking ignores what actually happened on the day. (Critical)**
- *Simple:* The ranking asks "over the last 120 days, which driver usually moves with this KPI?" It never asks "which driver moved *today*, and by enough to explain *this* drop?" On the outage day, latency jumped +391% and still ranked below traffic, which moved −4.9%.
- *Technical:* `score = |r| × coverage × sample_factor × stability` (`rank.py:558`). `driver_change_pct` is computed (`rank.py:610`) but never used in the score. The ranking is a property of the window, not the event. With ~120 daily pairs, `sample_factor` and `coverage` both come out ≈ 1, so the score reduces to |r| × stability.
- *Fix:* Rank by **explained movement**: estimated sensitivity (β from a regression on first differences, or an elasticity) × the driver's change on the target period. Report the share of the KPI delta each driver explains, plus a residual.

**F-R4. Missing drivers for 2 of the 6 events. (High)**
- *Simple:* The real causes of the flash-sale spike and the cold-snap spike (discount and weather) are in the data, but nobody told the engine to look at them.
- *Technical:* `price_discount_depth`, `promo_flag` and `weather_temp_c` exist in `sales_daily.csv` but are absent from every `candidate_drivers` list in `kpi_engine/registry/*.yaml`. The action catalog (`kpi_engine/action.py:40`) has no pricing, promo or weather levers either.

**F-R5. No expected direction is declared, so wrong-sign associations are ranked as normal. (High)**
- *Simple:* The engine found "more marketing spend → lower revenue a week later" (r = −0.67) and still recommended checking marketing. That contradicts the business hypothesis and should have been flagged.
- *Technical:* No YAML sets `expected_direction`, so `direction_consistent` is always `None` and `DIRECTION_CONFLICT` (`rank.py:566`) can never trigger. Even when it does trigger, the score is not penalised.

**F-R6. The stability check is almost always "STABLE". (Medium)**
- *Simple:* The engine checks whether the relationship is stable by comparing the full window with the last 80% of the same window. Those two samples share 80% of their data, so they almost always agree.
- *Technical:* `stability_window_fraction = 0.8` (`rank.py:94`, `rank.py:533`). The recent window is nested inside the full window. Across our 95 runs, nearly every candidate was `STABLE`. Use disjoint windows (for example, first half vs second half, or a rolling out-of-sample check).

**F-R7. Statistical hygiene. (Medium)**
- The best lag is picked by maximising |r| on the same data, with no multiple-testing correction (`adjusted_significance: None`, `correction_method: None`). No p-values or confidence intervals are given for r.
- Pearson correlation is run on autocorrelated first differences with no effective-sample-size adjustment.
- Drivers are ranked one at a time (marginally), so correlated drivers (spend → paid traffic → traffic) are double-counted. There is no conditional or multivariate model.
- For monthly drivers, `allowed_lags // 30` collapses every lag to 0. For weekly drivers, `0..7 // 7` gives only {0, 1}.
- `effective_window_days = max(contract, 120)` is reported, but the frame was already cut to 120 days (`rank.py:231–233, 290–293`), so a contract asking for 180 days reports 180 while using 120.
- `max_lag` is capped at 7 regardless of the contract (`rank.py:289`).

**F-R8. `ShapleyContributor` is never connected. (Medium)**
- *Simple:* There is code to split a KPI change fairly across several drivers, but nothing feeds it data, so no driver contribution numbers are ever produced.
- *Technical:* `kpi_engine/contribute.py` needs caller-supplied coalition outcomes. It is only reachable through `quantify_scenario()`, which nothing in the pipeline or backend calls.

---

## 4. Confidence scores (deep dive)

**F-C1. The overall confidence ignores driver and causal evidence. (Critical)**
- *Simple:* Once the movement and the data sources look fine, the overall confidence is "MODERATE" every time. Whether the causal test passed, failed or never ran, and whether any driver was found at all, makes no difference.
- *Technical:* In `kpi_engine/confidence.py:356–370`, the driver dimension is never consulted, and every branch after the movement and source gates resolves to `MODERATE`. We ran all 96 combinations of `{BOTH, ROBUST_ONLY} × {AGREED, NOT_APPLICABLE} × {STABLE, SENSITIVE, none} × {SUPPORTED, REJECTED, INCONCLUSIVE, UNTESTABLE} × {approved, not}`. **All 96 gave `overall = MODERATE`.** Specifically:
  - causal `REJECTED` → causal dimension `CONFLICTING_EVIDENCE` → **overall `MODERATE`**
  - no driver passed → driver dimension `INSUFFICIENT_EVIDENCE` → **overall `MODERATE`**
  - Because `REJECTED` never becomes an overall `CONFLICTING_EVIDENCE`, the card-clearing guard at `pipeline.py:240` does not fire.
- *Fix:* Make the overall status the minimum across all required dimensions. A causal `CONFLICTING` should cap the overall status at `LOW`. The driver dimension must be allowed to lower the overall status.

**F-C2. "HIGH" can never be reached. (High)**
- *Technical:* The final `else` branch (`confidence.py:370`) can only return `HIGH` when movement = HIGH, source = HIGH and causal = MODERATE. That exact case is caught one branch earlier (`confidence.py:366`) and returns `MODERATE`, so `HIGH` is dead code. The UI therefore has a 3-level scale in practice.

**F-C3. Revenue, the flagship KPI, is almost always "LOW" confidence. (High)**
- *Simple:* Revenue is the only KPI with an independent finance cross-check. That check only runs when you pick the last day of a month *and* manually set the evaluation time to 5 or more days later. In normal use it never runs, and "not available" counts against revenue. KPIs with no cross-check at all are treated as fine. So the best-checked KPI looks the least trustworthy.
- *Technical:* In `reconcile.py:271`, closed-period mode needs `target_date == month_end`. The finance row is filtered by `available_at <= as_of`, and the default `as_of = target + 1.5 days`, while `closes_at = month_end + 5 days`. Across 96 weekly target dates, reconciliation returned `NOT_AVAILABLE_FOR_PERIOD` **96/96** times. It only returned `AGREED` when we passed `target=2023-07-31, as_of=2023-08-10`. `NOT_AVAILABLE_FOR_PERIOD` maps to source `LOW` (`confidence.py:202`), while `NOT_APPLICABLE` maps to `HIGH`.
- *Fix:* Treat "comparator not yet due" as neutral, like `NOT_APPLICABLE`. Also add the implemented-but-unused `snapshot` (MTD) mode, using the provisional finance row, so the check actually runs. The data README promises a "16–20% provisional gap" demo; this is the way to show it.

**F-C4. Event verification always reports causal "NOT_ASSESSED". (High)**
- *Technical:* `verify_event()` (`pipeline.py:306`) never sets `_causal_design_approved`, so `build_profile` marks the causal dimension `NOT_ASSESSED` even after a full DiD has run. `movement_assessment` is also `None` in this path, so the overall status is always `INSUFFICIENT_EVIDENCE`. Every one of our 10 `verify_event` probes returned `causal=NOT_ASSESSED, overall=INSUFFICIENT_EVIDENCE`, including the one that returned `REJECTED`.

**F-C5. No numbers and no calibration. (Medium, by design)**
- *Simple:* The engine deliberately shows no confidence percentages because it has no labelled history to calibrate them against. That is honest, but the brief lists "confidence calibration" as a real-world complexity. We need a labelled set to calibrate against.
- *Technical:* `score: None` everywhere. `tests/run_labeled_evaluation.py` exists, but no labels file is committed and `ground_truth_events.csv` is missing. Committing the 6 events plus negatives as a labelled set would allow precision/recall and calibration to be reported.

---

## 5. Causal verification (deep dive)

**F-V1. Only two hard-coded designs exist, and neither can succeed. (Critical)**
- *Simple:* Causal checks only run for two exact dates in one region. One of them is broken by its own settings. For every other date, KPI or region, the causal section just says "not assessed".
- *Technical:* `kpi_engine/verification/registry.py` holds 2 entries keyed by exact `(kpi, date, region, category)`.
  - `2023-07-24 / ad_spend_drop` has `treatment_start="2023-07-01"`. That date is a **Saturday**, and weekly drivers require a Monday start (`did.py:171`), so the result is always `UNTESTABLE / COARSE_TREATMENT_TIME`. The start date is also wrong: the true event starts on 2023-07-20.
  - `2023-08-06 / traffic_drop` returns `INCONCLUSIVE / CI_INCLUDES_ZERO` (effect −376 INR/day, CI [−764, +12]).
  - So the live app **never** produces `SUPPORTED_CONDITIONAL` on real data.

**F-V2. The known marketing cut is REJECTED because the control is contaminated. (Critical)**
- *Simple:* The engine compares North (where the cut happened) against South. But South ran its own large campaign in June and July and then cut back. Measured in rupees, South's spend fell *more* than North's, so the engine concluded the cut went "the wrong way". Nothing checks whether the comparison region is itself affected.
- *Technical:* With a corrected design (`start=2023-07-17`, `as_of=2023-08-20`), the result is `REJECTED / DRIVER_DIRECTION_MISMATCH`. From `marketing_weekly.csv`: North spend was ~5.3k/week before and ~0.5–1k after; South was 5k → 17.6k → 5k. The DiD is computed on **levels** (`did.py:201`, and the outcome gap regression below it), so South's larger absolute drop wins.
- *Fix:* Add a control-validity gate (the control's own driver must stay within a band). Use log or percentage differences, or a synthetic control built from several regions. Let a design declare several candidate controls and run `verify_sensitivity()`, which already exists but is unused.

**F-V3. Weekly-driver DiD is untestable at the default evaluation time. (High)**
- *Technical:* The default `as_of = post_end + 1.5 days`, but a weekly row becomes available at `week_end + 2 days 09:00`. So the last post-period week is always missing, and the result is `UNTESTABLE / INCOMPLETE_DRIVER_EXPOSURE`. Both of our `ad_spend_drop` probes hit this until we moved `as_of` later.

**F-V4. Causal checks only run on the day of a material alert. (Medium)**
- *Technical:* In `run_diagnosis`, verification only runs after `is_material` is true (`pipeline.py:720`). Many event days are not material (see §6), so no causal check runs for them, even when a design exists.

**F-V5. The causal result is not tied to the ranking or the actions. (Medium)**
- *Simple:* The engine can test driver A causally while recommending an action on driver B.
- *Technical:* The design's `driver_id` is fixed in the registry, separately from the ranker. In `verify_event`, testing `checkout_latency_spike` (REJECTED) still produced a `NEXT_CHECK` card for `traffic_drop`. The top ranked driver never automatically gets a causal test.

**F-V6. Method caveats. (Low to medium)**
- The placebo is "second half minus first half of a quiet window", compared with 0.5 × the effect. It has no uncertainty estimate and is not the same estimator as the main effect.
- The pre-trend test has low power (about 30 points, HAC). Passing it does not show parallel trends.
- A single control unit is used, with no synthetic control and no covariates.
- The verdict stays `MATERIAL_CAUSE_UNVERIFIED` even when DiD returns `SUPPORTED_CONDITIONAL`. This is intentional, but the UI should show the conditional support clearly.

---

## 6. Other findings across the codebase

### Detection (R2-1)

**F-D1. The primary detector ignores the day of the week. (High)**
- *Simple:* Sales naturally differ between weekdays and weekends. The main detector compares each day with the last 60 days lumped together, so ordinary Saturdays look unusual. On quiet days, 11 of 42 Saturdays raised a material alert, compared with 0–1 on other weekdays.
- *Technical:* `detection/robust.py` uses a rolling median/MAD with no seasonal adjustment. MSTL (`seasonal.py`) is used only for "review". From our 120 random quiet slice-days: material alerts by weekday were Mon 0/32, Tue 1/32, Wed 0/40, Thu 0/36, Fri 1/20, **Sat 11/42**, Sun 3/38.

**F-D2. Real, large drops are missed. (High)**
- *Technical:* The wide weekly spread inflates the MAD. Two examples:
  - EVT03 stockout, orders **−63.5%** (South/Apparel 2024-02-07): `NO_MATERIAL_MOVEMENT` (robust score −2.08 < 2.5).
  - EVT04 outage, revenue **−61.7%** (North/Electronics 2024-05-15): `SEASONAL_REVIEW` only.
- Revenue recall per event day: EVT01 2/4, EVT02 3/3, **EVT03 0/3**, EVT04 2/3, **EVT06 0/3**.
- *Fix:* Make the seasonal-residual detector primary, or compare each day with the same weekday. Also add a relative (%) materiality threshold.

**F-D3. Materiality is a single absolute number for every slice. (Medium)**
- `abs_threshold: 500 INR` applies equally to one small segment and to the company total. It should scale with the slice, for example as a % of baseline, or come from a per-slice policy.

**F-D4. Nothing prioritises across KPIs or slices. (Medium)**
- *Simple:* The brief says "detects and **prioritises**". Right now the user has to pick one region, category and date. Nothing scans every slice and says "here are today's top 5 movements".
- *Technical:* `build_marketing_brief` orders by a 2/1/0 bucket (material decline / decline / other). It does not use impact size or z-score, and positive material movements get the lowest priority.

**F-D5. The demo "non-material baseline" date is inside a real event. (Low)**
- `non-material-baseline` uses 2023-08-13, the last day of the EVT01 marketing cut (`backend/demo_scenarios.py`). A jury member who knows the data could challenge this.

### Unstructured data (Round 1 requirement)

**F-U1. Unstructured evidence is never used. (Critical for the brief)**
- *Simple:* The dataset includes support tickets such as "North Electronics paid-search budget cut ~90%" on the exact alert date. The engine never reads them, and the chat assistant never cites them, even when asked "is there any ticket about marketing budget?".
- *Technical:*
  - `kpi_engine/corroborate.py` is not called from anywhere (its own header says so).
  - `backend/retrieval.py:ingest_documents()` (the only code that loads `unstructured_evidence.csv`) and `retrieve_relevant_documents()` are **never called**.
  - `backend/ingest.py:ingest_kb()` indexes only the YAML contracts and `docs/*.md`. It writes to `backend/data/chroma`, while `ContextBuilder` reads from `backend/runtime/chroma` (`config.CHROMA_DIR`), so the chat's collection count is **0**.
  - The contract text it indexes uses keys that do not exist (`name`, `aggregation_method`, `materiality_thresholds`, …), so the content is mostly empty.
- *Fix:* Feed the tickets into diagnosis as a corroboration dimension (scope-filtered and as-of-filtered), and cite them in the narrative and in chat.

**F-U2. Retrieval, once wired up, would leak across scope and time. (High, latent)**
- *Technical:* `retrieve_vector_chunks` (`retrieval.py:105`) applies no region or category filter. Its as-of filter reads `meta["timestamp"]`, but the evidence ingester writes `date`, so future documents would pass. A North manager could receive South tickets, and a 2023 diagnosis could cite 2024 notes. Fix this before wiring F-U1.

### Personas and narrative (R2-4)

**F-P1. Every persona gets the same narrative. (High)**
- *Simple:* The brief asks for at least two personas getting different stories or actions. The CFO, the marketing manager and the North regional manager all get the exact same narrative text and the same action cards. The only difference is that the CFO summary starts with "Financial review:".
- *Technical:* `NarrativeEngine` (`kpi_engine/narrative.py`) never reads `persona`. In our API test, the narrative was identical for all 3 identities and all KPIs. Persona only drives field redaction (`backend/response_projection.py`).
- *Fix:* Add persona templates that vary depth (CFO: P&L impact and reconciliation; marketing: channel and spend levers; regional: operational levers and stock), vary actions and owners, and vary channel.

**F-P2. The LLM contributes very little. (Medium)**
- The LLM may only pick between 1–2 pre-written wordings per sentence (`narrative.py:_variants`). This is safe, but the brief highlights "LLM-assisted intent understanding, orchestration, narrative synthesis". Show at least one place where the LLM adds value, such as persona rephrasing that is still validated against the claims, or intent parsing in chat.
- Without `GROQ_API_KEY`, the demo makes 0 model calls, so the token and cost telemetry always shows 0. For the jury, record at least one run with a key.

**F-P3. The chat fallback does not answer "why". (Medium)**
- "Why did revenue drop?" returns only actual/expected/delta. "What will revenue be next month?" returns the same text and does not decline cleanly. A prompt-injection question gets the full narrative back. That is harmless, but it is not an explicit refusal.

**F-P4. Chat rejects non-CFO users unless `persona` is sent. (Low)**
- `ChatRequest.persona` defaults to `"CFO"` (`backend/app.py:60`), so a marketing or regional user who omits it gets **403**. The frontend sends it, but any other client will hit this.

### Actions (R2-6)

**F-A1. Expected impact is never estimated. (High)**
- *Simple:* The brief's action chain is driver → lever → action → **expected impact** → owner → confidence → monitoring. Impact is always blank.
- *Technical:* `DecisionCard.expected_impact = None` for every card (`action.py:22`). Once F-R3 exists (β × driver change), a bounded impact range can be given together with its uncertainty.

**F-A2. The wrong people are named as action owners. (Medium)**
- *Technical:* `semantic.py:156` fills each driver's `owner` with the **KPI** owner. `action.py:_build_card` prefers that value over the lever catalog's owner. So a marketing lever on `net_sales_revenue` is assigned to `regional_manager`, and on `orders` to `ops_lead`, instead of `marketing_lead`.

**F-A3. Only one action card per run, with mislabelled evidence. (Low)**
- `recommend()` returns a single card. Evidence references for correlational cards point to `causal_verification.verdict` but are labelled `ranked_driver`.

### Feedback learning (R2-7)

**F-L1. Feedback never changes the live engine. (Medium)**
- *Simple:* There is a thorough review workflow (propose → accept → evaluate → roll back), but every path ends with "evaluation only, not deployed". Nothing the analysts say ever changes thresholds, driver lists or rankings.
- *Technical:* `api_apply_improvement_proposal` always returns `deployed: False`. The supported candidate types are only `EVALUATION_CASE_ADDITION` and `NARRATIVE_TEMPLATE_CHANGE`. Adding a gated `THRESHOLD_CHANGE` or `DRIVER_PRIOR_CHANGE` that versions the YAML contract would close the loop.

### Security, cost and scale (R2-8)

- **F-S1 (Medium).** Identity is a plain `user_id` string (`demo-cfo`, …). Any caller can claim to be the CFO, including on `/api/security-audit`. This is acceptable as a labelled demo, but the proposal should state the production auth design (OIDC/JWT → role claims).
- **F-S2 (Low).** The marketing manager has no FINANCE entitlement but still sees the reconciliation status and gap for revenue.
- **F-S3 (Low).** Access denial returns HTTP **200** with `verdict: ACCESS_DENIED` rather than 403. This is consistent, but should be documented.
- **F-S4 (Low).** Category-level security is never exercised: every role has `can_view_categories = ALL`. Add one category-restricted role to demonstrate the "column/domain-level" requirement.
- **F-SC1 (Low).** A new `KPIEnginePipeline` object is built and every CSV is re-read on each request (≈200 ms per KPI). This is fine for a demo, but the scalability story should mention the DuckDB query layer that is designed but only partly used.

### Housekeeping

- `docs/TEAM_HANDOFF.md` still says 123/12 tests; the actual numbers are 187/111.
- `ground_truth_events.csv` and `kpi_dataset.csv` (inputs to `data/fix_dataset.py`) are not in the repo, so the dataset cannot be regenerated and there is no committed labelled evaluation set.
- A stray `chroma.sqlite3` is committed at the repo root. `backend/ingest.py` ignores `KPI_CHROMA_DIR`.
- `kpi_engine/feedback.py` writes to `data/feedback_log.jsonl` inside the repo by default.

---

## 7. Round 2 minimum prototype checklist

| Brief requirement | Status | Notes |
|---|---|---|
| 3–5 connected KPIs, 2–3 sources, different grains/cadences | ✅ | 5 KPIs; daily, weekly and monthly sources with `available_at` |
| Lightweight KPI / semantic contract (definitions, calcs, drivers, thresholds, lineage, access) | ✅ | Strong. Thresholds are marked `PROVISIONAL` |
| ≥ 2 personas receive different narratives or actions | ❌ | Same narrative and cards (F-P1) |
| One multi-factor movement with known drivers | ⚠️ | Scenario exists, but ranking does not recover the known drivers (§3) |
| One low-confidence scenario that asks for clarification or abstains | ✅ | Abstains. Does not ask a clarifying question |
| One sparse-history / new KPI scenario | ✅ | Beauty → `INSUFFICIENT_HISTORY` |
| One role-based security scenario | ✅ | Regional manager denied South |
| Evidence: freshness, method, contribution, confidence, lineage | ⚠️ | Freshness and lineage are good. Driver contribution is missing (F-R3/F-R8). Confidence is flawed (§4) |
| Clear LLM vs non-LLM breakdown | ✅ | `processing_transparency` |
| Runtime telemetry: latency, calls, tokens, cost | ✅ | Present. Shows 0 without an API key (F-P2) |
| **Round 1:** structured **and unstructured** data | ❌ | F-U1 |
| LLM not the source of quantitative truth | ✅ | Excellent. Enforced by claim validation |

---

## 8. Recommended fix order

| # | Fix | Why first | Effort |
|---|---|---|---|
| 1 | Remap `stockout` → `stock_availability`. Add `discount`/`promo` and `weather` drivers. Declare `expected_direction` for every driver | One-line YAML changes that immediately make 3 more events findable | S |
| 2 | Remove funnel components (`traffic_drop`) from the driver list and show them in a traffic × conversion × AOV bridge | Stops the "traffic always wins" ranking | S–M |
| 3 | Re-score drivers by **explained movement** (β × Δdriver on the target period, plus residual) | Fixes ranking relevance and enables expected impact (F-A1) | M |
| 4 | Rewrite the overall confidence as "minimum of required dimensions"; let driver and causal evidence lower it; make HIGH reachable; treat "comparator not due" as neutral | Confidence becomes meaningful | S |
| 5 | Fix governed designs: Monday start, correct dates, control-validity gate, log/% DiD, `as_of` buffer for weekly sources; set `_causal_design_approved` in `verify_event` | Lets causal verification succeed on real data | M |
| 6 | Wire the unstructured evidence into diagnosis and chat, **with** region, category and as-of filters | Meets the Round 1 structured + unstructured requirement | M |
| 7 | Persona-specific narrative templates and action sets | Meets the persona minimum expectation | M |
| 8 | Same-weekday or seasonal-residual primary detector; relative materiality thresholds | Removes the Saturday false alarms and the missed −60% drops | M |
| 9 | Commit a labelled evaluation set (6 events + negatives) and report precision, recall and top-1 driver accuracy | Evidence for the jury, and the basis for calibration | S |

---

## 9. How to reproduce our probes

All probes call the public API only (`KPIEnginePipeline.run_diagnosis`, `verify_event`, `ConfidenceEngine.build_profile`) against the bundled `data/*.csv`. Minimal example:

```python
from kpi_engine.pipeline import KPIEnginePipeline
p = KPIEnginePipeline("kpi_engine/registry", "data/unstructured_evidence.csv",
                      access_csv="data/access_control.csv",
                      feedback_log_path="/tmp/fb.jsonl")
D = dict(sales_csv="data/sales_daily.csv", marketing_csv="data/marketing_weekly.csv",
         finance_csv="data/finance_monthly.csv")
r = p.run_diagnosis(kpi_id="net_sales_revenue", target_date="2024-02-07", persona="CFO",
                    dimension_slice={"region": "South", "category": "Apparel"}, **D)
print(r["verdict"], r["driver_analysis"]["excluded_drivers"])   # stockout -> CONSTANT_SERIES
```

The confidence check (F-C1): build a payload with movement `BOTH`, reconciliation `AGREED`, and `causal_verification.verdict = "REJECTED"`, then call `ConfidenceEngine.build_profile(payload, causal_design_approved=True)`. The result is `overall.status == "MODERATE"`.
