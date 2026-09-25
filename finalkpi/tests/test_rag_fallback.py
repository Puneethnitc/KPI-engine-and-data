import unittest

from backend.query_router import DynamicQueryRouter
from backend.rag_pipeline import DynamicRAGPipeline
from backend.retrieval import ContextBuilder
from backend.schemas import ChatRequest


DIAGNOSIS = {
    "kpi_id": "net_sales_revenue",
    "target_date": "2023-07-24",
    "verdict": "MATERIAL_CAUSE_UNVERIFIED",
    "movement_assessment": {
        "actual_value": 2919.67,
        "expected_value": 4283.82,
        "delta": -1364.15,
        "is_material": True,
    },
    "causal_verdict": "UNTESTABLE",
    "correlational_candidates": [{"driver_id": "traffic_drop", "max_correlation": 0.6362}],
    "narrative": "net_sales_revenue changed by -1364.15 in its declared unit on 2023-07-24.",
    "grounding_passed": True,
}


class RAGFallbackTests(unittest.TestCase):
    def test_metric_summary_aggregates_revenue_across_multiple_rows(self):
        pipeline = DynamicRAGPipeline(DynamicQueryRouter(), ContextBuilder())
        request = ChatRequest(
            question="What is the revenue total for North?",
            diagnosis_json=None,
            active_kpi="net_sales_revenue",
            active_date="2023-07-24",
            active_region="North",
            active_category="ALL",
            user_persona="CFO",
            user_access_tags=["public", "internal"],
            as_of_timestamp="2023-07-25T12:00:00",
        )

        answer = pipeline._metric_summary(request)
        self.assertIsNotNone(answer)
        self.assertIn("North", answer)
        self.assertIn("9263.120000", answer.replace(",", ""))

    def test_metric_summary_uses_ratio_of_sums_for_conversion_rate(self):
        pipeline = DynamicRAGPipeline(DynamicQueryRouter(), ContextBuilder())
        request = ChatRequest(
            question="What is North conversion rate?",
            diagnosis_json=None,
            active_kpi="conversion_rate",
            active_date="2023-07-24",
            active_region="North",
            active_category="ALL",
            user_persona="CFO",
            user_access_tags=["public", "internal"],
            as_of_timestamp="2023-07-25T12:00:00",
        )

        answer = pipeline._metric_summary(request)
        self.assertIsNotNone(answer)
        self.assertIn("0.024125", answer)

    def test_metric_summary_denies_unauthorized_chat_scope(self):
        pipeline = DynamicRAGPipeline(DynamicQueryRouter(), ContextBuilder())
        request = ChatRequest(
            question="What is the value for North?",
            diagnosis_json=None,
            active_kpi="net_sales_revenue",
            active_date="2023-07-24",
            active_region="North",
            active_category="Electronics",
            user_persona="regional_manager_south",
            user_access_tags=["public", "internal"],
            as_of_timestamp="2023-07-25T12:00:00",
        )

        self.assertIsNone(pipeline._metric_summary(request))

    def test_fallback_answer_matches_saved_revenue_diagnosis(self):
        request = ChatRequest(
            question="What changed in revenue?",
            diagnosis_json=DIAGNOSIS,
            active_kpi="net_sales_revenue",
            active_date="2023-07-24",
            active_region="North",
            active_category="Electronics",
            user_persona="CFO",
            user_access_tags=["public", "internal"],
            as_of_timestamp="2023-07-25T12:00:00",
        )
        pipeline = DynamicRAGPipeline(DynamicQueryRouter(), ContextBuilder())
        response = pipeline.run(request)

        self.assertIn("net_sales_revenue", response.answer)
        self.assertIn("-1364.15", response.answer)
        self.assertEqual(response.evidence_status, "MATERIAL_CAUSE_UNVERIFIED")

    def test_fallback_answer_explains_formula_without_model(self):
        request = ChatRequest(
            question="How is conversion rate calculated?",
            diagnosis_json=DIAGNOSIS,
            active_kpi="conversion_rate",
            active_date="2023-07-24",
            active_region="North",
            active_category="Electronics",
            user_persona="CFO",
            user_access_tags=["public", "internal"],
            as_of_timestamp="2023-07-25T12:00:00",
        )
        pipeline = DynamicRAGPipeline(DynamicQueryRouter(), ContextBuilder())
        response = pipeline.run(request)

        self.assertIn("orders", response.answer.lower())
        self.assertIn("traffic_total", response.answer.lower())
        self.assertTrue(any(c.evidence_type == "kpi_contract" for c in response.citations))

    def test_fallback_preserves_causal_limitations(self):
        request = ChatRequest(
            question="Did traffic cause the revenue drop?",
            diagnosis_json=DIAGNOSIS,
            active_kpi="net_sales_revenue",
            active_date="2023-07-24",
            active_region="North",
            active_category="Electronics",
            user_persona="CFO",
            user_access_tags=["public", "internal"],
            as_of_timestamp="2023-07-25T12:00:00",
        )
        pipeline = DynamicRAGPipeline(DynamicQueryRouter(), ContextBuilder())
        response = pipeline.run(request)

        self.assertIn("not proven", response.answer.lower())
        self.assertIn("causal", response.answer.lower())
        self.assertEqual(response.evidence_status, "MATERIAL_CAUSE_UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
