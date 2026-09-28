"""Ridge uncertainty supports bounded action projections without invented ranges."""

import unittest

import numpy as np
import pandas as pd

from kpi_engine.action import ActionRecommendationEngine
from kpi_engine.attribution import AttributionEngine


class RidgeImpactRangeTests(unittest.TestCase):
    def test_collinear_ridge_fit_has_reproducible_interval(self):
        x = np.linspace(-2.0, 2.0, 56)
        design = pd.DataFrame({"driver_a": x, "driver_b": x * 1.001})
        outcome = pd.Series(2.0 * x + 0.1 * np.sin(np.arange(56)))
        first = AttributionEngine._fit_joint(outcome, design)
        second = AttributionEngine._fit_joint(outcome, design)
        self.assertEqual(first["method"], "RIDGE")
        self.assertEqual(first["beta_ci_std"], second["beta_ci_std"])
        low, high = first["beta_ci_std"]["driver_a"]
        self.assertLess(low, high)
        self.assertTrue(np.isfinite([low, high]).all())

    def test_action_projection_carries_interval(self):
        impact = ActionRecommendationEngine._impact_estimate(
            {"contract_snapshot": {"materiality": {"business_thresholds": {"unit": "count"}}}},
            {"contribution": -3.0, "contribution_interval": [-4.0, -2.0]},
        )
        self.assertEqual((impact["expected_impact_low"], impact["expected_impact_high"]), (14.0, 28.0))


if __name__ == "__main__":
    unittest.main()
