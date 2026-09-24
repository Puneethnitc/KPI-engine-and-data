"""Print one stage-by-stage diagnosis without demo overrides."""

from run_full_demo import run


result = run()
for key in (
    "run_id", "target_date", "as_of", "reconciliation_verdict",
    "movement_assessment", "decomposition", "correlational_candidates",
    "causal_verdict", "confidence", "verdict", "narrative",
):
    print(f"{key}: {result[key]}")
