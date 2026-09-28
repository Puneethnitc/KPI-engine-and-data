# KPI engine: reviewed working copy

For cloning, local setup, frontend/backend startup, validation, and the safe
team branching workflow, read [`docs/TEAM_HANDOFF.md`](docs/TEAM_HANDOFF.md).

Start with [`docs/METRIC_COVERAGE.md`](docs/METRIC_COVERAGE.md) for the five
installed KPI diagnosis paths versus the wider set of numeric source fields,
and [`docs/ENGINE_FRONTEND_REVIEW.md`](docs/ENGINE_FRONTEND_REVIEW.md) for the
verified baseline and known engine/frontend limitations.

For a layer-by-layer explanation of formulas, choices, dataset behavior, and
limits suitable for a jury presentation, see
[`docs/METHODOLOGY_AND_DATASET.md`](docs/METHODOLOGY_AND_DATASET.md).
For a simpler, complete jury script with constant provenance and a fair
competitor comparison, see
[`docs/JURY_GUIDE_PLAIN_LANGUAGE.md`](docs/JURY_GUIDE_PLAIN_LANGUAGE.md).

## Current diagnosis path

The final prototype uses weekday-aware log-residual detection, then separates
arithmetic with an accounting/funnel bridge and estimates each moved driver's
share of the KPI movement with deseasonalised regression. Monthly finance
reconciliation uses available-to-date snapshots and reports `PENDING_CLOSE`
when a close is not yet due. Eligible material movements receive an
automatically designed log-outcome difference-in-differences check; candidate
controls are screened for authorization, driver exposure, and pre-period
outcome fit. Unstructured documents can corroborate or contradict a driver.
Per-driver Attribution Confidence reports evidence, caps, and bands. Persona
narratives and review/action cards stay grounded in the result; expected impact
is a fixed seven-day projection of statistical contribution, labelled as
unvalidated unless its confidence and causal gates pass.

The measured limits are visible: the EVT06 cold-snap/weather driver is not
recovered as the top driver; the holdout false-alarm rate is **5.6%**; and
EVT01's short post-period leaves its causal test `INCONCLUSIVE`, capping its
Attribution Confidence at **75%**. Evaluation covers **six synthetic events**,
not production data, and does not establish production accuracy.

The Python contract layer lives in `kpi_engine/contracts/` (models and registry).
The governed KPI definitions live in `kpi_engine/registry/`. They specify
source values, units, aggregation, decomposition inputs, reconciliation
availability, and correlational candidate signals. The loader rejects duplicate
YAML keys, unknown fields, mismatched filenames, and duplicate KPI IDs. These
contracts do not claim causal verification or executable SQL.

This folder is a clone of `Puneethnitc/KPI-engine-and-data` with the supplied
`kpi_engine_fixes.zip` applied and the high-risk diagnosis path repaired.

Five KPIs are currently registered: `net_sales_revenue`, `orders`,
`units_sold`, `traffic_total`, and `conversion_rate`.
The contract model supports daily `sum`, `mean`, `weighted_mean`, and
`ratio_of_sums` aggregation. Ratios use summed numerators and denominators,
not mean row percentages. Source value columns may differ from the KPI ID;
decomposition is optional; comparable additive KPIs can declare reconciliation
tolerance and contradiction multiples. These capabilities are tested with
temporary contracts and installed KPI definitions.

For CSVs with different column names, pass `source_schema_path` to
`KPIEnginePipeline` or `--source-schema` to the demo. The YAML maps canonical
columns to raw columns under `sales_daily`, `marketing_weekly`, or
`finance_monthly`, for example:

```yaml
sales_daily:
  date: business_day
  available_at: extract_time
  net_sales_revenue: sales_value
```

This covers column renames while retaining the three known source roles.
Weekly/monthly KPIs, a different file layout, new aggregation methods, and
new reconciliation algorithms still need implementation. The loader cannot
infer data semantics from a YAML file alone.

