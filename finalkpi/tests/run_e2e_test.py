"""A real sample diagnosis with assertions on its decision boundaries."""

from run_full_demo import run


result = run()
assert result["verdict"] == "MATERIAL_CAUSE_UNVERIFIED", result
assert result["decomposition"]["is_identity_held"]
assert result["causal_verdict"] == "UNTESTABLE"
assert result["decision_cards"][0]["kind"] == "NEXT_CHECK"
assert result["decision_cards"][0]["status"] == "AWAITING_REVIEW"
assert result["decision_cards"][0]["expected_impact"] is None
assert result["grounding_passed"]
print("End-to-end sample passed:", result["verdict"])
