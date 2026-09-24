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


if __name__ == "__main__":
    unittest.main()
