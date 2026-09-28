"""MovementScanner: fast, detection-only, access-respecting movement scan."""

import unittest
from pathlib import Path

from kpi_engine.scan import MovementScanner

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


class MovementScannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scanner = MovementScanner(
            str(ROOT / "kpi_engine" / "registry"), str(DATA / "access_control.csv"),
        )
        cls.sales_csv = str(DATA / "sales_daily.csv")

    def test_regional_persona_only_sees_its_own_region(self):
        movements = self.scanner.scan(
            date="2024-05-15", persona="regional_manager_north",
            kpis=["net_sales_revenue"], sales_csv=self.sales_csv,
        )
        self.assertTrue(movements)
        self.assertTrue(all(item["region"] == "North" for item in movements))

    def test_category_restricted_persona_is_limited_to_its_own_scope(self):
        # F-S4: category_manager_north_electronics is North/Electronics only.
        movements = self.scanner.scan(
            date="2024-05-15", persona="category_manager_north_electronics",
            kpis=["net_sales_revenue"], sales_csv=self.sales_csv,
        )
        self.assertTrue(movements)
        self.assertTrue(all(
            item["region"] == "North" and item["category"] == "Electronics"
            for item in movements
        ))

    def test_all_entitled_persona_gets_the_company_wide_rollup_too(self):
        movements = self.scanner.scan(
            date="2024-05-15", persona="CFO",
            kpis=["net_sales_revenue"], sales_csv=self.sales_csv,
        )
        self.assertTrue(any(item["region"] is None and item["category"] is None for item in movements))
        self.assertTrue(any(item["region"] is not None for item in movements))

    def test_movements_are_sorted_by_descending_priority(self):
        movements = self.scanner.scan(
            date="2024-05-15", persona="CFO",
            kpis=["net_sales_revenue", "orders", "units_sold"], sales_csv=self.sales_csv,
        )
        priorities = [item["priority"] for item in movements]
        self.assertEqual(priorities, sorted(priorities, reverse=True))

    def test_quiet_date_returns_no_material_movements_but_still_scores(self):
        # 2023-05-22 is a verified quiet North/Electronics date (Stage 0's
        # ground-truth negatives; see backend/demo_scenarios.py's
        # non-material-baseline scenario).
        movements = self.scanner.scan(
            date="2023-05-22", persona="regional_manager_north",
            kpis=["net_sales_revenue"], sales_csv=self.sales_csv,
        )
        north_electronics = next(
            item for item in movements
            if item["region"] == "North" and item["category"] == "Electronics"
        )
        self.assertFalse(north_electronics["is_material"])

    def test_unregistered_persona_gets_no_slices(self):
        movements = self.scanner.scan(
            date="2024-05-15", persona="not-a-real-role",
            kpis=["net_sales_revenue"], sales_csv=self.sales_csv,
        )
        self.assertEqual(movements, [])


if __name__ == "__main__":
    unittest.main()
