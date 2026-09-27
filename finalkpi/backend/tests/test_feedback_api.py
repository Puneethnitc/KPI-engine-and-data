import copy
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
    FeedbackEventRequest,
    FeedbackEventType,
    FeedbackMode,
    FeedbackSubmissionRequest,
    FeedbackTargetType,
    app,
    api_feedback,
    api_feedback_get,
    api_feedback_list,
    api_feedback_review,
)
from backend.service import get_feedback


class FeedbackApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(storage, "DB_PATH", Path(self.directory.name) / "feedback.sqlite3")
        self.db_patch.start()
        storage.initialize_db()
        self.result = {
            "run_id": "run-feedback-cfo",
            "kpi_id": "orders",
            "target_date": "2023-07-24",
            "as_of": "2023-07-25T12:00:00+00:00",
            "persona": "CFO",
            "verdict": "MATERIAL_CAUSE_UNVERIFIED",
            "movement_assessment": {"actual_value": 12, "expected_value": 10, "delta": 2, "is_material": True},
            "reconciliation_verdict": {"status": "AGREED"},
            "driver_analysis": {"ranked_drivers": [{"driver_id": "traffic_drop"}], "excluded_drivers": []},
            "correlational_candidates": [{"driver_id": "traffic_drop"}],
            "decomposition": {"total_delta": 2, "volume_effect": 1},
            "decomposition_status": "IDENTITY_HELD",
            "confidence_profile": {"overall": {"status": "MODERATE"}},
            "narrative_claims": [{"text": "Traffic was associated with the movement.", "claim_type": "CORRELATIONAL"}],
            "decision_cards": [{"action_id": "action-1", "recommendation": "Review the traffic series."}],
            "contract_version": "3",
            "contract_hash": "contract-hash-3",
            "policy_version": "rules-2",
            "policy_hash": "policy-hash-2",
            "source_data_version": "source-version-7",
            "source_snapshot_id": "snapshot-7",
            "source_snapshot_hash": "snapshot-hash-7",
        }
        self.scope = {"region": "North", "category": "Electronics"}
        storage.save_diagnosis_run(
            copy.deepcopy(self.result),
            scope=self.scope,
            access_context={"authorized": True},
        )

    def tearDown(self):
        self.db_patch.stop()
        self.directory.cleanup()

    def business_request(self, **overrides):
        values = {
            "mode": FeedbackMode.BUSINESS_FEEDBACK,
            "run_id": self.result["run_id"],
            "user_id": "demo-cfo",
            "target_type": FeedbackTargetType.MOVEMENT,
            "target_id": "delta",
            "rating": BusinessRating.USEFUL,
            "reason_code": BusinessReason.ACTIONABLE,
            "comment": " This is useful. ",
            "action_taken": ActionTaken.NO,
            "outcome_observation": "",
        }
        values.update(overrides)
        return FeedbackSubmissionRequest(**values)

    def analyst_request(self, **overrides):
        values = {
            "mode": FeedbackMode.ANALYST_CORRECTION,
            "run_id": self.result["run_id"],
            "user_id": "demo-cfo",
            "target_type": FeedbackTargetType.DRIVER,
            "target_id": "traffic_drop",
            "issue_category": AnalystIssueCategory.DRIVER,
            "correction_type": "REINTERPRET",
            "proposed_correction": "Treat as association only.",
            "rationale": "The evidence does not establish contribution.",
            "evidence_refs": ["driver_analysis.ranked_drivers"],
        }
        values.update(overrides)
        return FeedbackSubmissionRequest(**values)

    def test_business_feedback_submission_derives_run_identity_scope_and_versions(self):
        saved_run = storage.get_run(self.result["run_id"])
        feedback = api_feedback(self.business_request())
        self.assertEqual(feedback["mode"], "BUSINESS_FEEDBACK")
        self.assertEqual(feedback["user_id"], "demo-cfo")
        self.assertEqual(feedback["persona"], "CFO")
        self.assertEqual(feedback["kpi_id"], "orders")
        self.assertEqual(feedback["scope"], self.scope)
        self.assertEqual(feedback["versions"]["contract_version"], saved_run["contract_version"])
        self.assertEqual(feedback["versions"]["contract_hash"], saved_run["contract_hash"])
        self.assertEqual(feedback["versions"]["policy_version"], saved_run["policy_version"])
        self.assertEqual(feedback["versions"]["policy_hash"], saved_run["policy_hash"])
        self.assertEqual(feedback["versions"]["source_snapshot_id"], saved_run["source_snapshot_id"])
        self.assertEqual(feedback["comment"], "This is useful.")
        self.assertIsNone(feedback["outcome_observation"])
        self.assertEqual(feedback["state"], "CAPTURED")
        self.assertEqual(feedback["message"], "Feedback captured")
        self.assertEqual(len(feedback["events"]), 1)
        self.assertEqual(feedback["events"][0]["event_type"], "SUBMITTED")
        self.assertIsNone(feedback["events"][0]["from_state"])
        self.assertEqual(feedback["events"][0]["to_state"], "CAPTURED")
        self.assertEqual(feedback["events"][0]["actor_user_id"], "demo-cfo")
        self.assertEqual(feedback["events"][0]["actor_persona"], "CFO")

    def test_analyst_correction_submission_and_evidence_reference_are_typed(self):
        feedback = api_feedback(self.analyst_request())
        self.assertEqual(feedback["mode"], "ANALYST_CORRECTION")
        self.assertEqual(feedback["issue_category"], "DRIVER")
        self.assertEqual(feedback["correction_type"], "REINTERPRET")
        self.assertEqual(feedback["evidence_refs"], ["driver_analysis.ranked_drivers"])

    def test_client_kpi_and_diagnosis_snapshot_are_rejected_as_extra_fields(self):
        values = self.business_request().model_dump()
        with self.assertRaises(ValidationError):
            FeedbackSubmissionRequest(**{**values, "kpi_id": "other-kpi"})
        with self.assertRaises(ValidationError):
            FeedbackSubmissionRequest(**{**values, "original_snapshot": {"movement_assessment": {"delta": 999}}})

    def test_invalid_target_type_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.business_request(target_type="PRIVATE_PATH")

    def test_invalid_target_id_is_rejected(self):
        with self.assertRaises(HTTPException) as error:
            api_feedback(self.business_request(target_id="movement_assessment.secret"))
        self.assertEqual(error.exception.status_code, 422)

    def test_invalid_evidence_reference_is_rejected(self):
        with self.assertRaises(HTTPException) as error:
            api_feedback(self.analyst_request(evidence_refs=["private_source.rows"]))
        self.assertEqual(error.exception.status_code, 422)

    def test_text_fields_are_bounded_and_blank_optional_strings_become_null(self):
        with self.assertRaises(ValidationError):
            self.business_request(comment="x" * 1001)
        with self.assertRaises(ValidationError):
            self.analyst_request(rationale="x" * 2001)
        with self.assertRaises(ValidationError):
            self.analyst_request(proposed_correction="x" * 2001)
        normalized = self.business_request(comment="   ", outcome_observation=" ")
        self.assertIsNone(normalized.comment)
        self.assertIsNone(normalized.outcome_observation)

    def test_non_cfo_cannot_submit_analyst_correction(self):
        run = {**self.result, "run_id": "run-feedback-marketing", "persona": "marketing_manager"}
        storage.save_diagnosis_run(copy.deepcopy(run), scope=self.scope, access_context={"authorized": True})
        request = self.analyst_request(run_id=run["run_id"], user_id="demo-marketing")
        with self.assertRaises(HTTPException) as error:
            api_feedback(request)
        self.assertEqual(error.exception.status_code, 404)

    def test_nonmatching_run_identity_gets_generic_not_found(self):
        request = self.business_request(user_id="demo-marketing")
        with self.assertRaises(HTTPException) as error:
            api_feedback(request)
        self.assertEqual(error.exception.status_code, 404)
        self.assertEqual(error.exception.detail, "Feedback target not found.")

    def test_authorized_captured_to_triaged_to_rejected_appends_immutable_events(self):
        feedback = api_feedback(self.business_request())
        first_event = copy.deepcopy(feedback["events"][0])
        self.assertTrue(any(
            route.path == "/api/feedback/{feedback_id}/events" and "POST" in route.methods
            for route in app.routes
        ))
        triaged = api_feedback_review(
            feedback["feedback_id"],
            FeedbackEventRequest(event_type=FeedbackEventType.TRIAGED, reason="Queued for owner review."),
            user_id="demo-cfo",
        )
        self.assertEqual(triaged["state"], "TRIAGED")
        self.assertEqual(triaged["events"][0], first_event)
        self.assertEqual(triaged["events"][1]["actor_user_id"], "demo-cfo")
        self.assertEqual(triaged["events"][1]["actor_persona"], "CFO")
        rejected = api_feedback_review(
            feedback["feedback_id"],
            FeedbackEventRequest(event_type=FeedbackEventType.REJECTED, reason="Not supported by evidence."),
            user_id="demo-cfo",
        )
        self.assertEqual(rejected["state"], "REJECTED")
        self.assertEqual(len(rejected["events"]), 3)
        self.assertEqual(rejected["events"][0], first_event)
        self.assertEqual([event["to_state"] for event in rejected["events"]], ["CAPTURED", "TRIAGED", "REJECTED"])

    def test_invalid_transition_and_acceptance_are_rejected(self):
        feedback = api_feedback(self.business_request())
        api_feedback_review(feedback["feedback_id"], FeedbackEventRequest(event_type=FeedbackEventType.TRIAGED), user_id="demo-cfo")
        with self.assertRaises(HTTPException) as invalid:
            api_feedback_review(feedback["feedback_id"], FeedbackEventRequest(event_type=FeedbackEventType.TRIAGED), user_id="demo-cfo")
        self.assertEqual(invalid.exception.status_code, 409)
        with self.assertRaises(ValidationError):
            FeedbackEventRequest(event_type="ACCEPTED")
        with self.assertRaises(ValidationError):
            FeedbackEventRequest(event_type="TRIAGED", reviewer="forged-reviewer")

    def test_non_reviewer_cannot_triage_or_reject(self):
        feedback = api_feedback(self.business_request())
        with self.assertRaises(HTTPException) as error:
            api_feedback_review(
                feedback["feedback_id"],
                FeedbackEventRequest(event_type=FeedbackEventType.TRIAGED),
                user_id="demo-marketing",
            )
        self.assertEqual(error.exception.status_code, 404)

    def test_feedback_detail_is_scope_authorized_and_unknown_ids_are_generic(self):
        feedback = api_feedback(self.business_request())
        detail = api_feedback_get(feedback["feedback_id"], user_id="demo-cfo")
        self.assertEqual(detail["feedback_id"], feedback["feedback_id"])
        with self.assertRaises(HTTPException) as denied:
            api_feedback_get(feedback["feedback_id"], user_id="demo-marketing")
        with self.assertRaises(HTTPException) as missing:
            api_feedback_get("fb-does-not-exist", user_id="demo-cfo")
        self.assertEqual(denied.exception.status_code, 404)
        self.assertEqual(missing.exception.status_code, 404)
        self.assertEqual(denied.exception.detail, missing.exception.detail)

    def test_listing_is_owner_filtered_and_scope_safe(self):
        feedback = api_feedback(self.business_request())
        items = api_feedback_list(user_id="demo-marketing")["items"]
        self.assertNotIn(feedback["feedback_id"], {item["feedback_id"] for item in items})

        restricted_run = {**self.result, "run_id": "run-feedback-restricted", "persona": "regional_manager_north"}
        storage.save_diagnosis_run(copy.deepcopy(restricted_run), scope={"region": "South", "category": "Electronics"}, access_context={"authorized": True})
        storage.create_feedback_submission(
            payload={"mode": "BUSINESS_FEEDBACK", "target_type": "RUN", "target_id": restricted_run["run_id"], "rating": "USEFUL"},
            run=storage.get_run(restricted_run["run_id"]),
            user_id="demo-regional-north",
            persona="regional_manager_north",
        )
        regional_items = api_feedback_list(user_id="demo-regional-north")["items"]
        self.assertNotIn("run-feedback-restricted", {item["run_id"] for item in regional_items})

    def test_legacy_feedback_remains_readable_without_new_events(self):
        legacy = storage.save_feedback(
            run_id=self.result["run_id"], user_id="demo-cfo", kpi_id="orders",
            feedback_type="useful", comments="Legacy note.", snapshot={"verdict": self.result["verdict"]},
        )
        detail = api_feedback_get(str(legacy["id"]), user_id="demo-cfo")
        self.assertTrue(detail["legacy"])
        self.assertEqual(detail["comments"], "Legacy note.")
        self.assertEqual(detail["events"], [])

    def test_existing_feedback_table_migrates_and_preserves_legacy_row(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy_path = Path(directory) / "old-feedback.sqlite3"
            connection = sqlite3.connect(legacy_path)
            connection.execute(
                "CREATE TABLE feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, user_id TEXT NOT NULL, kpi_id TEXT NOT NULL, feedback_type TEXT NOT NULL, comments TEXT, created_at TEXT NOT NULL, metadata_json TEXT)"
            )
            connection.execute(
                "INSERT INTO feedback (run_id, user_id, kpi_id, feedback_type, comments, created_at, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("legacy-run", "demo-cfo", "orders", "useful", "Keep this note", "2024-01-01T00:00:00+00:00", "{}"),
            )
            connection.commit()
            connection.close()
            with patch.object(storage, "DB_PATH", legacy_path):
                storage.initialize_db()
                legacy = storage.list_feedback()[0]
                self.assertEqual(legacy["run_id"], "legacy-run")
                self.assertEqual(legacy["comments"], "Keep this note")
                self.assertEqual(legacy["status"], "PENDING_REVIEW")
                connection = sqlite3.connect(legacy_path)
                table_names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                connection.close()
                self.assertIn("feedback_submissions", table_names)
                self.assertIn("feedback_events", table_names)

    def test_existing_diagnosis_result_is_unchanged_by_feedback_and_events(self):
        before = storage.get_run(self.result["run_id"])["result"]
        feedback = api_feedback(self.business_request())
        api_feedback_review(feedback["feedback_id"], FeedbackEventRequest(event_type=FeedbackEventType.TRIAGED), user_id="demo-cfo")
        after = storage.get_run(self.result["run_id"])["result"]
        self.assertEqual(after, before)

    def test_sqlite_rejects_updates_and_deletes_of_submissions_and_events(self):
        feedback = api_feedback(self.business_request())
        connection = storage._connect()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE feedback_submissions SET comment = 'tampered' WHERE feedback_id = ?",
                    (feedback["feedback_id"],),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM feedback_submissions WHERE feedback_id = ?",
                    (feedback["feedback_id"],),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE feedback_events SET to_state = 'REJECTED' WHERE feedback_id = ?",
                    (feedback["feedback_id"],),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM feedback_events WHERE feedback_id = ?",
                    (feedback["feedback_id"],),
                )
        finally:
            connection.rollback()
            connection.close()


if __name__ == "__main__":
    unittest.main()