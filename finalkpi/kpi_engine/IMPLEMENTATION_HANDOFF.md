# Next-agent implementation guide

Status: documentation and comments only, prepared 2026-09-25. No DuckDB runtime,
schema migration, new formula evaluator or behavior change is implemented here.
The source of this plan is the user's audit and inspection of the current files.

## Read first

1. This guide for scope, sequence and cross-file dependencies.
2. [DuckDB implementation plan](duckdb/README.md) for the proposed data boundary.
3. The `IMPLEMENTATION HANDOFF`/`HANDOFF` comments in each Python and YAML file.
4. [Change record](DOCUMENTATION_CHANGELOG.md) for this documentation pass.

All existing runtime modules remain in place. `detect.py` and `causal.py` are
compatibility imports; moving them would require caller migrations. The new
`duckdb/` directory is documentation-only and deliberately has no `__init__.py`.
Implement the future runtime under `query/` to avoid confusion with the external
`duckdb` package. Do not move existing files just to match a proposed diagram.

## Current execution and boundaries

`pipeline.py` loads registry/access configuration and normalizes CSV inputs per
diagnosis. Access is checked before source loading. The source normalizer filters
availability, checks fixed daily/weekly keys, joins marketing lookups to sales and
keeps finance separate. Reconciliation can stop contradictory runs. Detection
computes daily KPI values; nonmaterial or unscorable runs return early. Material
runs build an optional accounting bridge and rank declared driver associations.
An explicit event design can request observational verification. Actions and
grounded narratives are generated from the resulting evidence.

`verify_event` assesses an event independently of a daily alert.
`quantify_scenario` allocates caller-supplied coalition outcomes independently of
the diagnosis flow. `corroborate.py` is a separate legacy helper, not an active
pipeline stage. Backend chat has its own retrieval implementation.

## Work in this order

| Priority | Task and owning files | Completion evidence |
| --- | --- | --- |
| P0 | Define calculation, source, coverage and comparison schemas in `contracts/`; map existing YAML without changing its meaning | Five current contracts resolve deterministically; unsupported methods and malformed fields fail before calculation |
| P0 | Specify numeric/null/zero, period completeness, timezone and revision policies | Hand-calculated cases distinguish valid zero, missing input and partial coverage; no unexplained partial sum |
| P0 | Implement the bounded query layer described in `duckdb/README.md` | Same scoped/as-of inputs produce matching pandas and SQL values; no source-specific branches needed for another supported KPI |
| P0 | Share prepared series and comparison plans through `pipeline.py`, `contracts/metrics.py`, detection, rank and verification | Detection delta and bridge total use identical periods/coverage; all consumers use one calculation definition |
| P0 | Resolve the omitted-category access gap in `access.py` and apply authorized scope in query reads | A category-limited role cannot omit the category to receive every category |
| P1 | Externalize analysis policies and make source reconciliation modes explicit | Resolved settings appear in results; closed-period and timestamped MTD snapshots have separate tests |
| P1 | Wire generic metadata and requests through backend and frontend | A new supported contract/source mapping works without adding KPI/region/category allowlists |
| P1 | Record actual source/contract/query/run lineage | Replaying the same snapshot and policy reproduces facts; execution time is separate from as-of time |
| P2 | Expand calendars, grains, decomposition methods and scenario model providers deliberately | Each capability has defined semantics and fixtures before it is advertised |

For a useful prototype, support a documented subset of calculations well. Full
context enables calculation only when its operator/grain is implemented; otherwise
return an explicit unsupported capability instead of guessing a formula.

## What belongs in configuration

- Source catalog: locations, formats, columns/types, natural keys, date/availability
  fields, timezones/calendars, revision selection and join keys/cardinality.
- Metric contract: authoritative values or structured expression, unit, source,
  dimension/temporal aggregation, dependencies and valid input/coverage rules.
- Comparison policy: actual period and baseline period(s), weighting, completeness
  and how the exact same comparison inputs reach detection and decomposition.
- Analysis policy: robust/seasonal choice, history, sustained window, scale floor,
  driver lag/search window/support threshold, verification thresholds and precision.
- Action catalog: optional driver-specific review text and owners.

Mathematical constants such as Shapley factorial weights, the six factor
permutations, MAD normalization and conversion from a fraction to percent are
method definitions. Do not convert every numeric literal into a YAML setting.
Defaults are acceptable when resolved centrally, validated and recorded in a run.

## Correctness details that must survive the migration

- `formula` currently documents intent; the aggregation fields execute it. Never
  evaluate arbitrary Python or untrusted SQL to make formula text executable.
