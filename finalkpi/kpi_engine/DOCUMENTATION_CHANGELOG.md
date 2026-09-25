# Documentation change record — 2026-09-25

## 2026-09-25 — Stage: access-control and numerical metric routing

Request: enforce the actual role-based access policy for diagnosis scope and numerical chat retrieval without widening the project beyond the active service path.

What changed in this pass:

- `backend/service.py` now validates the caller’s requested region/category against the configured access policy before accepting a diagnosis request, instead of relying on ad hoc scope checks alone.
- `backend/service.py` prepares KPI requests from a catalog-backed `QueryService` source snapshot rather than reusing a fixed sales-only dataset path; this keeps the requested scope and `as_of` in the same metadata-driven flow.
- `backend/rag_pipeline.py` now checks persona access before serving a numerical metric summary, so the numerical retrieval path honors the same access boundary as the diagnosis API.

Validation performed:

- `cd '/home/mansoor/Accenture Innovation Challenge/KPI-engine-and-data/finalkpi' && ./.venv/bin/python -m unittest backend.tests.test_backend_diagnosis tests.test_rag_fallback -q`
  -> 6 tests ran, 6 passed.
- `cd '/home/mansoor/Accenture Innovation Challenge/KPI-engine-and-data/finalkpi' && ./.venv/bin/python -m unittest discover -s tests -q`
  -> 118 tests ran, 118 passed.

Scope note: this pass stays inside the API access and numerical retrieval boundary. It does not change the public KPI output contract beyond enforcing the configured authorization policy.

## 2026-09-25 — Stage: config-driven source catalog validation

Request: replace the hardcoded source definitions in `kpi_engine/query/catalog.py` with validated metadata loaded from configuration, while preserving the bundled three sources and allowing new sources with new dimensions to be added without editing Python source.

What changed in this pass:

- `kpi_engine/query/catalog.py` now loads source metadata from a YAML config file, keeps the bundled three sources as the default catalog, and merges any extra config-defined sources without requiring source-specific branching in Python.
- The catalog validates dimensions, natural keys, date and availability fields, grain, revision policy, and declared field metadata before a source becomes active.
- `kpi_engine/query/source_catalog.yaml` is the default source catalog configuration preserving the bundled `sales_daily`, `marketing_weekly`, and `finance_monthly` sources.
- `tests/fixtures/source_catalog_config.yaml` adds a test-only source entry with a new `channel`/`region` dimensional model and revision metadata, proving config-only onboarding works.
- `tests/test_query_layer.py` adds a regression covering config-driven source registration and KPI calculation without a Python `if source_id == ...` branch.

Validation performed:

- `cd '/home/mansoor/Accenture Innovation Challenge/KPI-engine-and-data/finalkpi' && ./.venv/bin/python -m unittest tests.test_query_layer -q`
  -> 12 tests ran, 12 passed.

Scope note: this pass stays within the query catalog and validation boundary. It does not change the broader engine pipeline or rewrite the backend routing layer beyond the metadata-based source resolution it depends on.

## 2026-09-25 — Stage: DuckDB execution path and metric parity fix

Request: complete the query-layer execution path so a catalog-backed metric request runs the compiled SQL through DuckDB instead of returning raw source rows, while preserving scope/as-of handling and matching the existing pandas `daily_values()` behavior for the registered KPI contracts.

What changed in this pass:

- `kpi_engine/query/service.py` now registers the filtered source frame in an in-memory DuckDB connection, executes the compiled SQL with bound parameters, and returns aggregated `metric_value` rows in the `PreparedSeries` result instead of the original CSV records.
- `kpi_engine/query/connection.py` now supports registering a pandas DataFrame directly and normalizes pandas string-dtype columns before DuckDB registration so source tables load reliably.
- `kpi_engine/query/compiler.py` now respects the source catalog’s declared date column when defaulting `GROUP BY`, which keeps weekly/monthly sources aligned with their native grain rather than assuming a literal `date` column.
- `tests/test_query_layer.py` now includes a parity regression that iterates over the registered KPI contracts and compares the DuckDB-backed output to the reference `daily_values()` series for the same filtered source slice.

