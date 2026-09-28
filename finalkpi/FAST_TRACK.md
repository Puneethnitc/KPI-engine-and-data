# Fast-track plan (remaining work, trimmed)

Stages 0–4 are done (branch `fix/stage-04-source-reconciliation`). This file replaces Stages 5–11 of `IMPLEMENTATION_PLAN.md` with smaller versions. Section numbers such as "Plan §7.1" refer to that plan when more detail is needed. Rules: `AGENTS.md`.

| Step | Stage | Tool | Branch off |
|---|---|---|---|
| A | 7: Confidence + per-driver Attribution Confidence | **Claude Code** | stage-04 |
| B | 5-lite: Causal verification | **Claude Code** | A |
| C | 6-lite: Unstructured evidence | OpenCode (open model) | B |
| D | 8-lite: Personas + actions | OpenCode (open model) | C |
| E | Wrap-up: docs, telemetry sample, final eval | any | D |

Skipped: Stage 9 (feedback deploy), 10 (separate frontend pass), 11 (auth provider, performance). Each step ships its own UI.

---

## A. Stage 7: Confidence (Claude Code)

**Problem:** `kpi_engine/confidence.py:356–376`. The overall status is MODERATE for every input once movement and source pass. HIGH is unreachable, and the driver and causal results are ignored.

**Build:**
1. New `kpi_engine/attribution_confidence.py` plus `kpi_engine/models/attribution_confidence_v1.yaml`, holding the weights, caps and bands.
2. Per ranked driver, compute **Attribution Confidence (AC)**: the probability that this driver caused a material share (≥ 20%) of this movement.
   - Log-odds formula: prior (`1 / (moved drivers + 1)`) plus evidence items E1–E9 from Plan §7.1 (explained share, driver moved, direction, precedence, stability, adj. p-value, causal test, corroboration, data quality).
   - Missing inputs (causal not run, corroboration absent) contribute 0.
3. Caps:
   - no causal test → max 0.75
   - causal REJECTED → max 0.20
   - direction undeclared → max 0.60
   - movement not material → max 0.5, labelled `EXPLORATORY`
   - source CONTRADICTED or sparse history → not computed
4. Bands:
   - ≥ 0.80: HIGH, "Very likely a cause"
   - 0.60–0.79: MODERATE, "Likely a contributing cause"
   - 0.35–0.59: LOW, "Possible; needs verification"
   - below 0.35: VERY_LOW, "Unlikely to explain this change"
