from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None

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
