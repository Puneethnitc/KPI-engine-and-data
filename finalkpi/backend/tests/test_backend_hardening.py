import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd
from fastapi import HTTPException

from backend.app import DiagnosisRequest, api_diagnoses, api_timeseries
from backend.config import SALES_CSV
from backend.service import build_marketing_brief, get_timeseries
from backend import storage as backend_storage


class BackendHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._database_directory = TemporaryDirectory()
        cls._database_patch = patch.object(
            backend_storage,
            "DB_PATH",
            Path(cls._database_directory.name) / "kpi_backend.sqlite3",
        )
        cls._database_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls._database_patch.stop()
        cls._database_directory.cleanup()

    def test_all_supported_timeseries_are_non_empty(self):
        for kpi_id in ("net_sales_revenue", "orders", "units_sold", "traffic_total", "conversion_rate"):
            with self.subTest(kpi_id=kpi_id):
                payload = get_timeseries(kpi_id, "North", "Electronics")
                self.assertGreater(len(payload["points"]), 0)
                self.assertEqual(payload["points"][0]["observation_date"], "2023-01-01")

    def test_conversion_rate_is_ratio_of_sums(self):
        sales = pd.read_csv(SALES_CSV)
        scoped = sales[(sales.region == "North") & (sales.category == "Electronics")]
        daily_totals = scoped.groupby("date")[["orders", "traffic_total"]].sum()
        expected = daily_totals["orders"] / daily_totals["traffic_total"]
        payload = get_timeseries("conversion_rate", "North", "Electronics")
        actual = {point["observation_date"]: point["actual"] for point in payload["points"]}
        for day, value in expected.items():
            self.assertAlmostEqual(actual[day], value, places=10)

    def test_expected_baseline_excludes_current_observation(self):
        sales = pd.read_csv(SALES_CSV)
        scoped = sales[(sales.region == "North") & (sales.category == "Electronics")]
        daily = scoped.groupby("date").net_sales_revenue.sum().sort_index()
        payload = get_timeseries("net_sales_revenue", "North", "Electronics")
        point = payload["points"][60]
        target = point["observation_date"]
        prior = daily[daily.index < target].tail(60)
        self.assertEqual(point["baseline_count"], 60)
        self.assertAlmostEqual(point["expected"], prior.mean(), places=6)
        self.assertNotEqual(point["expected"], point["actual"])

    def test_unsupported_kpi_is_a_clear_client_error(self):
        with self.assertRaises(ValueError):
            get_timeseries("not_a_kpi", "North", "Electronics")

    def test_unknown_identity_is_unauthorized(self):
        with self.assertRaises(HTTPException) as context:
            api_timeseries("traffic_total", "North", "Electronics", "unknown-user")
        self.assertEqual(context.exception.status_code, 401)

    @staticmethod
    def _result(kpi_id, delta, material=True):
        return {kpi_id: {
            "movement_assessment": {"status": "OK", "actual_value": delta + 100, "expected_value": 100, "delta": delta, "is_material": material},
            "confidence": {"status": "NOT_ASSESSED", "reasons": ["No causal design supplied"]},
            "narrative": f"Observed {kpi_id} movement.",
            "decision_cards": [],
        }}

    def test_connected_funnel_declines_are_one_noncausal_story(self):
        results = {}
        results.update(self._result("traffic_total", -12))
        results.update(self._result("conversion_rate", -0.006))
        results.update(self._result("orders", -20))
        results.update(self._result("units_sold", -24))
        results.update(self._result("net_sales_revenue", -1500))
        brief = build_marketing_brief(results, {"region": "North", "category": "Electronics", "target_date": "2023-07-24"})
        self.assertEqual(brief["first_weak_stage"]["kpi_id"], "traffic_total")
        self.assertIn("traffic", brief["summary"].lower())
        self.assertIn("revenue", brief["summary"].lower())
        self.assertIn("not proof of cause", brief["summary"].lower())
        self.assertEqual(len(brief["funnel"]), 5)

    def test_traffic_growth_with_conversion_decline_is_not_more_traffic_advice(self):
        results = {}
        results.update(self._result("traffic_total", 12, False))
        results.update(self._result("conversion_rate", -0.006))
        results.update(self._result("orders", -8))
        results.update(self._result("units_sold", -9, False))
        results.update(self._result("net_sales_revenue", -600))
        brief = build_marketing_brief(results, {"region": "West", "category": "Apparel", "target_date": "2023-07-24"})
        self.assertEqual(brief["first_weak_stage"]["kpi_id"], "conversion_rate")
        self.assertIn("traffic increased while conversion rate declined", brief["summary"].lower())
        self.assertNotIn("caused by", brief["summary"].lower())

    def test_persona_briefing_changes_framing_not_numeric_facts(self):
        results = self._result("net_sales_revenue", -1250)
        marketing = build_marketing_brief(results, {"region": "South", "category": "Apparel", "target_date": "2023-07-24"}, "marketing_manager")
        cfo = build_marketing_brief(results, {"region": "South", "category": "Apparel", "target_date": "2023-07-24"}, "CFO")
        self.assertNotEqual(marketing["summary"], cfo["summary"])
        self.assertEqual(marketing["funnel"], cfo["funnel"])

    def test_diagnosis_api_returns_one_connected_five_stage_brief(self):
        response = api_diagnoses(DiagnosisRequest(
            kpis=["all"], target_date="2023-07-24", region="North",
            category="Electronics", persona="marketing_manager", user_id="demo-marketing",
        ))
        self.assertEqual(len(response["results"]), 5)
        brief = response["marketing_brief"]
        self.assertEqual(len(brief["funnel"]), 5)
        self.assertEqual(len(brief["ranked_insights"]), 5)
        self.assertIn("not proof of cause", brief["summary"].lower())

    def test_connected_positive_signals_are_grouped_without_generic_impact_copy(self):
        results = {}
        results.update(self._result("traffic_total", 50, True))
        results.update(self._result("units_sold", 20, True))
        results.update(self._result("net_sales_revenue", 1000, True))
        brief = build_marketing_brief(results, {"region": "North", "category": "Electronics", "target_date": "2023-07-24"})
        positive_stories = [s for s in brief["stories"] if s["id"] == "FUNNEL_GROWTH"]
        self.assertEqual(len(positive_stories), 1)
        story = positive_stories[0]
        self.assertEqual(set(story["affected_kpis"]), {"traffic_total", "units_sold", "net_sales_revenue"})
        self.assertIn("Observed revenue uplift (+1000.00 INR)", story["business_impact"])
        self.assertIn("must not be summed", story["business_impact"])
        self.assertIn("does not establish causal", story["causal_boundary"])
        self.assertNotIn("Directional opportunity; no incremental impact estimated.", str(brief))

    def test_single_positive_signal_has_kpi_specific_impact_and_is_not_automatically_an_opportunity(self):
        brief = build_marketing_brief(
            self._result("traffic_total", 50, False),
            {"region": "North", "category": "Electronics", "target_date": "2023-07-24"},
        )
        story = next(s for s in brief["stories"] if s["id"] == "POSITIVE_SIGNAL_traffic_total")
        self.assertIn("Traffic increased by 50.00 visits", story["business_impact"])
        self.assertIn("incrementality were not assessed", story["business_impact"])
        self.assertIn("does not establish marketing attribution", story["causal_boundary"])
        self.assertFalse(brief["positive_opportunity"])


if __name__ == "__main__":
    unittest.main()
