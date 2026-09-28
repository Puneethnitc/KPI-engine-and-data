# Agent rules for this repo (read before any change)

Project: BusinessIntelligence.ai KPI intelligence engine (Accenture challenge, Round 2 Track 3).
Full spec: `IMPLEMENTATION_PLAN.md`. **Current work order and stage scope: `FAST_TRACK.md`** (it overrides the plan where they differ).

## Layout
- `kpi_engine/`: Python engine (detection, attribution, reconciliation, verification, confidence, narrative, actions)
- `kpi_engine/registry/*.yaml`: KPI contracts
- `backend/`: FastAPI (`app.py` routes, `service.py` orchestration, `rag_pipeline.py` / `retrieval.py` chat)
- `frontend/`: Next.js (`app/page.tsx`, `components/`, `lib/`, `tests/`)
- `data/`: synthetic CSVs; `data/labels/eval_cases.csv` is the answer key
- `tests/run_ground_truth_eval.py`: scoreboard, run before and after every stage

## Hard rules
1. Branch per stage off the previous stage's branch: `fix/stage-XX-<slug>`. Commit when done. Never force-push.
2. **Bump `ENGINE_VERSION` in `backend/service.py`** whenever engine output changes (runs are cached by it).
3. The LLM is never the source of numbers. Keep narrative claim validation (`kpi_engine/narrative.py:validate`) and fail-closed access checks.
4. Never edit or delete a test just to make it pass. If behaviour intentionally changes, update the expected value and say why in the commit.
5. Tune thresholds or weights on `--split dev` only. Report `--split holdout` honestly, even when bad. Never game metrics.
6. Keep changes inside the stage scope in `FAST_TRACK.md`. No drive-by refactors.
7. Don't read huge files whole; grep for the function you need.

## Done = all green
Always prefix Python commands with `PYTHONPATH=.`. The package is an editable install pointing at the main checkout, so without it a git worktree silently imports the *main folder's* `kpi_engine`.
```bash
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
PYTHONPATH=. .venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'
(cd frontend && npm test && ./node_modules/.bin/tsc --noEmit --incremental false)
PYTHONPATH=. .venv/bin/python tests/run_ground_truth_eval.py --split all --markdown-out /tmp/gt.md
```
In a worktree, `.venv` and `frontend/node_modules` are symlinks to the main checkout (see FAST_TRACK.md "Parallel mode").
While iterating, run only the relevant test file and `--split dev`. Run the full set once at the end.

## Reporting
Append a short "Stage N: before → after" table to `docs/EVALUATION_BASELINE.md` (don't rewrite the file). Final message: what changed, test counts, harness numbers, anything not done.
