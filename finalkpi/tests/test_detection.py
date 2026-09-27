"""Synthetic detection cases; these are not the missing planted-event labels."""

import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
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
        # Stage 2 (F-D1): the detector now uses up to 90 days of history (not
        # a hard-capped 30) so there is enough same-weekday depth; with 60
        # quiet days supplied, baseline_count is all 60, not an artificial 30.
        self.assertEqual(result.baseline_count, 60)
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

    def test_weekday_aware_robust_now_confirms_the_seasonal_signal(self):
        # Stage 2 (F-D1): before the primary detector was weekday-aware, its
        # dispersion mixed the +30 weekly step into ordinary noise, so this
        # exact anomaly used to clear only the seasonal (MSTL) detector's
        # tighter bar -- SEASONAL_ONLY, review-only, never an alert. Now that
        # the primary detector also compares each day only against its own
        # weekday's history, the same anomaly is no longer hidden inside
        # weekday noise: both detectors agree, exactly the outcome the plan
        # calls for ("'BOTH' should become common for genuine events"). The
        # still-review-only SEASONAL_ONLY path itself remains covered by
        # test_pipeline_regressions.py::test_seasonal_only_signal_does_not_start_diagnosis
        # against the real dataset.
        values = [100 + (30 if i % 7 in (5, 6) else 0) + (i % 3 - 1)
                  for i in range(101)]
        values[-1] += 15
        result = self.assess(values)
        self.assertEqual(result.detector_agreement, "BOTH")
        self.assertTrue(result.robust_is_material)
        self.assertTrue(result.seasonal_is_material)
        self.assertEqual(result.seasonal_status, "OK")
        self.assertEqual(result.seasonal_calibration_count, 21)
        self.assertTrue(result.is_material)

    def test_walk_forward_seasonal_baseline_stays_quiet(self):
        values = [100 + (30 if i % 7 in (5, 6) else 0) + (i % 3 - 1)
                  for i in range(120)]
        result = self.assess(values)
        self.assertEqual(result.seasonal_status, "OK")
        self.assertFalse(result.seasonal_is_material)

    def test_seasonal_branch_abstains_on_history_gap(self):
        # A little noise on top of the weekly cycle (Stage 2, F-D1): once the
        # primary detector's dispersion is computed from weekday-adjusted
        # residuals, a perfectly noiseless periodic series has zero residual
        # variance (UNSCORABLE_BASELINE), which would skip the seasonal branch
        # entirely before it ever reaches the history-gap check this test
        # exercises.
        values = [100 + (i % 7) + (i % 3 - 1) for i in range(120)]
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

    def test_ordinary_saturday_is_not_material_but_a_real_saturday_drop_is(self):
        # Stage 2 (F-D1): the whole point of comparing a day only to the same
        # weekday's history. An ordinary Saturday sits inside the normal
        # Saturday-to-Saturday spread; a -40% Saturday does not.
        contract = replace(
            self.contract,
            materiality=MaterialityThresholds(z_threshold=2.5, abs_threshold=10.0, rel_threshold=0.10),
        )
        rng = np.random.default_rng(11)
        n = 90  # 2023-01-02 is a Monday; 90 days later lands on a Saturday.
        values = [200.0 + (60.0 if (i % 7) in (5, 6) else 0.0) + rng.normal(0, 3) for i in range(n)]

        def assess(series_values):
            dates = pd.date_range("2023-01-02", periods=len(series_values), freq="D")
            self.assertEqual(dates[-1].dayofweek, 5, "test fixture must target a Saturday")
            frame = pd.DataFrame({"date": dates, "orders": series_values})
            return self.detector.evaluate_movement(
                frame, contract, dates[-1].date().isoformat(), metric_col="orders",
            )

        ordinary = assess(values)
        self.assertFalse(ordinary.is_material)

        dropped = list(values)
        dropped[-1] *= 0.6  # -40%
        result = assess(dropped)
        self.assertTrue(result.is_material)
        self.assertLess(result.rel_delta, -0.10)

    def test_rel_threshold_gates_a_proportionally_small_change(self):
        # Stage 2 (F-D3): a large baseline where the absolute floor alone
        # would flag a proportionally tiny change must also clear the
        # relative gate.
        contract = replace(
            self.contract,
            materiality=MaterialityThresholds(z_threshold=0.01, abs_threshold=10.0, rel_threshold=0.10),
        )
        rng = np.random.default_rng(5)
        values = [10000.0 + rng.normal(0, 5) for _ in range(90)]
        values[-1] -= 50.0  # -0.5%: clears the old abs floor (10), not 10% relative
        dates = pd.date_range("2023-01-02", periods=len(values), freq="D")
        frame = pd.DataFrame({"date": dates, "orders": values})
        small_relative = self.detector.evaluate_movement(
            frame, contract, dates[-1].date().isoformat(), metric_col="orders",
        )
        self.assertTrue(small_relative.is_business_material is False)
        self.assertFalse(small_relative.is_material)

        values[-1] = values[-2] * 0.85  # -15%: clears both gates
        frame = pd.DataFrame({"date": dates, "orders": values})
        large_relative = self.detector.evaluate_movement(
            frame, contract, dates[-1].date().isoformat(), metric_col="orders",
        )
        self.assertTrue(large_relative.is_business_material)


if __name__ == "__main__":
    unittest.main()
