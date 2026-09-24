"""Causal checks require declared exposure and falsification, not correlation."""

import unittest
from dataclasses import replace
from pathlib import Path

import pandas as pd

from kpi_engine.contracts import KPIRegistry
from kpi_engine.verification import CausalVerifier, VerificationDesign


ROOT = Path(__file__).resolve().parents[1]


class VerificationCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = KPIRegistry(str(ROOT / "kpi_engine" / "registry")).get("orders")
        cls.verifier = CausalVerifier()
        cls.design = VerificationDesign(
            driver_id="traffic_drop",
            treated_slice={"region": "North", "category": "Electronics"},
            control_slice={"region": "South", "category": "Electronics"},
            pre_start="2023-03-01", treatment_start="2023-04-01", post_end="2023-04-21",
            quiet_windows=(("2023-01-01", "2023-01-14"),
                           ("2023-02-01", "2023-02-14")),
            expected_driver_direction=-1, expected_outcome_direction=-1,
        )

    @staticmethod
    def frame(pretrend=False, placebo=False, exposed=True, early_drop=False):
        rows = []
        for day in pd.date_range("2023-01-01", "2023-04-21"):
            event = day >= pd.Timestamp("2023-04-01")
            pre_slope = (day - pd.Timestamp("2023-03-01")).days if pretrend else 0
            placebo_drop = -20 if placebo and pd.Timestamp("2023-01-08") <= day <= pd.Timestamp("2023-01-14") else 0
            for region in ("North", "South"):
                treated = region == "North"
                rows.append({
                    "date": day, "region": region, "category": "Electronics",
                    "orders": 100 + (10 if treated else 0) + (
                    -20 if treated and (event or (early_drop and day >= pd.Timestamp("2023-03-24"))) else 0
                    ) + (pre_slope if treated and day < pd.Timestamp("2023-04-01") else 0) + (
                        placebo_drop if treated else 0
                    ),
                    "traffic_online": 1000 - (500 if treated and event and exposed else 0),
                })
        return pd.DataFrame(rows)

    def test_support_is_conditional_and_driver_exposure_is_observed(self):
        result = self.verifier.verify(self.frame(), self.contract, self.design)
        self.assertEqual(result.verdict, "SUPPORTED_CONDITIONAL")
        self.assertAlmostEqual(result.did_effect, -20.0)
        self.assertAlmostEqual(result.driver_exposure_effect, -500.0)
        self.assertEqual(len(result.placebo_effects), 2)
        self.assertIn("not proven", result.reason.lower())

    def test_missing_control_day_abstains(self):
        frame = self.frame()
        frame = frame[~((frame["date"] == pd.Timestamp("2023-03-10")) &
                        (frame["region"] == "South"))]
        result = self.verifier.verify(frame, self.contract, self.design)
        self.assertEqual((result.verdict, result.reason_code),
                         ("UNTESTABLE", "INCOMPLETE_OUTCOME"))

    def test_no_driver_exposure_cannot_verify_named_driver(self):
        result = self.verifier.verify(self.frame(exposed=False), self.contract, self.design)
        self.assertEqual((result.verdict, result.reason_code),
                         ("INCONCLUSIVE", "NO_EXPOSURE_CONTRAST"))

    def test_pretrend_and_placebo_fail_closed(self):
        trend = self.verifier.verify(self.frame(pretrend=True), self.contract, self.design)
        self.assertEqual((trend.verdict, trend.reason_code),
                         ("UNTESTABLE", "PRETREND_VIOLATION"))
        placebo = self.verifier.verify(self.frame(placebo=True), self.contract, self.design)
        self.assertEqual((placebo.verdict, placebo.reason_code),
                         ("UNTESTABLE", "PLACEBO_FAILED"))

    def test_outcome_movement_before_driver_start_abstains(self):
        result = self.verifier.verify(
            self.frame(early_drop=True), self.contract, self.design
        )
        self.assertEqual((result.verdict, result.reason_code),
                         ("UNTESTABLE", "PRE_EVENT_MOVEMENT"))

    def test_missing_quiet_windows_abstains(self):
        result = self.verifier.verify(
            self.frame(), self.contract, replace(self.design, quiet_windows=())
        )
        self.assertEqual((result.verdict, result.reason_code),
                         ("UNTESTABLE", "INVALID_DESIGN"))

    def test_sensitivity_reports_all_predeclared_windows_not_best_only(self):
        alternate = replace(self.design, post_end="2023-04-14")
        stable = self.verifier.verify_sensitivity(
            self.frame(), self.contract, (self.design, alternate)
        )
        self.assertEqual(stable.status, "CONSISTENT_CONDITIONAL")
        self.assertEqual(stable.design_count, 2)
        frame = self.frame()
        frame.loc[(frame["date"] >= pd.Timestamp("2023-04-15")) &
                  (frame["region"] == "North"), "orders"] += 40
        sensitive = self.verifier.verify_sensitivity(
            frame, self.contract, (self.design, alternate)
        )
        self.assertEqual(sensitive.status, "SENSITIVE")
        self.assertEqual(len(sensitive.results), 2)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.verifier.verify_sensitivity(self.frame(), self.contract,
                                             (self.design, self.design))

    def test_weekly_exposure_uses_complete_weeks_and_refuses_midweek_start(self):
        rows = []
        for day in pd.date_range("2023-01-01", "2023-04-23"):
            week_start = day - pd.Timedelta(days=day.dayofweek)
            event = day >= pd.Timestamp("2023-04-03")
            for region in ("North", "South"):
                treated = region == "North"
                rows.append({
                    "date": day, "week_start": week_start,
                    "region": region, "category": "Electronics",
                    "orders": 100 + (10 if treated else 0) - (20 if treated and event else 0),
                    "marketing_spend": 1000 - (
                        900 if treated and week_start >= pd.Timestamp("2023-04-03") else 0
                    ),
                })
        weekly = replace(
            self.design, driver_id="ad_spend_drop", treatment_start="2023-04-03",
            post_end="2023-04-23",
        )
        result = self.verifier.verify(pd.DataFrame(rows), self.contract, weekly)
        self.assertEqual(result.verdict, "SUPPORTED_CONDITIONAL")
        self.assertEqual(result.driver_exposure_periods, 7)
        midweek = self.verifier.verify(
            pd.DataFrame(rows), self.contract,
            replace(weekly, treatment_start="2023-04-04"),
        )
        self.assertEqual((midweek.verdict, midweek.reason_code),
                         ("UNTESTABLE", "COARSE_TREATMENT_TIME"))


if __name__ == "__main__":
    unittest.main()