Validation performed:

- `cd '/home/mansoor/Accenture Innovation Challenge/KPI-engine-and-data/finalkpi' && ./.venv/bin/python -m unittest tests.test_query_layer -q`
  -> 11 tests ran, 11 passed.
- `cd '/home/mansoor/Accenture Innovation Challenge/KPI-engine-and-data/finalkpi' && ./.venv/bin/python -m unittest discover -s tests -q`
  -> 117 tests ran, 117 passed.

Scope note: this pass stays within the query-layer execution boundary and acceptance coverage for the active DuckDB foundation. It does not broaden into a full data-layer migration or a replacement of the broader diagnosis pipeline.

## 2026-09-25 — Session summary: stage review, implementation, validation, and acceptance cleanup

This session began with a targeted documentation and runtime-boundary review of the
current engine state, followed by a stage-scoped implementation pass and a final
acceptance review.

What we did from the start of the session:

- Read the handoff and planning documents to establish the active implementation
  boundaries: `kpi_engine/IMPLEMENTATION_HANDOFF.md`,
  `kpi_engine/duckdb/README.md`, and `kpi_engine/DOCUMENTATION_CHANGELOG.md`.
- Kept the work limited to the requested Stage I scope and avoided unrelated
  edits while preserving other working-tree changes.
- Ran the existing engine and backend tests to identify the active entry points,
  confirm the five registered KPIs, and capture reproducible results before
  making broader changes.
- Separated known failures from the work in scope and did not broaden the fix
  into unrelated engine or migration areas.
- Replaced fixed dataset/KPI/dimension allowlists with catalog and registry
  metadata in the active request path, rather than hardcoding demo-only values.
- Passed generic `scope` and `as_of` through the live diagnosis and chat API
  path so the service respects caller intent and metadata-driven defaults.
- Routed numerical chat retrieval through the shared metric service instead of a
  narrow fallback path.
- Added a small independent fixture with different source names and dimensions,
  including unequal ratio denominators, missing periods, revisions, and a
  restricted scope, to validate configuration-only onboarding.
- Reviewed the diff against the stage acceptance criteria to catch unintended
  behavior changes and residual hardcoded assumptions.
- Removed the remaining hardcoded business-policy assumption in the service layer
  so the configured access policy remains the real gate rather than a fixed
  persona check.
- Fixed the SQLite path-resilience issue that surfaced during validation,
  ensuring the storage layer can create its parent directory before opening the
  database file during temp-path and reload scenarios.
- Updated the change record to reflect the actual implementation, validation
  evidence, and the final acceptance check.

What passed in validation:

- `python -m unittest tests.test_query_layer tests.test_storage_metadata tests.test_chat_storage -v`
  -> 10 tests ran, 10 passed
- `python -m unittest backend.tests.test_backend_diagnosis -v`
  -> 3 tests ran, 3 passed
- `python -m unittest backend.tests.test_backend_diagnosis tests.test_query_layer tests.test_storage_metadata tests.test_chat_storage -v`
  -> 15 tests ran, 15 passed

The final scope stayed within the registry/catalog-backed routing work and the
associated API/storage regression cleanup. It did not expand into a full DuckDB
migration or a broader pipeline rewrite.

Request: explain current engine code, annotate future changes for the next coding
agent, prepare a DuckDB implementation scaffold, and record all edits. Baseline
commit inspected: `873da2e` (the working tree was not fully clean).

Scope completed: all 28 Python files and five YAML contracts under `kpi_engine`,
all five existing package READMEs, four Python integration boundaries, and three
new documentation files. Total: 42 existing files edited and three files created.
The additions are comments, explanatory Markdown and blank-line separation only.
No executable statements, existing docstrings, imports, contract values, dependency
versions, data files or database contents were changed. No files were moved/deleted.

