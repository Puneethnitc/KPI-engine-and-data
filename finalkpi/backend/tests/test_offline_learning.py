import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from backend import storage
from backend.app import (
    ActionTaken,
    AnalystIssueCategory,
    BusinessRating,
    BusinessReason,
    CandidateRollbackRequest,
    FeedbackMode,
    FeedbackEventRequest,
    FeedbackEventType,
    FeedbackSubmissionRequest,
    FeedbackTargetType,
    ImprovementProposalCreateRequest,
    ImprovementProposalEventRequest,
    ImprovementProposalEventType,
    ImprovementProposalType,
    api_apply_improvement_proposal,
    api_evaluate_improvement_proposal,
    api_feedback,
    api_feedback_review,
    api_improvement_proposal_create,
    api_improvement_proposal_event,
    api_proposal_evaluation_get,
    api_rollback_candidate,
    api_candidate_artifact_get,
)
from backend.offline_learning import build_candidate_artifact


ROOT = Path(__file__).resolve().parents[2]


class OfflineLearningTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(storage, "DB_PATH", Path(self.directory.name) / "offline-learning.sqlite3")
        self.db_patch.start()
        storage.initialize_db()
        self.scope = {"region": "North", "category": "Electronics"}
        self.runs = {
            "offline-run-affected": self.save_run("offline-run-affected", "2026-01-10"),
            "offline-run-holdout": self.save_run("offline-run-holdout", "2026-01-11"),
        }

    def tearDown(self):
        self.db_patch.stop()
        self.directory.cleanup()

    def save_run(self, run_id, date):
        result = {
            "run_id": run_id,
            "kpi_id": "orders",
            "target_date": date,
            "as_of": f"{date}T23:59:00+00:00",
            "persona": "CFO",
            "verdict": "MATERIAL_CAUSE_UNVERIFIED",
            "movement_assessment": {
                "status": "OK", "actual_value": 115, "expected_value": 100,
                "delta": 15, "is_material": True,
                "is_statistically_significant": True, "is_business_material": True,
            },
            "reconciliation_verdict": {"status": "AGREED", "gap_pct": 0.2},
            "decomposition": {"total_delta": 15, "volume_effect": 10, "is_identity_held": True},
            "decomposition_status": "IDENTITY_HELD",
            "driver_analysis": {"status": "ASSESSED", "ranked_drivers": [{"driver_id": "checkout_latency", "relationship_type": "ASSOCIATION"}], "excluded_drivers": []},
            "correlational_candidates": [{"driver_id": "checkout_latency", "claim_type": "CORRELATIONAL"}],
            "causal_verdict": "UNTESTABLE",
            "causal_verification": {"verdict": "UNTESTABLE"},
            "confidence": {"status": "INSUFFICIENT"},
            "confidence_profile": {"overall": {"status": "MODERATE"}},
            "decision_cards": [{"action_id": "action-1", "recommendation": "Review the traffic association."}],
            "narrative_claims": [{
                "text": "checkout_latency is a correlational candidate, not an established cause.",
                "evidence_paths": ["correlational_candidates.0.driver_id"],
                "claim_type": "CORRELATIONAL",
            }],
            "narrative": "checkout_latency is a correlational candidate, not an established cause.",
            "grounding_passed": True,
            "contract_version": "3",
            "contract_hash": "contract-hash-3",
            "policy_version": "policy-2",
            "policy_hash": "policy-hash-2",
            "source_data_version": "source-v5",
            "source_snapshot_id": "snapshot-5",
            "source_snapshot_hash": "snapshot-hash-5",
            "engine_version": "engine-test-v1",
        }
        storage.save_diagnosis_run(result, scope=self.scope, access_context={"authorized": True})
        return storage.get_run(run_id)

    def correction(self, *, run_id="offline-run-affected", issue="NARRATIVE", target_type="NARRATIVE_CLAIM", target_id="0", change="This remains an association only, not a cause."):
        return api_feedback(FeedbackSubmissionRequest(
            mode=FeedbackMode.ANALYST_CORRECTION,
            run_id=run_id,
            user_id="demo-cfo",
            target_type=FeedbackTargetType(target_type),
            target_id=target_id,
            issue_category=AnalystIssueCategory(issue),
            correction_type="REINTERPRET",
            proposed_correction=change,
            rationale="The stored evidence supports association language only.",
            evidence_refs=["narrative_claims" if target_type == "NARRATIVE_CLAIM" else "movement_assessment"],
        ))

    def business_feedback(self, *, run_id="offline-run-affected"):
        return api_feedback(FeedbackSubmissionRequest(
            mode=FeedbackMode.BUSINESS_FEEDBACK,
            run_id=run_id,
            user_id="demo-cfo",
            target_type=FeedbackTargetType.MOVEMENT,
            target_id="delta",
            rating=BusinessRating.NOT_USEFUL,
            reason_code=BusinessReason.UNCLEAR,
            action_taken=ActionTaken.NO,
        ))

    def proposal(self, feedback_ids, *, proposal_type="NARRATIVE_TEMPLATE_CHANGE", proposed_change=None, cases=None):
        if proposed_change is None:
            correction = storage.get_feedback_submission(feedback_ids[0])
            proposed_change = {
                "source_feedback_id": feedback_ids[0],
                "template_target": "CORRELATIONAL",
                "proposed_wording": correction["proposed_correction"],
            }
        request = ImprovementProposalCreateRequest(
            user_id="demo-cfo",
            feedback_ids=feedback_ids,
            proposal_type=ImprovementProposalType(proposal_type),
            title="Candidate wording safeguard" if proposal_type == "NARRATIVE_TEMPLATE_CHANGE" else "Candidate evaluation case",
            rationale="Evaluate the proposed change offline against saved governed cases.",
            proposed_change=proposed_change,
            expected_improvement="Preserve evidence boundaries and governed outcomes.",
            affected_evaluation_cases=cases or ["offline-run-affected"],
            rollback_plan="Retire this candidate from evaluation consideration.",
        )
        return api_improvement_proposal_create(request)

    def accept(self, proposal_id):
        return api_improvement_proposal_event(
            proposal_id,
            ImprovementProposalEventRequest(event_type=ImprovementProposalEventType.ACCEPTED),
            user_id="demo-cfo",
        )

    def narrative_candidate_workflow(self):
        feedback = self.correction()
        proposal = self.proposal([feedback["feedback_id"]])
        self.accept(proposal["proposal_id"])
        return feedback, proposal

    def test_only_accepted_proposals_apply_and_unsupported_types_stay_accepted(self):
        feedback = self.correction(issue="DRIVER", target_type="DRIVER", target_id="checkout_latency", change="Keep this driver association-only.")
        proposal = self.proposal([feedback["feedback_id"]], proposal_type="DRIVER_CONFIGURATION_CHANGE", proposed_change={
            "source_feedback_id": feedback["feedback_id"], "driver_id": "checkout_latency", "proposed_configuration": feedback["proposed_correction"],
        })
        with self.assertRaises(HTTPException) as not_accepted:
            api_apply_improvement_proposal(proposal["proposal_id"], user_id="demo-cfo")
        self.assertEqual(not_accepted.exception.status_code, 409)
        self.accept(proposal["proposal_id"])
        unsupported = api_apply_improvement_proposal(proposal["proposal_id"], user_id="demo-cfo")
        self.assertEqual(unsupported["status"], "APPLICATION_NOT_SUPPORTED")
        self.assertEqual(unsupported["proposal_state"], "ACCEPTED")
        self.assertFalse(unsupported["applied"])
        self.assertIsNone(storage.get_candidate_for_proposal(proposal["proposal_id"]))

    def test_candidate_version_hash_are_deterministic_and_live_engine_file_is_unchanged(self):
        _, proposal = self.narrative_candidate_workflow()
        source_runs = [storage.get_run(run_id) for run_id in proposal["source_run_ids"]]
        first = build_candidate_artifact(proposal, source_runs)
        second = build_candidate_artifact(proposal, source_runs)
        self.assertEqual(first, second)
        self.assertEqual(first["candidate_version"], f"approved_narrative_templates_v1-candidate-{proposal['proposal_id'].replace('-', '')[-8:]}")
        self.assertEqual(first["payload_hash"], hashlib.sha256(json.dumps({
            "artifact_type": first["artifact_type"], "kpi_id": first["kpi_id"], "scope": first["scope"],
            "base_version": first["base_version"], "candidate_version": first["candidate_version"],
            "base_payload": first["base_payload"], "validated_change": first["validated_change"],
            "candidate_payload": first["candidate_payload"], "activation_status": "EVALUATION_ONLY",
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest())
        narrative_path = ROOT / "kpi_engine" / "narrative.py"
        before = hashlib.sha256(narrative_path.read_bytes()).hexdigest()
        candidate = api_apply_improvement_proposal(proposal["proposal_id"], user_id="demo-cfo")
        after = hashlib.sha256(narrative_path.read_bytes()).hexdigest()
        self.assertEqual(before, after)
        self.assertEqual(candidate["activation_status"], "EVALUATION_ONLY")
        self.assertFalse(candidate["deployed"])
        self.assertTrue(candidate["evaluation_only"])
        self.assertEqual(candidate["candidate_state"], "APPLIED")

    def test_application_is_idempotent_and_candidate_read_is_authorized(self):
        _, proposal = self.narrative_candidate_workflow()
        first = api_apply_improvement_proposal(proposal["proposal_id"], user_id="demo-cfo")
        replay = api_apply_improvement_proposal(proposal["proposal_id"], user_id="demo-cfo")
        self.assertEqual(first["candidate_artifact_id"], replay["candidate_artifact_id"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertFalse(replay["deployed"])
        with self.assertRaises(HTTPException) as hidden:
            api_candidate_artifact_get(first["candidate_artifact_id"], user_id="demo-marketing")
        self.assertEqual(hidden.exception.status_code, 404)

    def test_failed_candidate_materialization_leaves_no_artifact_or_applied_event(self):
        _, proposal = self.narrative_candidate_workflow()
        with patch("backend.app.build_candidate_artifact", side_effect=ValueError("Candidate rejected by schema")):
            result = api_apply_improvement_proposal(proposal["proposal_id"], user_id="demo-cfo")
        self.assertEqual(result["status"], "APPLICATION_FAILED")
        self.assertFalse(result["applied"])
        self.assertIsNone(storage.get_candidate_for_proposal(proposal["proposal_id"]))
        saved = storage.get_improvement_proposal(proposal["proposal_id"])
        self.assertEqual(saved["state"], "ACCEPTED")

    def test_protected_reference_wording_is_not_materialized(self):
        correction = self.correction(change="Do not expose source_evidence.secret.csv.")
        proposal = self.proposal([correction["feedback_id"]])
        self.accept(proposal["proposal_id"])
        result = api_apply_improvement_proposal(proposal["proposal_id"], user_id="demo-cfo")
        self.assertEqual(result["status"], "APPLICATION_FAILED")
        self.assertFalse(result["applied"])
        self.assertIsNone(storage.get_candidate_for_proposal(proposal["proposal_id"]))

    def test_passing_narrative_evaluation_verifies_and_preserves_quantitative_fields(self):
        feedback, proposal = self.narrative_candidate_workflow()
        saved_before = storage.get_run("offline-run-affected")["result"]
        protected_scope = {**copy.deepcopy(self.runs["offline-run-holdout"]), "run_id": "offline-run-south-protected", "scope": {"region": "South", "category": "Electronics"}}
        protected_scope["result"]["run_id"] = protected_scope["run_id"]
        storage.save_diagnosis_run(protected_scope["result"], scope=protected_scope["scope"], access_context={"authorized": True})
        candidate = api_apply_improvement_proposal(proposal["proposal_id"], user_id="demo-cfo")
        with patch("backend.service._build_pipeline", side_effect=AssertionError("evaluation must not invoke diagnosis or LLM pipeline")):
            evaluation = api_evaluate_improvement_proposal(proposal["proposal_id"], user_id="demo-cfo")
        self.assertEqual(evaluation["final_result"], "VERIFIED")
        self.assertEqual(evaluation["baseline_artifact_version"], candidate["base_version"])
        self.assertEqual(evaluation["candidate_artifact_version"], candidate["candidate_version"])
        self.assertIn("offline-run-affected", evaluation["affected_cases"])
        self.assertIn("offline-run-holdout", evaluation["holdout_cases"])
        self.assertEqual(evaluation["evaluator_method"], "frozen_saved_run_candidate_comparison")
        case = next(item for item in evaluation["case_results"] if item["case_id"] == "offline-run-affected")
        self.assertEqual(case["baseline_result"]["as_of"], case["candidate_result"]["as_of"])
        self.assertNotIn("movement_assessment", case["differences"])
        self.assertNotIn("decision_cards", case["differences"])
        self.assertTrue(case["gate_results"]["quantitative_fields_unchanged"])
        self.assertEqual(evaluation["proposal_id"], proposal["proposal_id"])
        self.assertEqual(evaluation["candidate_artifact_id"], candidate["candidate_artifact_id"])
        self.assertEqual(storage.get_feedback_submission(feedback["feedback_id"])["state"], "ACCEPTED")
        self.assertEqual(storage.get_run("offline-run-affected")["result"], saved_before)
        self.assertNotIn("offline-run-south-protected", evaluation["holdout_cases"])
        current = storage.get_improvement_proposal(proposal["proposal_id"])
        self.assertEqual(current["state"], "VERIFIED")
        self.assertTrue(current["verified"])
        self.assertFalse(current["deployed"])
        self.assertIn(feedback["feedback_id"], current["source_feedback_ids"])

    def test_failed_evaluation_records_exact_gate_failure_and_cannot_verify(self):
        business_a = self.business_feedback()
        business_b = self.business_feedback()
        proposal = self.proposal(
            [business_a["feedback_id"], business_b["feedback_id"]],
            proposal_type="EVALUATION_CASE_ADDITION",
            proposed_change={"case_description": "A mislabeled governed case", "expected_outcome": "ABSTAIN"},
            cases=["offline-run-affected"],
        )
        self.accept(proposal["proposal_id"])
        candidate = api_apply_improvement_proposal(proposal["proposal_id"], user_id="demo-cfo")
        evaluation = api_evaluate_improvement_proposal(proposal["proposal_id"], user_id="demo-cfo")
        self.assertEqual(evaluation["final_result"], "FAILED_VERIFICATION")
        self.assertTrue(any("candidate_case_expected_outcome_matches" in reason for reason in evaluation["failure_reasons"]))
        self.assertEqual(storage.get_improvement_proposal(proposal["proposal_id"])["state"], "FAILED_VERIFICATION")
        self.assertTrue(candidate["applied"])
        self.assertFalse(candidate["deployed"])
        rolled = api_rollback_candidate(proposal["proposal_id"], CandidateRollbackRequest(reason="Failed the expected outcome gate."), user_id="demo-cfo")
        self.assertEqual(rolled["proposal_state"], "ROLLED_BACK")
        self.assertEqual(storage.get_proposal_evaluation(evaluation["evaluation_run_id"])["final_result"], "FAILED_VERIFICATION")

    def test_evaluation_case_addition_passes_when_expected_broad_outcome_matches(self):
        first = self.business_feedback()
        second = self.business_feedback()
        proposal = self.proposal(
            [first["feedback_id"], second["feedback_id"]],
            proposal_type="EVALUATION_CASE_ADDITION",
            proposed_change={"case_description": "Material orders movement case", "expected_outcome": "MATERIAL"},
            cases=["offline-run-affected", "offline-run-holdout"],
        )
        self.accept(proposal["proposal_id"])
        candidate = api_apply_improvement_proposal(proposal["proposal_id"], user_id="demo-cfo")
        self.assertEqual(candidate["artifact_type"], "EVALUATION_CASE")
        evaluation = api_evaluate_improvement_proposal(proposal["proposal_id"], user_id="demo-cfo")
        self.assertEqual(evaluation["final_result"], "VERIFIED")
        self.assertEqual(evaluation["affected_cases"], ["offline-run-affected", "offline-run-holdout"])
        self.assertEqual(evaluation["metrics"]["affected_case_pass_count"], 2)

    def test_authorized_rollback_preserves_evaluation_and_blocks_reverification(self):
        _, proposal = self.narrative_candidate_workflow()
        candidate = api_apply_improvement_proposal(proposal["proposal_id"], user_id="demo-cfo")
        evaluation = api_evaluate_improvement_proposal(proposal["proposal_id"], user_id="demo-cfo")
        rolled = api_rollback_candidate(
            proposal["proposal_id"], CandidateRollbackRequest(reason="Retire from the evaluation workspace."), user_id="demo-cfo"
        )
        self.assertEqual(rolled["proposal_state"], "ROLLED_BACK")
        self.assertEqual(rolled["rollback_status"], "ROLLED_BACK")
        self.assertFalse(rolled["deployed"])
        self.assertEqual(storage.get_proposal_evaluation(evaluation["evaluation_run_id"])["evaluation_run_id"], evaluation["evaluation_run_id"])
        with self.assertRaises(HTTPException) as no_reverify:
            api_evaluate_improvement_proposal(proposal["proposal_id"], user_id="demo-cfo")
        self.assertEqual(no_reverify.exception.status_code, 409)
        self.assertEqual(storage.get_candidate_artifact(candidate["candidate_artifact_id"])["rollback_status"], "ROLLED_BACK")
        repeat_apply = api_apply_improvement_proposal(proposal["proposal_id"], user_id="demo-cfo")
        self.assertEqual(repeat_apply["status"], "ROLLED_BACK")
        self.assertFalse(repeat_apply["deployed"])

    def test_invalid_transitions_and_reviewer_authorization_are_rejected(self):
        _, proposal = self.narrative_candidate_workflow()
        candidate = api_apply_improvement_proposal(proposal["proposal_id"], user_id="demo-cfo")
        with self.assertRaises(HTTPException) as unauthorized_apply:
            api_apply_improvement_proposal(proposal["proposal_id"], user_id="demo-marketing")
        self.assertEqual(unauthorized_apply.exception.status_code, 404)
        with self.assertRaises(HTTPException) as unauthorized_rollback:
            api_rollback_candidate(proposal["proposal_id"], CandidateRollbackRequest(reason="x"), user_id="demo-marketing")
        self.assertEqual(unauthorized_rollback.exception.status_code, 404)
        with self.assertRaises(HTTPException) as rollback_early:
            api_rollback_candidate("proposal-not-applied", CandidateRollbackRequest(reason="x"), user_id="demo-cfo")
        self.assertEqual(rollback_early.exception.status_code, 404)
        self.assertTrue(candidate["evaluation_only"])

    def test_candidate_and_evaluation_rows_are_database_immutable(self):
        _, proposal = self.narrative_candidate_workflow()
        candidate = api_apply_improvement_proposal(proposal["proposal_id"], user_id="demo-cfo")
        evaluation = api_evaluate_improvement_proposal(proposal["proposal_id"], user_id="demo-cfo")
        connection = storage._connect()
        try:
            for statement, parameters in [
                ("UPDATE candidate_artifacts SET kpi_id='revenue' WHERE candidate_artifact_id=?", (candidate["candidate_artifact_id"],)),
                ("DELETE FROM candidate_artifact_events WHERE candidate_artifact_id=?", (candidate["candidate_artifact_id"],)),
                ("UPDATE proposal_evaluation_runs SET final_result='FAILED_VERIFICATION' WHERE evaluation_run_id=?", (evaluation["evaluation_run_id"],)),
                ("DELETE FROM evaluation_case_results WHERE evaluation_run_id=?", (evaluation["evaluation_run_id"],)),
            ]:
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(statement, parameters)
        finally:
            connection.rollback()
            connection.close()

    def test_complete_governed_learning_loop_is_traceable_and_never_deploys(self):
        """Exercise the jury workflow as one trace instead of isolated unit steps."""
        saved_before = copy.deepcopy(storage.get_run("offline-run-affected")["result"])
        narrative_path = ROOT / "kpi_engine" / "narrative.py"
        live_hash_before = hashlib.sha256(narrative_path.read_bytes()).hexdigest()

        feedback = self.correction()
        triaged = api_feedback_review(
            feedback["feedback_id"],
            FeedbackEventRequest(event_type=FeedbackEventType.TRIAGED),
            user_id="demo-cfo",
        )
        self.assertEqual(triaged["state"], "TRIAGED")

        proposal = self.proposal([feedback["feedback_id"]])
        accepted = self.accept(proposal["proposal_id"])
        self.assertEqual(accepted["state"], "ACCEPTED")
        self.assertFalse(accepted["applied"])
        self.assertFalse(accepted["verified"])

        candidate = api_apply_improvement_proposal(proposal["proposal_id"], user_id="demo-cfo")
        self.assertEqual(candidate["candidate_state"], "APPLIED")
        self.assertTrue(candidate["evaluation_only"])
        self.assertFalse(candidate["deployed"])

        evaluation = api_evaluate_improvement_proposal(proposal["proposal_id"], user_id="demo-cfo")
        self.assertEqual(evaluation["final_result"], "VERIFIED")
        self.assertTrue(evaluation["verified"])
        self.assertFalse(evaluation["deployed"])

        persisted_proposal = storage.get_improvement_proposal(proposal["proposal_id"])
        self.assertEqual(persisted_proposal["source_feedback_ids"], [feedback["feedback_id"]])
        self.assertEqual(persisted_proposal["candidate_artifact_id"], candidate["candidate_artifact_id"])
        self.assertIn(evaluation["evaluation_run_id"], persisted_proposal["evaluation_run_ids"])
        self.assertEqual(
            [event["to_state"] for event in persisted_proposal["events"]],
            ["PROPOSED", "ACCEPTED", "APPLIED", "VERIFIED"],
        )

        self.assertEqual(storage.get_run("offline-run-affected")["result"], saved_before)
        self.assertEqual(hashlib.sha256(narrative_path.read_bytes()).hexdigest(), live_hash_before)

        unsupported_feedback = self.correction(
            issue="DRIVER", target_type="DRIVER", target_id="checkout_latency",
            change="Keep this driver association-only.",
        )
        unsupported_proposal = self.proposal(
            [unsupported_feedback["feedback_id"]],
            proposal_type="DRIVER_CONFIGURATION_CHANGE",
            proposed_change={
                "source_feedback_id": unsupported_feedback["feedback_id"],
                "driver_id": "checkout_latency",
                "proposed_configuration": unsupported_feedback["proposed_correction"],
            },
        )
        self.accept(unsupported_proposal["proposal_id"])
        unsupported = api_apply_improvement_proposal(unsupported_proposal["proposal_id"], user_id="demo-cfo")
        self.assertEqual(unsupported["status"], "APPLICATION_NOT_SUPPORTED")
        self.assertIsNone(storage.get_candidate_for_proposal(unsupported_proposal["proposal_id"]))

        with self.assertRaises(HTTPException) as unauthorized:
            api_candidate_artifact_get(candidate["candidate_artifact_id"], user_id="demo-marketing")
        self.assertEqual(unauthorized.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