- Preserve authoritative source revenue/orders rather than multiplying rounded
  rates. The current `aov` bridge is revenue per **unit**, not revenue per order.
- Ratio parts currently sum independently across missing inputs. Define whether
  to reject incomplete groups or use paired rows; do not silently inherit SQL's
  null-skipping behavior and call it complete data.
- A date having some sales rows does not establish complete segment coverage.
  Define expected active segments and distinguish launches/exits from missing data.
- Derived rates, inventory snapshots, unique counts and daily averages have
  different rollup rules. Do not assume temporal sum or mean from a column's type.
- Drivers need source-qualified columns; the current sales/marketing suffixing can
  otherwise make an overlapping name resolve to the wrong source.
- Weekly lag calculations need an unbroken weekly calendar. The current union of
  observed week indexes can compress a missing week. The target-week gate also
  needs revisiting when a valid lag uses an available earlier week.
- Treat late reports and revised data as separate concepts. A cutoff filter alone
  does not choose one revision for a natural key.
- Reconciliation should validate units, period ends, compatible scope and coverage;
  aggregate agreement can hide offsetting segment discrepancies.
- Static baselines currently abstain. Decide explicitly how to flag a step away
  from a constant baseline; do not invent a standard deviation.
- Keep `SUPPORTED_CONDITIONAL`, `CORRELATIONAL`, accounting effects and modeled
  scenario contributions distinct throughout APIs, narrative and chat.

## Contributions: contracts the next agent must preserve

Accounting bridge: `decompose.py` represents total value as total quantity times
the segment-share-weighted rate. It switches quantity, mix and rate from baseline
to current across all six orders, averaging each marginal effect. Effects reconcile
to observed movement. Missing-segment rate inheritance is an assumption requiring
coverage checks; output is currently rounded to two decimals.

Scenario allocation: `contribute.py` requires all subsets of 2-4 declared drivers.
For each driver and subset of the other drivers, it weights the marginal modeled
outcome by `|S|! * (n-|S|-1)! / n!`. Effects sum to the modeled full-minus-empty
movement. Residual is observed minus modeled. Shares use the signed observed
movement; they can be negative or exceed 100%, and are undefined at zero movement.
There is no data-fitted coalition provider today. Preserve that boundary and require
model/version/scope/as-of provenance before adding one. Individual DiD estimates
and correlation coefficients are not interchangeable coalition outcomes.

## Integration files outside the core package

These are follow-up implementation targets; this pass adds notes to the main
Python integration boundaries, without rewriting backend/frontend behavior.

| File | Required follow-up |
| --- | --- |
| `backend/config.py` | Dataset/catalog selection; derive defaults from valid available scope |
| `backend/service.py` | Reuse one prepared source snapshot across KPIs; accept generic dimensions and as-of; fail mixed invalid KPI requests explicitly |
| `backend/app.py`, `backend/schemas.py` | Align typed request/result schema with contract capabilities; expose explicit event/scenario operations if needed |
| `backend/storage.py` | Actual created_at, contract/policy hashes and source snapshot lineage; preserve existing runs |
| `backend/retrieval.py`, `backend/rag_pipeline.py`, `backend/ingest.py`, `backend/chat.py` | Retrieve numerical facts through the same query service and cutoff/scope; reconcile parallel chat paths and citation provenance |
| `frontend_bridge.py` | Use registry-discovered IDs and a valid shared entry point; current `from run_full_demo import run` needs checking because the demo module is under `tests/` |
| `frontend/app/api/diagnose/route.ts` | Remove fixed KPI/region/category/year allowlists and avoid a second diagnosis implementation |
| `frontend/app/page.tsx` | Consume dynamic metadata and resolved unit/period labels; check the active backend path before removing a legacy route |
| `pyproject.toml` | Add/pin an appropriate DuckDB dependency only when implementing; verify its official API documentation at that time |
| `tests/`, `backend/tests/` | Add hand-calculated parity/generalization fixtures and integration assertions rather than merely reproducing SQL text |

## Verification for the future implementation

First compare the existing five metrics and their statuses at identical source
cutoffs. Then test an additional supported source/KPI with different dimensions,
unequal ratio denominators, partial-null inputs, missing periods, late revisions,
duplicate keys, zero denominator, and a join that would multiply rows. Include a
restricted scope and denied control. Validate baseline and accounting totals from
hand-calculated fixtures. Correct known bugs with explicit expected-result changes,
not by forcing parity with erroneous output. Independently labeled alert evaluation
is separate from calculation parity and remains necessary for threshold tuning.
