import json
import os
import sqlite3
import tempfile
import unittest

from backend import storage


class StorageMetadataRegressionTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = storage.DB_PATH
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tempdir.name, "kpi_backend.sqlite3")
        storage.DB_PATH = self.db_path

    def tearDown(self):
        storage.DB_PATH = self.original_db_path
        self.tempdir.cleanup()

    def test_save_diagnosis_run_stores_execution_and_provenance_metadata(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE diagnosis_runs (
                run_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                kpi_id TEXT NOT NULL,
                target_date TEXT NOT NULL,
                as_of TEXT NOT NULL,
                persona TEXT NOT NULL,
                region TEXT,
                category TEXT,
                scope_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                engine_version TEXT NOT NULL,
                source_data_version TEXT NOT NULL,
                access_context TEXT NOT NULL
            )
            """
        )
        conn.commit()
        conn.close()

        result = {
            "run_id": "run-metadata-test",
            "kpi_id": "net_sales_revenue",
            "target_date": "2024-01-31",
            "as_of": "2024-02-01T00:00:00",
            "persona": "CFO",
            "contract_version": "v2.1",
            "contract_hash": "abc123",
            "policy_hash": "policy456",
            "telemetry": {"execution_ms": 827, "query_provenance": {"sql": "SELECT 1"}},
            "source_snapshot": {"id": "sales_daily:snapshot-42", "hash": "snap999"},
            "comparison_scope": {"region": "North", "category": "Electronics"},
        }

        storage.save_diagnosis_run(
            result,
            scope={"region": "North", "category": "Electronics", "target_date": "2024-01-31", "persona": "CFO"},
            access_context={"role": "CFO", "authorized": True},
        )

        saved = storage.get_run("run-metadata-test")
        self.assertEqual(saved["result"]["telemetry"]["execution_ms"], 827)
        self.assertEqual(saved["result"]["contract_version"], "v2.1")
        self.assertEqual(saved["result"]["policy_hash"], "policy456")
        self.assertEqual(saved["result"]["source_snapshot"]["id"], "sales_daily:snapshot-42")

        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT execution_ms, contract_version, policy_hash, source_snapshot_id, comparison_scope_json, query_provenance_json FROM diagnosis_runs WHERE run_id = ?",
            ("run-metadata-test",),
        ).fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], 827)
        self.assertEqual(row[1], "v2.1")
        self.assertEqual(row[2], "policy456")
        self.assertEqual(row[3], "sales_daily:snapshot-42")
        self.assertIn("Electronics", row[4])
        self.assertIn("SELECT 1", row[5])

    def test_save_diagnosis_run_distinguishes_replay_revisions_with_different_cutoffs(self):
        def build_result(run_id: str, source_id: str, as_of: str, period: str):
            return {
                "run_id": run_id,
                "kpi_id": "net_sales_revenue",
                "target_date": "2024-01-31",
                "as_of": as_of,
                "persona": "CFO",
                "contract": {"version": "v2.1", "kpi_id": "net_sales_revenue", "source": "sales_daily", "aggregation": "sum"},
                "policy": {"version": "policy-8", "comparison_period": period},
                "source_snapshot": {"id": source_id, "hash": f"hash-{source_id}"},
                "comparison_scope": {"region": "North", "category": "Electronics"},
                "comparison_period": {"target_date": "2024-01-31", "baseline_start": "2023-12-31", "baseline_end": "2024-01-30"},
                "query_provenance": {"sql": f"SELECT SUM(net_sales_revenue) FROM {source_id} WHERE region = 'North'", "params": ["North"]},
                "telemetry": {"execution_ms": 250},
            }

        first = build_result("replay-run-1", "sales_daily:rev-1", "2024-02-01T00:00:00", "same_slice_closed_month_only")
        second = build_result("replay-run-2", "sales_daily:rev-2", "2024-03-01T00:00:00", "same_slice_closed_month_only")

        storage.save_diagnosis_run(
            first,
            scope={"region": "North", "category": "Electronics", "target_date": "2024-01-31", "as_of": "2024-02-01T00:00:00"},
            access_context={"role": "CFO", "authorized": True},
        )
        storage.save_diagnosis_run(
            second,
            scope={"region": "North", "category": "Electronics", "target_date": "2024-01-31", "as_of": "2024-03-01T00:00:00"},
            access_context={"role": "CFO", "authorized": True},
        )

        saved_one = storage.get_run("replay-run-1")
        saved_two = storage.get_run("replay-run-2")

        self.assertNotEqual(saved_one["result"]["source_snapshot"]["hash"], saved_two["result"]["source_snapshot"]["hash"])
        self.assertNotEqual(saved_one["result"]["execution_metadata"]["as_of_cutoff"], saved_two["result"]["execution_metadata"]["as_of_cutoff"])
        self.assertNotEqual(saved_one["result"]["query_provenance"]["sql"], saved_two["result"]["query_provenance"]["sql"])
        self.assertEqual(saved_one["result"]["comparison_period"]["target_date"], "2024-01-31")
        self.assertEqual(saved_two["result"]["comparison_period"]["target_date"], "2024-01-31")
        self.assertIn("source_snapshot", saved_one["result"])
        self.assertIn("comparison_period", saved_one["result"])


if __name__ == "__main__":
    unittest.main()
