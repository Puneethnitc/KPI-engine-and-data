import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.schemas import Citation
import backend.storage as storage
from backend.storage import append_message, create_conversation, get_conversation, get_run, save_diagnosis_run


class ChatStorageRegressionTests(unittest.TestCase):
    def test_append_message_accepts_pydantic_citation_objects(self):
        with TemporaryDirectory() as directory, patch.object(storage, "DB_PATH", Path(directory) / "chat.sqlite3"):
            conversation_id = create_conversation(
                run_id="run-chat-regression-test",
                user_id="demo-user",
                context={"kpi_id": "net_sales_revenue", "region": "North", "category": "Electronics"},
            )

            citations = [
                Citation(
                    source_path="run:run-chat-regression-test",
                    evidence_type="diagnosis_json",
                    line_or_row_ref="root",
                    kpi="net_sales_revenue",
                )
            ]

            append_message(conversation_id, "user", "What changed in revenue?", citations)
            saved = get_conversation(conversation_id)

            self.assertEqual(saved["messages"][0]["role"], "user")
            self.assertEqual(saved["messages"][0]["citations"][0]["source_path"], "run:run-chat-regression-test")

    def test_saved_confidence_profile_is_retrieved_as_immutable_run_snapshot(self):
        with TemporaryDirectory() as directory, patch.object(storage, "DB_PATH", Path(directory) / "runs.sqlite3"):
            original_profile = {
                "version": "1.0",
                "overall": {"status": "MODERATE", "reasons": ["No approved causal design."]},
                "movement": {"status": "HIGH", "score": None},
                "source": {"status": "HIGH", "score": None},
                "driver": {"status": "LOW", "score": None},
                "causal": {"status": "NOT_ASSESSED", "score": None},
            }
            result = {
                "run_id": "run-confidence-snapshot",
                "kpi_id": "net_sales_revenue",
                "target_date": "2026-09-01",
                "as_of": "2026-09-02T12:00:00+00:00",
                "persona": "CFO",
                "verdict": "MATERIAL_CAUSE_UNVERIFIED",
                "confidence_profile": original_profile,
                "driver_analysis": {
                    "status": "ASSESSED",
                    "ranked_drivers": [{"rank": 1, "driver_id": "traffic", "score": 0.42}],
                    "excluded_drivers": [{"driver_id": "stockout", "reason_code": "LOW_COVERAGE"}],
                },
            }
            save_diagnosis_run(
                result,
                scope={"region": "North", "category": "Retail"},
                access_context={"authorized": True},
            )
            result["confidence_profile"]["overall"]["status"] = "LOW"
            result["movement_assessment"] = {"is_material": False}
            result["driver_analysis"]["ranked_drivers"][0]["score"] = 0.01
            historical = get_run("run-confidence-snapshot")
            self.assertEqual(historical["result"]["confidence_profile"], {
                **original_profile,
                "overall": {"status": "MODERATE", "reasons": ["No approved causal design."]},
            })
            self.assertEqual(historical["result"]["driver_analysis"]["ranked_drivers"][0]["score"], 0.42)
            self.assertEqual(historical["result"]["driver_analysis"]["excluded_drivers"][0]["reason_code"], "LOW_COVERAGE")


if __name__ == "__main__":
    unittest.main()
