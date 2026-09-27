# Problem 10 Telemetry Report

## Scope and Files

Added an operational runtime panel inside the existing Processing Transparency section on the desktop run-detail page. Files changed for this chunk:

- `frontend/lib/processing-transparency.ts`
- `frontend/components/processing-transparency.tsx`
- `frontend/app/performance/[runId]/page.tsx`
- `frontend/app/globals.css`
- `frontend/tests/processing-transparency.test.js`
- `kpi_engine/pipeline.py`
- `backend/tests/test_demo_scenarios.py`
- `problem_10_telemetry_report.md`

No backend telemetry, analytical, security, or authorization code was changed in this chunk.

## Telemetry Display

The panel consumes the existing diagnosis `result.telemetry` object directly. It displays execution ID, measured total latency, start/completion timestamps, cache totals, ordered stage rows, optional provider/model, calls, token usage, estimated USD cost, usage source, configured limits, fallback behavior, and pricing version. It does not render stage `details` or invent a chat/timeseries telemetry contract.

Null input/output tokens and null cost display as **Unavailable**. Known deterministic zero calls, tokens and cost display as `0` and `$0.00`. Small non-zero costs are rounded to at most four decimal places; amounts below `$0.0001` display as `<$0.0001`.

The run-detail component suppresses operational telemetry for `ACCESS_DENIED`; older runs without telemetry show a historical-unavailable message. The panel states: “Quantitative KPI calculations are performed by deterministic/statistical engine stages. LLMs are used only where explicitly shown.”

Backend telemetry shape consumed: `execution_id`, `started_at`, `completed_at`, `total_latency_ms`, ordered `stages` (`stage`, `processing_type`, `method`, `latency_ms`, `status`, `cache_status`, provider/model, calls, tokens, cost, usage source), `llm_summary`, `cache_summary`, and `limits`.

## Runtime Stage Classification Correction

Internal pipeline stages declare their processing type explicitly at each instrumentation call. Corrected mapping:

| Stage | Processing type |
|---|---|
| `authorization` | `BUSINESS_RULE` |
| `source_preparation` | `DETERMINISTIC` |
| `reconciliation` | `DETERMINISTIC` |
| `movement_detection` | `STATISTICAL` |
| `driver_analysis` | `STATISTICAL` |
| `contribution_analysis` | `DETERMINISTIC` |
| `causal_verification` | `CAUSAL` |
| `confidence_and_actions` | `BUSINESS_RULE` |
| `narrative_synthesis` | `DETERMINISTIC` |
| `narrative_generation` | `LLM`, only when a provider call was attempted |
| `diagnosis_pipeline`, `diagnosis_cache`, `timeseries_query` | `DETERMINISTIC` |
| `query_routing`, `answer_generation` | `LLM` when called; otherwise `DETERMINISTIC` |

The change affects labels only; calculations, timing boundaries, early exits and model-call behavior are unchanged.

## Validation

Frontend test command:

```sh
cd /mnt/storage/Accenture/kpi-engine/finalkpi/frontend && node --experimental-strip-types --test tests/*.test.js
```

Result: **154 passed, 0 failed**.

TypeScript command:

```sh
cd /mnt/storage/Accenture/kpi-engine/finalkpi/frontend && node node_modules/.pnpm/typescript@5.7.3/node_modules/typescript/bin/tsc --noEmit
```

Result: **passed**. `git diff --check` also passed.

Focused backend telemetry/scenario command:

```sh
cd /mnt/storage/Accenture/kpi-engine/finalkpi && .venv/bin/python -m unittest backend.tests.test_runtime_telemetry backend.tests.test_demo_scenarios
```

Result for the classification correction: **20 passed** (6 runtime telemetry tests and 14 governed-scenario tests).

Focused frontend classification command:

```sh
cd /mnt/storage/Accenture/kpi-engine/finalkpi/frontend && node --experimental-strip-types --test tests/processing-transparency.test.js
```

Result for the classification correction: **21 passed**. The full frontend suite is **154 passed, 0 failed**. TypeScript validation passed and `git diff --check` passed.

The six governed scenarios were executed against temporary SQLite storage. All expected outcomes matched. For every authorized scenario, telemetry had unique execution IDs, non-negative timing, executed stages, truthful cache misses, deterministic zero calls/cost, and survived save/readback. Telemetry contained no prompts, credentials, SQL, filesystem paths, retrieved content, row values, or raw exception text.

| Scenario | Observed / expected | Telemetry result |
|---|---|---|
| `material-multi-driver` | `MATERIAL` / `MATERIAL` | 5 result telemetry records; all checks passed |
| `low-confidence-abstention` | `ABSTAIN` / `ABSTAIN` | 5 records; all checks passed |
| `contradictory-sources` | `CONTRADICTED` / `CONTRADICTED` | 1 record; all checks passed |
| `sparse-history-new-launch` | `INSUFFICIENT_HISTORY` / `INSUFFICIENT_HISTORY` | 5 records; all checks passed |
| `unauthorized-scope` | `ACCESS_DENIED` / `ACCESS_DENIED` | No business telemetry or source details exposed |
| `non-material-baseline` | `NO_MATERIAL_MOVEMENT` / `NO_MATERIAL_MOVEMENT` | 5 records; all checks passed |

Example deterministic execution: `exec-f6b50930-1fa0-48e2-b8da-3df4c06ff03f` completed in **231.786 ms**. It recorded authorization as `BUSINESS_RULE` (1.043 ms), source preparation as `DETERMINISTIC` (42.062 ms), reconciliation as `DETERMINISTIC` (2.854 ms), movement detection as `STATISTICAL` (104.188 ms), driver analysis as `STATISTICAL` (37.188 ms), contribution analysis as `DETERMINISTIC` (3.559 ms), causal verification as `CAUSAL` (8.201 ms), confidence/actions as `BUSINESS_RULE` (0.101 ms), and narrative synthesis as `DETERMINISTIC` (0.071 ms), plus the enclosing deterministic pipeline stage. LLM summary was 0 calls, 0 input/output tokens, `$0` cost; cache was 0 hits, 1 miss, 9 not applicable.

No LLM execution example is reported: no provider is configured in this environment. **No new LLM call was introduced. Unavailable token usage and cost are not fabricated.**

## Known Constraints

- The page displays diagnosis/saved-run telemetry only. Chat responses expose their separate `runtime_telemetry`, and timeseries responses expose top-level `telemetry`; those surfaces are not combined into this run-detail panel.
- Provider cost remains unavailable when model rates are not configured, even when a provider returns usage.
- The backend’s enclosing `diagnosis_pipeline` duration overlaps its internal stage durations; do not sum stage durations as a substitute for total latency.
- Persistence is verified by telemetry survival, but is not separately represented as a timed stage in the current backend telemetry.
- No mobile-specific layout work was performed.