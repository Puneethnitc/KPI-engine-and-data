from __future__ import annotations

import json
import time

from backend.schemas import QueryIntent, RouterAnalysis
from backend.llm_config import create_llm_client

ROUTER_PROMPT = """You are a query routing module for a KPI Diagnostic RAG engine.
Analyze the user question dynamically and classify its primary intent.

Intents:
- DIAGNOSIS_EXPLANATION: Inquiries about metric movements, anomalies, baseline deltas, or diagnosis run results.
- KPI_CONTRACT: Questions about metric definitions, formulas, dimensions, owners, or reconciliation policies.
- METHODOLOGY: Questions about engine algorithms, Shapley decomposition, MSTL/STL, or DiD verification rules.
- SCOPED_DATA_QUERY: Requests for raw source dataset schemas or data summaries.
- ACTION_RECOMMENDATION: Requests asking for business advice, monetary decisions, or prescriptive next steps.
- OUT_OF_SCOPE: Questions completely unrelated to KPIs, diagnostics, project data, or engine methodology.

Respond strictly in JSON matching this schema:
{
  "intent": "<QueryIntent>",
  "reformulated_query": "<optimized search query>",
  "target_kpi": "<KPI ID or null>",
  "requires_diagnosis_json": boolean,
  "requires_vector_docs": boolean,
  "requires_data_rows": boolean
}
"""


class DynamicQueryRouter:
    def __init__(self):
        self.client, self.llm_settings = create_llm_client()

    def route(self, question: str, active_kpi: str) -> RouterAnalysis:
        if self.client is None:
            return RouterAnalysis(
                intent=QueryIntent.DIAGNOSIS_EXPLANATION,
                reformulated_query=question,
                target_kpi=active_kpi,
                requires_diagnosis_json=True,
                requires_vector_docs=True,
                requires_data_rows=False,
                runtime_telemetry={"status": "SKIPPED", "latency_ms": 0, "model_calls": 0,
                                   "usage_source": "NOT_APPLICABLE"},
            )

        started = time.monotonic_ns()
        try:
            response = self.client.chat.completions.create(
                model=self.llm_settings.model,
                messages=[
                    {"role": "system", "content": ROUTER_PROMPT},
                    {"role": "user", "content": f"Active KPI: {active_kpi}\nQuestion: {question}"},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            data = json.loads(response.choices[0].message.content)
            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            output_tokens = getattr(usage, "completion_tokens", None) if usage else None
            data["runtime_telemetry"] = {
                "status": "COMPLETED", "latency_ms": (time.monotonic_ns() - started) / 1_000_000,
                "model_calls": 1, "provider": self.llm_settings.provider,
                "model": self.llm_settings.model, "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "usage_source": "PROVIDER_REPORTED" if input_tokens is not None and output_tokens is not None else "UNAVAILABLE",
            }
            return RouterAnalysis(**data)
        except Exception:
            return RouterAnalysis(
                intent=QueryIntent.DIAGNOSIS_EXPLANATION,
                reformulated_query=question,
                target_kpi=active_kpi,
                requires_diagnosis_json=True,
                requires_vector_docs=True,
                requires_data_rows=False,
                runtime_telemetry={
                    "status": "FALLBACK", "latency_ms": (time.monotonic_ns() - started) / 1_000_000,
                    "model_calls": 1, "provider": self.llm_settings.provider,
                    "model": self.llm_settings.model, "input_tokens": None, "output_tokens": None,
                    "usage_source": "UNAVAILABLE", "reason_code": "ROUTER_FALLBACK",
                },
            )
