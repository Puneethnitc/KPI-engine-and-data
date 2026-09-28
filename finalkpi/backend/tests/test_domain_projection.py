import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from backend import storage
from backend.app import DiagnosisRequest, api_diagnoses, api_diagnosis_run, api_evidence, api_kpi_contract, api_kpis
from backend.demo_scenarios import SCENARIOS, execute_demo_scenario
from backend.domain_policy import domains_for_persona, has_domain, require_domain
from backend.response_projection import (
    project_diagnosis,
    project_evidence,
    project_semantic_contract,
)
from backend.service import get_investigations
from kpi_engine.confidence import ConfidenceEngine
from kpi_engine.pipeline import KPIEnginePipeline
from kpi_engine.contracts import KPIRegistry
from backend.config import ENGINE_REGISTRY_DIR


class DomainProjectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(storage, "DB_PATH", Path(self.directory.name) / "projection.sqlite3")
        self.db_patch.start()
        storage.initialize_db()

    def tearDown(self):
        self.db_patch.stop()
        self.directory.cleanup()

    @staticmethod
    def diagnosis(run_id="projection-run", persona="marketing_manager", region="North"):
        return {
            "run_id": run_id,
            "kpi_id": "net_sales_revenue",
            "target_date": "2023-07-31",
            "as_of": "2023-08-07T12:00:00+00:00",
            "persona": persona,
            "segment": {"region": region, "category": "Electronics"},
            "verdict": "MATERIAL_CAUSE_UNVERIFIED",
            "movement_assessment": {
                "status": "OK", "actual_value": 1000.0, "expected_value": 900.0,
                "delta": 100.0, "baseline_count": 60, "is_material": True,
            },
            "reconciliation_verdict": {
                "status": "DRIFT", "gap_pct": 12.5, "tolerance_used": 3.5,
                "details": {
                    "sales_mtd_total": 1000.0, "finance_total": 875.0,
                    "year_month": "2023-07", "sales_column_used": "net_sales_revenue",
                    "finance_column_used": "net_sales_revenue", "mode": "closed_period",
                    "segment": {"region": region, "category": "Electronics"},
                },
            },
            "source_evidence": {
                "run_id": run_id,
                "source_readiness": {
                    "status": "READY", "required_sources": ["sales_daily", "finance_monthly"],
                    "available_sources": ["sales_daily", "finance_monthly"], "limitations": ["finance_monthly is ready"],
                },
                "sources": [
                    {"source_id": "sales_daily", "file_identifier": "sales_daily.csv", "access_classification": "internal", "records_read": 31, "coverage_status": "FULL"},
                    {"source_id": "finance_monthly", "file_identifier": "finance_monthly.csv", "access_classification": "restricted", "records_read": 1, "coverage_status": "FULL"},
                ],
                "alignment": [
                    {"source_id": "sales_daily", "alignment_status": "ALIGNED"},
                    {"source_id": "finance_monthly", "alignment_status": "ALIGNED"},
                ],
                "reconciliation": {
                    "status": "DRIFT", "applicable": True, "blocking": False,
                    "comparison_source": "finance_monthly", "metric": "net_sales_revenue",
                    "primary_value": 1000.0, "comparison_value": 875.0, "absolute_gap": 125.0,
                    "gap_percent": 12.5, "comparison_basis": "closed_period", "reason": "finance comparison",
                },
                "lineage": [
                    {"source_id": "sales_daily", "access_classification": "internal", "query_identifier": "sales_daily.rows"},
                    {"source_id": "finance_monthly", "access_classification": "restricted", "query_identifier": "finance_monthly.rows"},
                ],
                "narrative_claim_evidence": [
                    {"claim": "sales", "evidence_paths": ["movement_assessment.delta"]},
                    {"claim": "finance", "evidence_paths": ["finance_monthly.rows"]},
                ],
                "limitations": ["finance_monthly rows limited"],
            },
            "contract_snapshot": KPIRegistry(ENGINE_REGISTRY_DIR).semantic_snapshot("net_sales_revenue", allowed_roles=["CFO", "marketing_manager"]),
            "confidence_profile": {
                "overall": {"status": "MODERATE"},
                "source": {"status": "LOW", "inputs": {
                    "required_sources": ["sales_daily", "finance_monthly"],
                    "source_entries": [
                        {"source_id": "sales_daily", "coverage_status": "FULL"},
                        {"source_id": "finance_monthly", "coverage_status": "FULL", "access_classification": "restricted"},
                    ],
                    "evidence_refs": ["reconciliation_verdict", "movement_assessment"],
                }},
            },
            "driver_analysis": {"status": "ASSESSED", "ranked_drivers": [{"driver_id": "marketing_spend", "score": 0.5}]},
            "decision_cards": [{"action_id": "review", "status": "REVIEW"}],
        }

    def save_result(self, result, scope=None):
        storage.save_diagnosis_run(
            result,
            scope=scope or {"region": result["segment"]["region"], "category": "Electronics"},
            access_context={"authorized": True, "role": result["persona"]},
        )

    def test_central_domain_policy_is_explicit_and_fails_closed(self):
        self.assertEqual(domains_for_persona("CFO"), {
            "SALES", "MARKETING", "FINANCE", "OPERATIONS", "KPI_CONTRACT",
            "FEEDBACK_REVIEW", "CANDIDATE_EVALUATION", "CHAT_EVIDENCE",
        })
        self.assertTrue(has_domain("marketing_manager", "MARKETING"))
        self.assertFalse(has_domain("regional_manager_north", "MARKETING"))
        self.assertTrue(has_domain("regional_manager_north", "OPERATIONS"))
        with self.assertRaises(PermissionError):
            require_domain("marketing_manager", "FINANCE")
        with self.assertRaises(ValueError):
            domains_for_persona("unregistered_persona")

    def test_cfo_retains_full_reconciliation_values(self):
        original = self.diagnosis(persona="CFO")
        projected = project_diagnosis(original, "CFO")
        self.assertEqual(projected["reconciliation_verdict"]["details"]["finance_total"], 875.0)
        self.assertEqual(projected["source_evidence"]["reconciliation"]["comparison_value"], 875.0)
        self.assertEqual(projected["source_evidence"]["sources"][1]["file_identifier"], "finance_monthly.csv")
        self.assertEqual(projected["source_evidence"]["sources"][1]["coverage_status"], "FULL")

    def test_nonfinance_diagnosis_and_evidence_hide_finance_values_and_refs(self):
        original = self.diagnosis()
        before = copy.deepcopy(original)
        projected = project_diagnosis(original, "marketing_manager")
        encoded = repr(projected)
        self.assertEqual(projected["reconciliation_verdict"]["status"], "DRIFT")
        self.assertIsNone(projected["reconciliation_verdict"]["gap_pct"])
        self.assertTrue(projected["reconciliation_verdict"]["applicable"])
        self.assertIn("not visible", projected["reconciliation_verdict"]["reason"])
        self.assertNotIn("finance_total", encoded)
        self.assertNotIn("875.0", encoded)
        self.assertNotIn("finance_monthly.csv", encoded)
        self.assertNotIn("finance_monthly.rows", encoded)
        # The source participated in reconciliation; expose that fact while
        # keeping its values, dates, file identifiers, and paths hidden.
        self.assertEqual(projected["source_evidence"]["sources"][1], {
            "source_id": "finance_monthly", "coverage_status": "RESTRICTED",
            "access_classification": "restricted",
        })
        self.assertIn("Restricted finance evidence exists", repr(projected["source_evidence"]))
        self.assertEqual(original, before)

    def test_projection_is_deterministic_idempotent_and_preserves_analytic_outputs(self):
        original = self.diagnosis()
        first = project_diagnosis(original, "regional_manager_north")
        self.assertEqual(first, project_diagnosis(original, "regional_manager_north"))
        self.assertEqual(first, project_diagnosis(first, "regional_manager_north"))
        for key in ("verdict", "movement_assessment", "driver_analysis", "decision_cards"):
            self.assertEqual(first[key], original[key])
        self.assertNotIn("875.0", repr(first["reconciliation_verdict"]))
        self.assertIsNone(first["reconciliation_verdict"]["gap_pct"])
        self.assertEqual(first["confidence_profile"]["overall"]["status"], original["confidence_profile"]["overall"]["status"])
        self.assertEqual(first["confidence_profile"]["source"]["status"], original["confidence_profile"]["source"]["status"])
        with self.assertRaises(ValueError):
            project_diagnosis(original, "unknown_persona")

    def test_contract_projection_hides_internal_policy_and_source_mappings(self):
        contract = KPIRegistry(ENGINE_REGISTRY_DIR).semantic_snapshot("net_sales_revenue", allowed_roles=["CFO", "marketing_manager"])
        before = copy.deepcopy(contract)
        limited = project_semantic_contract(contract, "marketing_manager")
        self.assertEqual(contract, before)
        self.assertEqual(limited["identity"]["display_name"], contract["identity"]["display_name"])
        self.assertEqual(limited["calculation"]["formula"], contract["calculation"]["formula"])
        self.assertEqual(limited["materiality"]["statistical_thresholds"], contract["materiality"]["statistical_thresholds"])
        self.assertIsNone(limited["reconciliation"]["comparison_metric"])
        self.assertEqual(limited["security"]["allowed_roles"], [])
        self.assertEqual(limited["security"]["access_tags"], [])
        self.assertEqual(limited["source"]["primary_source_id"], "")
        self.assertEqual(limited["drivers"]["candidate_drivers"][0]["source_id"], "")
        self.assertNotIn("finance_monthly", repr(limited))
        cfo = project_semantic_contract(contract, "CFO")
        self.assertEqual(cfo["reconciliation"]["comparison_metric"], "net_sales_revenue")
        with_path = copy.deepcopy(contract)
        with_path["source"]["lineage_reference"] = "/private/data/file.csv"
        self.assertIsNone(project_semantic_contract(with_path, "CFO")["source"].get("lineage_reference"))

    def test_contract_api_and_catalog_use_role_projection(self):
        items = api_kpis(user_id="demo-marketing")["items"]
        self.assertEqual(len(items), 5)
        self.assertNotIn("region_scoped", repr(items))
        self.assertTrue(all(item["security"]["access_tags"] == [] for item in items))
        self.assertEqual(items[0]["security"]["allowed_roles"], [])
        current = api_kpi_contract("net_sales_revenue", user_id="demo-marketing")
        self.assertEqual(current["reconciliation"]["comparison_metric"], None)
        cfo = api_kpi_contract("net_sales_revenue", user_id="demo-cfo")
        self.assertEqual(cfo["reconciliation"]["comparison_metric"], "net_sales_revenue")

    def test_saved_diagnosis_projection_matches_current_and_does_not_mutate_store(self):
        response = api_diagnoses(DiagnosisRequest(
            kpis=["net_sales_revenue"], target_date="2023-07-31", region="North",
            category="Electronics", persona="marketing_manager", user_id="demo-marketing",
            as_of="2023-08-07T12:00:00",
        ))
        run_id = response["results"]["net_sales_revenue"]["run_id"]
        saved_before = storage.get_run(run_id)["result"]
        saved_response = api_diagnosis_run(run_id, user_id="demo-marketing")
        self.assertEqual(saved_response["result"]["reconciliation_verdict"], response["results"]["net_sales_revenue"]["reconciliation_verdict"])
        self.assertEqual(storage.get_run(run_id)["result"], saved_before)
        self.assertIsNotNone(saved_before["reconciliation_verdict"].get("details", {}).get("finance_total"))

    def test_evidence_endpoint_projects_only_after_authorized_run_read(self):
        result = self.diagnosis()
        self.save_result(result)
        before = storage.get_run(result["run_id"])["result"]
        marketing = api_evidence(result["run_id"], user_id="demo-marketing")
        # The finance source participated; its placeholder reveals only that
        # fact, while dates, values and file paths remain hidden.
        self.assertEqual(marketing["sources"][1], {
            "source_id": "finance_monthly", "coverage_status": "RESTRICTED",
            "access_classification": "restricted",
        })
        self.assertNotIn("875.0", repr(marketing))
        self.assertTrue(marketing["restricted_evidence_hidden"])
        self.assertEqual(storage.get_run(result["run_id"])["result"], before)

        cfo_result = self.diagnosis("evidence-cfo", persona="CFO")
        self.save_result(cfo_result)
        cfo = api_evidence(cfo_result["run_id"], user_id="demo-cfo")
        self.assertEqual(cfo["reconciliation"]["comparison_value"], 875.0)
        self.assertEqual(cfo["sources"][1]["file_identifier"], "finance_monthly.csv")

    def test_investigation_insight_list_results_are_projected(self):
        result = self.diagnosis("list-projection")
        self.save_result(result)
        response = get_investigations(user_id="demo-marketing")
        self.assertEqual(response["total"], 1)
        self.assertNotIn("875.0", repr(response["items"][0]["result"]))
        self.assertIsNone(response["items"][0]["result"]["reconciliation_verdict"]["gap_pct"])

    def test_access_denied_profile_has_no_fabricated_baseline(self):
        profile = KPIEnginePipeline._build_evidence_profile({"verdict": "ACCESS_DENIED"})
        self.assertIsNone(profile["movement"]["baseline_count"])
        self.assertIsNone(ConfidenceEngine().build_profile({"verdict": "ACCESS_DENIED"})["movement"]["inputs"].get("baseline_count"))

    def test_governed_marketing_scenario_uses_same_projection(self):
        from backend import demo_scenarios

        base = SCENARIOS["material-multi-driver"]
        scenario = replace(
            base,
            scenario_id="limited-marketing-projection",
            persona="marketing_manager",
            user_id="demo-marketing",
            expected_broad_outcome="MATERIAL",
        )
        result = self.diagnosis("scenario-projection", persona="marketing_manager")
        with patch.dict(demo_scenarios.SCENARIOS, {scenario.scenario_id: scenario}), \
             patch("backend.service.diagnose_scope", return_value={"results": {"net_sales_revenue": result}}), \
             patch("backend.service.build_marketing_brief", return_value={"summary": "safe narrative"}):
            payload = execute_demo_scenario(scenario.scenario_id, "demo-marketing")
        self.assertNotIn("875.0", repr(payload["engine_result"]))
        self.assertIsNone(payload["engine_result"]["reconciliation_verdict"]["gap_pct"])


if __name__ == "__main__":
    unittest.main()
