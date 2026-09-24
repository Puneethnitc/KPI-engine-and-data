from __future__ import annotations

import json
import os

from backend.schemas import QueryIntent, RouterAnalysis

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None

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
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", "mock-key")) if OpenAI is not None else None

    def route(self, question: str, active_kpi: str) -> RouterAnalysis:
        if self.client is None:
            return RouterAnalysis(
                intent=QueryIntent.DIAGNOSIS_EXPLANATION,
                reformulated_query=question,
                target_kpi=active_kpi,
                requires_diagnosis_json=True,
                requires_vector_docs=True,
                requires_data_rows=False,
            )

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": ROUTER_PROMPT},
                    {"role": "user", "content": f"Active KPI: {active_kpi}\nQuestion: {question}"},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            data = json.loads(response.choices[0].message.content)
            return RouterAnalysis(**data)
        except Exception:
            return RouterAnalysis(
                intent=QueryIntent.DIAGNOSIS_EXPLANATION,
                reformulated_query=question,
                target_kpi=active_kpi,
                requires_diagnosis_json=True,
                requires_vector_docs=True,
                requires_data_rows=False,
            )
