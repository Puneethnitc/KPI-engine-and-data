# KPI engine methodology and dataset evidence

This is a presentation guide for the **local research prototype**, not a claim
of production accuracy or proved causation. The implementation is under
`kpi_engine/`; `run_jury_review.py` creates a read-only five-KPI report and
`run_review_benchmark.py` reproduces the provisional case review below.

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

Where a comparable finance posting exists, the same month and slice are
compared:

`gap_% = 100 × |sales_total − finance_total| / |sales_total|`.

The contract's default tolerance is 3.5%; `AGREED` is within tolerance,
`DRIFT` is above tolerance up to 8.75% (2.5 × tolerance), and
`CONTRADICTED` is above that. A contradiction stops diagnosis. A missing or
non-comparable posting yields `NOT_RECONCILED`, **not** agreement. The current
finance extract has no timestamped provisional snapshots suitable for
historical open-month comparisons, so the default 2023-07-24 run is
`NOT_RECONCILED`. This is a conservative gate, not evidence that finance
disagreed.

### 4. Detection and materiality

The primary detector compares the target against a preceding rolling window.
Its robust center is the historical median, and its first dispersion estimate
is `1.4826 × MAD`, where `MAD = median(|x_i − median(x)|)`. IQR and then
standard deviation are fallback scales when MAD collapses. It computes a
point score `(target − robust_center) / robust_scale` and a sustained score
using the median of a recent seven-day window against earlier history.

The business change is `delta = target − mean(prior window)`. A trusted
material alert requires **both** a robust point/sustained threshold and
`|delta| >=` the contract's absolute threshold. The thresholds are currently
2.5 robust-score units plus 500 INR for revenue, 5 orders, 10 units, 100
visits, or 0.003 orders/visit for the other KPIs. They are provisional, not
calibrated to a measured false-alarm rate. Missing days, too little history,
or an unscorable baseline produce explicit states rather than “normal.”

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

For each contract-declared driver, the exploratory statistic is
`corr(ΔK_t, ΔD_(t−lag))` over available paired observations. Daily lags span
0–7 days; weekly signals are assessed at weekly grain. At least 14 daily or
8 weekly pairs are needed, and `|r| >= 0.3` is the current display filter.
These cutoffs are heuristic. Differencing reduces shared-trend artifacts but
does not remove confounding. Every row is explicitly `CORRELATIONAL`, and
excluded drivers get a reason such as unavailable source, insufficient pairs,
flat signal, or weak association. The driver's own change percentage is not a
percentage contribution to the KPI movement.

### 7. Observational verification

Only a supplied event design can trigger this layer: named driver, treated
slice, authorized control, intervention date, expected directions, pre/post
periods, and two or three earlier quiet windows. The core difference-in-
differences quantity is:

`DiD = (treated_post − control_post) − (treated_pre − control_pre)`.

Equivalently, an OLS regression on the daily treated-minus-control gap uses a
post-period indicator; HAC standard errors produce a 95% interval. The layer
also checks that driver exposure changed relative to control at the proposed
start, that the treated-control gap was not already moving, that the pretrend
is acceptable, and that quiet-window placebo effects are small. One treated
and one control slice are supported. Failed assumptions abstain; a passing
result is `SUPPORTED_CONDITIONAL`, **not proof**.

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

There is **no composite causal probability**. The three separate diagnostics
are: outcome-window coverage `min(1, pre_days/14, post_days/7)`; a binary or
unavailable temporal-precedence check; and a bounded DiD interval-precision
diagnostic, zero when the interval contains zero. They describe available
evidence; no strong sub-score can upgrade `INCONCLUSIVE` or `UNTESTABLE`.

### 10. Narrative, grounding, and recommendations

The deterministic renderer produces approved sentences with evidence paths.
Validation rejects changed text, unsupported numbers/entities, or conflicting
claim states. If a Groq key is supplied, the LLM may select among approved
sentence variants; it cannot add free-form assertions. Invalid model output
falls back to deterministic text. No live-provider result has yet been
validated in this workspace.

The lever library gives a `NEXT_CHECK` for unverified evidence, or a proposed
action marked `AWAITING_APPROVAL` after conditional observational support.
It executes nothing and invents no recovery estimate. Feedback is logged,
but it does not yet recalibrate thresholds or automatically update a causal
model.

## What the dataset review actually shows

`examples/review_windows.yaml` contains six event windows copied from the
dataset generator's comments and two reference contexts. One sampled date
from each context was evaluated across all five KPIs (40 KPI–case results):

| Context | Material | Seasonal review | Not material |
| --- | ---: | ---: | ---: |
| Six documented event dates × five KPIs | 14 | 1 | 15 |
| Two reference dates × five KPIs | 0 | 0 | 10 |

At least one KPI was material on each of the six sampled event dates, but
**not every KPI should necessarily move in every event**. The two reference
dates are not a representative negative set. All 40 generated narratives
passed grounding. These descriptive counts are **not precision, recall,
false-positive rate, or causal accuracy**. The referenced
`ground_truth_events.csv` is missing from the supplied project/archives; the
labels need independent review and a held-out evaluation before accuracy
claims. Thresholds, multiple-control robustness, actual LLM behavior, and
database-backed access likewise still require validation.

## The honest jury claim

“The prototype runs five dataset-backed KPIs across daily, weekly, and
monthly sources. It distinguishes a material alert, exact accounting bridge,
correlational hypothesis, and conditional observational test; it shows its
evidence and abstains when a claim is unsupported. Our tests establish those
software boundaries. Independent event labels are still needed to establish
real diagnostic accuracy.”
