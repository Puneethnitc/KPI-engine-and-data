# KPI engine implementation guide

The engine separates four questions: **did a KPI move**, **do sources agree**, **what arithmetic components add to the move**, and **what evidence may be associated with it**. It does not promote correlation or accounting decomposition into causal proof.

`pipeline.py` orchestrates the stages. `contracts/` defines governed KPI semantics; `normalize.py` applies source-schema and as-of availability rules; `access.py` applies the demo's regional role guard; and `detection/` assesses material movements. `reconcile.py` compares compatible sources, while `decompose.py` uses an order-independent Shapley split for quantity, mix, and rate accounting effects. `rank.py` ranks labelled correlations only. `verification/` performs bounded observational difference-in-differences checks, `contribute.py` computes exact Shapley allocations only for an explicitly supplied counterfactual model, `confidence.py` reports evidence-quality diagnostics rather than a causal probability, and `narrative.py` renders approved evidence-bound text. `action.py` produces review-only next steps; `feedback.py` persists proposed corrections pending review.

See [the metric coverage note](../docs/METRIC_COVERAGE.md) and [the review note](../docs/ENGINE_FRONTEND_REVIEW.md) for supported scope and known limitations.
