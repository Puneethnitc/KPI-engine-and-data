import unittest

from backend.service import _resolve_scope, diagnose_scope


class AggregateScopeTests(unittest.TestCase):
    def test_all_drops_the_dimension_and_is_not_defaulted(self):
        scope = _resolve_scope(scope=None, target_date="2023-07-24", region="ALL", category="all", as_of=None)
        self.assertNotIn("region", scope)
        self.assertNotIn("category", scope)

    def test_all_for_one_dimension_keeps_the_other_and_nothing_passed_still_defaults(self):
        scope = _resolve_scope(scope=None, target_date="2023-07-24", region="ALL", category="Home", as_of=None)
        self.assertNotIn("region", scope)
        self.assertEqual(scope["category"], "Home")
        defaults = _resolve_scope(scope=None, target_date=None, region=None, category=None, as_of=None)
        self.assertEqual((defaults["region"], defaults["category"]), ("North", "Electronics"))

    def test_cfo_all_all_gives_an_empty_segment(self):
        result = diagnose_scope(kpis=["orders"], target_date="2023-07-24", region="ALL", category="ALL", persona="CFO", scope=None, as_of=None)["results"]["orders"]
        self.assertNotEqual(result["verdict"], "ACCESS_DENIED")
        self.assertEqual(result["segment"], {})

    def test_regional_manager_cannot_request_region_all(self):
        result = diagnose_scope(kpis=["orders"], target_date="2023-07-24", region="ALL", category="Electronics", persona="regional_manager_north", scope=None, as_of=None)["results"]["orders"]
        self.assertEqual(result["verdict"], "ACCESS_DENIED")

    def test_category_manager_cannot_request_category_all(self):
        result = diagnose_scope(kpis=["orders"], target_date="2023-07-24", region="North", category="ALL", persona="category_manager_north_electronics", scope=None, as_of=None)["results"]["orders"]
        self.assertEqual(result["verdict"], "ACCESS_DENIED")

    def test_timeseries_all_aggregates_and_is_denied_for_regional_manager(self):
        from backend.service import get_timeseries
        points = get_timeseries("orders", "ALL", "ALL", user_id="demo-cfo", start_date="2023-07-01", end_date="2023-07-24")["points"]
        self.assertTrue(points)
        with self.assertRaises(PermissionError):
            get_timeseries("orders", "ALL", "Electronics", user_id="demo-regional-north")


if __name__ == "__main__":
    unittest.main()
