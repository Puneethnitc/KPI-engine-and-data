# KPI engine methodology and dataset evidence

This is a presentation guide for the **local research prototype**, not a claim
of production accuracy or proved causation. The implementation is under
`kpi_engine/`; `run_jury_review.py` creates a read-only five-KPI report and
`run_review_benchmark.py` reproduces the provisional case review below.

## Current implementation (Stage Final)

The active diagnosis path uses same-weekday baselines and log residuals for
movement detection; an exact accounting bridge plus a traffic/orders/revenue
funnel bridge; and deseasonalised joint regression to estimate explained
movement per driver. It reconciles monthly finance through MTD snapshots,
including `PENDING_CLOSE` when a comparator is not due. Material movements can
trigger an automatic log-outcome DiD design with authorized-control screening.
Driver-level document corroboration feeds per-driver Attribution Confidence,
whose evidence, caps, and bands are shown in persona-specific grounded
narratives and review cards. Card impact is a seven-day arithmetic projection,
not a measured recovery amount.

The evaluation is limited to six synthetic events. EVT06 weather is not the
top-ranked driver; the holdout false-alarm rate is 5.6%; and EVT01's short
post-period yields an `INCONCLUSIVE` causal result and a 0.75 AC cap. These
results are not production validation.

## What the prototype measures

The registered KPIs are:

| KPI | Daily definition | Unit | Exact accounting bridge? |
| --- | --- | --- | --- |
| `net_sales_revenue` | Sum of the authoritative revenue column | INR | Units × derived revenue per unit |
| `orders` | Sum of source orders | count | Total traffic × derived orders per visit |
| `units_sold` | Sum of source units | units | No bridge declared |
| `traffic_total` | Sum of source total traffic | visits | No bridge declared |
| `conversion_rate` | Sum of orders ÷ sum of traffic | orders per visit | No ratio bridge implemented |

The source `conversion_rate` field is **not** averaged to produce the KPI:
averaging regional percentages would weight a low-traffic region as heavily as
a high-traffic region. The ratio-of-sums definition preserves the correct
denominator. For revenue and orders, bridge rates are derived from the
authoritative value and quantity so rounded source display rates cannot break
the identity.

The supplied data has 8,880 daily sales rows (2023-01-01 through 2024-12-30),
1,296 weekly marketing rows, and 292 monthly finance rows (276 closed, 16
provisional-open-month). There are four regions and four categories; Beauty
appears only at the end and deliberately exercises insufficient-history
handling. These are synthetic data, not independently observed business
outcomes.

## Layer-by-layer methods

### 1. Contracts and access

Each YAML contract declares the source, grain, unit, aggregation, dimensions,
materiality thresholds, optional bridge/reconciliation, and candidate drivers.
The Python registry validates schema and compatible methods. This makes the
five KPIs governable without five different pipelines. A local CSV role policy
checks the requested slice. It is useful for a demo but is **not** authenticated
database row-level security; source files are still loaded locally.

### 2. Ingestion and freshness

Sales, marketing, and finance retain their native daily, weekly, and monthly
grains. Source rows are admitted only when `available_at <= as_of` (or the
finance close timestamp is eligible). Keys and duplicate source rows are
checked. Weekly marketing values may be aligned to sales dates for lookup,
but ranking counts one independent weekly observation, never seven daily
copies. This prevents look-ahead leakage and false sample-size inflation.

On the default 2023-07-24 North/Electronics run, sales is available by the
next-day-noon cutoff but that week's marketing report is not. The engine marks
the weekly candidate unavailable on the target day instead of interpreting
absence as zero spend.

### 3. Source reconciliation

Heterogeneous source unification (joining daily sales, weekly marketing, monthly finance) occurs during governed normalization and alignment. In contrast, cross-source reconciliation is an optional same-measure comparison against an independent system of record (such as monthly finance).

