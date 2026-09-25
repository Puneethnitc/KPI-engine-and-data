# DuckDB implementation scaffold

This directory reserves and explains the work; it contains no runtime code,
database, SQL migration or dependency changes. Read
[the overall handoff](../IMPLEMENTATION_HANDOFF.md) first.

## Goal and boundaries

Prepare scoped, as-of-correct KPI and driver series once, using governed
calculations. DuckDB will handle source reads, validation queries, period bucketing,
joins, aggregation and retrieval. Python can retain statistical detection, MSTL,
DiD, Shapley allocation and narrative rendering. Keep SQLite for saved conversations
and feedback initially; replacing transactional storage is unnecessary for this goal.

## Proposed future runtime files

Create these under `kpi_engine/query/` when implementation starts. Do not name a
module `duckdb.py`, which could shadow the installed dependency in some launch modes.

| Future file | Responsibility and completion condition |
| --- | --- |
| `models.py` | Typed source spec, query request, resolved comparison plan and prepared-series result; no connections or reads |
| `catalog.py` | Resolve source IDs, aliases/types, keys, calendar and revision rules; missing or ambiguous references fail early |
| `connection.py` | Own a bounded connection lifecycle and source registration; no database opening at module import |
| `compiler.py` | Translate supported structured metrics into validated SQL plus bound parameter values and dependencies |
| `validation.py` | Check duplicate keys, data types, finite values, coverage and declared join cardinality before publishing results |
| `service.py` | Apply authorized scope/as-of and obtain KPI, driver, baseline, component and reconciliation series through shared semantics |
| `lineage.py` | Record actual source snapshots/hashes, contract/policy versions, SQL/template version, parameters and result coverage |

Start with a small number of modules if that is easier; these are responsibilities,
not a requirement to build seven abstractions before the first working query.

## Source catalog requirements

Every source needs an ID and location/format, explicit column mapping and types,
business date or period start/end fields, availability timestamp, timezone,
calendar/grain, natural key and revision rule. Dimensions and permitted relationships
must be declared. Each join declares its keys and expected cardinality. Never join
facts at incompatible grains and then sum multiplied measures.

Raw ingestion must retain source identity and row/revision references. Choose one
eligible revision per key after applying the availability cutoff. If the source is
an immutable snapshot, record its identity/hash and reject duplicate natural keys.
For this prototype, local source files and one analytic connection per prepared
request are sufficient; there is no requirement for a server, scheduler or cluster.

## Contract compilation

Begin with the four existing aggregations: sum, mean, weighted mean and ratio of
sums. Specify required fields and allowed operators; add arithmetic or dependency
expressions only with defined null/unit/aggregation semantics. Validate dependencies
and reject cycles. Keep descriptive formula text separate from executable structure.

Bind scope values, timestamps and other literal inputs as query parameters. Resolve
identifiers from a validated catalog and quote them correctly; table/column names
cannot simply be treated as value parameters. Do not execute raw user or LLM SQL.
The compiler returns SQL, parameter values and resolved policy so the result is
inspectable. Verify exact DuckDB APIs and supported syntax from official docs when
coding; no version-specific implementation has been selected in this scaffold.

## Canonical query/result contract

Inputs: metric ID + contract version, requested dimensions/filters, allowed scope,
actual period, comparison policy, as-of cutoff and source snapshot selection.

Outputs: period start/end, grain, dimension keys, raw metric value and unit,
numerator/denominator or weight components when needed, expected/observed coverage,
quality status/reasons, source references, contract/policy identity and query lineage.
Return baseline period membership/weights with component inputs so detection and
decomposition cannot silently use different windows.

Null is not zero. Reject or label incomplete groups according to the contract.
Ratios must use compatible numerator/denominator populations and explicit zero or
negative denominator rules. Weighted means must define nonnegative/zero weights
and paired validity. Do not average displayed rates or round inputs before analysis.

## Native grain and periods

Keep weekly marketing as one observation per native key/week. Aggregate compatible
daily KPI components to that week for comparison. Use a full calendar for gaps and
lags. Never turn seven copies of one spend value into seven independent data points.
Availability is a publication timestamp, not an event date or permission to infer a
future observation. A lagged driver can use an earlier eligible period even when
the target week's report is unavailable.

Support daily parity first. Add weekly/monthly bucketing with explicit calendar
rules next. Fiscal periods and unique-count/snapshot metrics can remain explicitly
unsupported until their semantics are implemented.

## Reconciliation queries

Closed-period mode selects comparable completed postings and checks both systems'
period coverage. Snapshot mode requires explicit finance coverage-end and publication
timestamps; select a revision available at the cutoff with coverage matching sales.
Do not infer a mid-month balance by distributing a monthly total across days.
Report unit, scope, period and absolute/relative discrepancy with resolved thresholds.

## Migration and acceptance

1. Add dependency and source catalog with read-only fixtures; no existing DB migration.
2. Query existing metric series through a feature-selectable adapter and compare
   against pandas plus independent hand-calculated expected results.
3. Prepare sources once per request and share results across all requested KPIs.
4. Move driver and reconciliation preparation to native-grain queries.
5. Feed detectors, bridges and verifier through prepared inputs; preserve public
   result fields while adding explicit unit, comparison, coverage and lineage.
6. Connect API/UI metadata and numerical chat retrieval to this same service.
7. Add one differently named source with different dimensions through config only.

Acceptance cases: unequal ratio denominators/weights, null inputs, missing segment
days, zero values, negative/invalid inputs per policy, duplicate and revised keys,
late publications, timezone boundaries, missing weeks, overlapping source column
names, join fan-out, denied scope, cold start and no comparable finance snapshot.
Numerical parity is sufficient for the data-layer migration; it does not validate
causal claims or calibrate anomaly thresholds.
