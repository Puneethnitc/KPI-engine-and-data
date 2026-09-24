"""Recommendations are evidence-limited, non-executing review artifacts."""

import unittest

from kpi_engine.action import ActionRecommendationEngine


class ActionTests(unittest.TestCase):
    def test_conditional_support_requires_approval_and_promises_no_impact(self):
        cards = ActionRecommendationEngine.recommend({
            "verdict": "EVENT_ASSESSED_CAUSE_UNVERIFIED",
            "causal_verification": {
                "verdict": "SUPPORTED_CONDITIONAL", "driver_id": "stockout",
            },
        })
        self.assertEqual(cards[0]["kind"], "ACTION_PROPOSAL")
        self.assertEqual(cards[0]["status"], "AWAITING_APPROVAL")
        self.assertIsNone(cards[0]["expected_impact"])

    def test_rejected_driver_cannot_reenter_from_correlation(self):
        cards = ActionRecommendationEngine.recommend({
            "verdict": "MATERIAL_CAUSE_UNVERIFIED",
            "causal_verdict": "REJECTED",
            "causal_verification": {"verdict": "REJECTED", "driver_id": "stockout"},
            "correlational_candidates": [
                {"driver_id": "stockout", "claim_type": "CORRELATIONAL"}
            ],
        })
        self.assertEqual(cards[0]["kind"], "NEXT_CHECK")
        self.assertIsNone(cards[0]["driver_id"])

    def test_access_denial_and_contradiction(self):
        self.assertEqual(ActionRecommendationEngine.recommend({
            "verdict": "ACCESS_DENIED"
        }), [])
        cards = ActionRecommendationEngine.recommend({"verdict": "CONTRADICTED"})
        self.assertEqual(cards[0]["lever"], "Source integrity")
        self.assertEqual(cards[0]["kind"], "NEXT_CHECK")


if __name__ == "__main__":
    unittest.main()
