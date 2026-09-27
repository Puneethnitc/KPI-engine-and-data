"""Evidence diagnostics never turn an inconclusive result into a causal claim."""

import unittest

from kpi_engine.confidence import ConfidenceEngine
from kpi_engine.verification import CausalVerificationResult


class EvidenceQualityTests(unittest.TestCase):
    def test_missing_design_is_not_assessed(self):
        assessment = ConfidenceEngine.assess(CausalVerificationResult(
            "", "UNTESTABLE", "NO_DESIGN", "No design supplied",
        ))
        self.assertEqual(assessment.status, "NOT_ASSESSED")
        self.assertTrue(all(value is None for value in assessment.sub_scores.values()))
        self.assertIsNone(assessment.calibrated_probability)

    def test_inconclusive_interval_cannot_become_support(self):
        assessment = ConfidenceEngine.assess(CausalVerificationResult(
            "traffic_drop", "INCONCLUSIVE", "CI_INCLUDES_ZERO", "Interval spans zero",
            did_effect=-10, confidence_interval=(-25, 5), pre_days=30,
            post_days=14, temporal_precedence_passed=True,
        ))
        self.assertEqual(assessment.status, "INCONCLUSIVE")
        self.assertEqual(assessment.sub_scores["outcome_window_coverage"], 1)
        self.assertEqual(assessment.sub_scores["temporal_precedence"], 1)
        self.assertEqual(assessment.sub_scores["did_interval_precision"], 0)