Only `net_sales_revenue` declares a comparable finance measure. The other four KPIs (`orders`, `units_sold`, `traffic_total`, `conversion_rate`) return `NOT_APPLICABLE` and proceed through detection and ranking without finance files or warnings.

Where a comparable finance posting exists (`net_sales_revenue`), the same month and slice are compared:

`gap_% = 100 × |sales_total − finance_total| / |sales_total|`.

The canonical cross-source comparison statuses are:
- **`NOT_APPLICABLE`**: No comparable second-source measure is declared.
- **`NOT_AVAILABLE_FOR_PERIOD`**: A comparator is declared, but no valid matching period/as-of snapshot exists for the requested target date.
- **`PENDING_CLOSE`**: The month is still open and the next finance snapshot is not yet due; available MTD snapshots are compared only through their own coverage date.
- **`AGREED`**: Comparable values agree within tolerance (default 3.5%).
- **`DRIFT`**: Values differ beyond agreement tolerance but below contradiction boundary (up to 8.75%). Conclusions are qualified but non-blocking.
- **`CONTRADICTED`**: Evidence conflicts beyond contradiction boundary (>8.75%). This acts as the sole hard gate blocking downstream driver attribution.

### 4. Detection and materiality

The primary detector compares the target with earlier observations from the
same weekday, using a log residual `log(actual / expected)` so differences in
weekday scale do not dominate. The robust score divides that residual by a
MAD-based scale (`1.4826 × MAD`); IQR and standard deviation are fallback
scales when MAD collapses. A secondary sustained score compares a recent
seven-day window with earlier history.

The business change is measured against the same-weekday expected value. A
trusted material alert requires **both** a robust point/sustained threshold
and the contract's absolute materiality threshold. The thresholds are
provisional, not calibrated to production data. Missing days, too little
history, or an unscorable baseline produce explicit states rather than
“normal.”

A second, independent weekly-seasonal view uses MSTL fitted **only on prior
days**. Its one-step forecast errors over 21 preceding days supply a robust
forecast-error scale. A seasonal-only hit becomes `SEASONAL_REVIEW`, not an
automatic alert. We chose this over combining detectors with OR because an
untested OR rule can increase false positives. This model handles weekly
seasonality; annual/festival behavior has not been validated.

### 5. Exact decomposition

For one slice with `value = quantity × rate`, the symmetric bridge is:

`quantity_effect = (Q1 − Q0) × (r0 + r1)/2`

`rate_effect = (r1 − r0) × (Q0 + Q1)/2`.

For multiple segments, `value = Q × Σ_i(share_i × rate_i)`. We calculate
quantity, mix, and rate effects by averaging each factor's marginal change
over all six possible factor orders (exact three-factor Shapley). That avoids
making interaction attribution depend on a chosen sequence. The displayed
effects are balanced to the measured KPI delta after rounding. The default
North/Electronics revenue run has delta **−1364.15 INR**, quantity effect
**−1493.60**, mix **0**, and rate **+129.45**, which sum to −1364.15.

This is an **accounting identity**, not evidence that units independently
caused the revenue drop. A material conversion-rate case reports
`NOT_APPLICABLE` because a ratio mix bridge has not been built.

### 6. Correlational driver ranking

The primary driver method fits a deseasonalised joint regression to the KPI
and eligible driver histories, screens lags, and keeps only drivers that
actually moved. A driver's fitted coefficient times its target-period change
estimates its contribution; `explained_share` is that contribution divided by
the observed KPI movement. It is an observational estimate, not causal proof.
Weekly inputs retain weekly sample size and are not treated as seven independent
daily readings. Exclusions include unavailable sources, insufficient paired
history, and drivers that did not move. Correlational candidates remain a
separate diagnostic view where applicable.

### 7. Observational verification

For a material movement or sustained pattern, the pipeline can design a test
from the leading explained-movement drivers. It chooses an onset from driver
residuals, builds pre/post windows, and screens authorized controls for
contamination (driver change) and pre-period outcome fit. The estimate is a
DiD regression on log outcomes; HAC standard errors and quiet-window placebos
provide checks. The core difference-in-differences quantity is:

`DiD = (log(treated_post) − log(control_post)) − (log(treated_pre) − log(control_pre))`.

The regression uses the log outcome and a post-period interaction; HAC
standard errors produce a 95% interval. Failed control, exposure, coverage,
pretrend, or placebo checks abstain or return `INCONCLUSIVE`. A passing result
is `SUPPORTED_CONDITIONAL`, **not proof**.

In the supplied North/Electronics example ending 2023-08-06, the estimated
revenue DiD is **−376.06 INR** with 95% interval **[−764.33, +12.22]**.
Because zero is inside the interval, the engine returns `INCONCLUSIVE`.
The separate event-window API can run after the final day ceases to be an
alert, subject to the same source and access gates.

### 8. Contribution quantification

If an external counterfactual model supplies outcomes for **every** coalition
of two to four drivers, exact Shapley uses

`phi_i = Σ_(S⊆N\{i}) [|S|!(n−|S|−1)!/n!] × [v(S∪{i})−v(S)]`.

The modeled effects add to `v(all) − v(empty)`. The engine separately reports
`unexplained_residual = observed_movement − modeled_movement`. It does **not**
derive coalition outcomes from individual correlations or DiD estimates, so
this stage has no automatic dataset-specific causal ₹ allocation yet. Its
output is labeled `MODEL_BASED_SCENARIO`.

### 9. Evidence-quality diagnostics

Per-driver Attribution Confidence (AC) combines explained share, movement,
direction, timing, stability, statistical support, causal verdict,
document corroboration, and source quality. Hard caps are recorded alongside
the score: unsupported causal tests cap at 0.75, rejected tests at 0.20,
undeclared direction at 0.60, and non-material movement at 0.5 with an
`EXPLORATORY` band. AC is not calibrated as a real-world probability. Separate
causal diagnostics report coverage, timing, and interval precision; none can
upgrade an `INCONCLUSIVE` or `UNTESTABLE` result.

### 10. Narrative, grounding, and recommendations

The deterministic renderer produces approved sentences with evidence paths.
Validation rejects changed text, unsupported numbers/entities, or conflicting
claim states. Persona YAML controls claim order and allowed action levers;
persona selection cannot add facts or stronger claims. If a Groq key is
supplied, the LLM may select among approved sentence variants; it cannot add
free-form assertions. Invalid model output falls back to deterministic text.

The lever library produces persona-specific review cards, with a card kind
gated by AC and causal support. Eligible cards can show a low/high seven-day
projection from the fitted contribution interval; this is explicitly not
validated unless AC and causal conditions pass. Cards never execute changes.
Feedback is logged, but does not automatically recalibrate thresholds or
update a causal model.

## What the dataset review actually shows

`data/ground_truth_events.csv` contains six synthetic event windows. The
ground-truth harness evaluates 538 labeled cases across all six events and
quiet periods, with a separate 267-case holdout. See the final summary table
at the top of `docs/EVALUATION_BASELINE.md` for current metrics.

| Context | Material | Seasonal review | Not material |
| --- | ---: | ---: | ---: |
| Six documented event dates × five KPIs | 14 | 1 | 15 |
| Two reference dates × five KPIs | 0 | 0 | 10 |

The holdout false-alarm rate is 5.6%, and EVT06's weather driver does not win
top rank. EVT01's short post-period leaves the causal result inconclusive and
caps AC at 0.75. These are synthetic labels for six events; they are useful
for reproducible evaluation but do not establish behavior on production data.

## The honest jury claim

“The prototype runs five dataset-backed KPIs across daily, weekly, and
monthly sources. It distinguishes a material alert, exact accounting bridge,
correlational hypothesis, and conditional observational test; it shows its
evidence and abstains when a claim is unsupported. Our tests establish those
software boundaries. Independent event labels are still needed to establish
real diagnostic accuracy.”
