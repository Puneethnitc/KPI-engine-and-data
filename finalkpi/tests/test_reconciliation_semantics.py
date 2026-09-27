import unittest
import pandas as pd
from pathlib import Path

from kpi_engine.pipeline import KPIEnginePipeline
from kpi_engine.reconcile import SourceReconciler
from kpi_engine.narrative import NarrativeEngine
from backend.service import build_marketing_brief, diagnose_scope


class ReconciliationSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_dir = Path(__file__).resolve().parent.parent
        cls.sales_csv = str(cls.base_dir / "data" / "sales_daily.csv")
        cls.marketing_csv = str(cls.base_dir / "data" / "marketing_weekly.csv")
        cls.finance_csv = str(cls.base_dir / "data" / "finance_monthly.csv")
        cls.pipeline = KPIEnginePipeline(
            registry_dir=str(cls.base_dir / "kpi_engine" / "registry"),
            evidence_csv=str(cls.base_dir / "data" / "unstructured_evidence.csv"),
            access_csv=str(cls.base_dir / "data" / "access_control.csv"),
        )

    def test_unreconciled_kpis_return_not_applicable(self):
        """1 & 2. orders, units_sold, traffic_total, conversion_rate return NOT_APPLICABLE and proceed without finance."""
        for kpi_id in ["orders", "units_sold", "traffic_total", "conversion_rate"]:
            result = self.pipeline.run_diagnosis(
                kpi_id=kpi_id,
                target_date="2024-05-15",
                sales_csv=self.sales_csv,
                marketing_csv=self.marketing_csv,
                finance_csv="/nonexistent/finance.csv",
                persona="CFO",
                dimension_slice={"region": "North", "category": "Electronics"},
            )
            self.assertEqual(result["reconciliation_verdict"]["status"], "NOT_APPLICABLE")
            self.assertIn("movement_assessment", result)
            self.assertEqual(result["movement_assessment"]["status"], "OK")

    def test_mid_period_revenue_returns_not_available_for_period(self):
        """3. Mid-period revenue comparison returns NOT_AVAILABLE_FOR_PERIOD and continues diagnosis."""
        result = self.pipeline.run_diagnosis(
            kpi_id="net_sales_revenue",
            target_date="2024-05-15",
            sales_csv=self.sales_csv,
            marketing_csv=self.marketing_csv,
            finance_csv=self.finance_csv,
            persona="CFO",
            dimension_slice={"region": "North", "category": "Electronics"},
        )
        self.assertEqual(result["reconciliation_verdict"]["status"], "NOT_AVAILABLE_FOR_PERIOD")
        self.assertNotEqual(result["verdict"], "CONTRADICTED")
        self.assertEqual(result["movement_assessment"]["status"], "OK")

    def test_closed_period_revenue_agreed(self):
        """4. Closed-period revenue comparison returns AGREED when matching values agree."""
        daily = pd.DataFrame({
            "date": pd.date_range("2024-01-01", "2024-01-31"),
            "region": "North",
            "category": "Electronics",
            "net_sales_revenue": 100.0,
            "unit": "INR",
        })
        finance = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01"]),
            "month_end": pd.to_datetime(["2024-01-31"]),
            "region": "North",
            "category": "Electronics",
            "net_sales_revenue": 3100.0,
            "unit": "INR",
        })
        reconciler = SourceReconciler()
        verdict = reconciler.reconcile_mtd(
            daily, finance, target_year_month="2024-01", target_date="2024-01-31", mode="closed_period"
        )
        self.assertEqual(verdict.status, "AGREED")
        self.assertEqual(verdict.gap_pct, 0.0)

    def test_agreed_and_not_applicable_do_not_trigger_verification_required(self):
        """5 & 6. AGREED and NOT_APPLICABLE do not create VERIFICATION_REQUIRED story."""
        results = {
            "net_sales_revenue": {
                "reconciliation_verdict": {"status": "AGREED", "gap_pct": 0.0},
                "movement_assessment": {"status": "OK", "delta": -10.0, "is_material": True, "actual_value": 90, "expected_value": 100},
                "confidence": {"status": "HIGH"},
                "verdict": "MATERIAL_CAUSE_UNVERIFIED",
            },
            "orders": {
                "reconciliation_verdict": {"status": "NOT_APPLICABLE"},
                "movement_assessment": {"status": "OK", "delta": -5.0, "is_material": True, "actual_value": 45, "expected_value": 50},
                "confidence": {"status": "HIGH"},
                "verdict": "MATERIAL_CAUSE_UNVERIFIED",
            }
        }
        brief = build_marketing_brief(results, scope={"region": "North", "category": "Electronics"}, persona="CFO")
        story_ids = [s["id"] for s in brief.get("stories", [])]
        self.assertNotIn("VERIFICATION_REQUIRED", story_ids)

    def test_not_available_for_period_is_non_blocking_limitation(self):
        """7. NOT_AVAILABLE_FOR_PERIOD is non-blocking limitation."""
        results = {
            "net_sales_revenue": {
                "reconciliation_verdict": {"status": "NOT_AVAILABLE_FOR_PERIOD"},
                "movement_assessment": {"status": "OK", "delta": -10.0, "is_material": True, "actual_value": 90, "expected_value": 100},
                "confidence": {"status": "HIGH"},
                "verdict": "MATERIAL_CAUSE_UNVERIFIED",
            }
        }
        brief = build_marketing_brief(results, scope={"region": "North", "category": "Electronics"}, persona="CFO")
        story_ids = [s["id"] for s in brief.get("stories", [])]
        self.assertNotIn("VERIFICATION_REQUIRED", story_ids)

    def test_drift_continues_with_warning(self):
        """8. DRIFT continues downstream with warning."""
        daily = pd.DataFrame({
            "date": pd.date_range("2024-01-01", "2024-01-31"),
            "region": "North",
            "category": "Electronics",
            "net_sales_revenue": 100.0,
            "unit": "INR",
        })
        finance = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01"]),
            "month_end": pd.to_datetime(["2024-01-31"]),
            "region": "North",
            "category": "Electronics",
            "net_sales_revenue": 3250.0,
            "unit": "INR",
        })
        reconciler = SourceReconciler()
        verdict = reconciler.reconcile_mtd(
            daily, finance, target_year_month="2024-01", target_date="2024-01-31", mode="closed_period"
        )
        self.assertEqual(verdict.status, "DRIFT")

        results = {
            "net_sales_revenue": {
                "reconciliation_verdict": {"status": "DRIFT", "gap_pct": 4.8},
                "movement_assessment": {"status": "OK", "delta": -10.0, "is_material": True},
                "confidence": {"status": "HIGH"},
                "verdict": "MATERIAL_CAUSE_UNVERIFIED",
            }
        }
        brief = build_marketing_brief(results, scope={"region": "North", "category": "Electronics"}, persona="CFO")
        story_ids = [s["id"] for s in brief.get("stories", [])]
        self.assertIn("VERIFICATION_REQUIRED", story_ids)

    def test_contradicted_blocks_attribution(self):
        """9. CONTRADICTED is a hard gate that prevents attribution."""
        daily = pd.DataFrame({
            "date": pd.date_range("2024-01-01", "2024-01-31"),
            "region": "North",
            "category": "Electronics",
            "net_sales_revenue": 100.0,
            "unit": "INR",
        })
        finance = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01"]),
            "month_end": pd.to_datetime(["2024-01-31"]),
            "region": "North",
            "category": "Electronics",
            "net_sales_revenue": 5000.0,
            "unit": "INR",
        })
        reconciler = SourceReconciler()
        verdict = reconciler.reconcile_mtd(
            daily, finance, target_year_month="2024-01", target_date="2024-01-31", mode="closed_period"
        )
        self.assertEqual(verdict.status, "CONTRADICTED")

    def test_narrative_wording_for_all_five_statuses(self):
        """10. Narrative wording correct for all 5 statuses."""
        narrator = NarrativeEngine()
        statuses = ["NOT_APPLICABLE", "NOT_AVAILABLE_FOR_PERIOD", "AGREED", "DRIFT", "CONTRADICTED"]
        for st in statuses:
            payload = {
                "kpi_id": "net_sales_revenue",
                "target_date": "2026-04-14",
                "verdict": st if st == "CONTRADICTED" else "MATERIAL_CAUSE_UNVERIFIED",
                "reconciliation_verdict": {"status": st, "gap_pct": 2.0 if st == "AGREED" else 5.0 if st == "DRIFT" else None},
                "movement_assessment": {"status": "OK", "delta": -100.0, "is_material": True, "is_statistically_significant": True, "is_business_material": True},
            }
            rendered = narrator.render(payload)
            self.assertTrue(rendered["grounding_passed"])
            self.assertTrue(len(rendered["text"]) > 0)

    def test_five_kpi_overview_does_not_mark_all_unreconciled(self):
        """12. Five-KPI overview shows NOT_APPLICABLE for 4 KPIs and NOT_AVAILABLE_FOR_PERIOD for mid-period revenue."""
        res = diagnose_scope(
            kpis=["net_sales_revenue", "orders", "units_sold", "traffic_total", "conversion_rate"],
            target_date="2024-05-15",
            region="North",
            category="Electronics",
            persona="CFO",
        )
        results = res["results"]
        self.assertEqual(results["orders"]["reconciliation_verdict"]["status"], "NOT_APPLICABLE")
        self.assertEqual(results["units_sold"]["reconciliation_verdict"]["status"], "NOT_APPLICABLE")
        self.assertEqual(results["traffic_total"]["reconciliation_verdict"]["status"], "NOT_APPLICABLE")
        self.assertEqual(results["conversion_rate"]["reconciliation_verdict"]["status"], "NOT_APPLICABLE")
        self.assertEqual(results["net_sales_revenue"]["reconciliation_verdict"]["status"], "NOT_AVAILABLE_FOR_PERIOD")


if __name__ == "__main__":
    unittest.main()