The public path uses weekday-aware log-residual detection, an accounting and
funnel bridge, explained-movement driver attribution, MTD finance
reconciliation (`PENDING_CLOSE` when the close is not due), and automatically
designed log-outcome DiD checks with control screening. Unstructured evidence
can corroborate or contradict each driver. Per-driver Attribution Confidence
reports its evidence, caps, and band; it is not a calibrated causal probability.
Persona narratives and action cards are grounded in these results and remain
review-only. `INCONCLUSIVE` and `UNTESTABLE` remain so regardless of their other
diagnostics.
The public pipeline emits `narrative` and `narrative_claims`, each with
evidence paths and an exact-template grounding check. Without a model key it
uses deterministic text. Set `GROQ_API_KEY` for the demo to let the model select
among approved sentence variants; it receives only those approved variants,
not source rows or arbitrary payload fields. Invalid selections or provider
errors fall back to the deterministic narrative, with `llm_status` explaining
what happened. This is deliberately constrained LLM narration, not free-form
generation. Access-denied runs never contact the model or disclose slice details.

For the full assistant, query router and constrained narrative selector, set
`GROQ_API_KEY` and, if needed, `GROQ_MODEL`; the default model is
`openai/gpt-oss-20b`. The implementation uses the OpenAI-compatible Python SDK
as a client for Groq's `https://api.groq.com/openai/v1` endpoint; it does not
send requests to OpenAI. Keys
must stay in the backend environment and must never use a `NEXT_PUBLIC_` name.

`decision_cards` now contains review-only next checks for unverified cases,
or an `AWAITING_APPROVAL` action proposal only after conditional observational
support. The closed lever library does not execute anything or invent a
recovery amount. These cards still require human judgment before action.

Contribution quantification is available separately through
`KPIEnginePipeline.quantify_scenario(ContributionScenario(...))`. It requires
explicit outcomes for all 2–4-driver coalitions from a stated counterfactual
model; exact Shapley values allocate that model's movement, with the difference
from observed movement reported as an unexplained residual. The result is
`MODEL_BASED_SCENARIO`, never a verified causal or accounting contribution.
The engine does not manufacture coalition outcomes from correlations or a
single-driver DiD estimate; without a defensible model, this stage abstains.

For a material KPI with a declared quantity/rate bridge, the pipeline reports
`decomposition_status: IDENTITY_HELD` only when the bridge matches the detected
change. Displayed effects are balanced at two decimals, and `effect_labels`
identify the actual quantity and rate columns (for orders, the latter is
conversion rate, not price). A KPI without a declared bridge reports
`NOT_APPLICABLE`; unusable components report `INSUFFICIENT_COMPONENTS` rather
than implying an exact explanation.

When the requested slice spans multiple declared dimensions, the bridge now
separates changes in total quantity, segment mix, and within-segment rate.
It uses the average baseline day for each segment and an order-independent
three-factor Shapley allocation, rather than attributing interactions according
to an arbitrary quantity→mix→rate sequence. New or disappearing segments
inherit their observed rate from the period where they exist, so their effect
is mix/quantity, not a fictitious rate change. This is an accounting identity,
not a causal explanation.

Correlational ranking is a separate track. Declared daily drivers use their
contract-specified `sum` or `mean`; weekly marketing reports are counted once
per week, not seven times through the daily alignment. The ranker correlates
changes at nonnegative lags, reports the number of independent paired
observations and the driver's own percentage movement, and marks every result
`CORRELATIONAL`. That percentage is **not** a contribution to the KPI change.
The current 0.3 correlation filter and lag range are exploratory, not a causal
test or calibrated significance threshold. The response also includes
`driver_exclusions` with a reason for each requested driver that was not ranked
(such as unavailable weekly data, missing columns, flat signals, too few
independent pairs, or a weak association); an omitted row is not interpreted
as evidence that the driver had no effect.

## Run

Requires Python 3.10 or later. From this directory:

```bash
python -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python run_full_demo.py
.venv/bin/python run_test_scenarios.py
.venv/bin/python run_full_demo.py --date 2023-08-06 --persona CFO \
  --verification-design examples/verification_design_inconclusive.yaml
```

