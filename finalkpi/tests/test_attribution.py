"""Explained-movement attribution: a driver that did not move cannot explain
a movement, contributions must sum to (approximately) the observed delta, and
the linear model's Shapley allocation must equal its linear contribution."""

import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from kpi_engine.attribution import AttributionEngine
from kpi_engine.contracts import KPIRegistry

ROOT = Path(__file__).resolve().parents[1]


def make_contract(driver_specs):
    base = KPIRegistry(str(ROOT / "kpi_engine" / "registry")).get("orders")
    return replace(
        base, kpi_id="synthetic_kpi", value_column="synthetic_kpi", aggregation="sum",
        min_history_periods=60, seasonal_period=7, candidate_drivers=driver_specs,
        decomposition={}, reconciliation=None,
    )


def assessment_for(kpi_series: pd.Series, target: pd.Timestamp) -> SimpleNamespace:
    from kpi_engine.contracts.metrics import same_weekday_expected
    history = kpi_series[kpi_series.index < target]
    expected, _ = same_weekday_expected(history, target)
    actual = float(kpi_series.loc[target])
    return SimpleNamespace(expected_value=expected, delta=actual - expected, actual_value=actual, is_material=True)


class AttributionEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = AttributionEngine()

    def _driver_spec(self, driver_id, direction="positive"):
        return {
            "id": driver_id, "display_name": driver_id, "unit": "unit",
            "controllability": "controllable", "column": driver_id, "source": "sales_daily",
            "grain": "daily", "aggregation": "mean", "allowed_lags": [0],
            "min_pairs": 14, "minimum_coverage": 0.5, "expected_direction": direction,
        }

    def _synthetic_frame(self, n=220, seed=11, event_a=20.0, event_b=0.0, noise_scale=1.0):
        random = np.random.default_rng(seed)
        dates = pd.date_range("2023-01-01", periods=n, freq="D")
        a = 100 + random.normal(0, 3, n)
        b = 50 + random.normal(0, 3, n)
        a[-1] += event_a
        b[-1] += event_b
        noise = random.normal(0, noise_scale, n)
        kpi = 500 + 2 * (a - 100) - 3 * (b - 50) + noise
        frame = pd.DataFrame({"date": dates, "synthetic_kpi": kpi, "A": a, "B": b})
        return frame, dates[-1]

    def test_synthetic_known_beta_ranks_the_mover_first(self):
        frame, target = self._synthetic_frame()
        contract = make_contract([
            self._driver_spec("A", "positive"),
            self._driver_spec("B", "negative"),
        ])
        kpi_series = frame.set_index("date")["synthetic_kpi"]
        assessment = assessment_for(kpi_series, target)
        result = self.engine.attribute(
            frame, "synthetic_kpi", ["A", "B"], assessment, target.date().isoformat(),
            driver_columns={"A": "A", "B": "B"}, contract=contract,
        )
        self.assertEqual(len(result.ranked_drivers), 1)
        self.assertEqual(result.ranked_drivers[0].driver_id, "A")
        self.assertFalse(result.ranked_drivers[0].offsetting)
        self.assertTrue(result.ranked_drivers[0].moved)
        excluded = {item.driver_id: item.reason_code for item in result.excluded_drivers}
        self.assertEqual(excluded.get("B"), "DID_NOT_MOVE")
        total_contribution = sum(item.contribution for item in result.ranked_drivers)
        self.assertAlmostEqual(total_contribution, assessment.delta, delta=max(3.0, 0.25 * abs(assessment.delta)))
        self.assertLess(abs(result.driver_analysis["residual"]), max(6.0, 0.5 * abs(assessment.delta)))

    def test_collinear_drivers_warn_without_double_counting(self):
        frame, target = self._synthetic_frame()
        random = np.random.default_rng(3)
        frame["A2"] = frame["A"] + random.normal(0, 0.05, len(frame))
        contract = make_contract([
            self._driver_spec("A", "positive"),
            self._driver_spec("A2", "positive"),
            self._driver_spec("B", "negative"),
        ])
        kpi_series = frame.set_index("date")["synthetic_kpi"]
        assessment = assessment_for(kpi_series, target)
        result = self.engine.attribute(
            frame, "synthetic_kpi", ["A", "A2", "B"], assessment, target.date().isoformat(),
            driver_columns={"A": "A", "A2": "A2", "B": "B"}, contract=contract,
        )
        self.assertTrue(result.driver_analysis["collinearity_warning"])
        moved_ids = {item.driver_id for item in result.ranked_drivers if item.moved}
        self.assertTrue(moved_ids & {"A", "A2"})
        total_contribution = sum(item.contribution for item in result.ranked_drivers)
        # A and A2 together must still explain roughly one A-sized effect, not two.
        self.assertLess(abs(total_contribution), 3 * abs(assessment.delta))
        self.assertAlmostEqual(total_contribution, assessment.delta, delta=max(4.0, 0.3 * abs(assessment.delta)))

    def test_future_rows_after_the_cutoff_do_not_change_the_result(self):
        frame, target = self._synthetic_frame()
        contract = make_contract([
            self._driver_spec("A", "positive"),
            self._driver_spec("B", "negative"),
        ])
        kpi_series = frame.set_index("date")["synthetic_kpi"]
        assessment = assessment_for(kpi_series, target)
        baseline = self.engine.attribute(
            frame, "synthetic_kpi", ["A", "B"], assessment, target.date().isoformat(),
            driver_columns={"A": "A", "B": "B"}, contract=contract,
        )
        random = np.random.default_rng(99)
        future_dates = pd.date_range(target + pd.Timedelta(days=1), periods=10, freq="D")
        future = pd.DataFrame({
            "date": future_dates,
            "synthetic_kpi": 500 + random.normal(0, 5, 10),
            "A": 100 + random.normal(0, 3, 10),
            "B": 50 + random.normal(0, 3, 10),
        })
        extended = pd.concat([frame, future], ignore_index=True)
        extended_result = self.engine.attribute(
            extended, "synthetic_kpi", ["A", "B"], assessment, target.date().isoformat(),
            driver_columns={"A": "A", "B": "B"}, contract=contract,
        )
        self.assertEqual(
            [item["driver_id"] for item in baseline.driver_analysis["ranked_drivers"]],
            [item["driver_id"] for item in extended_result.driver_analysis["ranked_drivers"]],
        )
        for original, extended_item in zip(
            baseline.driver_analysis["ranked_drivers"], extended_result.driver_analysis["ranked_drivers"],
        ):
            self.assertAlmostEqual(original["contribution"], extended_item["contribution"], places=6)
            self.assertEqual(original["lag_days"], extended_item["lag_days"])

    def test_linear_model_shapley_equals_contribution(self):
        frame, target = self._synthetic_frame(event_a=20.0, event_b=-15.0)
        contract = make_contract([
            self._driver_spec("A", "positive"),
            self._driver_spec("B", "negative"),
        ])
        kpi_series = frame.set_index("date")["synthetic_kpi"]
        assessment = assessment_for(kpi_series, target)
        result = self.engine.attribute(
            frame, "synthetic_kpi", ["A", "B"], assessment, target.date().isoformat(),
            driver_columns={"A": "A", "B": "B"}, contract=contract,
        )
        check = result.driver_analysis["shapley_equivalence_check"]
        self.assertIsNotNone(check)
        self.assertTrue(check["passed"], check)
        self.assertLess(check["max_abs_diff"], 1e-6 * max(1.0, abs(assessment.delta)))
