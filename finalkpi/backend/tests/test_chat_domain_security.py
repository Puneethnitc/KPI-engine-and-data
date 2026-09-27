import unittest
from unittest.mock import patch

from backend.app import ChatRequest as ApiChatRequest, api_chat
from backend.domain_policy import retrieval_tags_for_persona
from backend.retrieval import ContextBuilder
from backend.schemas import ChatRequest, ChatResponse, QueryIntent, RouterAnalysis


class _Collection:
    def query(self, **_kwargs):
        return {
            "documents": [["restricted finance", "north marketing", "south marketing"]],
            "metadatas": [[
                {"source": "/private/finance.csv", "evidence_type": "data_summary", "access_tags": "finance", "kpi": "all", "region": "ALL", "category": "ALL"},
                {"source": "/private/marketing.md", "evidence_type": "methodology_doc", "access_tags": "marketing", "kpi": "orders", "region": "North", "category": "Electronics"},
                {"source": "/private/south.md", "evidence_type": "methodology_doc", "access_tags": "marketing", "kpi": "orders", "region": "South", "category": "Electronics"},
            ]],
        }


def _request(persona="marketing_manager"):
    return ChatRequest(
        question="Explain the evidence", diagnosis_json={"kpi_id": "orders"},
        active_kpi="orders", active_date="2023-07-24", active_region="North",
        active_category="Electronics", user_persona=persona,
        user_access_tags=retrieval_tags_for_persona(persona),
        as_of_timestamp="2023-07-25T12:00:00",
    )


class ChatDomainSecurityTests(unittest.TestCase):
    def test_retrieval_filters_domain_and_scope_and_returns_path_free_citations(self):
        builder = ContextBuilder()
        builder.collection = _Collection()
        context, citations = builder.retrieve_vector_chunks(
            _request(),
            RouterAnalysis(
                intent=QueryIntent.METHODOLOGY, reformulated_query="evidence",
                requires_diagnosis_json=False, requires_vector_docs=True,
            ),
        )
        self.assertIn("north marketing", context)
        self.assertNotIn("restricted finance", context)
        self.assertNotIn("south marketing", context)
        self.assertNotIn("/private/", context)
        self.assertEqual(len(citations), 1)
        self.assertTrue(citations[0]["source_path"].startswith("kb:methodology_doc:"))

    def test_server_ignores_client_access_tags_and_projects_runless_diagnosis(self):
        captured = {}

        def run(request):
            captured["request"] = request
            return ChatResponse(
                answer="bounded", citations=[], evidence_status="DRIFT",
                limitations=[], suggested_followups=[],
            )

        payload = ApiChatRequest(
            question="Explain this", user_id="demo-marketing", persona="marketing_manager",
            diagnosis_json={
                "kpi_id": "orders", "target_date": "2023-07-24", "verdict": "MATERIAL_CAUSE_UNVERIFIED",
                "segment": {"region": "North", "category": "Electronics"},
                "reconciliation_verdict": {"status": "DRIFT", "gap_pct": 12.5, "details": {"finance_total": 875.0}},
            },
            active_kpi="orders", active_date="2023-07-24", active_region="North",
            active_category="Electronics", user_access_tags=["finance", "internal"],
        )
        with patch("backend.app.pipeline.run", side_effect=run):
            api_chat(payload)
        request = captured["request"]
        self.assertNotIn("finance", request.user_access_tags)
        self.assertIn("marketing", request.user_access_tags)
        self.assertNotIn("875.0", repr(request.diagnosis_json))
        self.assertIsNone(request.diagnosis_json["reconciliation_verdict"]["gap_pct"])

    def test_chat_without_persona_field_works_for_non_cfo_identity(self):
        # F-P4 (plan §1.6): ChatRequest.persona now defaults to None, so a
        # marketing (or any non-CFO) caller that omits persona is resolved
        # from user_id instead of being rejected against a hard-coded "CFO".
        captured = {}

        def run(request):
            captured["request"] = request
            return ChatResponse(
                answer="bounded", citations=[], evidence_status="NOT_APPLICABLE",
                limitations=[], suggested_followups=[],
            )

        payload = ApiChatRequest(
            question="Explain this", user_id="demo-marketing",
            diagnosis_json={
                "kpi_id": "orders", "target_date": "2023-07-24", "verdict": "NO_MATERIAL_MOVEMENT",
                "segment": {"region": "North", "category": "Electronics"},
            },
            active_kpi="orders", active_date="2023-07-24", active_region="North",
            active_category="Electronics",
        )
        self.assertIsNone(payload.persona)
        with patch("backend.app.pipeline.run", side_effect=run):
            api_chat(payload)
        self.assertIn("request", captured)


if __name__ == "__main__":
    unittest.main()