The demo defaults to North/Electronics on 2023-07-24, a date where the
movement is material. `run_full_demo.py --help` lists the inputs. The result
is a JSON-serializable dictionary with explicit source, movement, accounting,
correlation, and causal-status fields.

For a five-KPI local review, run `python run_jury_review.py --output jury_review.html`
and open the generated HTML file. It is a read-only report, not an authenticated
web app. `python run_review_benchmark.py` reviews all five KPIs across the six
event windows documented in `data/fix_dataset.py` and two reference windows.
The manifest is `examples/review_windows.yaml`; this separate review is
provisional and distinct from the labeled ground-truth harness below. Its
counts are not accuracy metrics.
For independently reviewed per-KPI labels, use
`python run_labeled_evaluation.py reviewed_labels.csv`. Required columns are
`case_id,kpi_id,date,region,category,event_present,split,reviewer`, with
`event_present` set to `true` or `false` and `split` to `train` or `holdout`.
The evaluator reports per-KPI confusion counts, scored precision/recall, and
abstentions separately. Do not tune thresholds on the holdout. No reviewed
label file is included in this project; provisional generator notes are not
accepted as ground truth.
The supplied verification design is explicitly exploratory, not a recovered
ground-truth label; its real-data result is `INCONCLUSIVE` because the HAC
interval includes zero. A regional manager cannot use a control in another
region; such a design returns `CONTROL_NOT_AUTHORIZED` before verification
uses the control values. This local CSV role check is not database isolation.

For a completed event whose final day is not a material daily alert, call
`KPIEnginePipeline.verify_event(kpi_id, verification_design, sales_csv,
marketing_csv, finance_csv, persona="CFO", as_of=None)`. This explicit path
checks access to both slices, source availability, and reconciliation before
running the observational verifier. Its `EVENT_ASSESSED_CAUSE_UNVERIFIED`
result is independent of daily detection and never asserts a proven cause.

## What changed

- The marketing join requires the full date/region/category key, rejects source
  duplicates and row multiplication, and reports whether a weekly observation
  was available for the requested sales slice. Unavailable weekly signals are
  not ranked as target-day candidates.
- Sales, marketing, and finance are filtered by their recorded availability
  before a historical diagnosis. The default cutoff is noon on the day after
  the target date, when that day's sales extract is available. Required source
  timestamps, period fields, and declared row grains are validated rather than
  guessed from another column or a default delay.
- Source system names are preserved. Weekly marketing measurements are carried
  at their weekly value rather than divided into invented daily values.
- Heterogeneous-source unification occurs during governed normalization and alignment (joining daily sales, weekly marketing, and monthly finance), while cross-source reconciliation is an optional same-measure comparison against an independent system of record (such as monthly finance).
- Only `net_sales_revenue` declares a comparable finance measure. KPIs without a comparable finance measure (`orders`, `units_sold`, `traffic_total`, `conversion_rate`) return `NOT_APPLICABLE` and proceed through detection and ranking without finance files or warnings.
- Revenue reconciliation uses closed-month or available MTD snapshots. A still-open month may return `PENDING_CLOSE`; an MTD snapshot compares only through its own coverage date. `NOT_AVAILABLE_FOR_PERIOD` means a valid comparator snapshot is unavailable. `DRIFT` qualifies conclusions without blocking, while `CONTRADICTED` blocks downstream attribution.
- The public pipeline accepts only `sales_daily` as a primary KPI source until
  other native source paths are implemented. It reads marketing or finance only
  when the KPI contract actually declares a dependency on them, so an unrelated
  missing file cannot block a diagnosis.
- A regional role must request its own region. The supplied CSV is a demo role
  mapping, not authentication; a service must bind the role to an identity.
- Missing data and insufficient history have separate verdicts and null
  measurements. Demo switches that fabricate materiality or bypass source
  checks are rejected.
- Revenue and orders use thresholds in their own units. The accounting bridge
  uses the same target observation and baseline dates as detection.
