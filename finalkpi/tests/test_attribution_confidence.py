"""Attribution Confidence (AC) engine: log-odds arithmetic, caps, bands,
model loading and the ambiguity/no-confident-driver rules (Plan §7.1)."""

import math
import unittest

from kpi_engine.attribution_confidence import (
    AttributionConfidenceEngine,
    AttributionConfidenceModel,
    default_model,
)


def make_driver(driver_id="marketing_spend", **overrides):
    driver = {
        "driver_id": driver_id, "display_name": driver_id.replace("_", " ").title(),
        "explained_share": 0.62, "driver_change_z": 3.4,
        "direction_consistent": True, "expected_direction": "positive",
        "lag_days": 2, "stability_status": "STABLE", "p_value_adj": 0.008,
        "coverage_ratio": 0.95, "moved": True, "offsetting": False,
        "sample_size": 40, "contribution": 800,
    }
    driver.update(overrides)
    return driver


class ModelLoadingTests(unittest.TestCase):
    def test_default_model_loads_v1(self):
        model = default_model()
        self.assertEqual(model.version, "attribution-confidence-v1")
        self.assertIn("HIGH", model.bands)
        self.assertIn("no_causal_test_max", model.caps)

    def test_model_is_a_frozen_dataclass_with_bands_ordered(self):
        model = AttributionConfidenceModel.load()
        self.assertEqual(model.band_for(0.9)[0], "HIGH")
        self.assertEqual(model.band_for(0.8)[0], "HIGH")
        self.assertEqual(model.band_for(0.79)[0], "MODERATE")
        self.assertEqual(model.band_for(0.6)[0], "MODERATE")
        self.assertEqual(model.band_for(0.59)[0], "LOW")
        self.assertEqual(model.band_for(0.35)[0], "LOW")
        self.assertEqual(model.band_for(0.34)[0], "VERY_LOW")
        self.assertEqual(model.band_for(0.0)[0], "VERY_LOW")


class LogOddsArithmeticTests(unittest.TestCase):
    def test_prior_reflects_number_of_eligible_moved_drivers(self):
        self.assertAlmostEqual(AttributionConfidenceEngine.prior(0), 1.0)
        self.assertAlmostEqual(AttributionConfidenceEngine.prior(1), 0.5)
        self.assertAlmostEqual(AttributionConfidenceEngine.prior(3), 0.25)

    def test_prior_override_is_used_verbatim(self):
        self.assertAlmostEqual(AttributionConfidenceEngine.prior(3, override=0.9), 0.9)

    def test_ac_equals_sigmoid_of_logit_prior_plus_weighted_evidence_sum(self):
        model = default_model()
        driver = make_driver()
        record = AttributionConfidenceEngine.compute_driver(
            driver, prior=0.5, is_material=True, source_status="HIGH",
            causal_result={"driver_id": "marketing_spend", "verdict": "SUPPORTED_CONDITIONAL"},
            model=model,
        )
        manual_logit = math.log(0.5 / 0.5) + sum(item["weight_contribution"] for item in record["evidence"])
        expected = 1 / (1 + math.exp(-manual_logit))
        self.assertAlmostEqual(record["attribution_confidence"], round(expected, 4), places=4)

    def test_feature_activations_reconstruct_the_same_logit_as_compute_driver(self):
        # --calibrate (tests/run_ground_truth_eval.py) fits new weights
        # against feature_activations; it must stay in lockstep with
        # compute_driver's own logit sum, or a calibrated file would not
        # reproduce the engine's own scores.
        model = default_model()
        driver = make_driver()
        causal = {"driver_id": "marketing_spend", "verdict": "SUPPORTED_CONDITIONAL"}
        corroboration = {"status": "CORROBORATED", "documents": []}
        record = AttributionConfidenceEngine.compute_driver(
            driver, prior=0.5, is_material=True, source_status="HIGH",
            causal_result=causal, corroboration=corroboration, model=model,
        )
        features = AttributionConfidenceEngine.feature_activations(
            driver, causal_result=causal, corroboration=corroboration,
            source_status="HIGH", model=model,
        )
        reconstructed_logit = math.log(0.5 / 0.5) + sum(
            features[key] * model.weights[key] for key in AttributionConfidenceEngine.WEIGHT_KEYS
        )
        expected_ac = round(1 / (1 + math.exp(-reconstructed_logit)), 4)
        # No caps apply in this fixture (material, direction declared, causal ran).
        self.assertAlmostEqual(record["attribution_confidence"], expected_ac, places=4)

    def test_each_evidence_item_is_reported_with_its_weight_contribution(self):
        record = AttributionConfidenceEngine.compute_driver(
            make_driver(), prior=0.5, is_material=True, source_status="HIGH",
            causal_result={"driver_id": "marketing_spend", "verdict": "SUPPORTED_CONDITIONAL"},
        )
        ids = {item["id"] for item in record["evidence"]}
        self.assertEqual(ids, {f"E{i}" for i in range(1, 10)})


