import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.service import diagnose_scope, get_registered_kpis
from backend import storage as backend_storage

ROOT = Path(__file__).resolve().parents[1]
ENGINE_ROOT = ROOT.parent


class BackendDiagnosisApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._database_directory = tempfile.TemporaryDirectory()
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

    def test_registered_kpis_match_engine_registry(self):
        kpis = get_registered_kpis()
        self.assertEqual(
            {item["kpi_id"] for item in kpis},
            {"net_sales_revenue", "orders", "units_sold", "traffic_total", "conversion_rate"},
        )

    def test_diagnosis_api_matches_engine_results_for_all_five_kpis(self):
        results = diagnose_scope(kpis=["all"], target_date="2023-07-24", region="North", category="Electronics")
        self.assertEqual(set(results), {"results"})
        payload = results["results"]
        self.assertEqual(set(payload), {"net_sales_revenue", "orders", "units_sold", "traffic_total", "conversion_rate"})
        for kpi_id, result in payload.items():
            self.assertEqual(result["kpi_id"], kpi_id)
            self.assertEqual(result["target_date"], "2023-07-24")
            self.assertEqual(result["persona"], "CFO")
            self.assertIn(result["verdict"], {"MATERIAL_CAUSE_UNVERIFIED", "NO_MATERIAL_MOVEMENT", "SEASONAL_REVIEW"})
            self.assertIn("narrative", result)
            json.dumps(result, allow_nan=False)

    def test_fresh_database_returns_none_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            backend_storage, "DB_PATH", Path(tmpdir) / "kpi_backend.sqlite3"
        ):
            self.assertIsNone(backend_storage.get_run("missing-run-id"))


if __name__ == "__main__":
    unittest.main()