- Driver attribution uses deseasonalised histories, screened lags, and a joint regression. Correlation remains a separate diagnostic; neither method alone proves causation.

## Limits before a full diagnosis product

Both registered primary KPI values come from daily sales. Marketing is a
weekly candidate-driver source and finance is a monthly reconciliation source,
not a separately registered KPI. Supporting 4–6 KPI definitions is not the
same as implementing and validating 4–6 diagnosis paths.

The reconciliation completeness rule assumes one sales row per day for every
active region/category in the comparison month. If a future dataset omits
legitimate zero-activity days or adds segments mid-month, it will abstain
until the source supplies an explicit activity calendar or zero rows. Weekly
coverage currently distinguishes only `AVAILABLE` from
`UNAVAILABLE_OR_MISSING`; a historical as-of run cannot safely know whether
an unavailable future weekly extract will eventually arrive.

Detection lives in `kpi_engine/detection/`; `kpi_engine/detect.py` remains an
import-compatibility shim. Two methods run side by side: a rolling robust
baseline for point and sustained shifts, and a prior-history-only MSTL weekly
forecast scored against 21 walk-forward one-step forecast errors. With only
one declared seasonal period (seven days), MSTL is effectively a single-season
STL; a second period would require an explicit contract and validation.
Each applies the KPI's statistical and business
thresholds. The result retains both scores and labels agreement as `BOTH`,
`ROBUST_ONLY`, `SEASONAL_ONLY`, or `NEITHER`. `is_material` follows the robust
branch as the provisional primary alert policy; an MSTL-only result returns
`SEASONAL_REVIEW` and does not start diagnosis. Missing targets,
insufficient history, and unscorable baselines produce explicit abstentions;
the seasonal branch also abstains when daily observations have gaps.
Thresholds (`2.5` robust score and `500` INR for revenue; `2.5` and `5`
orders) are provisional. On the known 25-day North/Electronics EVT01 window,
the robust revenue detector alone flagged seven dates (four point, three sustained).
The labeled file covers six synthetic events, not independently verified
production outcomes. A held-out split is reported, but it does not replace
validation on real business data. On the two examined 61-day North/Electronics revenue comparison windows,
the recalibrated seasonal branch flagged 0 and 1 days, down from 26 and 15
with the earlier in-sample residual scale. It flagged 3 dates in EVT01,
including one not flagged by the robust branch. The former OR rule would have
flagged 8 of 25 days, but that extra day is now review-only. These are
exploratory windows, not independent labeled validation; neither detector is
yet calibrated for production alerts.

MTD reconciliation depends on the finance file's `available_at` and
`coverage_end` metadata. Missing or incomplete coverage still causes an
abstention; `PENDING_CLOSE` is used when a future close is known but not due.

The causal designer selects an onset from driver residuals and screens
authorized controls for exposure contamination, complete history, and
pre-period outcome fit. The verifier requires sufficient pre/post coverage and
quiet windows, and checks pretrends, a log-outcome HAC DiD interval, and
placebos. Missing or contaminated inputs abstain. `SUPPORTED_CONDITIONAL` means
these observational checks passed, not that causation was proved. Multi-slice
exposure consistency, broader robustness review, held-out validation, and
calibrated causal confidence remain open. The engine also has no
authenticated API or enforced user identity, so it is a local research
prototype rather than a production service.

`CausalVerifier.verify_sensitivity(frame, contract, designs)` now runs two or
more predeclared designs for the same hypothesis and exposes every result. It
reports `CONSISTENT_CONDITIONAL` only if all designs pass; mixed results are
`SENSITIVE` or `UNTESTABLE`. This helper does not select a best control, prove
causation, or replace the pipeline's authorized single-design check. Multiple
eligible controls and exposure consistency still need dataset-specific design
and review.

Feedback can now store `original_text` and `corrected_text` together as a
`PENDING_REVIEW` before/after record. This is a proposed correction, not an
automatic change to a past diagnosis or model.
