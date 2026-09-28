"""GET /api/movements: the Stage 2 (F-D4) fast, access-respecting movement scan."""

import unittest

from fastapi import HTTPException

from backend.app import api_movements
from backend.service import get_movements


class MovementsServiceTests(unittest.TestCase):
    def test_regional_persona_only_sees_its_own_region(self):
        payload = get_movements("2024-05-15", "demo-regional-north", ["net_sales_revenue"])
        self.assertEqual(payload["persona"], "regional_manager_north")
        self.assertTrue(payload["movements"])
        self.assertTrue(all(item["region"] == "North" for item in payload["movements"]))

    def test_cfo_gets_the_company_wide_rollup_and_it_sorts_first_when_material(self):
        payload = get_movements("2024-05-15", "demo-cfo", ["net_sales_revenue"])
        movements = payload["movements"]
        self.assertTrue(any(item["region"] is None for item in movements))
        priorities = [item["priority"] for item in movements]
        self.assertEqual(priorities, sorted(priorities, reverse=True))

    def test_unknown_kpi_is_rejected(self):
        with self.assertRaises(ValueError):
            get_movements("2024-05-15", "demo-cfo", ["not_a_real_kpi"])

    def test_defaults_to_every_registered_kpi(self):
        payload = get_movements("2024-05-15", "demo-cfo", None)
        self.assertTrue({item["kpi_id"] for item in payload["movements"]} >= {"net_sales_revenue"})


class MovementsRouteTests(unittest.TestCase):
    def test_missing_identity_is_401(self):
        with self.assertRaises(HTTPException) as context:
            api_movements(date="2024-05-15", user_id=None)
        self.assertEqual(context.exception.status_code, 401)

    def test_kpis_query_param_is_comma_split(self):
        result = api_movements(date="2024-05-15", user_id="demo-cfo", kpis="net_sales_revenue, orders")
        self.assertTrue({item["kpi_id"] for item in result["movements"]} <= {"net_sales_revenue", "orders"})

    def test_unknown_kpi_is_400(self):
        with self.assertRaises(HTTPException) as context:
            api_movements(date="2024-05-15", user_id="demo-cfo", kpis="not_a_real_kpi")
        self.assertEqual(context.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
