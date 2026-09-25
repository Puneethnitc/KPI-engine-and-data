import unittest

import pandas as pd
from fastapi import HTTPException

from backend.app import api_timeseries
from backend.config import SALES_CSV
from backend.service import get_timeseries


class BackendHardeningTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