class CapTests(unittest.TestCase):
    def test_no_causal_test_caps_at_0_75(self):
        record = AttributionConfidenceEngine.compute_driver(
            make_driver(), prior=0.5, is_material=True, source_status="HIGH",
        )
        self.assertLessEqual(record["attribution_confidence"], 0.75)
        self.assertEqual(record["caps_applied"][0]["name"], "no_causal_test")

    def test_causal_rejected_caps_at_0_20(self):
        record = AttributionConfidenceEngine.compute_driver(
            make_driver(), prior=0.5, is_material=True, source_status="HIGH",
            causal_result={"driver_id": "marketing_spend", "verdict": "REJECTED"},
        )
        self.assertLessEqual(record["attribution_confidence"], 0.20)
        self.assertTrue(any(cap["name"] == "causal_rejected" for cap in record["caps_applied"]))

    def test_direction_undeclared_caps_at_0_60(self):
        driver = make_driver(direction_consistent=None, expected_direction=None)
        record = AttributionConfidenceEngine.compute_driver(
            driver, prior=0.5, is_material=True, source_status="HIGH",
            causal_result={"driver_id": "marketing_spend", "verdict": "SUPPORTED_CONDITIONAL"},
        )
        self.assertLessEqual(record["attribution_confidence"], 0.60)
        self.assertTrue(any(cap["name"] == "direction_undeclared" for cap in record["caps_applied"]))

    def test_non_material_movement_caps_at_0_5_and_is_exploratory(self):
        record = AttributionConfidenceEngine.compute_driver(
            make_driver(), prior=0.5, is_material=False, source_status="HIGH",
            causal_result={"driver_id": "marketing_spend", "verdict": "SUPPORTED_CONDITIONAL"},
        )
        self.assertLessEqual(record["attribution_confidence"], 0.5)
        self.assertEqual(record["band"], "EXPLORATORY")

    def test_multiple_caps_take_the_strictest_bound(self):
        driver = make_driver(direction_consistent=None, expected_direction=None)
        record = AttributionConfidenceEngine.compute_driver(
            driver, prior=0.5, is_material=True, source_status="HIGH",
            causal_result={"driver_id": "marketing_spend", "verdict": "REJECTED"},
        )
        self.assertLessEqual(record["attribution_confidence"], 0.20)


