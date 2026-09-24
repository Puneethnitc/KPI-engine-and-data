"""Jury review and provisional evaluation remain reproducible and honest."""

import unittest

from run_jury_review import build_report
from run_review_benchmark import run


class DemoTests(unittest.TestCase):
    def test_provisional_review_has_no_accuracy_claim(self):
        review = run(kpi_ids=["net_sales_revenue"])
        self.assertEqual(review["label_status"], "PROVISIONAL_GENERATOR_NOTES")
        self.assertIsNone(review["accuracy_metrics"])
        self.assertEqual(len(review["cases"]), 8)
        self.assertTrue(all(row["grounding_passed"] for row in review["cases"]))
        self.assertIn("NO_MATERIAL_MOVEMENT",
                      {row["verdict"] for row in review["cases"]})

    def test_html_review_shows_five_kpis_and_review_boundary(self):
        report = build_report()
        for kpi in ("net_sales_revenue", "orders", "units_sold",
                    "traffic_total", "conversion_rate"):
            self.assertIn(f"<h2>{kpi}</h2>", report)
        self.assertIn("No action is executed", report)
        self.assertIn("Evidence-bound claims", report)
        self.assertIn("AWAITING_REVIEW", report)


if __name__ == "__main__":
    unittest.main()
