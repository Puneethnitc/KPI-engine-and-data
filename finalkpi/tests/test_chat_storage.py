import unittest

from backend.schemas import Citation
from backend.storage import append_message, create_conversation, get_conversation


class ChatStorageRegressionTests(unittest.TestCase):
    def test_append_message_accepts_pydantic_citation_objects(self):
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


if __name__ == "__main__":
    unittest.main()