class CorroborationMonotonicityTests(unittest.TestCase):
    def test_corroborated_never_scores_below_none(self):
        base_kwargs = dict(
            prior=0.5, is_material=True, source_status="HIGH",
            causal_result={"driver_id": "marketing_spend", "verdict": "SUPPORTED_CONDITIONAL"},
        )
        none_record = AttributionConfidenceEngine.compute_driver(make_driver(), **base_kwargs)
        corroborated_record = AttributionConfidenceEngine.compute_driver(
            make_driver(), corroboration={"status": "CORROBORATED", "documents": [{"doc_id": "TCK-1001"}]},
            **base_kwargs,
        )
        self.assertGreaterEqual(
            corroborated_record["attribution_confidence"], none_record["attribution_confidence"],
        )

    def test_contradicted_never_scores_above_none(self):
        base_kwargs = dict(
            prior=0.5, is_material=True, source_status="HIGH",
            causal_result={"driver_id": "marketing_spend", "verdict": "SUPPORTED_CONDITIONAL"},
        )
        none_record = AttributionConfidenceEngine.compute_driver(make_driver(), **base_kwargs)
        contradicted_record = AttributionConfidenceEngine.compute_driver(
            make_driver(), corroboration={"status": "CONTRADICTED", "documents": []}, **base_kwargs,
        )
        self.assertLessEqual(
            contradicted_record["attribution_confidence"], none_record["attribution_confidence"],
        )

    def test_compute_profile_raises_the_ac_of_the_corroborated_driver_only(self):
        """E8 wired through the profile, not just compute_driver.

        A corroborated driver must end up with a strictly higher AC than the
        same driver with no documents in scope, and the corroborating doc_id
        must be named in its E8 evidence row. The other driver's AC must not
        move: corroboration is per-driver, never a run-level bonus.
        """
        corroboration = {
            "marketing_spend": {"status": "CORROBORATED", "documents": [{"doc_id": "TCK-1001"}]},
            "promo_flag": {"status": "NONE", "documents": []},
        }
        base = dict(is_material=True, source_status="HIGH")
        # Deliberately middling drivers: a strong one sits on the 0.75 "no
        # causal test" cap either way, and the cap would hide whether E8 was
        # applied at all. Identical apart from the id, so the only thing that
        # can move one of the two ACs is its own corroboration block.
        weak = dict(explained_share=0.22, driver_change_z=1.6, p_value_adj=0.06,
                    stability_status="SENSITIVE", lag_days=0)
        ranked = [make_driver("marketing_spend", **weak), make_driver("promo_flag", **weak)]
        with_docs = AttributionConfidenceEngine.compute_profile(
            ranked_drivers=ranked, corroboration_by_driver=corroboration, **base,
        )
        without_docs = AttributionConfidenceEngine.compute_profile(ranked_drivers=ranked, **base)

        def ac_by_id(profile, driver_id):
            return next(item["attribution_confidence"] for item in profile["drivers"]
                        if item["driver_id"] == driver_id)

        self.assertLess(
            ac_by_id(without_docs, "marketing_spend"), default_model().caps["no_causal_test_max"],
        )
        self.assertGreater(
            ac_by_id(with_docs, "marketing_spend"), ac_by_id(without_docs, "marketing_spend"),
        )
        self.assertEqual(
            ac_by_id(with_docs, "promo_flag"), ac_by_id(without_docs, "promo_flag"),
        )
        # Corroboration is what moves it across a band boundary, not just a digit.
        self.assertLess(ac_by_id(without_docs, "marketing_spend"), 0.60)
        self.assertGreaterEqual(ac_by_id(with_docs, "marketing_spend"), 0.60)
        e8 = next(item for item in with_docs["drivers"][0]["evidence"] if item["id"] == "E8")
        self.assertEqual(e8["value"], "CORROBORATED")
        self.assertEqual(e8["doc_ids"], ["TCK-1001"])
        self.assertGreater(e8["weight_contribution"], 0.0)


class OffsettingDriverCoverageTests(unittest.TestCase):
    def test_an_offsetting_ranked_driver_still_gets_an_ac(self):
        """No ranked driver may be shown without an AC.

        An offsetting driver moved against the KPI's direction. That is a
        statement about the driver, and it is already scored through E2
        (strong movement) and E3 (direction conflict), so it is scored like any
        other mover instead of being left out of the profile entirely -- a
        ranked driver with no AC reads to the user as "never assessed".
        """
        profile = AttributionConfidenceEngine.compute_profile(
            ranked_drivers=[
                make_driver("marketing_spend"),
                make_driver("weather_temp", offsetting=True, direction_consistent=False,
                            expected_direction="negative"),
            ],
            is_material=True, source_status="HIGH",
        )
        by_id = {item["driver_id"]: item for item in profile["drivers"]}
        self.assertIn("weather_temp", by_id)
        self.assertIsNotNone(by_id["weather_temp"]["attribution_confidence"])
        # Moved the wrong way for a movement it is being ranked against, so it
        # must not outrank the driver whose direction agrees.
        self.assertEqual(profile["top_driver_id"], "marketing_spend")


class NonMaterialBandTests(unittest.TestCase):
    def test_non_material_driver_reports_the_exploratory_label(self):
        record = AttributionConfidenceEngine.compute_driver(
            make_driver(), prior=0.5, is_material=False, source_status="HIGH",
            causal_result={"driver_id": "marketing_spend", "verdict": "SUPPORTED_CONDITIONAL"},
        )
        self.assertEqual(record["band"], "EXPLORATORY")
        # The band is not just renamed: its label must not still claim the
        # driver is a "likely contributing cause".
        self.assertNotIn("Likely", record["label"])
        self.assertIn("not material", record["label"])

    def test_exploratory_is_a_separate_band_not_a_material_rung(self):
        model = default_model()
        self.assertIn("EXPLORATORY", model.bands)
        # A material run is never labelled exploratory, however low it scores.
        record = AttributionConfidenceEngine.compute_driver(
            make_driver(explained_share=0.01, driver_change_z=1.6, p_value_adj=0.4),
            prior=0.5, is_material=True, source_status="LOW",
        )
        self.assertNotEqual(record["band"], "EXPLORATORY")


