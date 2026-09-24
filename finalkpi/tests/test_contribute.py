"""Exact coalition allocation and explicit non-causal boundaries."""

import unittest

from kpi_engine.contribute import ContributionScenario, ShapleyContributor


class ContributionTests(unittest.TestCase):
    def test_interaction_split_and_residual(self):
        scenario = ContributionScenario(
            "orders", "count", ("traffic_drop", "stockout"),
            {(): 100, ("traffic_drop",): 90, ("stockout",): 80,
             ("stockout", "traffic_drop"): 60},
            observed_movement=-50,
        )
        result = ShapleyContributor.quantify(scenario)
        effects = {item.driver_id: item.modeled_effect for item in result.contributions}
        self.assertEqual(effects, {"traffic_drop": -15, "stockout": -25})
        self.assertEqual(result.modeled_movement, -40)
        self.assertEqual(result.unexplained_residual, -10)
        self.assertEqual(result.claim_type, "MODEL_BASED_SCENARIO")

    def test_missing_or_invalid_coalitions_abstain(self):
        base = ContributionScenario("orders", "count", ("a", "b"),
                                    {(): 0, ("a",): 1, ("b",): 2}, 3)
        with self.assertRaisesRegex(ValueError, "every coalition"):
            ShapleyContributor.quantify(base)
        with self.assertRaisesRegex(ValueError, "unique finite"):
            ShapleyContributor.quantify(ContributionScenario(
                "orders", "count", ("a", "b"),
                {(): 0, ("a",): 1, ("b",): 2, ("a", "b"): float("nan")}, 3,
            ))

    def test_zero_observed_has_no_percentage(self):
        result = ShapleyContributor.quantify(ContributionScenario(
            "orders", "count", ("a", "b"),
            {(): 0, ("a",): 1, ("b",): 2, ("a", "b"): 3}, 0,
        ))
        self.assertTrue(all(item.share_of_observed_pct is None
                            for item in result.contributions))


if __name__ == "__main__":
    unittest.main()
