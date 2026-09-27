from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend.app import api_security_audit
from backend.storage import (
    append_security_audit_event,
    list_security_audit_events,
    verify_security_audit_chain,
)


class SecurityAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tempdir.name, "audit.db")
        self.db_patch = patch("backend.storage.DB_PATH", self.db_path)
        self.db_patch.start()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.tempdir.cleanup()

    def test_events_are_hash_chained_and_sensitive_metadata_is_dropped(self) -> None:
        first = append_security_audit_event(
            actor_user_id="cfo_user", actor_persona="CFO",
            action="DIAGNOSIS_EXECUTE", resource_type="DIAGNOSIS",
            decision="ALLOW", reason_code="AUTHORIZED_SCOPE",
            scope={"region": "North", "category": "Electronics"},
            metadata={"kpi_id": "net_sales", "prompt": "secret", "path": "/tmp/private.csv"},
        )
        second = append_security_audit_event(
            actor_user_id="cfo_user", actor_persona="CFO",
            action="EVIDENCE_READ", resource_type="EVIDENCE",
            resource_id="run-1", decision="ALLOW", reason_code="AUTHORIZED_SCOPE",
        )
        self.assertEqual(second["previous_event_hash"], first["event_hash"])
        self.assertEqual({"kpi_id": "net_sales"}, list_security_audit_events()[1]["metadata"])
        self.assertEqual({"valid": True, "event_count": 2, "failed_sequence": None}, verify_security_audit_chain())

    def test_database_rejects_update_and_delete(self) -> None:
        append_security_audit_event(
            actor_user_id="cfo_user", actor_persona="CFO", action="READ",
            resource_type="RUN", decision="ALLOW", reason_code="AUTHORIZED_SCOPE",
        )
        connection = sqlite3.connect(self.db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("UPDATE security_audit_events SET reason_code = 'CHANGED'")
        connection.rollback()
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM security_audit_events")
        connection.close()

    def test_only_cfo_can_read_audit_view(self) -> None:
        with patch("backend.app.identity_persona", return_value="marketing_manager"):
            with self.assertRaises(HTTPException) as denied:
                api_security_audit(user_id="marketing_user")
        self.assertEqual(404, denied.exception.status_code)

        with patch("backend.app.identity_persona", return_value="CFO"), patch("backend.app.require_domain"):
            response = api_security_audit(user_id="cfo_user")
        self.assertTrue(response["integrity"]["valid"])
        self.assertEqual("DEMO_SIMULATED", response["identity_mode"])


if __name__ == "__main__":
    unittest.main()