class ProfileAmbiguityTests(unittest.TestCase):
    def test_confident_single_driver(self):
        profile = AttributionConfidenceEngine.compute_profile(
            ranked_drivers=[make_driver()], is_material=True, source_status="HIGH",
            causal_verification={"driver_id": "marketing_spend", "verdict": "SUPPORTED_CONDITIONAL"},
        )
        self.assertEqual(profile["attribution_status"], "CONFIDENT")
        self.assertEqual(profile["top_driver_id"], "marketing_spend")

    def test_close_top_two_above_0_5_are_ambiguous(self):
        profile = AttributionConfidenceEngine.compute_profile(
            ranked_drivers=[
                make_driver("marketing_spend", explained_share=0.5, driver_change_z=3.0, p_value_adj=0.03),
                make_driver("promo_flag", explained_share=0.48, driver_change_z=2.9, p_value_adj=0.03),
            ],
            is_material=True, source_status="HIGH",
        )
        self.assertEqual(profile["attribution_status"], "AMBIGUOUS")

    def test_wide_gap_top_two_is_not_ambiguous(self):
        profile = AttributionConfidenceEngine.compute_profile(
            ranked_drivers=[
                make_driver("marketing_spend"),
                make_driver("promo_flag", explained_share=0.05, driver_change_z=1.6, p_value_adj=0.3),
            ],
            is_material=True, source_status="HIGH",
            causal_verification={"driver_id": "marketing_spend", "verdict": "SUPPORTED_CONDITIONAL"},
        )
        self.assertNotEqual(profile["attribution_status"], "AMBIGUOUS")

    def test_low_top_driver_is_no_confident_driver(self):
        weak = make_driver(
            explained_share=0.05, driver_change_z=1.5, direction_consistent=None,
            expected_direction=None, lag_days=0, stability_status="SENSITIVE",
            p_value_adj=0.25, coverage_ratio=0.5,
        )
        profile = AttributionConfidenceEngine.compute_profile(
            ranked_drivers=[weak], is_material=True, source_status="HIGH",
        )
        self.assertEqual(profile["attribution_status"], "NO_CONFIDENT_DRIVER")

    def test_no_ranked_drivers_is_no_drivers(self):
        profile = AttributionConfidenceEngine.compute_profile(
            ranked_drivers=[], is_material=True, source_status="HIGH",
        )
        self.assertEqual(profile["attribution_status"], "NO_DRIVERS")
        self.assertIsNone(profile["top_driver_id"])

    def test_source_blocking_short_circuits_to_blocked(self):
        profile = AttributionConfidenceEngine.compute_profile(
            ranked_drivers=[make_driver()], is_material=True, source_status="CONFLICTING_EVIDENCE",
            source_blocking=True,
        )
        self.assertEqual(profile["attribution_status"], "BLOCKED")
        self.assertEqual(profile["drivers"], [])

    def test_unexplained_row_is_one_minus_top_ac(self):
        profile = AttributionConfidenceEngine.compute_profile(
            ranked_drivers=[make_driver()], is_material=True, source_status="HIGH",
            causal_verification={"driver_id": "marketing_spend", "verdict": "SUPPORTED_CONDITIONAL"},
        )
        top_ac = profile["drivers"][0]["attribution_confidence"]
        self.assertAlmostEqual(profile["unexplained"]["attribution_confidence"], round(1 - top_ac, 4))

    def test_sparse_history_driver_is_not_scored(self):
        sparse = make_driver(sample_size=3)
        profile = AttributionConfidenceEngine.compute_profile(
            ranked_drivers=[sparse], is_material=True, source_status="HIGH",
        )
        self.assertEqual(profile["drivers"][0]["status"], "INSUFFICIENT_HISTORY")
        self.assertIsNone(profile["drivers"][0]["attribution_confidence"])


if __name__ == "__main__":
    unittest.main()
