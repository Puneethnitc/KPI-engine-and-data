import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from datetime import date
from kpi_engine.evidence import SourceEvidenceBuilder

class TestSourceEvidence(unittest.TestCase):
    def test_reconciliation_verdicts(self):
        """Test the semantic rules around reconciliation states."""
        builder = SourceEvidenceBuilder()

        # 1 & 2. NOT_APPLICABLE: informational, not blocking
        recon = builder._build_reconciliation_evidence(
            recon_result={"status": "NOT_APPLICABLE", "details": {}},
            result={"kpi_id": "traffic_total", "segment": {"unit": "visits"}},
            scope={"region": "North", "category": "Apparel"},
            authorized=True
        )
        self.assertEqual(recon.status, "NOT_APPLICABLE")
        self.assertFalse(recon.blocking)
        self.assertFalse(recon.applicable)

        # 3. NOT_AVAILABLE_FOR_PERIOD: not blocking
        recon_na = builder._build_reconciliation_evidence(
            recon_result={"status": "NOT_AVAILABLE_FOR_PERIOD", "details": {"reason": "Period not closed"}},
            result={}, scope={}, authorized=True
        )
        self.assertEqual(recon_na.status, "NOT_AVAILABLE_FOR_PERIOD")
        self.assertFalse(recon_na.blocking)

        # 3b. PENDING_CLOSE (Stage 4, F-C3): not due yet, not blocking, and
        # distinct from NOT_AVAILABLE_FOR_PERIOD's "overdue or missing" reason.
        recon_pending = builder._build_reconciliation_evidence(
            recon_result={"status": "PENDING_CLOSE", "details": {"reason": "Finance close not due until 2024-06-15"}},
            result={}, scope={}, authorized=True
        )
        self.assertEqual(recon_pending.status, "PENDING_CLOSE")
        self.assertFalse(recon_pending.blocking)
        self.assertEqual(recon_pending.reason, "Finance close not due until 2024-06-15")

        # 4. AGREED: success
        recon_agreed = builder._build_reconciliation_evidence(
            recon_result={"status": "AGREED", "details": {"reason": "Matches within tolerance"}},
            result={}, scope={}, authorized=True
        )
        self.assertEqual(recon_agreed.status, "AGREED")
        self.assertFalse(recon_agreed.blocking)

        # 5. DRIFT: out of tolerance, warning, not blocking
        recon_drift = builder._build_reconciliation_evidence(
            recon_result={"status": "DRIFT", "details": {"reason": "Exceeds tolerance"}},
            result={}, scope={}, authorized=True
        )
        self.assertEqual(recon_drift.status, "DRIFT")
        self.assertFalse(recon_drift.blocking)

        # 6. CONTRADICTED: materially conflicting, blocking
        recon_contra = builder._build_reconciliation_evidence(
            recon_result={"status": "CONTRADICTED", "details": {"reason": "Contradictory"}},
            result={}, scope={}, authorized=True
        )
        self.assertEqual(recon_contra.status, "CONTRADICTED")
        self.assertTrue(recon_contra.blocking)

        # 7. Data-quality failure (Quality flag)
        recon_quality = builder._build_reconciliation_evidence(
            recon_result={"status": "DRIFT", "details": {"quality_flag": "QUALITY_FAILED"}},
            result={}, scope={}, authorized=True
        )
        self.assertEqual(recon_quality.quality_status, "QUALITY_FAILED")
        self.assertEqual(recon_quality.status, "DRIFT")

    def test_unauthorized_scope(self):
        """Unauthorized access hides evidence."""
        builder = SourceEvidenceBuilder()
        evidence = builder.build(
            result={"verdict": "ACCESS_DENIED"},
            scope={"region": "Global"},
        )
        self.assertEqual(evidence["source_readiness"]["status"], "MISSING")
        self.assertEqual(evidence["reconciliation"]["status"], "NOT_APPLICABLE")
        self.assertIn("unauthorized", evidence["limitations"][0])
        self.assertEqual(evidence["sources"][0]["authorized"], False)

    def test_safe_file_identifiers_and_fixtures(self):
        builder = SourceEvidenceBuilder()
        self.assertEqual(builder._safe_file_identifier("data/sales.csv"), "sales.csv")
        self.assertEqual(builder._safe_file_identifier("/absolute/path/data/sales.csv"), "sales.csv")
        self.assertEqual(
            builder._safe_file_identifier("data/demo_fixtures/contradicted_july_2023/sales.csv"),
            "demo_fixtures/contradicted_july_2023/sales.csv"
        )

    def test_contract_derived_required_sources(self):
        builder = SourceEvidenceBuilder()
        evidence = builder.build(
            result={
                "kpi_id": "traffic_total",
                "reconciliation_verdict": {"status": "NOT_APPLICABLE"}
            },
            scope={},
            sales_frame=pd.DataFrame({"date": []}),
        )
        self.assertEqual(evidence["source_readiness"]["required_sources"], ["sales_daily"])
        self.assertEqual(len(evidence["sources"]), 1)
        self.assertEqual(evidence["sources"][0]["source_id"], "sales_daily")

    def test_readiness_statuses(self):
        builder = SourceEvidenceBuilder()

        # MISSING: no frame at all
        evidence_missing = builder.build(result={}, scope={}, sales_frame=None)
        self.assertEqual(evidence_missing["source_readiness"]["status"], "MISSING")

        # MISSING: primary sales frame exists but has zero rows (EMPTY primary = MISSING)
        df_empty = pd.DataFrame(columns=["date", "region", "category", "available_at"])
        evidence_empty = builder.build(result={}, scope={}, sales_frame=df_empty)
        self.assertEqual(evidence_empty["sources"][0]["coverage_status"], "EMPTY")
        self.assertEqual(evidence_empty["source_readiness"]["status"], "MISSING",
                         "Empty primary source must be MISSING, not PARTIAL")

        # FULL coverage → READY (as_of 1 day after latest_available = within 2-day SLA)
        df_full = pd.DataFrame({
            "date": [pd.Timestamp("2023-01-01")],
            "region": ["North"], "category": ["Apparel"],
            "available_at": [pd.Timestamp("2023-01-02")],
        })
        evidence_full = builder.build(result={"as_of": "2023-01-03"},
                                      scope={"region": "North"}, sales_frame=df_full)
        self.assertEqual(evidence_full["source_readiness"]["status"], "READY")
        self.assertEqual(evidence_full["sources"][0]["coverage_status"], "FULL")

        # STALE: latest_available_time is many days behind as_of
        evidence_stale = builder.build(
            result={"as_of": "2023-01-15"},
            scope={"region": "North"},
            sales_frame=df_full,  # latest available 2023-01-02, cutoff 2023-01-15 = 13 days
        )
        self.assertEqual(evidence_stale["source_readiness"]["status"], "STALE",
                         "Source that is >2 days stale should be STALE")
        self.assertTrue(any("STALE" in lim for lim in evidence_stale["source_readiness"]["limitations"]),
                        "STALE limitation should be reported")

        # QUALITY_FAILED: reconciliation quality flag propagates
        evidence_quality = builder.build(
            result={"reconciliation_verdict": {"status": "AGREED",
                                               "details": {"quality_flag": "QUALITY_FAILED"}}},
            scope={"region": "North"},
            sales_frame=df_full,
            finance_frame=df_full,
            finance_path="finance.csv",
        )
        self.assertEqual(evidence_quality["source_readiness"]["status"], "QUALITY_FAILED")

        # Finance NOT_APPLICABLE → finance NOT required → readiness not affected
        evidence_no_fin = builder.build(
            result={"reconciliation_verdict": {"status": "NOT_APPLICABLE"}, "as_of": "2023-01-03"},
            scope={"region": "North"},
            sales_frame=df_full,
        )
        self.assertEqual(evidence_no_fin["source_readiness"]["status"], "READY",
                         "NOT_APPLICABLE reconciliation must not add finance as required")
        self.assertNotIn("finance_monthly",
                         evidence_no_fin["source_readiness"]["required_sources"],
                         "Finance must not appear as required when NOT_APPLICABLE")

    def test_saved_run_stability(self):
        from backend.service import get_evidence
        from backend.storage import initialize_db, _connect, _canonical_json
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "evidence-test.sqlite3"
            with patch("backend.storage.DB_PATH", database):
                initialize_db()
                conn = _connect()
                saved_evidence = {
                    "run_id": "test_saved_run_stability_v2",
                    "source_readiness": {"status": "READY"},
                    "reconciliation": {"status": "AGREED"},
                }
                result_payload = {"source_evidence": saved_evidence}
                scope = {}
                conn.execute(
                    "INSERT OR REPLACE INTO diagnosis_runs "
                    "(run_id, created_at, kpi_id, target_date, as_of, persona, region, category, "
                    "result_json, scope_json, engine_version, source_data_version, access_context) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "test_saved_run_stability_v2",
                        "2023-01-01", "test", "2023-01-01", "2023-01-01",
                        "CFO", None, None,
                        _canonical_json(result_payload),
                        _canonical_json(scope),
                        "test", "test",
                        _canonical_json({"allowed": True}),
                    ),
                )
                conn.commit()
                conn.close()

                evidence = get_evidence("test_saved_run_stability_v2")
                self.assertEqual(evidence["source_readiness"]["status"], "READY")
                self.assertEqual(evidence["reconciliation"]["status"], "AGREED")

    def test_target_period_coverage_is_not_inferred_from_any_nonempty_row(self):
        builder = SourceEvidenceBuilder()
        frame = pd.DataFrame({
            "date": [pd.Timestamp("2023-01-01")],
            "region": ["North"],
            "category": ["Electronics"],
            "available_at": [pd.Timestamp("2023-01-02")],
        })
        evidence = builder.build(
            result={"target_date": "2023-01-05"},
            scope={"region": "North", "category": "Electronics"},
            sales_frame=frame,
        )
        self.assertEqual(evidence["sources"][0]["coverage_status"], "PARTIAL")
        self.assertEqual(evidence["source_readiness"]["status"], "PARTIAL")

    def test_contradictory_fixture_evidence_is_bound_to_fixture_run(self):
        from backend.demo_scenarios import execute_demo_scenario
        from backend.service import get_evidence

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "fixture-evidence.sqlite3"
            with patch("backend.storage.DB_PATH", database):
                execution = execute_demo_scenario("contradictory-sources", "demo-cfo")
                result = execution["engine_result"]
                evidence = get_evidence(result["run_id"])

        identifiers = {item["file_identifier"] for item in evidence["sources"]}
        self.assertTrue(identifiers)
        self.assertTrue(all(identifier.startswith("demo_fixtures/contradicted_july_2023/") for identifier in identifiers))
        self.assertEqual(evidence["source_mode"], "demo_fixture")
        self.assertEqual(evidence["snapshot_status"], "CAPTURED_AT_EXECUTION")
        self.assertEqual(evidence["reconciliation"]["status"], "CONTRADICTED")
        self.assertEqual(evidence["reconciliation"]["primary_value"], 124489.15)
        self.assertEqual(evidence["reconciliation"]["comparison_value"], 373467.45)

    def test_evidence_endpoint_authorizes_before_loading_evidence(self):
        from fastapi import HTTPException
        from backend.app import api_evidence

        with patch("backend.app.get_authorized_diagnosis", return_value=None), \
             patch("backend.app.get_evidence") as loader:
            with self.assertRaises(HTTPException) as raised:
                api_evidence("secret-run", user_id="demo-marketing")
        self.assertEqual(raised.exception.status_code, 404)
        loader.assert_not_called()

if __name__ == '__main__':
    unittest.main()
