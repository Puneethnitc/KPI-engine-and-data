"""Regression coverage for persona-specific grounded claims and action cards."""

import unittest
import math
from dataclasses import replace

from kpi_engine.action import ActionRecommendationEngine
from kpi_engine.attribution_confidence import AttributionConfidenceEngine
from kpi_engine.narrative import NarrativeEngine


class PersonaTests(unittest.TestCase):
    def test_inconclusive_strong_evidence_is_capped_and_named(self):
        driver = {
            "driver_id": "marketing_spend", "explained_share": 0.62,
            "driver_change_z": 3.4, "direction_consistent": True,
            "expected_direction": "positive", "lag_days": 2,
            "stability_status": "STABLE", "p_value_adj": 0.008,
            "coverage_ratio": 0.95, "moved": True, "offsetting": False,
            "sample_size": 40, "contribution": 800,
        }
        record = AttributionConfidenceEngine.compute_driver(
            driver, prior=0.5, is_material=True, source_status="HIGH",
            causal_result={"driver_id": "marketing_spend", "verdict": "INCONCLUSIVE"},
        )
        self.assertLessEqual(record["attribution_confidence"], 0.75)
        self.assertIn("no_supported_causal_test", {cap["name"] for cap in record["caps_applied"]})

    def _payload(self, persona):
        return {
            "persona": persona,
            "kpi_id": "orders", "target_date": "2023-07-24",
            "verdict": "MATERIAL_CAUSE_UNVERIFIED",
            "reconciliation_verdict": {"status": "NOT_RECONCILED"},
            "movement_assessment": {
                "status": "OK", "delta": -12.5, "is_material": True,
                "is_statistically_significant": True, "is_business_material": True,
            },
            "decomposition_status": "IDENTITY_HELD",
            "decomposition": {"total_delta": -12.5, "is_identity_held": True},
            "driver_analysis": {"status": "ASSESSED", "ranked_drivers": [
                {"driver_id": "checkout_latency", "claim_type": "ATTRIBUTED_DRIVER",
                 "relationship_type": "ATTRIBUTION", "attribution_confidence": 0.72,
                 "band": "MODERATE", "explained_share": 0.25, "contribution": -3.0,
                 "contribution_interval": [-4.0, -2.0]},
            ]},
            "correlational_candidates": [
                {"driver_id": "checkout_latency", "claim_type": "CORRELATIONAL"}
            ],
            "causal_verdict": "INCONCLUSIVE",
            "causal_verification": {"verdict": "INCONCLUSIVE"},
        }

    def test_same_payload_has_distinct_valid_claim_orders_for_three_personas(self):
        engine = NarrativeEngine()
        claim_sets = []
        for persona in ("cfo", "marketing_manager", "regional_manager_north"):
            payload = self._payload(persona)
            claims = engine._claims(payload)
            passed, errors = engine.validate(payload, claims)
            self.assertTrue(passed, errors)
            claim_sets.append(tuple(claim.claim_type for claim in claims))
        self.assertGreater(len(set(claim_sets)), 1)

    def test_likely_caused_wording_requires_confidence_and_supported_test(self):
        engine = NarrativeEngine()
        for confidence, verdict in ((0.55, "SUPPORTED_CONDITIONAL"),
                                    (0.75, "INCONCLUSIVE")):
            with self.subTest(confidence=confidence, verdict=verdict):
                payload = self._payload("cfo")
                payload["causal_verdict"] = verdict
                payload["causal_verification"] = {"verdict": verdict, "driver_id": "checkout_latency"}
                payload["driver_analysis"]["ranked_drivers"][0]["attribution_confidence"] = confidence
                claims = list(engine._claims(payload))
                index = next(i for i, claim in enumerate(claims)
                             if claim.claim_type == "ATTRIBUTED_DRIVER")
                claims[index] = replace(claims[index], text="checkout_latency likely caused the orders change.")
                passed, _ = engine.validate(payload, tuple(claims))
                self.assertFalse(passed)

    def test_verified_cause_renders_grounded_narrative(self):
        payload = self._payload("cfo")
        payload["causal_verdict"] = "SUPPORTED_CONDITIONAL"
        payload["causal_verification"] = {
            "verdict": "SUPPORTED_CONDITIONAL", "driver_id": "checkout_latency",
        }
        rendered = NarrativeEngine().render(payload)
        self.assertTrue(rendered["grounding_passed"], rendered["rejected_claims"])
        self.assertIn("likely caused", rendered["text"])

    def test_attribution_confidence_display_never_rounds_to_100_percent(self):
        phrase = NarrativeEngine._confidence_phrase
        self.assertIn("99.5%", phrase({"attribution_confidence": 0.995}))
        self.assertIn("99.8%", phrase({"attribution_confidence": 0.998}))
        self.assertIn("99.9%", phrase({"attribution_confidence": 1.0}))
        self.assertNotIn("100%", phrase({"attribution_confidence": 1.0}))

    def test_impact_projection_and_validation_label(self):
        result = {"contract_snapshot": {"materiality": {"business_thresholds": {"unit": "orders/day"}}}}
        driver = {"contribution": -3.0, "contribution_interval": [-4.0, -2.0]}
        impact = ActionRecommendationEngine._impact_estimate(result, driver)
        self.assertEqual(impact["expected_impact"], 21.0)
        self.assertEqual((impact["expected_impact_low"], impact["expected_impact_high"]), (14.0, 28.0))

        action_payload = self._payload("cfo")
        action_payload.update({
            "confidence_profile": {"overall": {"status": "LOW"}, "source": {"status": "HIGH"}},
            "driver_analysis": {"status": "ASSESSED", "ranked_drivers": [
                {"driver_id": "checkout_latency", "rank": 1, "contribution": -3.0,
                 "contribution_interval": [-4.0, -2.0], "attribution_confidence": 0.42,
                 "band": "LOW", "controllability": "controllable"},
            ]},
        })
        card = ActionRecommendationEngine.recommend(action_payload)[0]
        self.assertIsNotNone(card["expected_impact"])
        self.assertIn("not validated", card["impact_explanation"].lower())

    def test_impact_bounds_normalize_negative_zero(self):
        impact = ActionRecommendationEngine._impact_estimate({}, {
            "contribution": 0.0, "contribution_interval": [0.0, 0.0],
        })
        for key in ("expected_impact_low", "expected_impact_high"):
            self.assertEqual(math.copysign(1, impact[key]), 1)
            self.assertEqual(str(impact[key]), "0")

    def test_card_kind_tracks_attribution_confidence_and_causal_support(self):
        def card(ac, verdict):
            payload = self._payload("cfo")
            payload["confidence_profile"] = {"overall": {"status": "MODERATE"}, "source": {"status": "HIGH"}}
            payload["causal_verification"] = {"verdict": verdict, "driver_id": "checkout_latency"}
            payload["driver_analysis"]["ranked_drivers"][0]["attribution_confidence"] = ac
            return ActionRecommendationEngine.recommend(payload)[0]

        self.assertEqual(card(0.42, "INCONCLUSIVE")["kind"], "NEXT_CHECK")
        self.assertEqual(card(0.72, "INCONCLUSIVE")["kind"], "VERIFY_THEN_ACT")
        self.assertEqual(card(0.72, "SUPPORTED_CONDITIONAL")["kind"], "ACTION_PROPOSAL")

    def test_action_proposal_carries_projected_impact_range(self):
        payload = self._payload("cfo")
        payload["confidence_profile"] = {"overall": {"status": "MODERATE"}, "source": {"status": "HIGH"}}
        payload["causal_verification"] = {"verdict": "SUPPORTED_CONDITIONAL", "driver_id": "checkout_latency"}
        card = ActionRecommendationEngine.recommend(payload)[0]
        self.assertEqual(card["kind"], "ACTION_PROPOSAL")
        self.assertEqual((card["expected_impact_low"], card["expected_impact_high"]), (14.0, 28.0))


if __name__ == "__main__":
    unittest.main()
