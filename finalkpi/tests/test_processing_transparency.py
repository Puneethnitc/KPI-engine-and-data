import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import storage
from kpi_engine.narrative import NarrativeEngine
from kpi_engine.pipeline import KPIEnginePipeline
from kpi_engine.processing_transparency import build_processing_transparency

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


class ProcessingTransparencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pipeline = KPIEnginePipeline(
            registry_dir=str(ROOT / "kpi_engine" / "registry"),
            evidence_csv=str(DATA / "unstructured_evidence.csv"),
            access_csv=str(DATA / "access_control.csv"),
            feedback_log_path="/tmp/finalkpi-transparency-feedback.jsonl",
        )

    def normal_result(self):
        return self.pipeline.run_diagnosis(
            kpi_id="orders",
            target_date="2023-07-24",
            sales_csv=str(DATA / "sales_daily.csv"),
            marketing_csv=str(DATA / "marketing_weekly.csv"),
            finance_csv=str(DATA / "finance_monthly.csv"),
            persona="regional_manager_north",
            dimension_slice={"region": "North", "category": "Electronics"},
        )

    def test_real_diagnosis_contains_complete_transparency_contract(self):
        result = self.normal_result()
        transparency = result["processing_transparency"]
        stage_ids = {stage["stage_id"] for stage in transparency["stages"]}
        self.assertTrue({
            "scope_contract_validation", "source_loading_normalization", "reconciliation",
            "movement_materiality", "driver_ranking", "accounting_decomposition",
            "causal_verification", "confidence_evaluation", "action_recommendation",
            "narrative_generation", "llm_wording_selection", "sql_query_execution", "retrieval",
        }.issubset(stage_ids))
        self.assertFalse(transparency["summary"]["llm_used"])
        self.assertFalse(transparency["summary"]["retrieval_used"])
        self.assertFalse(transparency["summary"]["sql_executed"])
        self.assertEqual(
            next(stage for stage in transparency["stages"] if stage["stage_id"] == "sql_query_execution")["execution_status"],
            "SKIPPED",
        )
        self.assertEqual(
            next(stage for stage in transparency["stages"] if stage["stage_id"] == "retrieval")["execution_status"],
            "SKIPPED",
        )
        causal = next(stage for stage in transparency["stages"] if stage["stage_id"] == "causal_verification")
        self.assertEqual(causal["execution_status"], "NOT_REQUESTED")
        narrative = next(stage for stage in transparency["stages"] if stage["stage_id"] == "narrative_generation")
        self.assertEqual(narrative["method_category"], "DETERMINISTIC")
        self.assertEqual(narrative["method_id"], "approved_narrative_templates_v1")
        self.assertFalse(narrative["quantitative_truth"])
        ranking = next(stage for stage in transparency["stages"] if stage["stage_id"] == "driver_ranking")
        self.assertEqual(ranking["execution_status"], "USED")
        for stage in transparency["stages"]:
            for ref in stage["evidence_refs"]:
                current = result
                for part in ref.split("."):
                    self.assertIsInstance(current, dict, ref)
                    self.assertIn(part, current, ref)
                    current = current[part]

    def test_llm_wording_is_non_quantitative_and_failure_falls_back(self):
        base = {
            "kpi_id": "orders", "target_date": "2023-07-24", "verdict": "NO_MATERIAL_MOVEMENT",
            "movement_assessment": {"status": "OK", "delta": 0, "is_material": False},
            "narrative_claims": [{"text": "Observed movement.", "evidence_paths": ["movement_assessment"], "claim_type": "OBSERVED_MOVEMENT"}],
            "narrative": "Observed movement.",
        }
        def choose(options):
            return {"variants": [0 for _ in options]}
        rendered = NarrativeEngine(llm_client=choose).render(base)
        used = build_processing_transparency({**base, "narrative_claims": [dict(item) for item in rendered["claims"]], "narrative": rendered["text"], "narrative_method": rendered["method"], "llm_status": rendered["llm_status"], "movement_assessment": base["movement_assessment"]})
        llm_stage = next(stage for stage in used["stages"] if stage["stage_id"] == "llm_wording_selection")
        self.assertEqual(llm_stage["execution_status"], "USED")
        self.assertEqual(llm_stage["llm_role"], "WORDING_ONLY")
        self.assertFalse(llm_stage["quantitative_truth"])
        narrative_stage = next(stage for stage in used["stages"] if stage["stage_id"] == "narrative_generation")
        self.assertEqual(narrative_stage["method_category"], "DETERMINISTIC")
        self.assertEqual(narrative_stage["execution_status"], "USED")
        self.assertEqual(narrative_stage["method_id"], "approved_narrative_templates_v1")
        self.assertFalse(narrative_stage["quantitative_truth"])
        self.assertFalse(used["summary"]["sql_executed"])

        failed = NarrativeEngine(llm_client=lambda options: (_ for _ in ()).throw(TimeoutError())).render(base)
        fallback = build_processing_transparency({**base, "narrative_claims": [dict(item) for item in failed["claims"]], "narrative": failed["text"], "narrative_method": failed["method"], "llm_status": failed["llm_status"]})
        self.assertEqual(next(stage for stage in fallback["stages"] if stage["stage_id"] == "llm_wording_selection")["execution_status"], "FALLBACK")
        fallback_narrative = next(stage for stage in fallback["stages"] if stage["stage_id"] == "narrative_generation")
        self.assertEqual(fallback_narrative["method_category"], "DETERMINISTIC")
        self.assertEqual(fallback_narrative["execution_status"], "FALLBACK")
        self.assertEqual(fallback_narrative["method_id"], "approved_narrative_templates_v1")
        self.assertFalse(fallback_narrative["quantitative_truth"])

    def test_llm_wording_does_not_change_quantitative_fields(self):
        result = self.normal_result()
        deterministic = copy.deepcopy(result)
        deterministic.pop("processing_transparency", None)
        wording = copy.deepcopy(result)
        wording["narrative"] = "Approved alternate wording."
        wording["llm_status"] = "USED"
        wording["narrative_method"] = "llm_selected_approved_templates"
        wording["processing_transparency"] = build_processing_transparency(wording, causal_design_approved=False)
        for field in ("movement_assessment", "reconciliation_verdict", "decomposition", "driver_analysis", "confidence_profile", "decision_cards"):
            self.assertEqual(deterministic.get(field), wording.get(field), field)
        self.assertTrue(wording["processing_transparency"]["summary"]["llm_used"])

    def test_saved_and_legacy_runs_preserve_compatibility(self):
        result = self.normal_result()
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, "DB_PATH", Path(directory) / "runs.sqlite3"):
            storage.save_diagnosis_run(result, scope={"region": "North", "category": "Electronics"}, access_context={"authorized": True})
            saved = storage.get_run(result["run_id"])
            self.assertEqual(saved["result"]["processing_transparency"], result["processing_transparency"])

            legacy = {"run_id": "legacy-transparency-run", "kpi_id": "orders", "target_date": "2023-07-24", "as_of": "2023-07-25T12:00:00", "persona": "CFO", "verdict": "NO_MATERIAL_MOVEMENT"}
            storage.save_diagnosis_run(legacy, scope={"region": "North", "category": "Electronics"}, access_context={"authorized": True})
            legacy_saved = storage.get_run("legacy-transparency-run")
            self.assertNotIn("processing_transparency", legacy_saved["result"])

    def test_access_denied_transparency_is_sanitized(self):
        result = self.pipeline.run_diagnosis(
            kpi_id="orders", target_date="2023-07-24",
            sales_csv=str(DATA / "sales_daily.csv"), marketing_csv=str(DATA / "marketing_weekly.csv"),
            finance_csv=str(DATA / "finance_monthly.csv"), persona="regional_manager_north",
            dimension_slice={"region": "South", "category": "Electronics"},
        )
        self.assertEqual(result["verdict"], "ACCESS_DENIED")
        transparency = result["processing_transparency"]
        self.assertEqual(len(transparency["stages"]), 1)
        self.assertEqual(transparency["stages"][0]["execution_status"], "BLOCKED")
        self.assertEqual(transparency["stages"][0]["evidence_refs"], [])
        self.assertFalse(transparency["summary"]["llm_used"])
        self.assertNotIn("source_evidence", json.dumps(transparency))

    def test_non_executed_driver_ranking_is_skipped(self):
        transparency = build_processing_transparency({
            "verdict": "INSUFFICIENT_HISTORY",
            "driver_analysis": {"status": "INSUFFICIENT_EVIDENCE", "excluded_drivers": []},
            "narrative": "Insufficient history.",
            "narrative_method": "deterministic_evidence_template",
            "llm_status": "NOT_REQUESTED",
        })
        ranking = next(stage for stage in transparency["stages"] if stage["stage_id"] == "driver_ranking")
        self.assertEqual(ranking["execution_status"], "SKIPPED")

    def test_driver_ranking_status_requires_assessed_execution(self):
        def ranking_status(driver_analysis=None):
            result = {"verdict": "NO_MATERIAL_MOVEMENT"}
            if driver_analysis is not None:
                result["driver_analysis"] = driver_analysis
            transparency = build_processing_transparency(result)
            return next(stage for stage in transparency["stages"] if stage["stage_id"] == "driver_ranking")["execution_status"]

        self.assertEqual(ranking_status({"status": "ASSESSED", "ranked_drivers": [], "excluded_drivers": []}), "USED")
        self.assertEqual(ranking_status({"status": "COMPLETED", "excluded_drivers": []}), "USED")
        self.assertEqual(ranking_status({"status": "BLOCKED", "excluded_drivers": [{"driver_id": "x"}]}), "BLOCKED")
        self.assertEqual(ranking_status({"status": "DIAGNOSTIC_ONLY", "excluded_drivers": [{"driver_id": "x"}]}), "SKIPPED")
        self.assertEqual(ranking_status(), "SKIPPED")


if __name__ == "__main__":
    unittest.main()