## Existing modules and exact kinds of additions

Paths in this table are relative to `finalkpi/`.

| File | Recorded addition |
| --- | --- |
| `kpi_engine/__init__.py` | Package handoff marker, side-effect-free import guidance and roadmap pointers |
| `kpi_engine/pipeline.py` | Stage-order/ownership header; local notes on fixed source roles, supplied coalition inputs, shared comparison window, segment coverage, derived rate labels and lag-aware weekly availability |
| `kpi_engine/normalize.py` | Catalog/validation migration header; local notes on revenue-per-unit naming and declared join keys/cardinality |
| `kpi_engine/access.py` | Current CSV guard limitations, authorization boundary, omitted-category gap and scope acceptance checks |
| `kpi_engine/action.py` | Current fixed lever catalog, future configured actions/owners and evidence checks |
| `kpi_engine/confidence.py` | Diagnostic interpretation, shared verification-policy denominators and unknown-evidence rules |
| `kpi_engine/contribute.py` | Coalition Shapley inputs/math/residual explanation, provider provenance and percentage interpretation |
| `kpi_engine/corroborate.py` | Standalone legacy status, separate backend retrieval path, cutoff/scope/load-error and evidence limitations |
| `kpi_engine/decompose.py` | Accounting bridge assumptions, baseline/precision/coverage plan; local comments on derived rates and six switching orders |
| `kpi_engine/rank.py` | Policy constants, native-grain preparation, source qualification and stability checks; local comments on lag selection and missing-week calendar compression |
| `kpi_engine/reconcile.py` | Closed-period behavior versus MTD naming, snapshot/unit/scope policy and offsetting discrepancy checks |
| `kpi_engine/narrative.py` | Approved-claim rendering and optional wording selection; future units/coverage/lineage and grounding checks |
| `kpi_engine/feedback.py` | Pending-review persistence and backend alignment; record/persistence section comments and blank-line separation |
| `kpi_engine/evaluation.py` | Independent-label boundary, future lineage and metric parity versus alert calibration |
| `kpi_engine/detect.py` | Compatibility-facade explanation and migration guard |
| `kpi_engine/causal.py` | Compatibility-facade explanation and removed-API guard |
| `kpi_engine/contracts/__init__.py` | Stable exports and import-side-effect guidance |
| `kpi_engine/contracts/models.py` | Current versus executable semantics, schema/policy validation plan; threshold/model section comments and spacing |
| `kpi_engine/contracts/registry.py` | Loader ownership, schema-version versus KPI-version guidance, nested validation and hash requirements |
| `kpi_engine/contracts/metrics.py` | Current aggregation reference, shared-service migration and partial-null/temporal-rollup acceptance cases |
| `kpi_engine/detection/__init__.py` | Public API and prepared-series migration note |
| `kpi_engine/detection/models.py` | Payload semantics, unit/comparison/coverage/lineage and raw/display precision plan |
| `kpi_engine/detection/robust.py` | Scoring center versus mean baseline, current policy defaults, static/scale/calendar checks |
| `kpi_engine/detection/seasonal.py` | Current fit/calibration settings, prepared-series policy and no-future-fit checks |
| `kpi_engine/detection/ensemble.py` | Robust-primary decision/early-return behavior, shared series and explicit policy change guard |
| `kpi_engine/verification/__init__.py` | Stable explicit-design public API note |
| `kpi_engine/verification/models.py` | Design/result provenance, predeclaration limits, units and evidence-label checks |
| `kpi_engine/verification/did.py` | Current regression/gates, fixed policy values, sensitivity access boundary and per-day effect interpretation |
| `backend/config.py` | Bundled dataset/default assumptions and future catalog selection |
| `backend/service.py` | Shared request preparation, generic scope/as-of, metadata and unknown-KPI validation plan |
| `backend/storage.py` | Current fixed lineage/created_at behavior, future real provenance and preservation of SQLite records |
| `frontend_bridge.py` | Fixed IDs, shared-entry-point migration and demo-module import-path investigation note |

