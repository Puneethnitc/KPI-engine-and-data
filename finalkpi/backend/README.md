# Backend checkpoint plan

This folder contains the staged prototype backend for the KPI engine.

## Stage 1: diagnosis API
- Keep the engine in `kpi_engine/` unchanged.
- Wrap `KPIEnginePipeline` in `backend/service.py`.
- Validate request scope against the supported demo filters.
- Save each diagnosis run in SQLite.
- Serve diagnosis metadata through FastAPI under `/api/diagnoses` and `/api/diagnoses/{run_id}`.

## Stage 2: retrieval and chat
- Register KPI metadata, filters, and diagnosis results through the API.
- Index evidence documents in ChromaDB when available.
- Answer questions using the saved run and grounded citations.
- Keep conversation history tied to the diagnosis run.

## Stage 3: frontend integration
- Replace per-request subprocess execution with HTTP calls from the Next.js app.
- Populate selectors from backend metadata and keep the frontend result-bound.

## Local run

```bash
cd finalkpi
.venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

The prototype intentionally keeps the demo identity server-side and does not allow arbitrary persona selection.
