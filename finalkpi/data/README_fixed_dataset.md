# Fixed dataset — what changed and why

Your original `kpi_dataset.csv` had a rock-solid causal structure (adstock,
saturation, elasticity, stockout capping, the two decoys) and 6 well-labeled
ground-truth events — none of that was touched. What was missing was
everything *around* the numbers that the brief scores you on. Six files now
replace the one:

## 1. `sales_daily.csv` — Source A: the operational system
Daily grain, one row per (date, region, category). This is your original
table's operational columns (orders, units, revenue, stock, latency,
conversion, channel split). `available_at` says when that day's row would
actually land in a warehouse — same day, next morning 06:00.

## 2. `marketing_weekly.csv` — Source B: the ad platform export
Weekly grain (Mon-Sun), aggregated up from the same underlying daily numbers
— spend, adstock, email sends, traffic by source. `available_at` is set to
week-end + 2 days, 09:00, matching how ad platforms actually batch-report.
This is your **different-grain, different-cadence** source: querying "this
week's marketing" and "today's sales" now genuinely means touching two
systems that don't refresh in sync.

## 3. `finance_monthly.csv` — Source C: the ledger of record
Monthly grain. Every *closed* month matches the sales rollup exactly
(`status = closed`). The **most recent month is `status =
provisional_open_month`** — finance's number only reflects data through 6
days before the snapshot date, because the ledger hasn't closed yet. Run the
script's printed reconciliation table and you'll see gaps of 16-20% between
what sales_daily says the month totals so far and what finance is currently
reporting for it. This is a real, demoable instance of "sources disagree
because of refresh timing, not because either is wrong" — exactly the kind
of reconciliation the brief wants you to handle explicitly, not paper over.

## 4. `unstructured_evidence.csv` — the retrieval corpus
11 short synthetic documents (support tickets, an internal engineering note,
promo-calendar entries, news snippets), each tagged with `date`, `region`,
`category`, `source_type`. They're timed inside the 6 ground-truth event
windows, so your retrieval layer has something real to find:
EVT01 gets a ticket about the paid-search budget cut, EVT03 gets stockout
tickets, EVT04 gets an engineering-incident note scoped correctly to
Online-only, EVT06 gets a news snippet about the cold snap plus a
merchandising note about the coat/sweater bump. This is what lets your
Analysis Engine move from "here's a number" to "here's corroborating
evidence," and lets Evidence & Confidence check whether sources agree.

## 5. Sparse-history segment — appended to `sales_daily.csv`
A brand-new `category = "Beauty"`, all 4 regions, **only the last 30 days**
of the dataset's timeline (2024-12-01 to 2024-12-30). No seasonal or
ad-stock machinery behind it deliberately — it's meant to break any pipeline
logic that assumes a full year of history exists before it'll compute a
baseline. This is your sparse-history / newly-launched-KPI scenario, ready
to use as-is.

## 6. `access_control.csv` — row-level ownership
One owner role per region (`regional_manager_north`, etc.) plus a `cfo` role
scoped to `ALL`. Deliberately minimal — this is metadata for your KPI
Registry / Data Adapter layer to enforce, not a data engineering problem.
Use it to demo: a North manager's query only ever returns North rows; the
CFO's query returns everything, aggregated.

## What this now satisfies from the brief

| Requirement | Covered by |
|---|---|
| 3-5 KPIs across 2-3 sources, different grains/cadences | sales_daily (daily) + marketing_weekly (weekly) + finance_monthly (monthly), each with its own `available_at`/`closes_at` |
| Multi-factor KPI movement with known drivers | EVT01-EVT06 in `ground_truth_events.csv`, untouched |
| Low-confidence / abstain scenario | EVT05 (marketing looks causal, isn't) |
| Sparse-history / newly-launched KPI | Beauty category, 30 days, all regions |
| Role-based security scenario | `access_control.csv` + region-scoped queries |
| Structured *and* unstructured data | `unstructured_evidence.csv` alongside the numeric sources |
| Evidence of source freshness/lineage | `available_at` / `closes_at` / `status` columns on every source |

Still needed from your side, not a data problem: 2+ persona narrative
templates, the KPI Registry config itself, and the pipeline code — that's
the implementation phase next.