## Existing YAML and Markdown

| File | Recorded addition |
| --- | --- |
| `kpi_engine/registry/net_sales_revenue.yaml` | Authoritative revenue, derived-rate naming, reconciliation defaults and coverage/currency checks; separated identity, thresholds, bridge, reconciliation and drivers |
| `kpi_engine/registry/orders.yaml` | Recorded/fractional orders, derived conversion and zero-traffic/cancellation checks; separated major contract sections |
| `kpi_engine/registry/conversion_rate.yaml` | Ratio-of-sums, paired nulls, fraction/percentage-point units and denominator checks; separated major contract sections |
| `kpi_engine/registry/units_sold.yaml` | Recorded units, returns and missing-versus-zero policy; separated major contract sections |
| `kpi_engine/registry/traffic_total.yaml` | Recorded totals, channel additivity and native weekly driver grain; separated major contract sections |
| `kpi_engine/README.md` | Entry links to handoff, DuckDB scaffold and this record; explicit status and preserved-path decision |
| `kpi_engine/contracts/README.md` | File ownership, structured-schema migration and contract acceptance criteria |
| `kpi_engine/detection/README.md` | File ownership, shared prepared-series/baseline plan and detection acceptance criteria |
| `kpi_engine/verification/README.md` | File ownership, resolved-policy/auth/design plan and verification acceptance criteria |
| `kpi_engine/registry/README.md` | Per-KPI preserve/clarify table, loader compatibility and configuration-only extension criteria |

## New documents and organization decisions

| File | Contents |
| --- | --- |
| `kpi_engine/IMPLEMENTATION_HANDOFF.md` | Read order, current execution, P0/P1/P2 implementation sequence, policy ownership, correctness gaps, contribution methods, backend/frontend integration map and future verification |
| `kpi_engine/duckdb/README.md` | Documentation-only scaffold: source catalog, proposed `query/` modules, safe compiler, canonical inputs/results, native grain, reconciliation, migration and acceptance cases |
| `kpi_engine/DOCUMENTATION_CHANGELOG.md` | This complete per-file record, scope boundaries, baseline and verification results |

No existing files were rearranged: current imports and entry points depend on their
locations, and moving them is unnecessary for a comment-only handoff. The new
`duckdb/` folder contains a plan; future runtime files are proposed under `query/`
to distinguish application code from the third-party DuckDB module.

Frontend runtime files, remaining backend code, tests, examples, generated reports,
source CSVs, binary stores and dependency manifests were not edited. Relevant
integration work is mapped in the handoff instead. The pre-existing deletion of
`finalkpi/data/.~lock.finance_monthly.csv#` belongs to the initial working tree and
was left untouched; it is not part of this documentation work.

## Verification record

- Compared parsed Python ASTs against `git show HEAD:<path>` for all 32 modified
  Python files: identical, excluding location attributes. Existing docstrings are
  included in that comparison; no executable or docstring semantics changed.
- Compared parsed YAML values for all five changed contracts: identical.
- Checked handoff-marker coverage: all 33 engine Python/YAML files have notes.
- Ran `git diff --check`: passed with no whitespace errors.
- Checked the modified/new file inventory against the tables in this record.
- Runtime tests were not run: this pass changes only comments/Markdown/spacing;
  AST and YAML comparison directly verify the requested behavior preservation.
- Bugs and proposed capabilities are documented, not fixed or claimed complete.

The next coding agent should append a new dated entry recording implementation,
changed behavior, migrations and validation rather than rewriting this historical
documentation-only record as if its proposed work had already shipped.

## 2026-09-25 — Stage: registry/catalog-backed scope and metric-service routing

Request: replace the fixed KPI/region/category allowlists with registry and
catalog metadata, pass generic `scope` and `as_of` through the active API path,
route numerical chat lookups through the shared metric service, and cover the
onboarding path with a small independent source fixture.

