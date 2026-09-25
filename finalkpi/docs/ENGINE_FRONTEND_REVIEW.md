# Engine and frontend review

This is a review note, not a request to change the engine's statistical or causal claims.

## Verified baseline

- Python environment: the declared dependencies install into `finalkpi/.venv` and all 93 unit tests pass.
- Frontend dependencies: `pnpm install --frozen-lockfile` completes successfully.
- TypeScript: `pnpm exec tsc --noEmit` completes successfully.
- Production build: `pnpm run build` currently fails in Next.js 16.3.3/Turbopack while CSS processing tries to bind a local helper port (`Operation not permitted`). It also fails outside this task sandbox, so it is presently an environment/toolchain blocker rather than a source-level TypeScript failure.

## Engine limitations and risks

1. **Prototype access control.** The caller supplies a persona such as `CFO`; there is no authenticated identity binding. The CSV role map is a local demonstration guard, not production authorization.
2. **Limited primary-source support.** Contracts can describe more source types than the public diagnosis path runs. Primary KPI diagnosis currently accepts daily `sales_daily` data only.
3. **Historical reconciliation limit.** Finance data without an as-of snapshot cannot establish an open-month historical comparison. The engine returns `NOT_RECONCILED`, which is safe but limits coverage.
4. **No causal proof.** Ranked drivers are correlations. DiD is available only for a predeclared observational design with controls and returns conditional support or abstention, never proof of a material cause.
5. **No production persistence or service boundary.** Files are local CSVs; feedback is a local JSONL log; there is no database, job queue, audit store, or authenticated HTTP API.
6. **Dependency reproducibility.** Python dependencies have lower bounds but no lock file, so a later installation can select newer numerical-library versions.

## Frontend limitations and risks

1. **One Python process per API request.** The Next.js route starts `frontend_bridge.py` for every request, including five sequential full diagnoses for the overview. It can be slow and does not scale under concurrent traffic.
2. **Frontend/backend lists can drift.** The allowed KPI, region, and category values are duplicated in TypeScript rather than being exposed by the registry.
3. **Error detail exposure.** The API returns the underlying process error message to the browser. In a deployed service, it should log detailed diagnostics server-side and return a safe public error.
4. **Date validation is syntactic only.** The route checks the `YYYY-MM-DD` shape but accepts impossible calendar dates until the Python process rejects them, producing a server error instead of a clear client validation response.
5. **No frontend automated tests or CI workflow.** The Python suite is strong, but UI behavior, API-route validation, and a production build are not covered by committed automation.
6. **Demo-only chat.** The assistant panel is intentionally scripted and does not persist conversations or answer beyond the current result object.

## Recommended order of work

1. Stabilize the Next.js build/toolchain and add a CI workflow that runs Python tests, TypeScript checks, and production build.
2. Replace per-request process spawning with an authenticated backend API/service and a bounded worker model.
3. Serve registry metadata to the UI so its selectable KPIs and filters cannot drift from the engine.
4. Add KPI contracts and tests only for metrics that have approved business definitions and source semantics.
