# KPI engine: a plain-language guide for a jury

**Status:** working local prototype, not a validated production service.  
**Code reviewed:** our `finalkpi` working tree and the public WhyChain snapshot at
[`b1d2649`](https://github.com/AbhiAltElite/Accenture/tree/b1d2649898491469a3e2778cf9b7ecff1e5b56dc).
The competitor may have changed after that commit.  
**Purpose of this guide:** explain what we built, why we chose each method,
where every important number comes from, what our dataset shows, and what we
still cannot honestly claim.

## The idea in one minute

Imagine a shop's revenue suddenly falls. A dashboard can show the fall, but a
manager needs more than an alarming chart. Our engine asks, in order:

1. **Can we trust the data we had at the time?** Check source freshness,
   permissions, and whether sales and finance agree where they can be compared.
2. **Is the movement genuinely unusual *and* large enough to matter?** Compare
   it with past days and the KPI's business threshold.
3. **What part of the arithmetic moved?** For revenue, separate units sold
   from revenue per unit. For orders, separate traffic from orders per visit.
4. **What might explain it?** Look for signals that moved earlier or at the
   same time, but label them as correlations.
5. **Does a proposed explanation survive a comparison?** Compare the affected
   group with an unaffected group before and after a predeclared event, and
   check that similar “effects” do not appear in quiet periods.
6. **What can a person do next?** Show the evidence, state uncertainty, and
   offer a review task or an approval-only proposal. The engine executes
   nothing.

The key promise is **not** “the computer always knows the cause.” It is that
each answer says what kind of evidence supports it—and says *we do not know*
when the evidence is insufficient.

## What we have built so far

We have five configured KPIs, three source roles, a tested local pipeline,
readable grounded explanations, review-only recommendations, a read-only jury
HTML report, and a provisional case-review script. The Python test suite had
**86 passing tests** at the time of this guide; tests prove specified software
behavior, **not** real-world detection accuracy.

| KPI shown to the jury | Where its value comes from | Simple meaning |
| --- | --- | --- |
| Net sales revenue | `sales_daily.net_sales_revenue`, summed | Money from sales, in INR |
| Orders | `sales_daily.orders`, summed | Number of orders in this synthetic dataset; values may be fractional |
| Units sold | `sales_daily.units_sold`, summed | Quantity of items sold |
| Total traffic | `sales_daily.traffic_total`, summed | Visits across channels |
| Conversion rate | `sum(orders) / sum(traffic_total)` | Orders per visit; not an average of displayed percentages |

These values come from the supplied synthetic CSVs. Marketing spend is in a
separate **weekly** file and finance revenue in a **monthly** file. They are
not additional KPIs in our current registry; they are evidence sources.

The files contain 8,880 daily sales rows from 2023-01-01 to 2024-12-30,
1,296 weekly marketing rows, and 292 monthly finance rows. Beauty appears
only near the end of the sales history to test a new/sparse segment. The data
are synthetic, so a passing demo is not evidence of performance on a real
company's data.

## Layer by layer: what happens and why

### 1. KPI contract: the rulebook

**In ordinary words:** A YAML file tells the engine what each KPI means,
which source column is authoritative, what unit it uses, what history it needs,
and which signals are allowed as candidate drivers. The Python registry
rejects malformed or contradictory definitions.

**Why:** “Revenue” can mean gross sales, net sales, invoiced sales, or cash
received. The calculation cannot be trusted until its definition is explicit.
Contracts also let the same pipeline handle five KPIs without five copies of
the code.

**Other option:** Hard-code each KPI in Python. We did not choose that for
supported calculations because it makes definitions harder to review and
change. YAML cannot magically implement a new source type or algorithm; such
changes still require code.

**Current data result:** All five installed KPI definitions load and pass
contract tests. Revenue and orders declare an accounting bridge; the other
three do not claim one.

### 2. Ingestion, freshness, and access: what was actually knowable?

**Rule:** A row can be used only if its publication time is no later than the
requested `as_of` time. Daily sales, weekly marketing, and monthly finance
retain their native grains. Duplicate keys and incompatible source columns
are rejected. A role check limits the requested region/category.

**Why:** A Monday diagnosis must not quietly use a weekly marketing report
that arrived on Tuesday. Repeating a weekly number across seven daily rows
for alignment must not turn it into seven independent observations.

**Other option:** Join all CSVs and use every row regardless of publication
time. That would make historical replay look better than the information a
real analyst had. A database with authenticated row-level security is the
right production direction; our CSV role check is only a prototype gate.

**Example from our data:** On the 2023-07-24 North/Electronics diagnosis,
sales is available by the default next-day-noon cutoff, but that week's
marketing report is not. The marketing driver is marked unavailable rather
than “zero.”

### 3. Reconciliation: do two systems agree?

**Formula:**

`gap % = 100 × |sales total − finance total| / |sales total|`.

The engine compares the *same month and region/category slice*, only when a
comparable finance posting is available. It reports `AGREED`, `DRIFT`,
`CONTRADICTED`, or `NOT_RECONCILED`. A contradiction stops diagnosis.

**Why:** It is risky to explain a revenue drop if the sales system and ledger
disagree about whether the drop happened.

**Other option:** Treat a missing finance figure as agreement, or compare a
partial sales month with a full finance month. Both would create a false
answer. Our finance file lacks timestamped provisional snapshots for honest
historical open-month comparison, so the July 2023 example correctly says
`NOT_RECONCILED`, not “agreed.”

### 4. Detection: is the movement unusual and meaningful?

The primary detector looks at preceding days. It uses a **median** for a
typical level and median absolute deviation (MAD) for a robust noise scale:

`robust scale = 1.4826 × median(|past value − past median|)`  
`point score = (today − past median) / robust scale`.

If MAD is nearly zero, it tries an IQR-based scale and then standard
deviation. It also examines a recent seven-day median, so a prolonged shift
is not missed merely because the final day is not an extreme point. The
business change is `today − mean(past days)`. A material alert requires
**both** an unusual robust score and a minimum change in the KPI's own unit.

Alongside this, a weekly-seasonal MSTL model forecasts today using **only
earlier days**. It compares the forecast error with 21 earlier one-step
forecast errors. If only the seasonal model flags a day, the output is
`SEASONAL_REVIEW`, not a trusted alert.

**Why these methods:** Median/MAD resists a few extreme past days. The
seasonal model recognizes normal weekly rhythms. The business-unit gate
prevents statistically unusual but trivial movements from alarming a manager.

**Other options:** A single plain z-score is easily distorted by outliers;
an OR rule between two detectors can increase false alarms. More complex
BSTS/BOCPD/CUSUM ensembles were deferred because we lack reviewed labels
with which to tune or compare them. MSTL is used for a seven-day rhythm here;
annual holidays have **not** been validated.

**Current data result:** In a provisional review of six documented event
dates across five KPIs, 14 KPI–date checks were material and one was
seasonal-review. Ten KPI–date checks on two reference dates were all
non-material. This is encouraging case behavior, **not a detection-accuracy
score**: the event notes are not independent labels, the sample is tiny, and
not every KPI should react to every event.

### 5. Exact decomposition: what changed inside a KPI?

For one revenue slice, think of `revenue = units × revenue per unit`. The
engine divides the change fairly between the two factors:

`units effect = (units now − units before) × average(before rate, now rate)`  
`rate effect = (rate now − rate before) × average(before units, now units)`.

For a slice containing several regions/categories, it also separates **mix**:
selling a different proportion of each category can change overall revenue
even if total units and within-category rates are unchanged. The engine
averages over all six orders in which quantity, mix, and rate could be changed
(exact three-factor Shapley), so the split is not dependent on an arbitrary
order. The displayed parts must add back to the measured change.

For orders, the same identity uses `orders = traffic × orders per visit`.
Rates are derived from source totals, not rounded display columns.

**Why:** This gives a mathematically checkable answer to *what changed*.
**What it cannot tell us:** It does not prove that changing traffic or price
*caused* the result. A manager should not read “units effect” as “units are
the independent root cause.”

**Other option:** Change volume first, then mix, then price. That also gives
an exact bridge but assigns interaction effects according to the chosen
order. Our symmetric approach avoids that choice. Ratio-KPI mix
decomposition is not yet implemented, so a material conversion-rate case
reports `NOT_APPLICABLE` instead of a made-up breakdown.

**Real prototype example:** North/Electronics on 2023-07-24 showed revenue
change **−1364.15 INR**: units effect **−1493.60**, mix **0**, rate effect
**+129.45**. Those parts add to −1364.15.

### 6. Correlational ranking: what is worth investigating?

For an allowed candidate such as checkout latency, stockouts, or ad spend,
the engine compares **changes** rather than raw levels:

`r(lag) = correlation(change in KPI today, earlier change in driver)`.

It checks short nonnegative lags, retains independent daily/weekly sample
sizes, and labels every returned candidate `CORRELATIONAL`. A rejected or
unavailable candidate carries a reason.

**Why:** This is a simple, understandable way to find leads without claiming
they are causes. Differencing reduces some misleading shared trends.

**Other option:** WhyChain uses standardized ridge regression, which can
handle several correlated signals at once. We kept a simpler ranking because
our data and validation do not yet justify interpreting a larger model's
coefficients. Neither a correlation nor a ridge coefficient proves causation.

**Known issue:** For the conversion-rate KPI, the *weekly marketing-ranking*
path currently averages seven daily rates. It should use weekly
`sum(orders) / sum(traffic)` instead. The daily KPI definition is correct;
this weekly ranking path needs a fix before its conversion-rate result is
trusted. On one North/Electronics week the two calculations were 0.019372
and 0.019248, respectively.

### 7. Observational verification: does a proposed cause survive checks?

This does **not** run automatically from a correlation. A person must provide
the proposed event date, named driver, affected group, unaffected comparison
group, expected direction, and earlier quiet periods.

The main difference-in-differences (DiD) formula is:

`effect = (affected after − unaffected after) − (affected before − unaffected before)`.

The engine estimates the change in the affected-minus-unaffected daily gap,
with a HAC 95% confidence interval. It also asks: Did the driver really
change at the proposed start? Was the KPI already diverging before it? Does
the same method find a suspicious “effect” during quiet placebo windows?

**Why:** A company-wide holiday can lower both groups. Comparing with a
control can remove some shared background movement. Pretrend and placebo
checks challenge convenient but weak stories.

**Other options:** Automatic causal graphs, Granger tests, or synthetic
controls require additional assumptions and data. We chose an explicit,
auditable one-control test first. This is still observational: a good result
is `SUPPORTED_CONDITIONAL`, **never proof**. No valid control or insufficient
history means we abstain.

**Actual data example:** For North/Electronics versus South/Electronics,
ending 2023-08-06, the estimated revenue effect was **−376.06 INR** and the
95% interval was **[−764.33, +12.22]**. Because zero is inside that interval,
the result is `INCONCLUSIVE`—we do not name a proven cause.

### 8. Model-based contribution: how much might each driver account for?

If an external counterfactual model provides the outcome for **every
combination** of two to four proposed drivers, exact Shapley shares that
model's predicted movement across them. For each driver, it averages what
adding that driver changes over every possible set of already-added drivers.

`unexplained remainder = observed movement − model-predicted movement`.

**Why:** Interacting drivers cannot safely be assigned money by simply
adding their separate DiD estimates. Shapley provides a fair allocation
*of a specified model*. It is marked `MODEL_BASED_SCENARIO`, not verified
causal revenue.

**Current status:** We do not have a validated coalition model for this
dataset, so the pipeline does **not** automatically claim that a given driver
caused a particular INR amount. This is an honest limit, not a missing sum.

### 9. Evidence quality: how much of the test could we actually trust?

The engine reports three separate diagnostics: enough pre/post observations,
whether the event timing passed the pre-event checks, and how narrow the DiD
interval is relative to its estimated effect. It **does not average them into
a “70% chance this cause is true.”** An inconclusive causal test stays
inconclusive even if data coverage is excellent.

**Why:** A single confidence number would suggest calibration that we have
not earned. True probability calibration needs held-out labeled cases.

### 10. Explanation, recommendations, and feedback

The engine turns results into approved sentences with evidence paths. Its
validator blocks changed numbers, names, and stronger causal wording. With
an optional Groq key, an LLM may choose among **preapproved sentence
versions**, but cannot add unrestricted new claims. If the provider fails or
returns an invalid choice, deterministic text is used. A live provider call
has not been validated here.

Recommendations come from a closed library: weak evidence leads to a
`NEXT_CHECK`; conditional support can lead to an `AWAITING_APPROVAL` proposal.
No recommendation executes, and none invents a recovery estimate. User
feedback can be logged but does not yet change the model automatically.

## Where do the numbers and constants come from?

This distinction matters. A value read from the dataset is not the same as
a mathematical constant or a threshold chosen by us.

| Value or setting | Source | What it means / how defensible it is |
| --- | --- | --- |
| Daily revenue, orders, units, traffic, operational signals | Supplied `data/sales_daily.csv` | Synthetic observations; actual inputs for each diagnosis |
| Weekly spend and publication time | Supplied `data/marketing_weekly.csv` | Independent weekly source; unavailable until its `available_at` |
| Finance postings and closing time | Supplied `data/finance_monthly.csv` | Comparison source, not automatically equal to sales |
| Region/category permissions | Supplied `data/access_control.csv` | Local role policy, not authenticated DB security |
| KPI definitions and units | Five YAML files in `kpi_engine/registry/` | Explicit project configuration; source columns are not invented by the LLM |
| `1.4826 × MAD`, IQR divisor `1.349` | Standard robust-scale normalizations in detector code | Converts robust dispersion estimates to roughly standard-deviation scale under a normal model; the normal approximation may not fit every KPI |
| Seven-day seasonality | YAML `seasonal_period: 7` | Calendar/weekly rhythm for daily data; annual rhythm not modeled |
| 2.5 robust-score threshold | Every KPI YAML | **Provisional engineering choice**, not tuned on independent labels |
| Business thresholds: 500 INR, 5 orders, 10 units, 100 visits, 0.003 orders/visit | Corresponding KPI YAMLs | **Provisional materiality choices**; a business owner has not signed them off |
| History: 60 days for four KPIs, 30 for orders | KPI YAMLs | Prototype minimums; sparse Beauty cases should abstain |
| MSTL 21 forecast-error calibration days; minimum 60 fit days; default 90-day fit window | `kpi_engine/detection/seasonal.py` | Engineering sample-size/window choices, not optimized on held-out events |
| Reconciliation tolerance 3.5% and contradiction multiple 2.5 (8.75% boundary) | Defaults in `kpi_engine/reconcile.py`, used because YAMLs do not override them | Prototype policy; **not** a finance-approved tolerance |
| Ranking lag 0–7 days, `|r| >= 0.3`, at least 14 daily / 8 weekly paired changes, 120-day window | `kpi_engine/rank.py` | Exploratory display settings, not statistical significance claims |
| DiD at least 14 pre days, 7 post days, 2–3 quiet windows of at least 14 days | `kpi_engine/verification/did.py` | Minimum design requirements chosen for prototype feasibility |
| Weekly treatment must start Monday; 3 complete pre and 2 complete post weeks | `kpi_engine/verification/did.py` | Prevents pretending a weekly report resolves a midweek event |
| 95% HAC interval, pretrend `p < 0.05`, pre-event shift at 0.75× effect, placebo at 0.5× effect | `kpi_engine/verification/did.py` | Conventional interval plus **heuristic** gates; not proof or calibrated error control |
| Shapley two to four drivers | `kpi_engine/contribute.py` | Exact enumeration is cheap at this size; coalition values must come from an external model |
| LLM model, temperature 0, five-second timeout | `kpi_engine/narrative.py` | Operational defaults; they do not guarantee truth, which is why output is constrained |
| Review-case dates | `examples/review_windows.yaml`, copied from `data/fix_dataset.py` comments | Provisional contexts, **not independently reviewed ground truth** |

The main point for the jury: **a threshold is not “learned from the data”
just because it appears in a YAML file.** Most cutoffs above are explicit
prototype choices and must be evaluated and approved before deployment.

## How well does it work on this dataset?

The case-review script selected one date in each of six event windows
documented by the dataset generator, plus two reference dates. It ran all
five KPIs on each date: **40 KPI–date results**.

| Context | Material alert | Seasonal-only review | Not material |
| --- | ---: | ---: | ---: |
| Six documented event dates × five KPIs | 14 | 1 | 15 |
| Two reference dates × five KPIs | 0 | 0 | 10 |

At least one KPI alerted on each of the six sampled event dates, and all 40
generated narratives passed their deterministic grounding check. This shows
the pipeline can produce useful, internally consistent outputs on supplied
examples. It does **not** establish precision, recall, false-alarm rate, or
causal accuracy. We lack the referenced `ground_truth_events.csv`, the two
reference dates are too few, and these cases come from the same synthetic
scenario documentation rather than an independent holdout.

## How are we different from WhyChain, the competing team?

We inspected the public [WhyChain snapshot](https://github.com/AbhiAltElite/Accenture/tree/b1d2649898491469a3e2778cf9b7ecff1e5b56dc),
not its private evaluation results. We did **not** copy their code. Both
teams use established ideas such as robust seasonal detection, exact
accounting identities, correlation-vs-causation separation, DiD/placebos,
source reconciliation, and cautious narration. Using the same named method
does not make two implementations identical—or one better.

| Question | Our prototype | WhyChain snapshot | Fair conclusion |
| --- | --- | --- | --- |
| Detecting unusual movement | Robust point/sustained score is primary; separate MSTL forecast can trigger review | [MSTL residual with robust score](https://github.com/AbhiAltElite/Accenture/blob/b1d2649898491469a3e2778cf9b7ecff1e5b56dc/whychain/detect/anomaly.py), with grain-aware settings | Different alert policies; neither is proven more accurate on a shared test |
| Explaining arithmetic | Order-independent quantity/mix/rate Shapley bridge | [Sequential price/volume/mix bridge](https://github.com/AbhiAltElite/Accenture/blob/b1d2649898491469a3e2778cf9b7ecff1e5b56dc/whychain/decompose/bridge.py) | Both can reconcile exactly; ours avoids a path-order choice |
| Finding possible drivers | Lagged change-correlation, explicit `CORRELATIONAL` label | [Standardized ridge ranking](https://github.com/AbhiAltElite/Accenture/blob/b1d2649898491469a3e2778cf9b7ecff1e5b56dc/whychain/rank/tracks.py), also separates correlational track | Ours is simpler to inspect; theirs can model several correlated signals together |
| Challenging a proposed cause | One treated/control comparison, timing checks, HAC DiD interval, 2–3 quiet windows | [DiD, isolation, multi-region exposure consistency, and more placebos](https://github.com/AbhiAltElite/Accenture/blob/b1d2649898491469a3e2778cf9b7ecff1e5b56dc/whychain/verify/tests.py) | Their verification covers more multi-region cases; ours is narrower and explicit about it |
| Contribution | Exact accounting bridge plus *optional* Shapley of fully supplied counterfactual coalition values | Dimensional arithmetic contribution and exact bridge | Our model-based contribution refuses to turn one DiD effect into invented INR allocations |
| Confidence and communication | Separate uncalibrated evidence diagnostics; constrained approved sentence variants | Broader scoring/calibration, document evidence links, and review UI described in their [README](https://github.com/AbhiAltElite/Accenture/blob/b1d2649898491469a3e2778cf9b7ecff1e5b56dc/README.md) | They currently present a more complete product; ours avoids a causal-probability claim without labels |

What we can defend as **distinct design choices**: visible disagreement
between two detection views, an order-independent accounting bridge,
explicit `NOT_RECONCILED` and `INCONCLUSIVE` states, and refusal to invent
counterfactual Shapley money. What we **cannot** defend today: “we are more
accurate than WhyChain.” That requires the same labeled test set and metrics
for both systems. WhyChain's repository describes a richer UI, evidence
links, and broader verification; we should acknowledge those strengths.

## What should happen next?

1. **Weekly conversion-rate ranking formula — fixed.** It now uses a weekly
   ratio of summed orders and traffic, with a regression test designed to
   distinguish that from averaging daily rates.
2. **Get reviewed event labels.** Recover `ground_truth_events.csv` or create
   an independently reviewed holdout with genuine events, quiet periods,
   decoys, expected affected KPIs, and onset dates. Then measure false
   alerts, misses, timing, and abstention. Tune thresholds *only on training
   cases*, then report held-out results.
3. **Stress-test causal designs.** A separate helper now reports all
   predeclared control/window results without selecting a winner. Multiple
   eligible controls, exposure consistency across affected slices, and
   dataset-specific sensitivity review remain to be completed.
4. **Validate the real LLM path and usability.** Test provider failure,
   malicious suggestions, persona access, and whether reviewers can follow
   evidence. The current HTML file is a read-only local report, not an
   authenticated application.
5. **Plan production data access only if deployment is required.** Replace
   CSV reads and caller-supplied roles with authenticated database queries,
   row-level policy, logging, and controlled release.

The prototype is suitable for a **transparent demonstration** now. It is not
yet suitable for claims of measured diagnostic superiority or unattended
business decisions.

## A short script to say aloud

> “Our engine does not jump from a falling number to a confident story. It
> first checks whether the data were available and whether sources agree.
> It then asks whether the change is unusual and large enough to matter.
> For revenue and orders it gives an exact accounting breakdown, but labels
> that as arithmetic, not cause. It separately offers correlated signals
> as investigation leads. A proposed cause must survive a before-and-after
> comparison against a control and quiet-period checks; otherwise the engine
> says it cannot verify it. Every sentence and next step stays tied to the
> evidence. We can demonstrate this across five synthetic KPIs today; the
> missing independently reviewed event labels are what we need next to
> measure real accuracy.”