What changed in this stage:

- `backend/service.py` now derives dimensions and filter values from the active
  registry and source catalog instead of hardcoded legacy assumptions, while
  retaining legacy request fields only as compatibility adapters.
- `backend/service.py` now preserves configured string values such as `NA` when
  scanning source CSVs for available dimension values, ensuring custom metadata
  entries remain visible to the backend instead of being silently dropped as
  missing data.
- `backend/service.py` continues to validate unsupported dimensions and unknown
  KPI IDs explicitly through the registry-backed flow rather than letting stale
  demo assumptions leak into the request layer.
- `backend/rag_pipeline.py` and the query service path remain routed through the
  shared governed metric preparation flow so numerical chat answers use the same
  scoped/as-of source snapshot as the diagnosis pipeline.
- `tests/test_query_layer.py` contains the regression proving a configured KPI
  with custom dimensions such as `channel` and `market` can be accepted without
  editing service logic.

Validation performed:

- `cd '/home/mansoor/Accenture Innovation Challenge/KPI-engine-and-data/finalkpi' && ./.venv/bin/python -m unittest tests.test_query_layer -q`
  -> 13 tests ran, 13 passed.
- `cd '/home/mansoor/Accenture Innovation Challenge/KPI-engine-and-data/finalkpi' && ./.venv/bin/python -m unittest discover -s tests -q`
  -> 122 tests ran, 122 passed.

Scope note: this pass remains within the backend scope/filter governance and
metadata-driven onboarding boundary. It does not broaden the project beyond the
active API and query-service path.

## 2026-09-25 — Stage: registry/catalog-backed scope and metric-service routing

Request: replace the fixed KPI/region/category allowlists with registry and
catalog metadata, pass generic `scope` and `as_of` through the active API path,
route numerical chat lookups through the shared metric service, and cover the
onboarding path with a small independent source fixture.

What changed in this stage:

- `backend/service.py` now resolves scope defaults from metadata-backed filters,
  accepts generic `scope` and `as_of` arguments, and rejects unknown KPI IDs
  explicitly instead of silently dropping them.
- `backend/app.py` now forwards `scope` and `as_of` in the live diagnosis and
  chat request path while keeping the legacy fields working as compatibility
  shims.
- `backend/rag_pipeline.py` now tries a shared metric-service lookup before the
  generic fallback answer when a user asks for numerical values or KPI totals.
- `frontend_bridge.py` now derives the active KPI list from the registry rather
  than a fixed tuple.
- `tests/fixtures/channel_daily.csv` adds an independent source with a different
  grain/dimension layout (`channel`, `region`) and revision history.
- `tests/test_query_layer.py` adds regressions covering the generic scope/as-of
  path, mixed invalid KPI rejection, and a catalog-driven custom-source
  onboarding case.

Unintended behavior change identified and fixed:

- The stage initially kept a hardcoded `CFO`-only permission gate in the backend
  service layer. That was removed so the active access model comes from the
  configured access policy instead of a fixed business persona assumption.
- The remaining default persona/region/category values in `backend/config.py` are
  default configuration values for the prototype, not an API allowlist.

What passed in validation:

- `python -m unittest tests.test_query_layer tests.test_storage_metadata tests.test_chat_storage -v`
  -> 10 tests ran, 10 passed.
- `python -m unittest backend.tests.test_backend_diagnosis -v`
  -> the fresh-database diagnosis API check passed in the existing backend suite.

This stage is intentionally limited to registry/catalog-backed scope routing,
shared metric lookups, and configuration-driven onboarding. It does not claim a
full DuckDB migration, unrestricted access model, or broader pipeline rewrite.

## 2026-09-25 — Stage I diagnosis API read initialization fix

Request: preserve the Stage I backend diagnosis boundary and fix the fresh-database
read crash without changing the engine runtime behavior outside the API/storage
layer.

