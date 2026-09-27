import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from backend import storage
from backend.app import (
    api_conversation,
    api_diagnosis_contract,
    api_diagnosis_run,
    api_evidence,
    api_investigations,
    api_insights,
)
from backend.service import DEMO_IDENTITY_MODE


class RowAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(storage, "DB_PATH", Path(self.directory.name) / "rows.sqlite3")
        self.db_patch.start()
        storage.initialize_db()

    def tearDown(self):
        self.db_patch.stop()
        self.directory.cleanup()

    @staticmethod
    def save_run(run_id, persona, region, day):
        result = {
            "run_id": run_id,
            "kpi_id": "orders",
            "target_date": day,
            "as_of": f"{day}T12:00:00+00:00",
            "persona": persona,
            "verdict": "NO_MATERIAL_MOVEMENT",
            "movement_assessment": {"is_material": False},
            "decision_cards": [],
        }
        storage.save_diagnosis_run(
            result,
            scope={"region": region, "category": "Electronics", "target_date": day},
            access_context={"role": persona, "authorized": True, "identity_mode": DEMO_IDENTITY_MODE},
        )
        return result

    def test_lists_filter_scope_before_totals_and_pagination(self):
        self.save_run("cfo-north", "CFO", "North", "2023-07-01")
        self.save_run("cfo-south", "CFO", "South", "2023-07-02")
        self.save_run("north-manager-north", "regional_manager_north", "North", "2023-07-03")
        self.save_run("north-manager-south", "regional_manager_north", "South", "2023-07-04")

        cfo = api_investigations(user_id="demo-cfo")
        self.assertEqual(cfo["total"], 2)
        self.assertEqual({item["run_id"] for item in cfo["items"]}, {"cfo-north", "cfo-south"})

        regional = api_investigations(user_id="demo-regional-north")
        self.assertEqual(regional["total"], 1)
        self.assertEqual([item["run_id"] for item in regional["items"]], ["north-manager-north"])

        insights = api_insights(user_id="demo-regional-north", limit=1, offset=0)
        self.assertEqual(insights["total"], 1)
        self.assertEqual([item["run_id"] for item in insights["items"]], ["north-manager-north"])
        cfo_page = api_insights(user_id="demo-cfo", limit=1, offset=1)
        self.assertEqual(cfo_page["total"], 2)
        self.assertEqual(len(cfo_page["items"]), 1)

    def test_individual_regional_south_run_is_generic_not_found(self):
        self.save_run("regional-south-hidden", "regional_manager_north", "South", "2023-07-05")
        with self.assertRaises(HTTPException) as hidden:
            api_diagnosis_run("regional-south-hidden", user_id="demo-regional-north")
        self.assertEqual(hidden.exception.status_code, 404)
        self.assertEqual(hidden.exception.detail, "Diagnosis run not found")

    def test_unknown_identity_is_401_for_saved_objects_and_lists(self):
        self.save_run("identity-check-run", "CFO", "North", "2023-07-06")
        checks = (
            lambda: api_diagnosis_run("identity-check-run", user_id="unknown-user"),
            lambda: api_evidence("identity-check-run", user_id="unknown-user"),
            lambda: api_diagnosis_contract("identity-check-run", user_id="unknown-user"),
            lambda: api_investigations(user_id="unknown-user"),
            lambda: api_insights(user_id="unknown-user"),
            lambda: api_conversation("not-a-conversation", user_id="unknown-user"),
        )
        for check in checks:
            with self.subTest(check=check):
                with self.assertRaises(HTTPException) as denied:
                    check()
                self.assertEqual(denied.exception.status_code, 401)

    def test_missing_identity_is_401_on_saved_reads(self):
        checks = (
            lambda: api_diagnosis_run("missing-run"),
            lambda: api_evidence("missing-run"),
            lambda: api_diagnosis_contract("missing-run"),
            lambda: api_investigations(),
            lambda: api_insights(),
            lambda: api_conversation("missing-conversation"),
        )
        for check in checks:
            with self.subTest(check=check):
                with self.assertRaises(HTTPException) as denied:
                    check()
                self.assertEqual(denied.exception.status_code, 401)

    def test_conversation_read_reauthorizes_linked_run(self):
        self.save_run("conversation-north-run", "CFO", "North", "2023-07-07")
        authorized_id = storage.create_conversation(
            "conversation-north-run", "demo-cfo", {"region": "North", "category": "Electronics"}
        )
        self.assertEqual(api_conversation(authorized_id, user_id="demo-cfo")["conversation_id"], authorized_id)

        self.save_run("conversation-south-run", "regional_manager_north", "South", "2023-07-08")
        hidden_id = storage.create_conversation(
            "conversation-south-run", "demo-regional-north", {"region": "South", "category": "Electronics"}
        )
        with self.assertRaises(HTTPException) as hidden:
            api_conversation(hidden_id, user_id="demo-regional-north")
        self.assertEqual(hidden.exception.status_code, 404)
        self.assertEqual(hidden.exception.detail, "Conversation not found")

    def test_missing_and_unknown_conversations_do_not_reveal_existence(self):
        run = self.save_run("conversation-owner-run", "CFO", "North", "2023-07-09")
        conversation_id = storage.create_conversation(run["run_id"], "demo-cfo", {})
        with self.assertRaises(HTTPException) as unknown:
            api_conversation(conversation_id, user_id="not-known")
        with self.assertRaises(HTTPException) as missing:
            api_conversation("not-a-conversation", user_id="demo-cfo")
        self.assertEqual(unknown.exception.status_code, 401)
        self.assertEqual(missing.exception.status_code, 404)
        with self.assertRaises(HTTPException) as other_owner:
            api_conversation(conversation_id, user_id="demo-marketing")
        self.assertEqual(other_owner.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