5. Output fields per driver: `attribution_confidence`, `band`, `label`, `evidence[]` (id, value, weight_contribution, note), `caps_applied`, `model_version`.
6. Add an "unexplained" row.
7. Set `attribution_status = AMBIGUOUS` when the top two drivers are within 0.1 of each other and both are ≥ 0.5. Set `NO_CONFIDENT_DRIVER` when the top driver is below 0.35.
8. Rewrite the overall status in `build_profile` as the **weakest required dimension**, on the scale `CONFLICTING < INSUFFICIENT < LOW < MODERATE < HIGH`:
   - Rename `driver` to `attribution` (the top driver's AC band) and keep `driver` as an alias.
   - A causal REJECTED on the top driver, with no other driver at AC ≥ 0.6, gives CONFLICTING.
   - Add `overall.movement_conclusion` ("Is it real?") and `overall.explanation_conclusion` ("Do we know why?").
9. `tests/run_ground_truth_eval.py`:
   - add AC metrics: mean AC of true drivers minus mean AC of false drivers, decoy max AC, Brier score
   - add a `--calibrate` flag that fits the weights with logistic regression on dev only and writes a v2 yaml
10. Frontend: `lib/confidence-profile.ts` and `components/confidence-workspace.tsx`:
    - two headline answers
    - per-driver AC bar (%, band, label) with an expandable evidence breakdown and caps
11. Tests:
    - all 5 overall statuses reachable
    - REJECTED → CONFLICTING
    - caps
    - bands
    - corroboration never lowers AC
    - update the old MODERATE assertions

**Accept (holdout):**
- mean true-driver AC minus mean false-driver AC ≥ 0.30
- decoy max AC < 0.5
- Brier score reported
- `low-confidence-abstention` demo still abstains

---

## B. Stage 5-lite: Causal verification (Claude Code)

**Problem:** the only causal design is hard-coded, and South (the control) is contaminated for EVT01. Weekly exposure can't be completed at the default as-of time.

**Build** (the Plan §5.1 subset only):
1. New `kpi_engine/verification/designer.py`: for the top 2 attributed drivers with explained share ≥ 20%, build designs automatically.
   - Onset: the first period where the driver's deseasonalised residual crosses 1.5× its noise scale within 42 days.
   - Pre period: 42 days before onset. Post period: onset to the target date.
   - Controls: authorised slices whose own driver change is ≤ 25% of the treated change and whose pre-period log-outcome correlation is ≥ 0.6. Use the average of valid controls; no synthetic control.
2. `kpi_engine/verification/did.py`:
   - DiD on the **log outcome**
   - placebo = the same estimator run at a fake onset in the pre period
   - weekly drivers: truncate the post period to the last *published* week instead of returning `INCOMPLETE_DRIVER_EXPOSURE`
3. Run it when the movement is material **or** `pattern == SUSTAINED`.
4. Keep `verification/registry.py` as manual overrides only.
5. Each result carries `design_id`, `controls_used` and `controls_rejected` (with reasons).
6. AC's causal-test evidence item (E7) then picks up the verdicts automatically.
7. Skip: synthetic control, sensitivity runs, saving designs to the database.

**Accept:**
- EVT01 marketing → SUPPORTED_CONDITIONAL, with South rejected as a control
- EVT03 stockout → SUPPORTED_CONDITIONAL
- EVT05 decoy → not SUPPORTED
- wrong-driver design → not SUPPORTED
- EVT04 (all regions affected) → UNTESTABLE/NO_VALID_CONTROL is fine

---

## C. Stage 6-lite: Unstructured evidence (OpenCode)

**Problem:** `data/unstructured_evidence.csv` is never used. Ingest and retrieval use different Chroma folders.

**Build:**
1. Data patch `data/patches/enrich_evidence.py`:
   - add `available_at`, `access_tags`, `driver_tags` and `stance` (supports/refutes/neutral) columns
   - add about 10 distractor docs: another region, a future date, and one containing a prompt-injection string
2. Rewrite `kpi_engine/corroborate.py` as a deterministic `EvidenceCorroborator`:
   - mandatory filters: `available_at ≤ as_of`, date within [target − 21 days, target], region/category ∈ {slice, ALL}, access tags within the persona's entitlements
   - match by `driver_tags` first, then keywords
   - output per driver: `corroboration: {status: CORROBORATED|CONTRADICTED|NONE, documents[]}`
3. Call it in `kpi_engine/pipeline.py` after attribution. It feeds AC item E8 (already implemented in step A).
4. `backend/ingest.py` must use `config.CHROMA_DIR` (the same folder as `backend/retrieval.py`) and also ingest the evidence CSV.
5. Add the same scope, as-of and access filters to `retrieve_vector_chunks`.
6. In the chat fallback (`backend/rag_pipeline.py`):
   - "why" questions answer with the top drivers, their AC % and cited doc IDs
   - forecast questions ("next month", "forecast", "will") are politely declined
7. Frontend: new `components/corroboration-panel.tsx` under each driver, showing doc cards (type, date, snippet, supports/refutes).
8. Tests:
   - North never sees South docs
   - no future docs
   - EVT01 2023-07-24 → marketing_spend CORROBORATED by TCK-1001
   - EVT03 → stock_availability CORROBORATED
   - the injection doc is ignored

---

## D. Stage 8-lite: Personas and actions (OpenCode)

**Problem:** the CFO, marketing and regional personas all get an identical narrative and cards. Expected impact is always null.

**Build:**
1. `kpi_engine/personas/{cfo,marketing_manager,regional_manager}.yaml` with `claim_order`, `driver_priority` (lever families first), `allowed_action_levers` and `approval_threshold`.
2. `kpi_engine/narrative.py`:
   - `_claims(payload, persona_cfg)` changes selection, order and wording only
   - new claim types: `FUNNEL_BRIDGE`, `ATTRIBUTED_DRIVER` ("{driver} explains ~{share}% ({contribution}); confidence {AC}% ({label})"), `CORROBORATION`, `CLARIFICATION_REQUEST` (when attribution is AMBIGUOUS or NO_CONFIDENT_DRIVER)
   - wording like "likely caused by" only when AC ≥ 0.6 **and** causal is SUPPORTED; otherwise "associated with"
   - everything still passes `validate()`
   - no LLM rewrite in this step
3. `kpi_engine/action.py`: up to 3 cards (drivers with AC ≥ 0.35).
   - `kind`: ACTION_PROPOSAL (AC ≥ 0.6 and SUPPORTED), VERIFY_THEN_ACT (AC ≥ 0.6), NEXT_CHECK (0.35–0.6), ADVISORY (contextual drivers)
   - `expected_impact = −contribution × 7 days`, with a range from the β confidence interval
   - owner and approval from the persona config
4. Backend:
   - `build_marketing_brief` → `build_persona_brief(persona)`
   - add the regional manager to the personas returned by `/api/filters`
5. Frontend:
   - persona selector gets "Regional manager (North)"
   - replace the hard-coded CFO/marketing header text in `app/page.tsx`
   - `components/action-workspace.tsx`: multiple cards with impact range, AC chip, kind and owner
6. Tests:
   - the same payload gives different claim sets and order for the 3 personas, all passing `validate()`
   - causal wording is rejected at low AC
   - impact calculation
   - card kinds by AC

---

## E. Wrap-up (any tool)

1. With a real `GROQ_API_KEY`, run one diagnosis and save the telemetry to `docs/telemetry_sample.json` (LLM tokens and cost).
2. Update `README.md`, `docs/METHODOLOGY_AND_DATASET.md` and `docs/JURY_GUIDE_PLAIN_LANGUAGE.md` with the new methods.
3. Run `run_ground_truth_eval.py` on `--split all` and `holdout`, and add a final before (Stage 0) → after table.
4. Run `next build` once to confirm the frontend compiles.

---

## Parallel mode (two agents at once)

Run in **two waves**, each pair in its own git worktree (a separate folder), never in the same folder:

| Wave | Claude Code (main folder) | OpenCode (worktree) | Why this pairing is safe |
|---|---|---|---|
| 1 | A: confidence | C: evidence | Different files. A treats corroboration as "absent = 0"; C only produces it |
| 2 | B: causal | D: personas | D needs A's AC fields (merged in wave 1). B only adds a causal verdict that A already reads |

Shared interfaces, so parallel agents don't guess:
- AC per driver: `attribution_confidence`, `band`, `label`, `evidence[]`, `caps_applied` (Step A §5).
- Corroboration per driver: `corroboration: {status, documents[]}` (Step C §2).
- Causal verdict on `causal_verification` (existing field).

**Set up the worktree** (run in `/mnt/storage/Accenture/kpi-engine`):
```bash
git worktree add ../kpi-wt-oc fix/stage-04-source-reconciliation -b fix/stage-06-evidence   # wave 1; wave 2: base = merged branch, -b fix/stage-08-personas
ln -s /mnt/storage/Accenture/kpi-engine/finalkpi/.venv ../kpi-wt-oc/finalkpi/.venv
ln -s /mnt/storage/Accenture/kpi-engine/finalkpi/frontend/node_modules ../kpi-wt-oc/finalkpi/frontend/node_modules
```
Open OpenCode in `../kpi-wt-oc/finalkpi`.

**Merge after each wave** (in the main folder):
```bash
git switch -c fix/wave-1-merged fix/stage-07-confidence
git merge fix/stage-06-evidence
```
- Conflicts to expect: `ENGINE_VERSION` (pick a new value), `docs/EVALUATION_BASELINE.md` (keep both appended sections), and small hooks in `kpi_engine/pipeline.py` (keep both calls: attribution → corroboration → attribution confidence).
- Then run **all four commands again on the merged branch**. The numbers each agent reported were measured before merging and are no longer valid. Add a short "Wave N merged" table to the baseline doc.
- Wave 2 branches off `fix/wave-1-merged`. Step E runs after merging wave 2.

---

## Ready-made prompts (start a **fresh session** for each)
In parallel mode, use the wave base branch: A and C off `fix/stage-04-source-reconciliation`; B and D off `fix/wave-1-merged`.

**A (Claude Code):**
> Read AGENTS.md and FAST_TRACK.md. Do step A (Stage 7) on branch `fix/stage-07-confidence` off `fix/stage-04-source-reconciliation`. Follow its Build and Accept lists exactly, then report.

**B (Claude Code):**
> Read AGENTS.md and FAST_TRACK.md. Do step B (Stage 5-lite) on `fix/stage-05-causal` off `fix/stage-07-confidence`. Follow its Build and Accept lists exactly, then report.

**C (OpenCode):**
> Read AGENTS.md and FAST_TRACK.md. Do step C (Stage 6-lite) on `fix/stage-06-evidence` off `fix/stage-05-causal`. Follow its Build list exactly. Run all four test commands from AGENTS.md before reporting. Do not modify existing tests to make them pass.

**D (OpenCode):**
> Read AGENTS.md and FAST_TRACK.md. Do step D (Stage 8-lite) on `fix/stage-08-personas` off `fix/stage-06-evidence`. Follow its Build list exactly. Run all four test commands from AGENTS.md before reporting. Do not modify existing tests to make them pass.

**E (any):**
> Read AGENTS.md and FAST_TRACK.md. Do step E (wrap-up) on `fix/stage-final` off `fix/stage-08-personas`, then report.

After A and B, and once at the very end, paste the agent's report back to me for a quick review.