Implementation: added a regression test for reading a diagnosis run from a newly
initialized SQLite path and updated the storage layer to call the database
initialization routine before read access. This keeps the existing API contract
unchanged while preventing `OperationalError: no such table: diagnosis_runs` on a
fresh backend database.

Validation: ran `python -m unittest backend.tests.test_backend_diagnosis -v` in the
project virtual environment. Result: 3 tests executed, 3 passed.

Limitations: this is a Stage I diagnosis API fix only; it does not add DuckDB,
new query-layer contracts, or broader backend/data migration work. The repository
still documents those as follow-up work outside this implementation scope.

## 2026-09-25 — Stage I acceptance review and SQLite path resilience fix

Request: review the stage against the acceptance criteria, remove the remaining
hardcoded business assumption, and fix the database-path regression exposed by the
fresh-database and storage tests without widening the scope beyond this stage.

What changed in this acceptance pass:

- `backend/storage.py` now ensures the parent directory for the configured SQLite
  database exists before opening the connection, so temp-directory teardown and
  config reloads no longer cause `sqlite3.OperationalError: unable to open
  database file` in active API usage.
- `backend/service.py` was adjusted to remove the remaining hardcoded `CFO`-only
  service-layer gate while keeping the configured access policy as the authority.
- `backend/service.py` and `backend/app.py` remain aligned with the generic
  `scope`/`as_of` contract and metadata-backed filter resolution added in the
  registry/catalog stage.

Validation performed:

- `cd /home/mansoor/Accenture\ Innovation\ Challenge/KPI-engine-and-data/finalkpi && python -m unittest backend.tests.test_backend_diagnosis tests.test_query_layer tests.test_storage_metadata tests.test_chat_storage -v`
  -> 15 tests ran, 15 passed.

This pass is limited to acceptance-review cleanup and the DB path resilience fix
for this stage. It does not change the broader DuckDB migration plan or expand
beyond the active API/query-layer back-end contracts already in scope.

## 2026-09-25 — Stage: project test repair for demo paths and RAG fallback

Goal:
Fix the five currently failing tests without changing the data layer or broadening
scope beyond the active runtime boundaries.

Files changed:
- `tests/run_jury_review.py`
- `tests/run_review_benchmark.py`
- `backend/rag_pipeline.py`
- `kpi_engine/DOCUMENTATION_CHANGELOG.md`

Behavior changed:
- The demo review scripts now resolve the repository root correctly instead of
  pointing at `tests/kpi_engine/registry`, which restores the HTML review and
  benchmark flows.
- The numeric RAG fallback now sets `evidence_status` from the diagnosis verdict
  before returning the metric summary, preserving the current behavior while
  preventing an undefined variable.

Known limitations:
- This does not change the data layer or broaden the scope into a DuckDB rewrite.
- The fix is limited to the active runtime path that is currently failing in the
  test suite.

Validation:
- command: `cd /home/mansoor/Accenture\ Innovation\ Challenge/KPI-engine-and-data/finalkpi && ./.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v`
- result: passed after the fix; the previously failing five tests now pass and the full project test suite completed successfully.
- command: `cd /home/mansoor/Accenture\ Innovation\ Challenge/KPI-engine-and-data/finalkpi && ./.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py' -v`
- result: passed after the fix; backend suite completed successfully.

## 2026-09-25 — Stage: generated runtime data cleanup

Goal:
Keep the implementation diff free of accidental SQLite and Chroma runtime outputs while preserving intentional source fixtures under the project data folders.

Files changed:
- `.gitignore`
- `kpi_engine/DOCUMENTATION_CHANGELOG.md`

Behavior changed:
- Generated runtime data under `backend/data/` is now ignored so test execution and vector-store writes do not pollute the implementation diff.
- The tracked SQLite and Chroma files were restored to their committed state because they are runtime artifacts, not required application fixtures.
- Intentional source fixtures such as the CSV datasets under `data/` were left intact.

