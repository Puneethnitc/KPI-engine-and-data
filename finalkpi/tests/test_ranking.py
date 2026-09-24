"""Correlational ranking must respect lag, grain, and source observations."""

import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from kpi_engine.contracts import KPIRegistry
from kpi_engine.rank import CorrelationalRanker


ROOT = Path(__file__).resolve().parents[1]


class RankingCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = KPIRegistry(str(ROOT / "kpi_engine" / "registry")).get("orders")
        cls.ranker = CorrelationalRanker()

    def test_daily_driver_lead_is_labeled_association(self):
        random = np.random.default_rng(7)
        driver = random.normal(100, 10, 100)
        kpi = np.r_[driver[:2], driver[:-2]]
        frame = pd.DataFrame({
            "date": pd.date_range("2023-01-01", periods=100),
            "orders": kpi,
            "traffic_online": driver,
        })
        candidates = self.ranker.rank_candidates(
            frame, "orders", ["traffic_drop"], contract=self.contract,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].optimal_lag_days, 2)
        self.assertGreater(candidates[0].max_correlation, 0.99)
        self.assertEqual(candidates[0].claim_type, "CORRELATIONAL")
        self.assertEqual(candidates[0].source_grain, "daily")

    def test_repeated_weekly_values_count_as_weeks_not_days(self):
        random = np.random.default_rng(3)
        weekly_values = random.normal(500, 60, 20)
        rows = []
        for week, spend in enumerate(weekly_values):
            start = pd.Timestamp("2023-01-02") + pd.Timedelta(weeks=week)
            for day in range(7):
                rows.append({
                    "date": start + pd.Timedelta(days=day),
                    "week_start": start,
                    "region": "North", "category": "Electronics",
                    "orders": spend / 7.0,
                    "marketing_spend": spend,
                })
        candidates = self.ranker.rank_candidates(
            pd.DataFrame(rows), "orders", ["ad_spend_drop"],
            contract=self.contract, window_days=200,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].source_grain, "weekly")
        self.assertEqual(candidates[0].sample_size, 19)
        self.assertEqual(candidates[0].optimal_lag_days, 0)
        self.assertGreater(candidates[0].max_correlation, 0.99)

    def test_weekly_conversion_rate_uses_ratio_of_sums_not_daily_rate_mean(self):
        contract = KPIRegistry(str(ROOT / "kpi_engine" / "registry")).get("conversion_rate")
        random = np.random.default_rng(42)
        rows = []
        for week, signal in enumerate(random.uniform(-0.015, 0.015, 25)):
            start = pd.Timestamp("2023-01-02") + pd.Timedelta(weeks=week)
            for day in range(7):
                traffic = 10000.0 if day == 0 else 10.0
                rate = 0.05 + signal if day == 0 else 0.05 - signal
                rows.append({
                    "date": start + pd.Timedelta(days=day), "week_start": start,
                    "region": "North", "category": "Electronics",
                    "orders": traffic * rate, "traffic_total": traffic,
                    "marketing_spend": 1000.0 * (0.05 + signal),
                })
        result = self.ranker.evaluate_candidates(
            pd.DataFrame(rows), "conversion_rate", ["ad_spend_drop"],
            contract=contract, window_days=200,
        )
        self.assertEqual(result.exclusions, [])
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].sample_size, 24)
        self.assertGreater(result.candidates[0].max_correlation, 0.99)

    def test_future_rows_cannot_change_historical_ranking(self):
        random = np.random.default_rng(11)
        driver = random.normal(100, 10, 100)
        frame = pd.DataFrame({
            "date": pd.date_range("2023-01-01", periods=100),
            "orders": driver * 0.5,
            "traffic_online": driver,
        })
        first = self.ranker.rank_candidates(
            frame, "orders", ["traffic_drop"], contract=self.contract,
            target_date="2023-04-10",
        )
        future = pd.DataFrame({
            "date": pd.date_range("2023-04-11", periods=10),
            "orders": [10000.0] * 10,
            "traffic_online": [1.0] * 10,
        })
        replay = self.ranker.rank_candidates(
            pd.concat([frame, future]), "orders", ["traffic_drop"],
            contract=self.contract, target_date="2023-04-10",
        )
        self.assertEqual(first, replay)

    def test_partial_segment_coverage_cannot_make_a_weekly_candidate(self):
        rows = []
        for week in range(20):
            start = pd.Timestamp("2023-01-02") + pd.Timedelta(weeks=week)
            for day in range(7):
                for region in ("North", "South"):
                    rows.append({
                        "date": start + pd.Timedelta(days=day),
                        "week_start": start if region == "North" else pd.NaT,
                        "region": region, "category": "Electronics",
                        "orders": float(week + 1),
                        "marketing_spend": float(week + 1) if region == "North" else np.nan,
                    })
        evaluation = self.ranker.evaluate_candidates(
            pd.DataFrame(rows), "orders", ["ad_spend_drop"],
            contract=self.contract, window_days=200,
        )
        self.assertEqual(evaluation.candidates, [])
        self.assertEqual(evaluation.exclusions[0].reason_code, "INCOMPLETE_WEEKLY_COVERAGE")

    def test_missing_flat_and_short_drivers_have_distinct_reasons(self):
        dates = pd.date_range("2023-01-01", periods=40)
        frame = pd.DataFrame({
            "date": dates,
            "orders": [100 + (i % 5) for i in range(40)],
            "traffic_online": [5.0] * 40,
        })
        evaluation = self.ranker.evaluate_candidates(
            frame, "orders", ["checkout_latency_spike", "traffic_drop"],
            contract=self.contract,
        )
        self.assertEqual(evaluation.candidates, [])
        self.assertEqual(
            {item.driver_id: item.reason_code for item in evaluation.exclusions},
            {"checkout_latency_spike": "MISSING_COLUMN", "traffic_drop": "NO_VARIATION"},
        )
        short = self.ranker.evaluate_candidates(
            frame.iloc[:10].assign(traffic_online=range(10)),
            "orders", ["traffic_drop"], contract=self.contract,
        )
        self.assertEqual(short.exclusions[0].reason_code, "INSUFFICIENT_PAIRS")


if __name__ == "__main__":
    unittest.main()
