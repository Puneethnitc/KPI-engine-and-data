from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None

from kpi_engine.access import AccessController
from kpi_engine.contracts import KPIRegistry
from kpi_engine.query import QueryRequest
from kpi_engine.query.catalog import SourceCatalog
from kpi_engine.query.service import QueryService

from backend.prompts import SYSTEM_PROMPT
from backend.query_router import DynamicQueryRouter
from backend.schemas import ChatRequest, ChatResponse, Citation, QueryIntent
from backend.retrieval import ContextBuilder


class DynamicRAGPipeline:
    def __init__(self, router: DynamicQueryRouter, context_builder: ContextBuilder):
        self.router = router
        self.cb = context_builder
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", "mock-key")) if OpenAI is not None else None

    def _diagnosis_verdict(self, request: ChatRequest) -> str:
        diagnosis = request.diagnosis_json or {}
        if diagnosis.get("verdict"):
            return str(diagnosis["verdict"])
        if diagnosis.get("causal_verdict"):
            return str(diagnosis["causal_verdict"])
        return "INSUFFICIENT_EVIDENCE"

    def _contract_citation(self, kpi_id: str) -> Citation:
        contract_path = Path(__file__).resolve().parents[1] / "kpi_engine" / "registry" / f"{kpi_id}.yaml"
        return Citation(
            source_path=str(contract_path),
            evidence_type="kpi_contract",
            line_or_row_ref="definition",
            kpi=kpi_id,
        )

    def _metric_summary(self, request: ChatRequest) -> str | None:
        if not request.active_kpi:
            return None
        registry = KPIRegistry(str(Path(__file__).resolve().parents[1] / "kpi_engine" / "registry"))
        try:
            contract = registry.get(request.active_kpi)
        except Exception:
            return None
        catalog = SourceCatalog()
        if contract.source not in catalog.sources:
            return None

        scope: Dict[str, str] = {}
        for key in ("region", "category"):
            value = getattr(request, f"active_{key}", None)
            if value and value not in {"ALL", "all", None}:
                scope[key] = str(value)

        access = AccessController(str(Path(__file__).resolve().parents[1] / "data" / "access_control.csv")).check(
            request.user_persona or "CFO",
            scope,
        )
        if not access.allowed:
            return None

        query = QueryRequest(
            source_id=contract.source,
            aggregation=contract.aggregation,
            value_column=contract.value_column,
            numerator_column=getattr(contract, "numerator_column", None),
            denominator_column=getattr(contract, "denominator_column", None),
            weight_column=getattr(contract, "weight_column", None),
            scope=scope or None,
            as_of=request.as_of_timestamp,
        )

        try:
            prepared = QueryService(catalog).prepare_metric(query)
        except Exception:
            return None

        rows = prepared.rows
        if not rows:
            return None

        if request.active_date:
            target_date = pd.Timestamp(request.active_date).normalize()
            date_rows = [
                row for row in rows
                if pd.Timestamp(row.get(catalog.get_source(contract.source).date_column)).normalize() == target_date
            ]
            if date_rows:
                rows = date_rows
            elif rows:
                rows = [rows[-1]]

        metric_row = rows[-1]
        value = metric_row.get("metric_value")
        if value is None:
            return None
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return None

        location = " / ".join(f"{key}={scope[key]}" for key in sorted(scope)) or "global"
        return f"The current {contract.kpi_id} value for {location} on {request.active_date or 'the selected date'} is {numeric_value:,.6f} {contract.unit}."

    def _fallback_answer(self, request: ChatRequest, analysis, default_citations: List[Dict[str, Any]]) -> ChatResponse:
        diagnosis = request.diagnosis_json or {}
        question = request.question.lower()
        verdict = self._diagnosis_verdict(request)

        citations = [Citation(**c) for c in default_citations] if default_citations else [
            Citation(source_path=f"engine/diagnosis_runs/{request.active_kpi}_{request.active_date}.json", evidence_type="diagnosis_json", line_or_row_ref="root", kpi=request.active_kpi)
        ]

        if "conversion rate" in question or "calculate" in question or "formula" in question:
            contract = self._contract_citation(request.active_kpi or "conversion_rate")
            citations.insert(0, contract)
            answer = (
                f"The calculation for {request.active_kpi} is defined in the KPI contract as: "
                f"orders / traffic_total. The engine treats it as a ratio of sums rather than an averaged displayed rate."
            )
            limitations = ["This answer is bounded to the local KPI contract and saved diagnosis context."]
            suggested = [
                "What changed in the KPI on the selected date?",
                "How does the current diagnosis compare to the expected baseline?",
            ]
            return ChatResponse(answer=answer, citations=citations, evidence_status=verdict, limitations=limitations, suggested_followups=suggested)

        if "cause" in question or ("traffic" in question and "drop" in question):
            correlational = diagnosis.get("correlational_candidates", [])
            causal = diagnosis.get("causal_verdict") or "UNTESTABLE"
            candidate = correlational[0].get("driver_id") if correlational else "traffic_drop"
            answer = (
                f"The diagnosis does not prove that traffic caused the revenue drop. The engine status is {verdict}, and the strongest correlational signal is {candidate}; "
                f"that is not the same as established causality. The causal verification label remains {causal}. This is not proven causation."
            )
            limitations = ["Correlation is not proof of causation.", "No approved causal design or counterfactual was supplied in the engine result."]
            suggested = [
                "What changed in revenue?",
                "What is the diagnosis verdict and source state?",
            ]
            return ChatResponse(answer=answer, citations=citations, evidence_status=verdict, limitations=limitations, suggested_followups=suggested)

        if "what changed" in question or "revenue" in question or "delta" in question:
            movement = diagnosis.get("movement_assessment", {})
            actual = movement.get("actual_value")
            expected = movement.get("expected_value")
            delta = movement.get("delta")
            answer = (
                f"The saved diagnosis for {request.active_kpi} on {request.active_date} shows actual={actual}, expected={expected}, and delta={delta}. "
                f"This is the authoritative movement from the engine run, and the ledger-level verdict remains {verdict}."
            )
            limitations = ["The answer uses the saved diagnosis and does not extrapolate beyond it."]
            suggested = [
                "What caused this movement?",
                "What evidence supports the source status and reconciliation state?",
            ]
            return ChatResponse(answer=answer, citations=citations, evidence_status=verdict, limitations=limitations, suggested_followups=suggested)

        fallback_answer = diagnosis.get("narrative") or (
            f"The saved diagnosis for {request.active_kpi} on {request.active_date} remains the authoritative context. "
            f"The current evidence status is {verdict}."
        )
        return ChatResponse(
            answer=fallback_answer,
            citations=citations,
            evidence_status=verdict,
            limitations=["The available local evidence is insufficient to answer this question beyond the saved diagnosis."],
            suggested_followups=[
                "What changed in the KPI on the selected date?",
                "How is the KPI defined and calculated?",
            ],
        )

    def run(self, request: ChatRequest) -> ChatResponse:
        analysis = self.router.route(request.question, request.active_kpi)

        if analysis.intent == QueryIntent.OUT_OF_SCOPE:
            return ChatResponse(
                answer="I can only answer questions related to local KPI contracts, methodology, diagnosis runs, and source data summaries. The question provided is outside my available evidence scope.",
                citations=[],
                evidence_status="INSUFFICIENT_EVIDENCE",
                limitations=["Query falls outside local KPI diagnostic context."],
                suggested_followups=[
                    f"Why did {request.active_kpi} change?",
                    f"What is the definition of {request.active_kpi}?",
                    "What methodology was used for reconciliation?",
                ],
            )

        context_str, default_citations = self.cb.build_dynamic_context(request, analysis)

        intent_instruction = ""
        if analysis.intent == QueryIntent.ACTION_RECOMMENDATION:
            intent_instruction = "\nSPECIAL INSTRUCTION: The user is asking for actions/recommendations. State human review boundaries and required verification steps. Do NOT prescribe business actions."

        question_lower = request.question.lower()
        direct_value_request = (
            analysis.intent == QueryIntent.SCOPED_DATA_QUERY
            or any(phrase in question_lower for phrase in [
                "what is the value",
                "what was the value",
                "what is the total",
                "what was the total",
                "how much",
                "current value",
                "value for",
                "total for",
                "average for",
                "sum for",
            ])
        )
        fallback_like_question = any(phrase in question_lower for phrase in [
            "what changed",
            "how is",
            "formula",
            "calculated",
            "cause",
            "delta",
            "did traffic cause",
        ])

        if direct_value_request and not fallback_like_question:
            metric_summary = self._metric_summary(request)
            if metric_summary:
                evidence_status = self._diagnosis_verdict(request)
                return ChatResponse(
                    answer=metric_summary,
                    citations=[Citation(**c) for c in default_citations] if default_citations else [
                        Citation(source_path=f"source/{request.active_kpi}", evidence_type="data_summary", line_or_row_ref="metric_service", kpi=request.active_kpi)
                    ],
                    evidence_status=evidence_status,
                    limitations=["This numerical value was resolved from the shared source catalog and metric service for the active scope."],
                    suggested_followups=[
                        "What changed versus the baseline for this KPI?",
                        "How does this compare to the diagnosis verdict?",
                    ],
                )

        user_prompt = f"""DYNAMIC INTENT: {analysis.intent}
{intent_instruction}

CONTEXT EVIDENCE:
{context_str}

USER QUESTION:
{request.question}

Respond using the required JSON schema with exact engine status labels.
"""

        try:
            if self.client is None:
                return self._fallback_answer(request, analysis, default_citations)

            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            result_json = json.loads(response.choices[0].message.content)
            raw_citations = result_json.get("citations", [])
            citations = [Citation(**c) for c in raw_citations] if raw_citations else [Citation(**c) for c in default_citations]
            evidence_status = result_json.get("evidence_status") or self._diagnosis_verdict(request)
            return ChatResponse(
                answer=result_json.get("answer", "Unable to formulate answer."),
                citations=citations,
                evidence_status=evidence_status,
                limitations=result_json.get("limitations", []),
                suggested_followups=result_json.get("suggested_followups", []),
            )
        except Exception as exc:
            return self._fallback_answer(request, analysis, default_citations)
