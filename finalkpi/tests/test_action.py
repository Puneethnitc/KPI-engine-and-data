"""Recommendations are evidence-limited, non-executing review artifacts."""

import unittest

from kpi_engine.action import ActionRecommendationEngine


class ActionTests(unittest.TestCase):
    def _ranked_result(self, **overrides):
        result = {
            "verdict": "MATERIAL_CAUSE_UNVERIFIED",
            "target_date": "2024-01-31",
            "contract_snapshot": {
                "drivers": {"candidate_drivers": [{
                    "driver_id": "stockout",
                    "display_name": "Stockout units",
                    "source_id": "sales_daily",
                    "unit": "units/day",
                    "controllability": "controllable",
                    "owner": "operations_lead",
                }]},
            },
            "driver_analysis": {
                "status": "ASSESSED",
                "ranked_drivers": [{
                    "driver_id": "stockout", "rank": 1, "claim_type": "CORRELATIONAL",
                    "source_id": "sales_daily", "controllability": "controllable",
                    "alignment_method": "daily_date_grouping",
                }],
                "excluded_drivers": [],
            },
            "causal_verification": {"verdict": "INCONCLUSIVE", "driver_id": "stockout"},
            "confidence_profile": {
                "overall": {"status": "LOW"},
                "source": {"status": "HIGH", "blocking": False},
            },
        }
        result.update(overrides)
        return result

    def test_ranked_driver_contains_complete_structured_action_contract(self):
        card = ActionRecommendationEngine.recommend(self._ranked_result())[0]
        for field in (
            "action_id", "kind", "status", "driver_id", "driver_rank", "driver_relationship",
            "controllability", "lever", "recommendation", "owner", "owner_source", "decision_right",
            "approval_required", "expected_impact", "expected_impact_unit", "impact_method",
            "impact_explanation", "evidence_status", "confidence_status", "evidence_references",
            "constraints", "monitoring_plan", "success_metric", "review_window", "stop_conditions",
            "limitations", "evidence_paths",
        ):
            self.assertIn(field, card)
        self.assertEqual(card["kind"], "NEXT_CHECK")
        self.assertEqual(card["owner"], "operations_lead")
        self.assertEqual(card["owner_source"], "contract.candidate_drivers.owner")
        self.assertFalse(card["approval_required"])
        self.assertIsNone(card["expected_impact"])
        self.assertIsNone(card["expected_impact_unit"])
        self.assertEqual(card["impact_method"], "NOT_ESTIMATED")
        self.assertTrue(card["evidence_references"])
        self.assertEqual(card["evidence_references"][0]["driver_id"], "stockout")
        self.assertIn("stockout", card["monitoring_plan"])
        self.assertTrue(card["stop_conditions"])

    def test_low_confidence_and_not_assessed_cannot_create_action_proposal(self):
        supported = self._ranked_result(
            causal_verification={"verdict": "SUPPORTED_CONDITIONAL", "driver_id": "stockout"},
            confidence_profile={"overall": {"status": "LOW"}, "source": {"status": "HIGH", "blocking": False}},
        )
        self.assertEqual(ActionRecommendationEngine.recommend(supported)[0]["kind"], "NEXT_CHECK")

        not_assessed = self._ranked_result(
            causal_verification={"verdict": "UNTESTABLE", "driver_id": "stockout"},
            confidence_profile={"overall": {"status": "NOT_ASSESSED"}, "source": {"status": "HIGH", "blocking": False}},
        )
        self.assertEqual(ActionRecommendationEngine.recommend(not_assessed)[0]["kind"], "NEXT_CHECK")

    def test_conditional_support_is_approved_but_impact_remains_unestimated(self):
        result = self._ranked_result(
            causal_verification={"verdict": "SUPPORTED_CONDITIONAL", "driver_id": "stockout"},
            confidence_profile={"overall": {"status": "MODERATE"}, "source": {"status": "HIGH", "blocking": False}},
        )
        card = ActionRecommendationEngine.recommend(result)[0]
        self.assertEqual(card["kind"], "ACTION_PROPOSAL")
        self.assertTrue(card["approval_required"])
        self.assertEqual(card["status"], "AWAITING_APPROVAL")
        self.assertIsNone(card["expected_impact"])
        self.assertIn("not estimated", card["impact_explanation"].lower())

    def test_blocked_or_insufficient_evidence_never_produces_rollout_action(self):
        blocked = self._ranked_result(
            confidence_profile={"overall": {"status": "CONFLICTING_EVIDENCE"}, "source": {"status": "CONFLICTING_EVIDENCE", "blocking": True}},
        )
        self.assertNotEqual(ActionRecommendationEngine.recommend(blocked)[0]["kind"], "ACTION_PROPOSAL")
        insufficient = self._ranked_result(driver_analysis={"status": "INSUFFICIENT_EVIDENCE", "ranked_drivers": [], "excluded_drivers": []})
        insufficient_cards = ActionRecommendationEngine.recommend(insufficient)
        self.assertFalse(any(card["kind"] == "ACTION_PROPOSAL" for card in insufficient_cards))

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

    def test_excluded_driver_cannot_reenter_from_legacy_candidate_list(self):
        cards = ActionRecommendationEngine.recommend({
            "verdict": "MATERIAL_CAUSE_UNVERIFIED",
            "causal_verification": {"verdict": "UNTESTABLE", "driver_id": "stockout"},
            "driver_analysis": {
                "status": "INSUFFICIENT_EVIDENCE",
                "ranked_drivers": [],
                "excluded_drivers": [{
                    "driver_id": "stockout", "reason_code": "LOW_COVERAGE",
                    "reason": "Coverage below threshold",
                }],
            },
            "correlational_candidates": [
                {"driver_id": "stockout", "claim_type": "CORRELATIONAL"}
            ],
        })
        self.assertIsNone(cards[0]["driver_id"])
        self.assertEqual(cards[0]["lever"], "Evidence collection")


if __name__ == "__main__":
    unittest.main()
