# KPI engine mentor demo

Architecture and operational limitations are recorded in
[`../docs/ENGINE_FRONTEND_REVIEW.md`](../docs/ENGINE_FRONTEND_REVIEW.md). Folder
guides alongside the source explain the UI, API adapter, shared components,
and static assets without changing their behavior.

This frontend calls the existing Python KPI engine through a local Next.js route.
It displays **real engine output**, not the hard-coded claims from the original
v0 export. The chat is deliberately a scripted evidence explainer, not a live LLM.

## Run locally

From `finalkpi/`:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
cd frontend
npm run dev
```

The frontend dependencies are already installed in this workspace. If you
ever need to reinstall them, use the bundled pnpm executable (your terminal
may not have `pnpm` on `PATH`):

```bash
/home/puneeth/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm install --frozen-lockfile
```

Open <http://localhost:3000>. The supplied sample scope is **2023-07-24,
North / Electronics**. The overview runs all five registered KPIs and usually
loads in a few seconds. Click **Net sales revenue** for the main demo path.

The API route assumes `finalkpi/.venv/bin/python`. Set `KPI_PYTHON` to another
Python executable with this project's dependencies installed if needed.

## Suggested three-minute mentor walkthrough

1. Overview: point out the three material movements among five KPI definitions.
2. Revenue: actual ₹2,919.67 against expected ₹4,283.82; delta −₹1,364.15.
3. Source status: finance has no as-of snapshot, so **NOT_RECONCILED** is shown.
4. Exact bridge: units −₹1,493.60 plus rate +₹129.45 = −₹1,364.15.
5. Traffic is **correlational**. Ask “Is the cause proven?”; the answer is **no**
   because no eligible predeclared verification design was supplied.
6. Show the suggested next check and the light/dark toggle.

Do not change the date or filters while presenting unless you have tested that
slice first. Some slices correctly abstain or have missing source data.

## Demo limits

- Historical CSV dataset, not a live database or streaming feed.
- No authenticated users or persisted run history.
- No free-form LLM chat; answers are scripted from the selected engine result.
- No operational action is executed.
- The accounting bars are exact effects; the association bar is not a causal
  impact estimate.