Known limitations:
- The project continues to use the committed SQLite/Chroma state as runtime output; the repository should treat those files as generated artifacts, not hand-edited sources.
- If a future workflow needs a different runtime DB or a refreshed vector store, it should be recreated locally rather than committed as part of the implementation patch.

Validation:
- command: `cd /home/mansoor/Accenture\ Innovation\ Challenge/KPI-engine-and-data/finalkpi && git status --short -- backend/data && git status --short --untracked-files=all | grep -E 'backend/data|:memory' || true`
- result: no backend/data runtime artifact changes remain in git status after restore and ignore rules were applied.

## 2026-09-25 — Stage: DuckDB connection foundation

Goal:
Add the DuckDB connection foundation described in the query-layer scaffold without changing the diagnosis pipeline or the data layer semantics.

Files changed:
- `pyproject.toml`
- `kpi_engine/query/__init__.py`
- `kpi_engine/query/connection.py`
- `tests/test_duckdb_connection.py`
- `kpi_engine/DOCUMENTATION_CHANGELOG.md`

Behavior changed:
- Added and pinned the DuckDB dependency to the project.
- Added a bounded DuckDB connection wrapper that opens a connection only when needed, registers CSV or Parquet catalog sources safely, and closes the connection cleanly.
- Added tests proving a catalog source can be queried through DuckDB using a native SQL `SELECT` statement with no Pandas-driven calculation in the test path.

Known limitations:
- This stage does not change the diagnosis pipeline or move any calculation logic into DuckDB.
- The connection wrapper is intentionally limited to source registration and native SQL access as described in the scaffold.

Validation:
- command: `cd /home/mansoor/Accenture\ Innovation\ Challenge/KPI-engine-and-data/finalkpi && ./.venv/bin/python -m unittest tests.test_duckdb_connection -v`
- result: `Ran 2 tests in 0.046s` and `OK`
- command: `cd /home/mansoor/Accenture\ Innovation\ Challenge/KPI-engine-and-data/finalkpi && ./.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v && ./.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py' -v`
- result: project suite `Ran 116 tests ... OK` and backend suite `Ran 3 tests ... OK`

## 2026-09-25 — Stage: diagnosis run provenance and replay lineage (audit trail)

Request: ensure each diagnosis run records the actual execution timestamp,
contract version/hash, policy hash, source snapshot/hash, as-of cutoff,
resolved scope, comparison period, and generated query provenance so any saved
result can answer which data, contract, policy, and query produced it.

What changed in this pass:

- `backend/storage.py` now normalizes execution lineage into a dedicated
  `execution_metadata` payload and persists it alongside the run, including
  explicit `executed_at`, `contract_version`, `contract_hash`, `policy_version`,
  `policy_hash`, `source_snapshot_id`, `source_snapshot_hash`, `as_of_cutoff`,
  `comparison_scope`, `comparison_period`, and `query_provenance`.
- `backend/storage.py` keeps the resolved scope and comparison window in the
  saved result so a replayed diagnosis can distinguish different as-of cutoffs
  and source revisions even when the KPI and target date are the same.
- `tests/test_storage_metadata.py` adds a replay-oriented regression that saves
  two runs with different source revisions and as-of cutoffs and asserts the
  saved lineage remains distinguishable.

Validation performed:

- `cd '/home/mansoor/Accenture Innovation Challenge/KPI-engine-and-data/finalkpi' && ./.venv/bin/python -m unittest tests.test_storage_metadata -q`
  -> 2 tests ran, 2 passed.
- `cd '/home/mansoor/Accenture Innovation Challenge/KPI-engine-and-data/finalkpi' && ./.venv/bin/python -m unittest discover -s tests -q`
  -> 123 tests ran, 123 passed.

Scope note: this pass is limited to persisted diagnosis provenance and replay
traceability. It does not change the KPI calculations themselves or broaden the
implementation beyond the active run-logging and auditability boundary.
