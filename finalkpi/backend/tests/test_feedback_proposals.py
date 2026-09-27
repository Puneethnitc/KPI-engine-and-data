import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from backend import storage
from backend.app import (
    ActionTaken,
    AnalystIssueCategory,
    BusinessRating,
    BusinessReason,
    FeedbackMode,
    FeedbackSubmissionRequest,
    FeedbackTargetType,
    ImprovementProposalCreateRequest,
    ImprovementProposalEventRequest,
    ImprovementProposalEventType,
    ImprovementProposalType,
    api_feedback,
    api_feedback_aggregations,
    api_feedback_list,
    api_improvement_proposal_create,
    api_improvement_proposal_event,
    api_improvement_proposal_get,
    api_improvement_proposal_list,
)
from backend.feedback_learning import aggregate_feedback_records


class FeedbackProposalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(storage, "DB_PATH", Path(self.directory.name) / "proposals.sqlite3")
        self.db_patch.start()
        storage.initialize_db()
        self.base_result = {
            "kpi_id": "orders",
            "target_date": "2023-07-24",
            "as_of": "2023-07-25T12:00:00+00:00",
            "persona": "CFO",
            "verdict": "MATERIAL_CAUSE_UNVERIFIED",
            "movement_assessment": {"actual_value": 12, "expected_value": 10, "delta": 2, "is_material": True},
            "reconciliation_verdict": {"status": "AGREED"},
            "driver_analysis": {"ranked_drivers": [{"driver_id": "checkout_latency"}], "excluded_drivers": []},
            "correlational_candidates": [{"driver_id": "checkout_latency"}],
            "decomposition": {"total_delta": 2, "volume_effect": 1},
            "confidence_profile": {"overall": {"status": "MODERATE"}},
            "narrative_claims": [{"text": "Traffic was associated.", "claim_type": "CORRELATIONAL"}],
            "decision_cards": [{"action_id": "action-1", "recommendation": "Review traffic."}],
            "contract_version": "contract-v3",
            "contract_hash": "contract-hash-v3",
            "policy_version": "policy-v2",
            "policy_hash": "policy-hash-v2",
            "source_data_version": "source-v5",
            "source_snapshot_id": "snapshot-5",
            "source_snapshot_hash": "snapshot-hash-5",
        }
        self.scope = {"region": "North", "category": "Electronics"}
        self.save_run("run-proposal-1")

    def tearDown(self):
        self.db_patch.stop()
        self.directory.cleanup()

    def save_run(self, run_id, *, kpi_id="orders", scope=None, contract_version="contract-v3", persona="CFO"):
        result = {
            **copy.deepcopy(self.base_result),
            "run_id": run_id,
            "kpi_id": kpi_id,
            "persona": persona,
            "contract_version": contract_version,
            "contract_hash": f"hash-{contract_version}",
        }
        storage.save_diagnosis_run(result, scope=scope or self.scope, access_context={"authorized": True})
        return storage.get_run(run_id)

    def business_feedback(self, *, run_id="run-proposal-1", user_id="demo-cfo", rating=BusinessRating.USEFUL, comment="Useful note."):
        request = FeedbackSubmissionRequest(
            mode=FeedbackMode.BUSINESS_FEEDBACK,
            run_id=run_id,
            user_id=user_id,
            target_type=FeedbackTargetType.MOVEMENT,
            target_id="delta",
            rating=rating,
            reason_code=BusinessReason.ACTIONABLE,
            comment=comment,
            action_taken=ActionTaken.NO,
        )
        return api_feedback(request)

    def analyst_feedback(self, *, run_id="run-proposal-1", user_id="demo-cfo", issue=AnalystIssueCategory.DRIVER, target_type=FeedbackTargetType.DRIVER, target_id="checkout_latency", proposed="Keep this as an association only."):
        request = FeedbackSubmissionRequest(
            mode=FeedbackMode.ANALYST_CORRECTION,
            run_id=run_id,
            user_id=user_id,
            target_type=target_type,
            target_id=target_id,
            issue_category=issue,
            correction_type="REINTERPRET",
            proposed_correction=proposed,
            rationale="The evidence does not establish contribution.",
            evidence_refs=["driver_analysis.ranked_drivers"],
        )
        return api_feedback(request)

    def proposal_request(self, **overrides):
        values = {
            "user_id": "demo-cfo",
            "feedback_ids": [],
            "proposal_type": ImprovementProposalType.DRIVER_CONFIGURATION_CHANGE,
            "title": "Clarify driver interpretation",
            "rationale": "Review the wording against the saved association evidence.",
            "proposed_change": None,
            "expected_improvement": "Reduce unsupported causal interpretation.",
            "affected_evaluation_cases": ["scenario-material-1"],
            "rollback_plan": "Keep the current version if regression results worsen.",
        }
        values.update(overrides)
        return ImprovementProposalCreateRequest(**values)

    def test_aggregation_key_summary_and_order_are_deterministic_and_comment_free(self):
        first = {
            "feedback_id": "fb-b", "state": "CAPTURED", "mode": "BUSINESS_FEEDBACK",
            "kpi_id": "orders", "scope": self.scope, "persona": "CFO",
            "target_type": "MOVEMENT", "target_id": "movement_assessment.delta",
            "versions": {"contract_version": "v1", "contract_hash": "h1", "policy_version": "p1", "policy_hash": "ph1", "source_data_version": "s1", "source_snapshot_id": "ss1", "source_snapshot_hash": "sh1"},
            "reason_code": "ACTIONABLE", "issue_category": None, "correction_type": None,
            "rating": "USEFUL", "action_taken": "YES", "user_id": "demo-cfo",
            "run_id": "run-2", "created_at": "2026-01-02T00:00:00+00:00", "comment": "Do not expose me",
        }
        second = {**first, "feedback_id": "fb-a", "rating": "NOT_USEFUL", "action_taken": "NO", "user_id": "demo-cfo-2", "run_id": "run-1", "created_at": "2026-01-01T00:00:00+00:00", "comment": "Private comment"}
        forward = aggregate_feedback_records([first, second])
        reverse = aggregate_feedback_records([second, first])
        self.assertEqual(forward, reverse)
        summary = forward[0]
        self.assertEqual(summary["source_feedback_ids"], ["fb-a", "fb-b"])
        self.assertEqual(summary["affected_run_ids"], ["run-1", "run-2"])
        self.assertEqual(summary["feedback_count"], 2)
        self.assertEqual(summary["business_feedback_count"], 2)
        self.assertEqual(summary["analyst_correction_count"], 0)
        self.assertEqual(summary["useful_count"], 1)
        self.assertEqual(summary["not_useful_count"], 1)
        self.assertEqual(summary["reason_counts"], {"ACTIONABLE": 2})
        self.assertEqual(summary["action_taken_counts"], {"NO": 1, "YES": 1})
        self.assertEqual(summary["unique_authorized_submitter_count"], 2)
        self.assertEqual(summary["earliest_created_at"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(summary["latest_created_at"], "2026-01-02T00:00:00+00:00")
        self.assertNotIn("comment", summary)
        self.assertNotIn("Private comment", json.dumps(summary))
        self.assertEqual(summary["current_artifact_versions"]["source_snapshots"], [{"hash": "sh1", "id": "ss1"}])
        self.assertEqual([option["proposal_type"] for option in summary["proposal_type_options"]], ["REVIEW_REQUIRED", "EVALUATION_CASE_ADDITION"])

    def test_aggregation_does_not_cross_kpi_scope_target_or_version_boundaries(self):
        base = {
            "feedback_id": "fb-base", "state": "CAPTURED", "mode": "BUSINESS_FEEDBACK",
            "kpi_id": "orders", "scope": self.scope, "persona": "CFO", "target_type": "MOVEMENT",
            "target_id": "delta", "versions": {"contract_version": "v1", "contract_hash": "h1", "policy_version": "p1", "policy_hash": "ph1"},
            "reason_code": "UNCLEAR", "issue_category": None, "correction_type": None,
            "rating": "USEFUL", "action_taken": "UNKNOWN", "user_id": "demo-cfo", "run_id": "run-1", "created_at": "2026-01-01T00:00:00+00:00",
        }
        variants = [
            {**base, "feedback_id": "fb-kpi", "kpi_id": "revenue"},
            {**base, "feedback_id": "fb-scope", "scope": {"region": "South", "category": "Electronics"}},
            {**base, "feedback_id": "fb-target", "target_type": "ACTION", "target_id": "action-1"},
            {**base, "feedback_id": "fb-contract", "versions": {**base["versions"], "contract_version": "v2"}},
            {**base, "feedback_id": "fb-policy", "versions": {**base["versions"], "policy_hash": "p-hash-2"}},
        ]
        aggregates = aggregate_feedback_records([base, *variants])
        self.assertEqual(len(aggregates), 6)
        self.assertEqual(len({item["aggregation_key"] for item in aggregates}), 6)

    def test_rejected_feedback_is_excluded_from_aggregation(self):
        feedback = self.business_feedback()
        from backend.app import FeedbackEventRequest, FeedbackEventType, api_feedback_review
        api_feedback_review(feedback["feedback_id"], FeedbackEventRequest(event_type=FeedbackEventType.REJECTED), user_id="demo-cfo")
        response = api_feedback_aggregations(user_id="demo-cfo")
        self.assertNotIn(feedback["feedback_id"], {fid for agg in response["items"] for fid in agg["source_feedback_ids"]})

    def test_api_aggregation_filters_scope_before_counting(self):
        north = self.save_run("run-north-regional", persona="regional_manager_north")
        south = self.save_run("run-south-regional", persona="regional_manager_north", scope={"region": "South", "category": "Electronics"})
        for run in (north, south):
            storage.create_feedback_submission(
                payload={"mode": "BUSINESS_FEEDBACK", "target_type": "RUN", "target_id": run["run_id"], "rating": "USEFUL", "reason_code": "OTHER"},
                run=run, user_id="demo-regional-north", persona="regional_manager_north",
            )
        response = api_feedback_aggregations(user_id="demo-regional-north")
        self.assertEqual(len(response["items"]), 1)
        self.assertEqual(response["items"][0]["scope"]["region"], "North")
        self.assertEqual(response["items"][0]["feedback_count"], 1)

    def test_aggregation_endpoint_does_not_return_raw_comments(self):
        self.business_feedback(comment="A raw confidential comment")
        response = api_feedback_aggregations(user_id="demo-cfo")
        self.assertNotIn("comment", response["items"][0])
        self.assertNotIn("A raw confidential comment", json.dumps(response))

    def test_analyst_proposal_uses_matching_structured_correction_and_server_version(self):
        feedback = self.analyst_feedback()
        request = self.proposal_request(
            feedback_ids=[feedback["feedback_id"]],
            proposed_change={
                "source_feedback_id": feedback["feedback_id"],
                "driver_id": "checkout_latency",
                "proposed_configuration": feedback["proposed_correction"],
            },
        )
        proposal = api_improvement_proposal_create(request)
        self.assertEqual(proposal["proposal_type"], "DRIVER_CONFIGURATION_CHANGE")
        self.assertEqual(proposal["target_artifact_type"], "DRIVER_CONFIGURATION")
        self.assertEqual(proposal["before_version"], "contract-v3")
        self.assertEqual(proposal["before_version_hash"], "hash-contract-v3")
        self.assertEqual(proposal["source_feedback_ids"], [feedback["feedback_id"]])
        self.assertEqual(proposal["source_run_ids"], ["run-proposal-1"])
        self.assertEqual(proposal["state"], "PROPOSED")
        self.assertEqual(proposal["events"][0]["from_state"], None)
        self.assertEqual(proposal["events"][0]["to_state"], "PROPOSED")
        self.assertEqual(proposal["events"][0]["actor_user_id"], "demo-cfo")
        self.assertEqual(proposal["message"], "Improvement proposed")
        self.assertEqual(proposal["supporting_evidence_refs"], [{"feedback_id": feedback["feedback_id"], "evidence_refs": ["driver_analysis.ranked_drivers"]}])
        self.assertFalse(proposal["applied"])
        self.assertFalse(proposal["verified"])

    def test_business_feedback_produces_review_only_or_evaluation_proposal(self):
        first = self.business_feedback(comment="Do not copy this into the proposal.")
        second = self.business_feedback(comment="Second private note.", rating=BusinessRating.NOT_USEFUL)
        review = api_improvement_proposal_create(self.proposal_request(
            feedback_ids=[first["feedback_id"], second["feedback_id"]],
            proposal_type=ImprovementProposalType.REVIEW_REQUIRED,
            proposed_change=None,
        ))
        self.assertEqual(review["target_artifact_type"], "REVIEW_ONLY")
        self.assertEqual(review["proposed_change"], {"review_question": "Review recurring feedback; no production change is proposed."})
        self.assertNotIn("Do not copy", json.dumps(review))
        self.assertNotIn("Second private note", json.dumps(review))
        with self.assertRaises(HTTPException) as fake_fix:
            api_improvement_proposal_create(self.proposal_request(
                feedback_ids=[first["feedback_id"], second["feedback_id"]],
                proposal_type=ImprovementProposalType.BUSINESS_RULE_CHANGE,
                proposed_change={"source_feedback_id": first["feedback_id"], "rule_target": "movement", "proposed_rule": "lower threshold"},
            ))
        self.assertEqual(fake_fix.exception.status_code, 422)

        third = self.business_feedback(comment="A separate repeated observation.")
        fourth = self.business_feedback(comment="Another distinct observation.")
        evaluation = api_improvement_proposal_create(self.proposal_request(
            feedback_ids=[third["feedback_id"], fourth["feedback_id"]],
            proposal_type=ImprovementProposalType.EVALUATION_CASE_ADDITION,
            proposed_change={"case_description": "Repeated unclear movement output", "expected_outcome": "ABSTAIN"},
        ))
        self.assertEqual(evaluation["target_artifact_type"], "EVALUATION_CASE")

    def test_incompatible_feedback_selection_and_issue_category_mismatch_are_rejected(self):
        correction = self.analyst_feedback()
        self.save_run("run-contract-v4", contract_version="contract-v4")
        other = self.analyst_feedback(run_id="run-contract-v4")
        with self.assertRaises(HTTPException) as incompatible:
            api_improvement_proposal_create(self.proposal_request(
                feedback_ids=[correction["feedback_id"], other["feedback_id"]],
                proposed_change={"source_feedback_id": correction["feedback_id"], "driver_id": "checkout_latency", "proposed_configuration": correction["proposed_correction"]},
            ))
        self.assertEqual(incompatible.exception.status_code, 422)

        with self.assertRaises(HTTPException) as mismatch:
            api_improvement_proposal_create(self.proposal_request(
                feedback_ids=[correction["feedback_id"]],
                proposal_type=ImprovementProposalType.KPI_CONTRACT_CHANGE,
                proposed_change={"source_feedback_id": correction["feedback_id"], "contract_field": "drivers", "proposed_value": correction["proposed_correction"]},
            ))
        self.assertEqual(mismatch.exception.status_code, 422)

    def test_invalid_proposed_change_schema_or_content_is_rejected(self):
        feedback = self.analyst_feedback()
        with self.assertRaises(HTTPException) as arbitrary:
            api_improvement_proposal_create(self.proposal_request(
                feedback_ids=[feedback["feedback_id"]],
                proposed_change={"script": "run this", "source_feedback_id": feedback["feedback_id"]},
            ))
        self.assertEqual(arbitrary.exception.status_code, 422)
        with self.assertRaises(HTTPException) as changed_value:
            api_improvement_proposal_create(self.proposal_request(
                feedback_ids=[feedback["feedback_id"]],
                proposed_change={"source_feedback_id": feedback["feedback_id"], "driver_id": "checkout_latency", "proposed_configuration": "invented configuration"},
            ))
        self.assertEqual(changed_value.exception.status_code, 422)

    def test_aggregation_key_proposal_is_idempotent_and_feedback_cannot_support_another(self):
        feedback = self.analyst_feedback()
        aggregation = api_feedback_aggregations(user_id="demo-cfo")["items"][0]
        request = self.proposal_request(
            aggregation_key=aggregation["aggregation_key"],
            proposed_change={"source_feedback_id": feedback["feedback_id"], "driver_id": "checkout_latency", "proposed_configuration": feedback["proposed_correction"]},
        )
        first = api_improvement_proposal_create(request)
        replay = api_improvement_proposal_create(request)
        self.assertEqual(replay["proposal_id"], first["proposal_id"])
        self.assertTrue(replay["idempotent_replay"])

        with self.assertRaises(HTTPException) as linked:
            api_improvement_proposal_create(self.proposal_request(
                feedback_ids=[feedback["feedback_id"]],
                proposal_type=ImprovementProposalType.EVALUATION_CASE_ADDITION,
                proposed_change={"case_description": "Capture the issue", "expected_outcome": "ABSTAIN"},
            ))
        self.assertEqual(linked.exception.status_code, 409)

    def test_proposal_acceptance_appends_feedback_acceptance_but_never_applies(self):
        feedback = self.analyst_feedback()
        proposal = api_improvement_proposal_create(self.proposal_request(
            feedback_ids=[feedback["feedback_id"]],
            proposed_change={"source_feedback_id": feedback["feedback_id"], "driver_id": "checkout_latency", "proposed_configuration": feedback["proposed_correction"]},
        ))
        accepted = api_improvement_proposal_event(
            proposal["proposal_id"],
            ImprovementProposalEventRequest(event_type=ImprovementProposalEventType.ACCEPTED, reason="Approved for a later change proposal."),
            user_id="demo-cfo",
        )
        self.assertEqual(accepted["state"], "ACCEPTED")
        self.assertEqual(accepted["message"], "Proposal accepted; not yet applied or verified")
        self.assertEqual(accepted["application_status"], "Not yet applied")
        self.assertEqual(accepted["verification_status"], "Not yet verified")
        self.assertFalse(accepted["applied"])
        self.assertFalse(accepted["verified"])
        saved_feedback = storage.get_feedback_submission(feedback["feedback_id"])
        self.assertEqual(saved_feedback["state"], "ACCEPTED")
        self.assertEqual(saved_feedback["events"][-1]["event_type"], "ACCEPTED")
        self.assertEqual(saved_feedback["events"][-1]["actor_user_id"], "demo-cfo")
        with self.assertRaises(ValidationError):
            ImprovementProposalEventRequest(event_type="APPLIED")
        with self.assertRaises(ValidationError):
            ImprovementProposalEventRequest(event_type="VERIFIED")

    def test_proposal_rejection_appends_linked_feedback_rejection(self):
        feedback = self.analyst_feedback()
        proposal = api_improvement_proposal_create(self.proposal_request(
            feedback_ids=[feedback["feedback_id"]],
            proposed_change={"source_feedback_id": feedback["feedback_id"], "driver_id": "checkout_latency", "proposed_configuration": feedback["proposed_correction"]},
        ))
        rejected = api_improvement_proposal_event(
            proposal["proposal_id"],
            ImprovementProposalEventRequest(event_type=ImprovementProposalEventType.REJECTED, reason="Not supported by the reviewed evidence."),
            user_id="demo-cfo",
        )
        self.assertEqual(rejected["state"], "REJECTED")
        self.assertEqual(rejected["events"][-1]["from_state"], "PROPOSED")
        self.assertEqual(storage.get_feedback_submission(feedback["feedback_id"])["state"], "REJECTED")

        with self.assertRaises(HTTPException) as no_longer_eligible:
            api_improvement_proposal_create(self.proposal_request(
                feedback_ids=[feedback["feedback_id"]],
                proposal_type=ImprovementProposalType.EVALUATION_CASE_ADDITION,
                proposed_change={"case_description": "Verify this rejected proposal's assumption", "expected_outcome": "ABSTAIN"},
            ))
        self.assertEqual(no_longer_eligible.exception.status_code, 409)

    def test_nonreviewer_and_unauthorized_proposal_reads_are_generic(self):
        feedback = self.analyst_feedback()
        with self.assertRaises(HTTPException) as cannot_create:
            api_improvement_proposal_create(self.proposal_request(user_id="demo-marketing", feedback_ids=[feedback["feedback_id"]]))
        self.assertEqual(cannot_create.exception.status_code, 404)
        proposal = api_improvement_proposal_create(self.proposal_request(
            feedback_ids=[feedback["feedback_id"]],
            proposed_change={"source_feedback_id": feedback["feedback_id"], "driver_id": "checkout_latency", "proposed_configuration": feedback["proposed_correction"]},
        ))
        with self.assertRaises(HTTPException) as hidden:
            api_improvement_proposal_get(proposal["proposal_id"], user_id="demo-marketing")
        with self.assertRaises(HTTPException) as missing:
            api_improvement_proposal_get("proposal-does-not-exist", user_id="demo-cfo")
        self.assertEqual(hidden.exception.status_code, 404)
        self.assertEqual(hidden.exception.detail, missing.exception.detail)
        for event_type in (ImprovementProposalEventType.ACCEPTED, ImprovementProposalEventType.REJECTED):
            with self.assertRaises(HTTPException) as cannot_review:
                api_improvement_proposal_event(proposal["proposal_id"], ImprovementProposalEventRequest(event_type=event_type), user_id="demo-marketing")
            self.assertEqual(cannot_review.exception.status_code, 404)

    def test_proposal_list_and_detail_have_summary_but_no_raw_feedback_comments(self):
        feedback = self.analyst_feedback()
        proposal = api_improvement_proposal_create(self.proposal_request(
            feedback_ids=[feedback["feedback_id"]],
            proposed_change={"source_feedback_id": feedback["feedback_id"], "driver_id": "checkout_latency", "proposed_configuration": feedback["proposed_correction"]},
        ))
        listing = api_improvement_proposal_list(user_id="demo-cfo")
        self.assertEqual(listing["items"][0]["proposal_id"], proposal["proposal_id"])
        self.assertNotIn("comment", listing["items"][0])
        detail = api_improvement_proposal_get(proposal["proposal_id"], user_id="demo-cfo")
        self.assertEqual(detail["source_feedback_ids"], [feedback["feedback_id"]])
        self.assertEqual(detail["supporting_feedback_summary"]["analyst_correction_count"], 1)
        self.assertNotIn("comment", detail)
        self.assertNotIn("rationale", detail["supporting_feedback_summary"])

    def test_sqlite_proposal_links_and_events_are_immutable_and_run_is_unchanged(self):
        before = storage.get_run("run-proposal-1")["result"]
        feedback = self.analyst_feedback()
        proposal = api_improvement_proposal_create(self.proposal_request(
            feedback_ids=[feedback["feedback_id"]],
            proposed_change={"source_feedback_id": feedback["feedback_id"], "driver_id": "checkout_latency", "proposed_configuration": feedback["proposed_correction"]},
        ))
        connection = storage._connect()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE improvement_proposals SET kpi_id='revenue' WHERE proposal_id=?", (proposal["proposal_id"],))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM improvement_proposal_feedback WHERE proposal_id=?", (proposal["proposal_id"],))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE improvement_proposal_events SET to_state='ACCEPTED' WHERE proposal_id=?", (proposal["proposal_id"],))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM improvement_proposal_events WHERE proposal_id=?", (proposal["proposal_id"],))
        finally:
            connection.rollback()
            connection.close()
        self.assertEqual(storage.get_run("run-proposal-1")["result"], before)

    def test_acceptance_never_mutates_saved_diagnosis(self):
        before = storage.get_run("run-proposal-1")["result"]
        feedback = self.analyst_feedback()
        proposal = api_improvement_proposal_create(self.proposal_request(
            feedback_ids=[feedback["feedback_id"]],
            proposed_change={"source_feedback_id": feedback["feedback_id"], "driver_id": "checkout_latency", "proposed_configuration": feedback["proposed_correction"]},
        ))
        api_improvement_proposal_event(
            proposal["proposal_id"],
            ImprovementProposalEventRequest(event_type=ImprovementProposalEventType.ACCEPTED),
            user_id="demo-cfo",
        )
        self.assertEqual(storage.get_run("run-proposal-1")["result"], before)


if __name__ == "__main__":
    unittest.main()