class ConfidenceProfileTests(unittest.TestCase):
    def setUp(self):
        self.engine = ConfidenceEngine()

    @staticmethod
    def base_result():
        return {
            "verdict": "MATERIAL_CAUSE_UNVERIFIED",
            "movement_assessment": {
                "status": "OK", "actual_value": 120, "expected_value": 100,
                "delta": 20, "z_score": 3.1, "is_statistically_significant": True,
                "is_business_material": True, "detector_agreement": "BOTH",
                "baseline_count": 60, "method": "robust_plus_mstl_forecast",
            },
            "source_evidence": {
                "source_readiness": {
                    "status": "READY", "required_sources": ["sales_daily"],
                    "available_sources": ["sales_daily"], "limitations": [],
                },
                "sources": [{"source_id": "sales_daily", "coverage_status": "FULL", "quality_status": "OK"}],
                "reconciliation": {"status": "NOT_APPLICABLE", "applicable": False, "blocking": False},
            },
            "reconciliation_verdict": {"status": "NOT_APPLICABLE", "applicable": False, "blocking": False},
            "correlational_candidates": [],
            "driver_exclusions": [],
            "driver_analysis": {
                "status": "INSUFFICIENT_EVIDENCE", "ranked_drivers": [],
                "excluded_drivers": [], "limitations": [],
            },
            "causal_verification": {
                "verdict": "UNTESTABLE", "reason_code": "NO_DESIGN",
                "reason": "No design supplied", "pre_days": 0, "post_days": 0,
            },
            "confidence": {"status": "NOT_ASSESSED", "reasons": ["NO_DESIGN", "No design supplied"]},
        }

    def test_material_movement_does_not_invent_causal_probability(self):
        profile = self.engine.build_profile(self.base_result())
        self.assertEqual(profile["movement"]["status"], "HIGH")
        self.assertEqual(profile["causal"]["status"], "NOT_ASSESSED")
        self.assertIsNone(profile["causal"]["score"])
        self.assertIsNone(profile["causal"].get("probability"))
        self.assertEqual(profile["overall"]["status"], "MODERATE")
        required_fields = {
            "status", "score", "score_scale", "score_interpretation", "method",
            "inputs", "reasons", "limitations", "evaluated_at", "applicable",
            "blocking", "evidence_refs",
        }
        for key in ("movement", "source", "driver", "causal"):
            self.assertTrue(required_fields.issubset(profile[key]))
            self.assertIsNone(profile[key]["score"])

    def test_sparse_history_abstains_overall(self):
        result = self.base_result()
        result["verdict"] = "INSUFFICIENT_HISTORY"
        result["movement_assessment"] = {"status": "INSUFFICIENT_HISTORY", "baseline_count": 4}
        profile = self.engine.build_profile(result)
        self.assertEqual(profile["movement"]["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(profile["overall"]["status"], "INSUFFICIENT_EVIDENCE")

    def test_contradictory_sources_block_causal_and_overall_claims(self):
        result = self.base_result()
        result["reconciliation_verdict"] = {"status": "CONTRADICTED", "applicable": True, "blocking": True}
        profile = self.engine.build_profile(result, causal_design_approved=True)
        self.assertEqual(profile["source"]["status"], "CONFLICTING_EVIDENCE")
        self.assertTrue(profile["source"]["blocking"])
        self.assertEqual(profile["causal"]["status"], "CONFLICTING_EVIDENCE")
        self.assertTrue(profile["causal"]["blocking"])
        self.assertEqual(profile["overall"]["status"], "CONFLICTING_EVIDENCE")

    def test_not_applicable_reconciliation_is_neutral(self):
        result = self.base_result()
        not_applicable_status = self.engine.build_profile(result)["source"]["status"]
        result["reconciliation_verdict"] = {"status": "AGREED", "applicable": True, "blocking": False}
        agreed_status = self.engine.build_profile(result)["source"]["status"]
        self.assertEqual(not_applicable_status, agreed_status)
        self.assertEqual(not_applicable_status, "HIGH")

    def test_ranked_correlation_is_association_not_causality(self):
        result = self.base_result()
        result["driver_analysis"] = {
            "status": "ASSESSED", "limitations": [], "excluded_drivers": [],
            "ranked_drivers": [{
                "driver_id": "traffic", "display_name": "Online traffic",
                "score_name": "composite association score", "score": 0.61,
                "raw_correlation": 0.72, "sample_size": 40,
                "stability_status": "STABLE", "relationship_type": "ASSOCIATION",
            }],
        }
        profile = self.engine.build_profile(result)
        self.assertEqual(profile["driver"]["status"], "MODERATE")
        self.assertIsNone(profile["driver"]["score"])
        self.assertIn("Association only, not a causal estimate.", profile["driver"]["limitations"])
        self.assertEqual(profile["driver"]["inputs"]["driver_analysis"]["ranked_drivers"][0]["driver_id"], "traffic")
        self.assertEqual(profile["causal"]["status"], "NOT_ASSESSED")

    def test_failed_driver_exclusions_are_visible_without_positive_score(self):
        result = self.base_result()
        result["driver_analysis"] = {
            "status": "INSUFFICIENT_EVIDENCE", "ranked_drivers": [], "limitations": [],
            "excluded_drivers": [{
                "driver_id": "traffic", "reason_code": "INSUFFICIENT_HISTORY",
                "reason": "Only 5 paired changes; need at least 14", "sample_size": 5,
            }],
        }
        profile = self.engine.build_profile(result)
        self.assertEqual(profile["driver"]["status"], "INSUFFICIENT_EVIDENCE")
        self.assertIsNone(profile["driver"]["score"])
        self.assertEqual(profile["driver"]["inputs"]["exclusions"][0]["reason_code"], "INSUFFICIENT_HISTORY")

    def test_approved_design_uses_diagnostics_and_interval_status(self):
        result = self.base_result()
        result["causal_verification"] = {
            "verdict": "INCONCLUSIVE", "reason_code": "CI_INCLUDES_ZERO",
            "reason": "Interval spans zero", "method": "daily_gap_did_hac",
            "pre_days": 30, "post_days": 14, "temporal_precedence_passed": True,
            "pretrend_slope": 0.01, "pretrend_p_value": 0.4,
            "did_effect": -10, "confidence_interval": [-25, 5],
        }
        result["confidence"] = {
            "status": "INCONCLUSIVE", "sub_scores": {"did_interval_precision": 0},
            "reasons": ["CI_INCLUDES_ZERO", "Interval spans zero"],
        }
        profile = self.engine.build_profile(result, causal_design_approved=True)
        self.assertEqual(profile["causal"]["status"], "LOW")
        self.assertEqual(profile["causal"]["inputs"]["pre_days"], 30)
        self.assertEqual(profile["causal"]["inputs"]["interval_precision_diagnostic"], 0)
        self.assertIsNone(profile["causal"]["score"])

    def test_approved_design_support_is_conditional_not_probability(self):
        result = self.base_result()
        result["causal_verification"] = {
            "verdict": "SUPPORTED_CONDITIONAL", "reason_code": "CHECKS_PASSED",
            "reason": "Predeclared diagnostics passed", "method": "daily_gap_did_hac",
            "pre_days": 30, "post_days": 14, "temporal_precedence_passed": True,
            "pretrend_slope": 0.01, "pretrend_p_value": 0.4,
            "did_effect": -10, "confidence_interval": [-15, -5],
            "placebo_effects": [0.01, -0.02],
        }
        result["confidence"] = {
            "status": "CONDITIONAL_SUPPORT",
            "sub_scores": {
                "outcome_window_coverage": 1,
                "temporal_precedence": 1,
                "did_interval_precision": 0.8,
            },
        }
        profile = self.engine.build_profile(result, causal_design_approved=True)
        self.assertEqual(profile["causal"]["status"], "MODERATE")
        self.assertEqual(profile["causal"]["inputs"]["outcome_window_coverage"], 1)
        self.assertEqual(profile["causal"]["inputs"]["interval"], [-15, -5])
        self.assertEqual(profile["causal"]["inputs"]["placebo_effects"], [0.01, -0.02])
        self.assertIsNone(profile["causal"]["score"])
        self.assertIn("not proof of causality", profile["causal"]["limitations"][0])

    def test_access_denied_profile_contains_no_protected_inputs(self):
        result = self.base_result()
        result.update(verdict="ACCESS_DENIED", secret_metric=991, movement_assessment={"actual_value": 991})
        profile = self.engine.build_profile(result)
        for key in ("movement", "source", "driver", "causal"):
            self.assertFalse(profile[key]["inputs"])
            self.assertFalse(profile[key]["evidence_refs"])
            self.assertFalse(profile[key]["applicable"])

    def test_blocking_failure_precedes_strong_other_dimensions(self):
        result = self.base_result()
        result["reconciliation_verdict"] = {"status": "CONTRADICTED", "blocking": True}
        profile = self.engine.build_profile(result)
        self.assertEqual(profile["movement"]["status"], "HIGH")
        self.assertEqual(profile["overall"]["status"], "CONFLICTING_EVIDENCE")
        self.assertEqual(profile["overall"]["blocking_dimensions"], ["source", "driver", "causal"])

    def test_conditional_support_is_not_probability(self):
        assessment = ConfidenceEngine.assess(CausalVerificationResult(
            "traffic_drop", "SUPPORTED_CONDITIONAL", "CHECKS_PASSED", "Passed",
            did_effect=-10, confidence_interval=(-15, -5), pre_days=14,
            post_days=7, temporal_precedence_passed=True,
        ))
        self.assertEqual(assessment.status, "CONDITIONAL_SUPPORT")
        self.assertIsNone(assessment.calibrated_probability)
        self.assertLess(assessment.sub_scores["did_interval_precision"], 1)

    def test_failed_temporal_gate_stays_insufficient(self):
        assessment = ConfidenceEngine.assess(CausalVerificationResult(
            "traffic_drop", "UNTESTABLE", "PRE_EVENT_MOVEMENT", "Moved early",
            did_effect=-10, confidence_interval=(-15, -5), pre_days=20,
            post_days=7, temporal_precedence_passed=False,
        ))
        self.assertEqual(assessment.status, "INSUFFICIENT")
        self.assertEqual(assessment.sub_scores["temporal_precedence"], 0)

    def test_confidence_uses_resolved_verification_policy(self):
        policy = type("Policy", (), {"min_pre_days": 10, "min_post_days": 5})()
        assessment = ConfidenceEngine.assess(CausalVerificationResult(
            "traffic_drop", "SUPPORTED_CONDITIONAL", "CHECKS_PASSED", "Passed",
            did_effect=-10, confidence_interval=(-15, -5), pre_days=10,
            post_days=5, temporal_precedence_passed=True,
            policy=policy,
        ))
        self.assertEqual(assessment.sub_scores["outcome_window_coverage"], 1)


if __name__ == "__main__":
    unittest.main()
