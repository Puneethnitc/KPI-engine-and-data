"""Synthetic detection cases; these are not the missing planted-event labels."""

import unittest
from dataclasses import replace
from pathlib import Path

import pandas as pd

from kpi_engine.contracts import KPIRegistry, MaterialityThresholds
from kpi_engine.detection import AnomalyDetector


ROOT = Path(__file__).resolve().parents[1]


class DetectionCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = KPIRegistry(str(ROOT / "kpi_engine" / "registry")).get("orders")
        cls.contract = replace(
            base, min_history_periods=30, seasonal_period=7,
            materiality=MaterialityThresholds(z_threshold=2.5, abs_threshold=10.0),
        )
        cls.detector = AnomalyDetector()

    def assess(self, values: list[float], target_index: int | None = None):
        dates = pd.date_range("2023-01-01", periods=len(values), freq="D")
        frame = pd.DataFrame({"date": dates, "orders": values})
        target = dates[-1] if target_index is None else dates[target_index]
        return self.detector.evaluate_movement(
            frame, self.contract, target.date().isoformat(), metric_col="orders"
        )

    @staticmethod
    def quiet_values(count: int = 61) -> list[float]:
        return [100.0 + (i % 3 - 1) + (10.0 if i % 7 in (5, 6) else 0.0)
                for i in range(count)]

    def test_quiet_weekly_pattern_is_not_material(self):
        result = self.assess(self.quiet_values())
        self.assertEqual(result.status, "OK")
        self.assertFalse(result.is_material)
        self.assertEqual(result.pattern, "NONE")

    def test_one_day_spike_is_point_anomaly(self):
        values = self.quiet_values()
        values[-1] = 160.0
        result = self.assess(values)
        self.assertTrue(result.is_material)
        self.assertEqual(result.pattern, "POINT")
        self.assertEqual(result.baseline_count, 30)
        self.assertIsNotNone(result.robust_score)

    def test_sustained_shift_is_labeled(self):
        values = self.quiet_values()
        values[-7:] = [78.0, 79.0, 80.0, 78.0, 79.0, 80.0, 79.0]
        result = self.assess(values)
        self.assertTrue(result.is_material)
        self.assertEqual(result.pattern, "SUSTAINED")
        self.assertIsNotNone(result.sustained_score)

    def test_sparse_and_missing_target_abstain(self):
        sparse = self.assess(self.quiet_values(12))
        self.assertEqual(sparse.status, "INSUFFICIENT_HISTORY")
        self.assertIsNone(sparse.delta)
        missing = self.detector.evaluate_movement(
            pd.DataFrame({"date": pd.date_range("2023-01-01", periods=40),
                          "orders": self.quiet_values(40)}),
            self.contract, "2023-03-01", metric_col="orders",
        )
        self.assertEqual(missing.status, "NO_DATA_FOR_DATE")
        self.assertIsNone(missing.actual_value)

    def test_flat_baseline_abstains_instead_of_inventing_a_score(self):
        result = self.assess([100.0] * 30 + [70.0])
        self.assertEqual(result.status, "UNSCORABLE_BASELINE")
        self.assertIsNone(result.robust_score)
        self.assertFalse(result.is_material)

    def test_seasonal_only_evidence_is_kept_distinct(self):
        values = [100 + (30 if i % 7 in (5, 6) else 0) + (i % 3 - 1)
                  for i in range(101)]
        values[-1] += 15
        result = self.assess(values)
        self.assertEqual(result.detector_agreement, "SEASONAL_ONLY")
        self.assertFalse(result.robust_is_material)
        self.assertTrue(result.seasonal_is_material)
        self.assertEqual(result.seasonal_status, "OK")
        self.assertEqual(result.seasonal_calibration_count, 21)
        self.assertFalse(result.is_material)

    def test_walk_forward_seasonal_baseline_stays_quiet(self):
        values = [100 + (30 if i % 7 in (5, 6) else 0) + (i % 3 - 1)
                  for i in range(120)]
        result = self.assess(values)
        self.assertEqual(result.seasonal_status, "OK")
        self.assertFalse(result.seasonal_is_material)

    def test_seasonal_branch_abstains_on_history_gap(self):
        values = [100 + (i % 7) for i in range(120)]
        dates = pd.date_range("2023-01-01", periods=len(values), freq="D")
        frame = pd.DataFrame({"date": dates, "orders": values})
        frame = frame[frame["date"] != dates[-40]]
        result = self.detector.evaluate_movement(
            frame, self.contract, dates[-1].date().isoformat(), metric_col="orders"
        )
        self.assertEqual(result.seasonal_status, "INSUFFICIENT_HISTORY")

    def test_seasonal_branch_does_not_use_future_data(self):
        values = [100 + (20 if i % 7 in (5, 6) else 0) + (i % 3 - 1)
                  for i in range(105)]
        first = self.assess(values)
        replay = self.assess(values + [1000] * 10, target_index=104)
        self.assertEqual(first.seasonal_score, replay.seasonal_score)
        self.assertEqual(first.seasonal_status, replay.seasonal_status)

    def test_future_observations_cannot_change_past_assessment(self):
        values = self.quiet_values()
        values[-1] = 160.0
        first = self.assess(values)
        dates = pd.date_range("2023-01-01", periods=len(values) + 5, freq="D")
        frame = pd.DataFrame({"date": dates, "orders": values + [10000.0] * 5})
        replay = self.detector.evaluate_movement(
            frame, self.contract, dates[len(values) - 1].date().isoformat(),
            metric_col="orders",
        )
        self.assertEqual(first, replay)


if __name__ == "__main__":
    unittest.main()
