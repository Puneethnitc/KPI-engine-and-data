import unittest

from fastapi import HTTPException

from backend.app import api_driver_series
from backend.service import get_driver_series


class DriverSeriesTests(unittest.TestCase):
    def test_returns_daily_values_up_to_end_date(self):
        payload = get_driver_series("units_sold", "stock_availability", "North", "Electronics", user_id="demo-regional-north", end_date="2024-03-31")
        self.assertEqual(payload["grain"], "daily")
        self.assertTrue(0 < len(payload["points"]) <= 60)
        self.assertLessEqual(payload["points"][-1]["observation_date"], "2024-03-31")

    def test_as_of_cutoff_hides_unpublished_days(self):
        full = get_driver_series("units_sold", "stock_availability", "North", "Electronics", user_id="demo-cfo", end_date="2024-03-31")
        early = get_driver_series("units_sold", "stock_availability", "North", "Electronics", user_id="demo-cfo", end_date="2024-03-31", as_of="2024-03-20 12:00:00")
        self.assertLess(early["points"][-1]["observation_date"], full["points"][-1]["observation_date"])

    def test_regional_manager_cannot_read_another_region(self):
        with self.assertRaises(PermissionError):
            get_driver_series("units_sold", "stock_availability", "South", "Electronics", user_id="demo-regional-north")
        with self.assertRaises(HTTPException) as context:
            api_driver_series("units_sold", "stock_availability", "South", "Electronics", "demo-regional-north")
        self.assertEqual(context.exception.status_code, 403)

    def test_unknown_driver_is_client_error(self):
        with self.assertRaises(HTTPException) as context:
            api_driver_series("units_sold", "nope", "North", "Electronics", "demo-cfo")
        self.assertEqual(context.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
