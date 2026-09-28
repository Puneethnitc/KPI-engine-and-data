"""GET /api/movements: the Stage 2 (F-D4) fast, access-respecting movement scan."""

import unittest

from fastapi import HTTPException

from backend.app import api_movements
from backend.service import diagnose_scope, get_movements, movement_priority


class MovementsServiceTests(unittest.TestCase):
    def test_company_wide_movement_target_runs_without_a_dimension_filter(self):
        response = diagnose_scope(
            kpis=["orders"], target_date="2024-05-15", persona="CFO",
            scope={"region": None, "category": None},
        )
        result = response["results"]["orders"]
        self.assertEqual(result["segment"], {})
        self.assertIsNotNone(result["movement_assessment"]["actual_value"])

    def test_orders_outrank_a_smaller_revenue_movement_after_baseline_conversion(self):
        baseline = {"net_sales_revenue": 10000.0, "orders": 100.0}
        orders = movement_priority(
            {"delta": 20.0, "robust_score": 5.0},
            {"identity": {"kpi_id": "orders"}, "materiality": {"impact_to_revenue": {"method": "aov"}, "statistical_thresholds": {"z_threshold": 2.5}, "kpi_weight": 0.8}},
            baseline,
        )
        revenue = movement_priority(
            {"delta": 500.0, "robust_score": 5.0},
            {"identity": {"kpi_id": "net_sales_revenue"}, "materiality": {"impact_to_revenue": {"method": "identity"}, "statistical_thresholds": {"z_threshold": 2.5}, "kpi_weight": 1.0}},
            baseline,
        )
        self.assertGreater(orders, revenue)

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
        self.assertTrue(any(item["kpi_id"] != "net_sales_revenue" for item in payload["movements"][:5]))


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
