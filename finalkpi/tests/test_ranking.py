"""Correlational ranking must respect lag, grain, and source observations."""

import unittest
from copy import deepcopy
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
        analysis = self.ranker.evaluate_candidates(
            frame, "orders", ["traffic_drop"], contract=self.contract,
        ).driver_analysis
        ranked = analysis["ranked_drivers"][0]
        self.assertEqual(ranked["temporal_order"], "BEFORE")
        self.assertTrue(ranked["temporal_order_supported"])
        self.assertEqual(ranked["adjusted_significance"], None)
        self.assertIsNone(analysis["correction_method"])
        self.assertGreater(analysis["hypotheses_tested"], 1)
        self.assertEqual(ranked["alignment_method"], "daily date aggregation on the scoped as-of frame")

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
        analysis = self.ranker.evaluate_candidates(
            pd.DataFrame(rows), "orders", ["ad_spend_drop"],
            contract=self.contract, window_days=200,
        ).driver_analysis
        weekly_driver = analysis["ranked_drivers"][0]
        self.assertEqual(weekly_driver["sample_size"], 19)
        self.assertEqual(weekly_driver["temporal_order"], "COINCIDENT")
        self.assertFalse(weekly_driver["temporal_order_supported"])
        self.assertIn("week", weekly_driver["alignment_method"].lower())

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
            {"checkout_latency_spike": "SOURCE_UNAVAILABLE", "traffic_drop": "CONSTANT_SERIES"},
        )
        short = self.ranker.evaluate_candidates(
            frame.iloc[:10].assign(traffic_online=range(10)),
            "orders", ["traffic_drop"], contract=self.contract,
        )
        self.assertEqual(short.exclusions[0].reason_code, "INSUFFICIENT_HISTORY")

    def test_driver_analysis_represents_each_governed_candidate_once(self):
        dates = pd.date_range("2023-01-01", periods=60)
        frame = pd.DataFrame({
            "date": dates,
            "orders": np.arange(60, dtype=float),
            "traffic_online": np.arange(60, dtype=float),
            "checkout_latency_ms": np.ones(60),
        })
        evaluated_ids = ["traffic_drop", "checkout_latency_spike"]
        evaluation = self.ranker.evaluate_candidates(
            frame, "orders", evaluated_ids, contract=self.contract,
        )
        analysis = evaluation.driver_analysis
        represented = [item["driver_id"] for item in analysis["ranked_drivers"]]
        represented.extend(item["driver_id"] for item in analysis["excluded_drivers"])
        self.assertCountEqual(represented, evaluated_ids)
        self.assertEqual(len(represented), len(set(represented)))
        self.assertEqual(analysis["candidate_count"], 2)
        self.assertEqual(analysis["excluded_count"], len(analysis["excluded_drivers"]))

    def test_coverage_reports_usable_and_missing_pairs(self):
        random = np.random.default_rng(19)
        driver = random.normal(size=80)
        kpi = driver.copy()
        driver[[5, 10, 20, 30, 40, 50, 60, 70]] = np.nan
        frame = pd.DataFrame({
            "date": pd.date_range("2023-01-01", periods=80),
            "orders": kpi,
            "traffic_online": driver,
        })
        result = self.ranker.evaluate_candidates(
            frame, "orders", ["traffic_drop"], contract=self.contract,
        )
        self.assertEqual(len(result.candidates), 1)
        item = result.driver_analysis["ranked_drivers"][0]
        self.assertEqual(item["sample_size"], result.candidates[0].sample_size)
        self.assertGreater(item["missing_observations"], 0)
        self.assertAlmostEqual(item["coverage_ratio"], item["sample_size"] / 79, places=5)
        self.assertEqual(item["adjusted_significance"], None)
        self.assertIsNone(result.driver_analysis["correction_method"])
        self.assertIn("No multiple-testing correction is applied", " ".join(result.driver_analysis["limitations"]))

    def test_sparse_history_returns_abstention_without_ranked_drivers(self):
        frame = pd.DataFrame({
            "date": pd.date_range("2023-01-01", periods=10),
            "orders": np.arange(10, dtype=float),
            "traffic_online": np.arange(10, dtype=float),
        })
        result = self.ranker.evaluate_candidates(
            frame, "orders", ["traffic_drop"], contract=self.contract,
        )
        self.assertEqual(result.driver_analysis["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result.driver_analysis["ranked_drivers"], [])
        self.assertEqual(result.driver_analysis["excluded_drivers"][0]["reason_code"], "INSUFFICIENT_HISTORY")

    def test_not_applicable_requires_no_contract_candidates(self):
        dates = pd.date_range("2023-01-01", periods=30)
        frame = pd.DataFrame({"date": dates, "orders": np.arange(30, dtype=float), "traffic_online": np.arange(30, dtype=float)})
        declared = self.ranker.evaluate_candidates(frame, "orders", [], contract=self.contract)
        self.assertEqual(declared.driver_analysis["candidate_count"], len(self.contract.candidate_drivers))
        self.assertNotEqual(declared.driver_analysis["status"], "NOT_APPLICABLE")

        no_candidates_contract = deepcopy(self.contract)
        no_candidates_contract.candidate_drivers = []
        not_applicable = self.ranker.evaluate_candidates(frame, "orders", [], contract=no_candidates_contract)
        self.assertEqual(not_applicable.driver_analysis["status"], "NOT_APPLICABLE")
        self.assertEqual(not_applicable.driver_analysis["candidate_count"], 0)

    def test_low_coverage_is_excluded(self):
        random = np.random.default_rng(31)
        driver = random.normal(size=80)
        driver[:40] = np.nan
        frame = pd.DataFrame({
            "date": pd.date_range("2023-01-01", periods=80),
            "orders": random.normal(size=80),
            "traffic_online": driver,
        })
        result = self.ranker.evaluate_candidates(frame, "orders", ["traffic_drop"], contract=self.contract)
        self.assertEqual(result.driver_analysis["ranked_drivers"], [])
        excluded = result.driver_analysis["excluded_drivers"][0]
        self.assertEqual(excluded["reason_code"], "LOW_COVERAGE")
        self.assertIn("minimum_coverage", excluded["failed_checks"])
        self.assertGreater(excluded["missing_observations"], 0)
        self.assertLess(excluded["coverage_ratio"], 0.6)
        self.assertGreater(excluded["lag_candidates_tested"], 1)
        self.assertEqual(len(excluded["tested_lags"]), excluded["lag_candidates_tested"])

    def test_monthly_driver_values_are_deduplicated_before_aggregation(self):
        monthly_contract = deepcopy(self.contract)
        monthly_contract.candidate_drivers = [{
            "id": "monthly_context", "display_name": "Monthly context signal",
            "column": "monthly_signal", "source": "monthly_context",
            "grain": "monthly", "aggregation": "sum", "monthly_min_pairs": "6",
            "max_lag": "0", "allowed_lags": "0", "threshold": "0.3",
            "controllability": "contextual", "unit": "index",
        }]
        dates = pd.date_range("2023-01-01", "2024-08-31", freq="D")
        rng = np.random.default_rng(43)
        month_values = {period: float(value) for period, value in zip(
            pd.period_range("2023-01", "2024-08", freq="M"), rng.normal(size=20)
        )}
        monthly_signal = pd.Series([month_values[day.to_period("M")] for day in dates])
        month_order_values = pd.Series([month_values[day.to_period("M")] * 30 for day in dates])
        frame = pd.DataFrame({
            "date": dates,
            "orders": month_order_values / dates.to_series().dt.days_in_month.to_numpy(),
            "monthly_signal": monthly_signal,
        })
        result = self.ranker.evaluate_candidates(
            frame, "orders", ["monthly_context"], contract=monthly_contract,
            target_date="2024-08-31", window_days=700,
        )
        self.assertEqual(result.driver_analysis["ranked_count"], 1)
        candidate = result.driver_analysis["ranked_drivers"][0]
        self.assertEqual(candidate["source_grain"], "monthly")
        self.assertEqual(candidate["sample_size"], 19)
        self.assertIn("deduplicate by calendar month", candidate["alignment_method"])

    def test_recent_window_sign_reversal_is_sensitive(self):
        random = np.random.default_rng(57)
        driver_changes = random.normal(size=200)
        kpi_changes = driver_changes.copy()
        kpi_changes[160:] = -driver_changes[160:]
        driver = np.r_[0.0, np.cumsum(driver_changes)]
        kpi = np.r_[0.0, np.cumsum(kpi_changes)]
        contract = deepcopy(self.contract)
        contract.candidate_drivers = [dict(
            self.contract.candidate_drivers[-1], max_lag="0", allowed_lags="0",
            stability_window_fraction="0.3",
        )]
        frame = pd.DataFrame({
            "date": pd.date_range("2023-01-01", periods=201),
            "orders": kpi,
            "traffic_online": driver,
        })
        result = self.ranker.evaluate_candidates(
            frame, "orders", ["traffic_drop"], contract=contract,
            window_days=201,
        )
        self.assertEqual(result.driver_analysis["ranked_count"], 1)
        self.assertEqual(result.driver_analysis["ranked_drivers"][0]["stability_status"], "SENSITIVE")


if __name__ == "__main__":
    unittest.main()
