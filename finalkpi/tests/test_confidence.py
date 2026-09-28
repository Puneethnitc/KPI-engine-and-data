"""Evidence diagnostics never turn an inconclusive result into a causal claim.

Stage 7 rewrite (F-C1, F-C2): `build_profile`'s overall status is now the
weakest-required-dimension rule over movement/source/attribution/causal, with
`attribution` (the top-ranked driver's Attribution Confidence band) replacing
the old stability-only `driver` dimension. `driver` remains as an alias of
`attribution`. The old MODERATE-for-everything assertions are replaced:
MODERATE is no longer the default outcome when nothing was explained.
"""

import unittest

from kpi_engine.confidence import ConfidenceEngine
from kpi_engine.verification import CausalVerificationResult


def make_driver(driver_id="marketing_spend", **overrides):
    driver = {
        "driver_id": driver_id, "display_name": driver_id.replace("_", " ").title(),
        "rank": 1, "explained_share": 0.62, "driver_change_z": 3.4,
        "direction_consistent": True, "expected_direction": "positive",
        "lag_days": 2, "stability_status": "STABLE", "p_value_adj": 0.008,
        "coverage_ratio": 0.95, "moved": True, "offsetting": False,
        "sample_size": 40, "contribution": 800, "limitations": [],
    }
    driver.update(overrides)
    return driver


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
            "checkout_latency", "INCONCLUSIVE", "CI_INCLUDES_ZERO", "Interval spans zero",
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
    def base_result(ranked_drivers=None, excluded_drivers=None, causal_verification=None):
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
            "driver_exclusions": excluded_drivers or [],
            "driver_analysis": {
                "status": "ASSESSED" if ranked_drivers else "INSUFFICIENT_EVIDENCE",
                "ranked_drivers": ranked_drivers or [],
                "excluded_drivers": excluded_drivers or [], "limitations": [],
            },
            "causal_verification": causal_verification or {
                "verdict": "UNTESTABLE", "reason_code": "NO_DESIGN",
                "reason": "No design supplied", "pre_days": 0, "post_days": 0,
            },
            "confidence": {"status": "NOT_ASSESSED", "reasons": ["NO_DESIGN", "No design supplied"]},
        }

    # -- reachability of all 5 overall statuses --------------------------

    def test_all_five_overall_statuses_are_reachable(self):
        cases = {
            "HIGH": self.base_result(
                ranked_drivers=[make_driver()],
                causal_verification={
                    "driver_id": "marketing_spend", "verdict": "SUPPORTED_CONDITIONAL",
                    "reason_code": "CHECKS_PASSED", "reason": "Passed", "pre_days": 30, "post_days": 14,
                },
            ),
            "MODERATE": self.base_result(ranked_drivers=[make_driver()]),
            "LOW": self.base_result(ranked_drivers=[make_driver(explained_share=0.05, driver_change_z=1.6)]),
            "INSUFFICIENT_EVIDENCE": self.base_result(),
            "CONFLICTING_EVIDENCE": self.base_result(
                ranked_drivers=[make_driver()],
                causal_verification={
                    "driver_id": "marketing_spend", "verdict": "REJECTED",
                    "reason_code": "PLACEBO_FAILED", "reason": "Placebo effect too large",
                    "pre_days": 30, "post_days": 14,
                },
            ),
        }
        for expected_status, result in cases.items():
            with self.subTest(expected=expected_status):
                approved = expected_status in ("HIGH", "CONFLICTING_EVIDENCE")
                profile = self.engine.build_profile(result, causal_design_approved=approved)
                self.assertEqual(profile["overall"]["status"], expected_status)

    # -- corroboration reaching the AC calculation (Step C -> Step A) -----

    def test_corroboration_on_a_ranked_driver_raises_its_ac(self):
        """Stage 6-lite writes `corroboration` in the pipeline; Step A's
        build_profile is what has to read it and hand it to the AC model.

        This is the seam the two wave-1 agents could not both own: before this
        the field was produced but never consumed, so AC evidence item E8 was
        permanently dead and a document that corroborated a driver had no
        effect on how confident the engine was about it.
        """
        weak = dict(explained_share=0.22, driver_change_z=1.6, p_value_adj=0.06,
                    stability_status="SENSITIVE", lag_days=0)
        corroborated = make_driver(
            "marketing_spend", **weak,
            corroboration={"status": "CORROBORATED", "documents": [{"doc_id": "TCK-1001"}]},
        )
        unmatched = make_driver("promo_flag", **weak, corroboration={"status": "NONE", "documents": []})

        def ac_of(profile, driver_id):
            return next(item["attribution_confidence"] for item in profile["attribution_confidence"]
                        if item["driver_id"] == driver_id)

        with_docs = self.engine.build_profile(self.base_result(ranked_drivers=[corroborated, unmatched]))
        without_docs = self.engine.build_profile(
            self.base_result(ranked_drivers=[make_driver("marketing_spend", **weak), make_driver("promo_flag", **weak)]),
        )

        self.assertGreater(ac_of(with_docs, "marketing_spend"), ac_of(without_docs, "marketing_spend"))
        # A driver with no documents in scope must be unaffected: absent
        # corroboration contributes 0, never a penalty.
        self.assertEqual(ac_of(with_docs, "promo_flag"), ac_of(without_docs, "promo_flag"))

    def test_corroboration_cannot_score_a_driver_while_source_evidence_is_blocking(self):
        result = self.base_result(
            ranked_drivers=[make_driver(corroboration={"status": "CORROBORATED", "documents": [{"doc_id": "T"}]})],
        )
        result["source_evidence"]["reconciliation"] = {
            "status": "CONTRADICTED", "applicable": True, "blocking": True,
            "reason": "Ledger disagrees with the bank feed",
        }
        result["reconciliation_verdict"] = result["source_evidence"]["reconciliation"]
        profile = self.engine.build_profile(result)
        self.assertEqual(profile["attribution"]["status"], "CONFLICTING_EVIDENCE")
        # Blocked means no AC at all, not a low one: documents cannot rescue a
        # driver whose own source contradicts itself.
        self.assertEqual(profile["attribution_status"], "BLOCKED")
        self.assertEqual(profile["attribution_confidence"], [])

    # -- non-material and seasonal-review runs ---------------------------

    def test_non_material_run_caps_its_driver_ac_at_0_5_and_marks_it_exploratory(self):
        """A driver can clear every material band and still be capped out,
        because the movement itself never cleared materiality. Reporting that
        as MODERATE would be a number the engine does not believe."""
        result = self.base_result(ranked_drivers=[make_driver()])
        result["movement_assessment"]["is_material"] = False
        profile = self.engine.build_profile(result)
        driver = next(item for item in profile["attribution_confidence"] if item["driver_id"] == "marketing_spend")
        self.assertLessEqual(driver["attribution_confidence"], 0.5)
        self.assertEqual(driver["band"], "EXPLORATORY")
        self.assertTrue(any(cap["name"] == "non_material" for cap in driver["caps_applied"]))

    def test_seasonal_only_day_is_not_treated_as_material_just_because_the_delta_was_large(self):
        """The regression that motivated reading the ensemble's own verdict.

        A big delta can clear business materiality while still failing
        significance, which is exactly a SEASONAL_REVIEW day: the pipeline
        declines to diagnose it, but AC used to be computed as if it had, and
        the driver came out at 0.75 / MODERATE.
        """
        result = self.base_result(ranked_drivers=[make_driver()])
        result["movement_assessment"].update({
            "is_material": False, "is_statistically_significant": False,
            "is_business_material": True, "detector_agreement": "SEASONAL_ONLY",
        })
        profile = self.engine.build_profile(result)
        driver = next(item for item in profile["attribution_confidence"] if item["driver_id"] == "marketing_spend")
        self.assertLessEqual(driver["attribution_confidence"], 0.5)
        self.assertEqual(driver["band"], "EXPLORATORY")

    def test_every_ranked_driver_carries_an_ac_field(self):
        """No ranked driver may be shown without an AC.

        Offsetting drivers (they moved against the KPI) used to fall out of the
        AC set entirely, so they reached the UI with no score at all, which
        reads as "never assessed" rather than "scored, and low".
        """
        result = self.base_result(ranked_drivers=[
            make_driver("marketing_spend"),
            make_driver("weather_temp", offsetting=True, direction_consistent=False,
                        expected_direction="negative", contribution=-120),
        ])
        profile = self.engine.build_profile(result)
        for driver in result["driver_analysis"]["ranked_drivers"]:
            self.assertIn("attribution_confidence", driver)
            self.assertIsNotNone(driver["attribution_confidence"])
        by_id = {item["driver_id"]: item for item in profile["attribution_confidence"]}
        self.assertIn("weather_temp", by_id)
        self.assertLess(
            by_id["weather_temp"]["attribution_confidence"], by_id["marketing_spend"]["attribution_confidence"],
        )

    def test_rejected_top_driver_with_no_alternative_is_conflicting(self):
        result = self.base_result(
            ranked_drivers=[make_driver()],
            causal_verification={
                "driver_id": "marketing_spend", "verdict": "REJECTED",
                "reason_code": "PLACEBO_FAILED", "reason": "Placebo effect too large",
                "pre_days": 30, "post_days": 14,
            },
        )
        profile = self.engine.build_profile(result, causal_design_approved=True)
        self.assertEqual(profile["causal"]["status"], "CONFLICTING_EVIDENCE")
        self.assertEqual(profile["overall"]["status"], "CONFLICTING_EVIDENCE")

    def test_rejected_top_driver_with_strong_alternative_is_not_conflicting(self):
        result = self.base_result(
            ranked_drivers=[
                make_driver("marketing_spend", explained_share=0.4),
                make_driver("stock_availability", explained_share=0.55, driver_change_z=4.0, p_value_adj=0.002),
            ],
            causal_verification={
                "driver_id": "marketing_spend", "verdict": "REJECTED",
                "reason_code": "PLACEBO_FAILED", "reason": "Placebo effect too large",
                "pre_days": 30, "post_days": 14,
            },
        )
        profile = self.engine.build_profile(result, causal_design_approved=True)
        drivers_by_id = {item["driver_id"]: item for item in profile["attribution_confidence"] if item["driver_id"] != "unexplained"}
        self.assertGreaterEqual(drivers_by_id["stock_availability"]["attribution_confidence"], 0.6)
        self.assertNotEqual(profile["overall"]["status"], "CONFLICTING_EVIDENCE")

    def test_no_ranked_driver_is_insufficient_evidence(self):
        result = self.base_result()
        profile = self.engine.build_profile(result)
        self.assertEqual(profile["attribution"]["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(profile["driver"]["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(profile["overall"]["status"], "INSUFFICIENT_EVIDENCE")

    def test_no_causal_test_caps_attribution_below_high(self):
        result = self.base_result(ranked_drivers=[make_driver()])
        profile = self.engine.build_profile(result)
        top = profile["attribution_confidence"][0]
        self.assertLessEqual(top["attribution_confidence"], 0.75)
        self.assertIn("no_supported_causal_test", [cap["name"] for cap in top["caps_applied"]])
        self.assertNotEqual(profile["attribution"]["status"], "HIGH")

    def test_causal_rejected_caps_attribution_at_0_20(self):
        result = self.base_result(
            ranked_drivers=[make_driver()],
            causal_verification={
                "driver_id": "marketing_spend", "verdict": "REJECTED",
                "reason_code": "PLACEBO_FAILED", "reason": "Placebo effect too large",
                "pre_days": 30, "post_days": 14,
            },
        )
        profile = self.engine.build_profile(result, causal_design_approved=True)
        top = profile["attribution_confidence"][0]
        self.assertLessEqual(top["attribution_confidence"], 0.20)
        self.assertIn("causal_rejected", [cap["name"] for cap in top["caps_applied"]])

    def test_absent_corroboration_is_neutral_not_penalized(self):
        # Step C (Stage 6-lite) is not built yet, so build_profile always
        # calls the AC engine with corroboration absent; that must score the
        # same as an explicit NONE, never a CONTRADICTED-style penalty.
        result = self.base_result(ranked_drivers=[make_driver()])
        profile = self.engine.build_profile(result)
        top = profile["attribution_confidence"][0]
        corroboration_evidence = next(item for item in top["evidence"] if item["id"] == "E8")
        self.assertEqual(corroboration_evidence["weight_contribution"], 0.0)

    def test_contradictory_sources_block_causal_and_overall_claims(self):
        result = self.base_result(ranked_drivers=[make_driver()])
        result["reconciliation_verdict"] = {"status": "CONTRADICTED", "applicable": True, "blocking": True}
        profile = self.engine.build_profile(result, causal_design_approved=True)
        self.assertEqual(profile["source"]["status"], "CONFLICTING_EVIDENCE")
        self.assertTrue(profile["source"]["blocking"])
        self.assertEqual(profile["causal"]["status"], "CONFLICTING_EVIDENCE")
        self.assertTrue(profile["causal"]["blocking"])
        self.assertEqual(profile["attribution"]["status"], "CONFLICTING_EVIDENCE")
        self.assertEqual(profile["overall"]["status"], "CONFLICTING_EVIDENCE")

    def test_not_applicable_reconciliation_is_neutral(self):
        result = self.base_result()
        not_applicable_status = self.engine.build_profile(result)["source"]["status"]
        result["reconciliation_verdict"] = {"status": "AGREED", "applicable": True, "blocking": False}
        agreed_status = self.engine.build_profile(result)["source"]["status"]
        self.assertEqual(not_applicable_status, agreed_status)
        self.assertEqual(not_applicable_status, "HIGH")

    def test_failed_driver_exclusions_are_visible_without_a_confident_driver(self):
        result = self.base_result(excluded_drivers=[{
            "driver_id": "traffic", "reason_code": "INSUFFICIENT_HISTORY",
            "reason": "Only 5 paired changes; need at least 14", "sample_size": 5,
        }])
        profile = self.engine.build_profile(result)
        self.assertEqual(profile["driver"]["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(profile["driver"]["inputs"]["exclusions"][0]["reason_code"], "INSUFFICIENT_HISTORY")

    def test_ambiguous_top_two_drivers_downgrade_attribution_to_low(self):
        result = self.base_result(ranked_drivers=[
            make_driver("marketing_spend", explained_share=0.5, driver_change_z=3.0, p_value_adj=0.03),
            make_driver("promo_flag", explained_share=0.48, driver_change_z=2.9, p_value_adj=0.03),
        ])
        profile = self.engine.build_profile(result)
        self.assertEqual(profile["attribution_status"], "AMBIGUOUS")
        self.assertEqual(profile["attribution"]["status"], "LOW")

    def test_low_confidence_top_driver_is_no_confident_driver(self):
        weak = make_driver(
            explained_share=0.05, driver_change_z=1.5, direction_consistent=None,
            expected_direction=None, lag_days=0, stability_status="SENSITIVE",
            p_value_adj=0.25, coverage_ratio=0.5,
        )
        result = self.base_result(ranked_drivers=[weak])
        profile = self.engine.build_profile(result)
        self.assertEqual(profile["attribution_status"], "NO_CONFIDENT_DRIVER")
        self.assertEqual(profile["attribution"]["status"], "INSUFFICIENT_EVIDENCE")

    def test_access_denied_profile_contains_no_protected_inputs(self):
        result = self.base_result()
        result.update(verdict="ACCESS_DENIED", secret_metric=991, movement_assessment={"actual_value": 991})
        profile = self.engine.build_profile(result)
        for key in ("movement", "source", "driver", "attribution", "causal"):
            self.assertFalse(profile[key]["inputs"])
            self.assertFalse(profile[key]["evidence_refs"])
            self.assertFalse(profile[key]["applicable"])
        self.assertEqual(profile["attribution_confidence"], [])

    def test_blocking_failure_precedes_strong_other_dimensions(self):
        result = self.base_result()
        result["reconciliation_verdict"] = {"status": "CONTRADICTED", "blocking": True}
        profile = self.engine.build_profile(result)
        self.assertEqual(profile["movement"]["status"], "HIGH")
        self.assertEqual(profile["overall"]["status"], "CONFLICTING_EVIDENCE")
        self.assertIn("source", profile["overall"]["blocking_dimensions"])
        self.assertIn("attribution", profile["overall"]["blocking_dimensions"])
        self.assertIn("causal", profile["overall"]["blocking_dimensions"])

    def test_two_headline_conclusions_are_reported(self):
        result = self.base_result(ranked_drivers=[make_driver()])
        profile = self.engine.build_profile(result)
        self.assertIn("movement_conclusion", profile["overall"])
        self.assertIn("explanation_conclusion", profile["overall"])
        self.assertEqual(profile["overall"]["movement_conclusion"], "HIGH")

    def test_conditional_support_is_not_probability(self):
        assessment = ConfidenceEngine.assess(CausalVerificationResult(
            "checkout_latency", "SUPPORTED_CONDITIONAL", "CHECKS_PASSED", "Passed",
            did_effect=-10, confidence_interval=(-15, -5), pre_days=14,
            post_days=7, temporal_precedence_passed=True,
        ))
        self.assertEqual(assessment.status, "CONDITIONAL_SUPPORT")
        self.assertIsNone(assessment.calibrated_probability)
        self.assertLess(assessment.sub_scores["did_interval_precision"], 1)

    def test_failed_temporal_gate_stays_insufficient(self):
        assessment = ConfidenceEngine.assess(CausalVerificationResult(
            "checkout_latency", "UNTESTABLE", "PRE_EVENT_MOVEMENT", "Moved early",
            did_effect=-10, confidence_interval=(-15, -5), pre_days=20,
            post_days=7, temporal_precedence_passed=False,
        ))
        self.assertEqual(assessment.status, "INSUFFICIENT")
        self.assertEqual(assessment.sub_scores["temporal_precedence"], 0)

    def test_confidence_uses_resolved_verification_policy(self):
        policy = type("Policy", (), {"min_pre_days": 10, "min_post_days": 5})()
        assessment = ConfidenceEngine.assess(CausalVerificationResult(
            "checkout_latency", "SUPPORTED_CONDITIONAL", "CHECKS_PASSED", "Passed",
            did_effect=-10, confidence_interval=(-15, -5), pre_days=10,
            post_days=5, temporal_precedence_passed=True,
            policy=policy,
        ))
        self.assertEqual(assessment.sub_scores["outcome_window_coverage"], 1)


if __name__ == "__main__":
    unittest.main()
