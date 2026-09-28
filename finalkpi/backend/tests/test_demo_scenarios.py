import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from backend.app import DiagnosisRequest, api_demo_scenario_execute, api_demo_scenarios, api_diagnoses, api_kpi_contract, api_diagnosis_contract
from backend.demo_scenarios import REQUIRED_SCENARIO_IDS, SCENARIOS, execute_demo_scenario, list_scenarios, validate_catalog
from backend import storage as backend_storage


class DemoScenarioTests(unittest.TestCase):
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

    def test_catalog_returns_all_required_scenario_ids(self):
        validate_catalog()
        catalog = api_demo_scenarios()
        ids = [item["scenario_id"] for item in catalog["items"]]
        self.assertEqual(ids, list(REQUIRED_SCENARIO_IDS))
        self.assertIsNone(catalog["standard_view"]["scenario_id"])

    def test_every_scenario_has_governed_configuration(self):
        for scenario_id in REQUIRED_SCENARIO_IDS:
            scenario = SCENARIOS[scenario_id]
            self.assertTrue(scenario.persona)
            self.assertTrue(scenario.user_id)
            self.assertTrue(scenario.primary_kpi)
            self.assertTrue(scenario.region)
            self.assertTrue(scenario.category)
            self.assertRegex(scenario.target_date, r"^\d{4}-\d{2}-\d{2}$")
            self.assertIn(scenario.source_mode, {"production", "demo_fixture"})
            self.assertTrue(scenario.expected_broad_outcome)
            public = scenario.public_dict()
            self.assertNotIn("delta", public)
            self.assertNotIn("narrative", public)
            self.assertNotIn("confidence", public)

    def test_material_scenario_produces_material_class(self):
        payload = execute_demo_scenario("material-multi-driver", "demo-cfo")
        result = payload["engine_result"]
        self.assertEqual(payload["observed_broad_outcome"], "MATERIAL")
        self.assertTrue(payload["expected_outcome_observed"])
        self.assertTrue(result["movement_assessment"]["is_material"])
        self.assertTrue((result.get("decomposition") or {}).get("is_identity_held"))
        self.assertGreater(len(result.get("correlational_candidates") or []), 1)
        profile = result["confidence_profile"]
        self.assertEqual(profile["movement"]["status"], "HIGH")
        self.assertEqual(profile["driver"]["status"], "MODERATE")
        self.assertIsNone(profile["causal"]["score"])
        driver_analysis = result["driver_analysis"]
        self.assertEqual(driver_analysis["status"], "ASSESSED")
        # net_sales_revenue's candidate_drivers (Stage 1, F-R1/F-R2/F-R4): checkout_latency,
        # competitor_price_index, marketing_spend, stock_availability, price_discount,
        # promo_flag, weather_temp.
        self.assertEqual(driver_analysis["candidate_count"], 7)
        self.assertEqual(driver_analysis["candidate_count"], driver_analysis["ranked_count"] + driver_analysis["excluded_count"])
        self.assertGreater(driver_analysis["ranked_count"], 1)
        supported_ids = {item["driver_id"] for item in driver_analysis["ranked_drivers"]}
        narrative_driver_claims = [
            claim for claim in result["narrative_claims"]
            if claim["claim_type"] == "ATTRIBUTED_DRIVER"
        ]
        recommended_ids = {item["driver_id"] for item in result["decision_cards"] if item.get("driver_id")}
        self.assertEqual(len(narrative_driver_claims), len(supported_ids))
        self.assertTrue(recommended_ids.issubset(supported_ids))

    def test_runtime_stage_types_match_executed_material_pipeline(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            backend_storage, "DB_PATH", Path(directory) / "stage-types.sqlite3"
        ):
            payload = execute_demo_scenario("material-multi-driver", "demo-cfo")
        result = payload["engine_result"]
        telemetry = result["telemetry"]
        stages = {stage["stage"]: stage for stage in telemetry["stages"]}
        expected_types = {
            "diagnosis_pipeline": "DETERMINISTIC",
            "authorization": "BUSINESS_RULE",
            "source_preparation": "DETERMINISTIC",
            "reconciliation": "DETERMINISTIC",
            "movement_detection": "STATISTICAL",
            "driver_analysis": "STATISTICAL",
            "contribution_analysis": "DETERMINISTIC",
            "causal_verification": "CAUSAL",
            "confidence_and_actions": "BUSINESS_RULE",
            "narrative_synthesis": "DETERMINISTIC",
        }
        for stage_name, processing_type in expected_types.items():
            with self.subTest(stage=stage_name):
                self.assertEqual(stages[stage_name]["processing_type"], processing_type)
        for stage in telemetry["stages"]:
            if stage["processing_type"] != "LLM":
                self.assertEqual(stage["model_calls"], 0, stage["stage"])
                self.assertEqual(stage["input_tokens"], 0, stage["stage"])
                self.assertEqual(stage["output_tokens"], 0, stage["stage"])
                self.assertEqual(stage["estimated_cost_usd"], 0, stage["stage"])
        narrative_stage = stages.get("narrative_generation")
        attempted = result.get("llm_status") in {"USED", "REJECTED", "ERROR_FALLBACK"}
        self.assertEqual(narrative_stage is not None, attempted)
        if narrative_stage:
            self.assertEqual(narrative_stage["processing_type"], "LLM")

    def test_early_exit_scenarios_omit_unexecuted_later_stages(self):
        scenarios = {
            "contradictory-sources": {"movement_detection", "driver_analysis", "contribution_analysis", "causal_verification"},
            "sparse-history-new-launch": {"driver_analysis", "contribution_analysis", "causal_verification"},
            "non-material-baseline": {"contribution_analysis", "causal_verification"},
        }
        for scenario_id, later_stages in scenarios.items():
            with self.subTest(scenario=scenario_id):
                with tempfile.TemporaryDirectory() as directory, patch.object(
                    backend_storage, "DB_PATH", Path(directory) / "early-exit.sqlite3"
                ):
                    result = execute_demo_scenario(scenario_id, "demo-cfo")["engine_result"]
                executed = {stage["stage"] for stage in result["telemetry"]["stages"]}
                self.assertTrue(later_stages.isdisjoint(executed), later_stages & executed)

    def test_low_confidence_scenario_abstains(self):
        payload = execute_demo_scenario("low-confidence-abstention", "demo-cfo")
        result = payload["engine_result"]
        self.assertEqual(payload["observed_broad_outcome"], "ABSTAIN")
        self.assertEqual(result["verdict"], "SEASONAL_REVIEW")
        self.assertEqual(result.get("causal_verdict"), None)
        self.assertFalse(any(card.get("kind") == "ACTION_PROPOSAL" for card in result.get("decision_cards") or []))
        self.assertFalse(any(card.get("expected_impact") not in (None,) for card in result.get("decision_cards") or []))
        self.assertEqual(result["confidence_profile"]["causal"]["status"], "NOT_ASSESSED")
        # Stage 3: a non-material movement still runs attribution but is
        # labelled EXPLORATORY_NON_MATERIAL (plan Stage 3, step C) rather than
        # ASSESSED, so the narrative never presents drivers as explanations.
        self.assertIn(
            result["driver_analysis"]["status"],
            {"ASSESSED", "INSUFFICIENT_EVIDENCE", "EXPLORATORY_NON_MATERIAL"},
        )

    def test_contradictory_scenario_blocks_attribution(self):
        payload = execute_demo_scenario("contradictory-sources", "demo-cfo")
        result = payload["engine_result"]
        self.assertEqual(payload["observed_broad_outcome"], "CONTRADICTED")
        self.assertEqual(result["verdict"], "CONTRADICTED")
        self.assertEqual((result.get("reconciliation_verdict") or {}).get("status"), "CONTRADICTED")
        self.assertEqual(result.get("correlational_candidates") or [], [])
        profile = result["confidence_profile"]
        self.assertEqual(profile["source"]["status"], "CONFLICTING_EVIDENCE")
        self.assertTrue(profile["source"]["blocking"])
        self.assertEqual(profile["causal"]["status"], "CONFLICTING_EVIDENCE")
        self.assertTrue(profile["causal"]["blocking"])
        self.assertEqual(profile["driver"]["status"], "CONFLICTING_EVIDENCE")
        self.assertEqual(profile["overall"]["status"], "CONFLICTING_EVIDENCE")
        self.assertEqual(result.get("decision_cards"), [])
        self.assertEqual(result["driver_analysis"]["status"], "BLOCKED")
        self.assertEqual(result["driver_analysis"]["ranked_drivers"], [])
        self.assertEqual(result["driver_analysis"]["excluded_count"], result["driver_analysis"]["candidate_count"])
        self.assertTrue(all(
            item["reason_code"] == "BLOCKED_BY_RECONCILIATION"
            for item in result["driver_analysis"]["excluded_drivers"]
        ))
        self.assertFalse(result["correlational_candidates"])
        self.assertFalse(any(item.get("driver_id") for item in result["decision_cards"]))
        self.assertTrue(payload["uses_demo_fixture"])
        self.assertEqual(payload["scenario"]["fixture_label"], "Simulated demonstration data")

    def test_sparse_history_returns_insufficient_history(self):
        payload = execute_demo_scenario("sparse-history-new-launch", "demo-cfo")
        result = payload["engine_result"]
        self.assertEqual(payload["observed_broad_outcome"], "INSUFFICIENT_HISTORY")
        self.assertEqual(result["verdict"], "INSUFFICIENT_HISTORY")
        self.assertEqual(result.get("correlational_candidates") or [], [])
        self.assertIsNotNone(payload["history"]["baseline_count"])
        self.assertGreater(payload["history"]["required_observation_count"], payload["history"]["baseline_count"])
        profile = result["confidence_profile"]
        self.assertEqual(profile["movement"]["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(profile["overall"]["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result["driver_analysis"]["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result["driver_analysis"]["ranked_drivers"], [])
        self.assertEqual(result["driver_analysis"]["candidate_count"], result["driver_analysis"]["excluded_count"])

    def test_unauthorized_scenario_is_denied_without_leaking_data(self):
        with self.assertRaises(HTTPException) as context:
            api_demo_scenario_execute("unauthorized-scope", type("Req", (), {"user_id": "demo-regional-north"})())
        self.assertEqual(context.exception.status_code, 403)
        detail = context.exception.detail
        self.assertEqual(detail["observed_broad_outcome"], "ACCESS_DENIED")
        engine = detail["engine_result"]
        self.assertEqual(engine["verdict"], "ACCESS_DENIED")
        self.assertIsNone(engine.get("movement_assessment"))
        self.assertIsNone(engine.get("decomposition"))
        self.assertEqual(engine.get("correlational_candidates") or [], [])
        self.assertNotIn("confidence_profile", engine)
        self.assertIsNone(engine.get("driver_analysis"))
        self.assertNotIn("actual_value", json.dumps(engine.get("movement_assessment")))
        transparency = engine["processing_transparency"]
        self.assertEqual(len(transparency["stages"]), 1)
        blocked_stage = transparency["stages"][0]
        self.assertEqual(blocked_stage["stage_id"], "scope_contract_validation")
        self.assertEqual(blocked_stage["execution_status"], "BLOCKED")
        self.assertEqual(blocked_stage["method_category"], "BUSINESS_RULE")
        self.assertFalse(blocked_stage["quantitative_truth"])
        self.assertEqual(blocked_stage["evidence_refs"], [])
        self.assertNotIn("source_evidence", json.dumps(transparency))
        with self.assertRaises(HTTPException) as mismatched:
            api_demo_scenario_execute("unauthorized-scope", type("Req", (), {"user_id": "demo-cfo"})())
        self.assertEqual(mismatched.exception.status_code, 403)
        self.assertIsInstance(mismatched.exception.detail, str)

    def test_category_restricted_scenario_is_denied(self):
        # F-S4 (plan §1.9): category_manager_north_electronics is authorized
        # for North, but only the Electronics category; North/Home must be
        # denied even though the region matches.
        with self.assertRaises(HTTPException) as context:
            api_demo_scenario_execute(
                "category-restricted-scope",
                type("Req", (), {"user_id": "demo-category-manager-north-electronics"})(),
            )
        self.assertEqual(context.exception.status_code, 403)
        detail = context.exception.detail
        self.assertEqual(detail["observed_broad_outcome"], "ACCESS_DENIED")
        self.assertEqual(detail["engine_result"]["verdict"], "ACCESS_DENIED")

    def test_scenario_requires_explicit_known_governed_identity(self):
        for user_id, expected_status in ((None, 401), ("unknown-user", 401), ("demo-regional-north", 403)):
            with self.subTest(user_id=user_id):
                with self.assertRaises(HTTPException) as denied:
                    api_demo_scenario_execute(
                        "material-multi-driver",
                        type("Req", (), {"user_id": user_id})(),
                    )
                self.assertEqual(denied.exception.status_code, expected_status)

        with self.assertRaises(HTTPException) as missing_via_diagnosis:
            api_diagnoses(DiagnosisRequest(scenario_id="material-multi-driver"))
        self.assertEqual(missing_via_diagnosis.exception.status_code, 401)

    def test_non_material_scenario_is_not_escalated(self):
        payload = execute_demo_scenario("non-material-baseline", "demo-cfo")
        result = payload["engine_result"]
        self.assertEqual(payload["observed_broad_outcome"], "NO_MATERIAL_MOVEMENT")
        self.assertEqual(result["verdict"], "NO_MATERIAL_MOVEMENT")
        self.assertFalse((result.get("movement_assessment") or {}).get("is_material"))
        self.assertEqual(result["confidence_profile"]["movement"]["status"], "LOW")
        # Stage 3: attribution still runs on a non-material movement, but is
        # labelled EXPLORATORY_NON_MATERIAL, not ASSESSED (plan Stage 3, step C)
        # -- "not escalated" means no driver is presented as an explanation,
        # which the narrative/claim_type layer enforces separately.
        self.assertEqual(result["driver_analysis"]["status"], "EXPLORATORY_NON_MATERIAL")
        self.assertEqual(result["driver_analysis"]["candidate_count"], result["driver_analysis"]["ranked_count"] + result["driver_analysis"]["excluded_count"])

    def test_diagnoses_endpoint_accepts_scenario_id(self):
        response = api_diagnoses(DiagnosisRequest(scenario_id="non-material-baseline", user_id="demo-cfo"))
        self.assertEqual(response["observed_broad_outcome"], "NO_MATERIAL_MOVEMENT")
        self.assertEqual(response["resolved_scope"]["target_date"], "2023-05-22")

    def test_scenario_id_does_not_bypass_identity(self):
        with self.assertRaises(HTTPException) as context:
            api_diagnoses(DiagnosisRequest(scenario_id="material-multi-driver", user_id="unknown-user"))
        self.assertEqual(context.exception.status_code, 401)

    def test_contract_routes_authorize_and_compare_saved_snapshot(self):
        current = api_kpi_contract("conversion_rate", user_id="demo-cfo")
        self.assertEqual(current["calculation"]["operator"], "RATIO_OF_SUMS")
        with self.assertRaises(HTTPException) as unknown_contract:
            api_kpi_contract("unregistered_kpi", user_id="demo-cfo")
        self.assertEqual(unknown_contract.exception.status_code, 404)
        with self.assertRaises(HTTPException) as unknown_identity:
            api_kpi_contract("orders", user_id="unknown-user")
        self.assertEqual(unknown_identity.exception.status_code, 401)
        with self.assertRaises(HTTPException) as denied_scope:
            api_kpi_contract("orders", user_id="demo-regional-north")
        self.assertEqual(denied_scope.exception.status_code, 403)

        run_id = "run-contract-route-snapshot"
        run = {
            "run_id": run_id,
            "kpi_id": "orders",
            "target_date": "2023-07-24",
            "as_of": "2023-07-25T12:00:00+00:00",
            "persona": "CFO",
            "verdict": "NO_MATERIAL_MOVEMENT",
            "contract_version": 0,
            "contract_hash": "historical-contract-hash",
            "contract_snapshot": {
                **current,
                "identity": {**current["identity"], "kpi_id": "orders", "version": 0, "definition": "Saved historical definition"},
                "governance": {**current["governance"], "contract_hash": "historical-contract-hash"},
            },
        }
        backend_storage.save_diagnosis_run(
            run,
            scope={"region": "North", "category": "Electronics"},
            access_context={"role": "CFO", "authorized": True},
        )
        historical = api_diagnosis_contract(run_id, user_id="demo-cfo")
        self.assertEqual(historical["contract_snapshot"]["identity"]["definition"], "Saved historical definition")
        self.assertTrue(historical["comparison"]["changed_since_run"])
        with self.assertRaises(HTTPException) as unauthorized_run:
            api_diagnosis_contract(run_id, user_id="demo-marketing")
        self.assertEqual(unauthorized_run.exception.status_code, 404)
        with self.assertRaises(HTTPException) as missing_run:
            api_diagnosis_contract("missing-contract-run", user_id="demo-cfo")
        self.assertEqual(missing_run.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
