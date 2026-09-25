# Team handoff

## Canonical working copy

- Repository: `https://github.com/Puneethnitc/KPI-engine-and-data.git`
- Handoff branch: `codex/team-handoff-20260926`
- Application root after cloning: `KPI-engine-and-data/finalkpi`

Do not copy `.venv`, `node_modules`, `.next`, runtime SQLite files, Chroma data,
or `.env` files between laptops. Git intentionally excludes them. Each developer
should create those locally.

## Project map

```text
finalkpi/
├── backend/       FastAPI API, persistence, retrieval and chat orchestration
├── contracts/     shared contract assets
├── data/          demo structured and unstructured source data
├── docs/          architecture, methodology and handoff documentation
├── examples/      example analysis and verification designs
├── frontend/      Next.js KPI dashboard and API gateway
├── kpi_engine/    deterministic/statistical KPI intelligence engine
├── tests/         engine and integration tests
├── .env.example   documented optional runtime configuration
└── pyproject.toml Python package and dependency definition
```

## Clone this exact working version

```bash
git clone --branch codex/team-handoff-20260926 --single-branch \
  https://github.com/Puneethnitc/KPI-engine-and-data.git
cd KPI-engine-and-data/finalkpi
```

If the repository is already cloned:

```bash
git fetch origin
git switch codex/team-handoff-20260926
git pull --ff-only
cd finalkpi
```

## Requirements

- Python 3.10 or newer
- Node.js 20.9 or newer
- Corepack/pnpm (the lockfile pins the frontend dependencies)

No model API key is required for the working deterministic prototype. An
optional provider key can be configured later without committing it.

## One-time setup

From `finalkpi/`:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
corepack enable
cd frontend
pnpm install --frozen-lockfile
cd ..
```

## Run locally

Terminal 1, from `finalkpi/`:

```bash
.venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Terminal 2, from `finalkpi/frontend/`:

```bash
pnpm dev
```

Open `http://127.0.0.1:3000/`.

The frontend gateway defaults to `http://127.0.0.1:8000`, so no environment
file is needed for the standard local setup. For overrides, copy the relevant
values from `.env.example` into local environment files; never commit secrets.

## Verify before changing code

From `finalkpi/`:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'
cd frontend
pnpm build
```

Expected handoff baseline: 123 engine tests, 12 backend tests, and a successful
Next.js production build.

## Safe collaboration workflow

Each developer should branch from the handoff branch instead of committing
directly to it:

```bash
git switch codex/team-handoff-20260926
git pull --ff-only
git switch -c feature/<short-description>
```

Commit only source, tests, contracts, and documentation. Open a pull request
back into `codex/team-handoff-20260926` after the tests above pass. Avoid force
pushes and do not merge unrelated legacy branches into the handoff branch.

## Current product boundary

This is a working research/demo prototype, not a production deployment. It
supports the connected Overview, Performance, Channel Signals (route name
`campaigns`), and Insights experiences; governed KPI diagnosis; explicit
uncertainty and abstention; traceable evidence; persona context; feedback
review; and a grounded assistant. It does not claim causal certainty when the
available evidence is observational or incomplete.
