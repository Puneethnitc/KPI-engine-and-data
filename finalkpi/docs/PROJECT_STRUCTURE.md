# Project structure

```text
finalkpi/
├── backend/          FastAPI boundary, saved runs, grounded chat and retrieval
│   └── runtime/      Generated SQLite/Chroma state; ignored by Git
├── data/             Versioned synthetic source fixtures
├── docs/             Methodology, jury guide, coverage and integration notes
├── examples/         Versioned scenario/design manifests
├── frontend/         Next.js application; consumes backend contracts
├── kpi_engine/       Deterministic/statistical analytical domain engine
│   ├── contracts/    Typed KPI contract models and registry loading
│   ├── detection/    Robust and seasonal movement detection
│   ├── registry/     Governed KPI YAML definitions
│   └── verification/ Bounded observational verification methods
└── tests/            Engine, backend, scenario and regression verification

imports/              Repository-root inbox for external frontend handoffs;
                      archives are ignored and reviewed before integration
```

## Dependency direction

```text
frontend → backend API → kpi_engine → versioned source fixtures
                         ↓
                    saved run/evidence
                         ↓
                 grounded chat/feedback
```

- `kpi_engine` must not import frontend or FastAPI modules.
- `backend` adapts the engine into authenticated, persisted API workflows.
- `frontend` renders backend facts and must not calculate or invent official
  KPI results.
- Generated runtime state never belongs in version control.

## Frontend handoff rule

External exports are placed at `imports/v0-frontend.zip`. They are never
extracted directly over `finalkpi/frontend/`. Approved visual components are
ported after reviewing framework and dependency differences, while the
backend-bound API layer remains canonical.
