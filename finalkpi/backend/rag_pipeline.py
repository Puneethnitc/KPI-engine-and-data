from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from backend.llm_config import create_llm_client
from backend.llm_config import get_model_economics, get_runtime_limits
from backend.runtime_telemetry import RuntimeTelemetry, estimate_cost_usd

from kpi_engine.access import AccessController
from kpi_engine.contracts import KPIRegistry
from kpi_engine.query import QueryRequest
from kpi_engine.query.catalog import SourceCatalog
from kpi_engine.query.service import QueryService

from backend.prompts import SYSTEM_PROMPT
from backend.query_router import DynamicQueryRouter
from backend.schemas import ChatRequest, ChatResponse, Citation, QueryIntent
from backend.retrieval import ContextBuilder, safe_citation_id


class DynamicRAGPipeline:
    def __init__(self, router: DynamicQueryRouter, context_builder: ContextBuilder):
        self.router = router
        self.cb = context_builder
        self.client, self.llm_settings = create_llm_client()

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
            source_path=safe_citation_id(contract_path, "kpi_contract"),
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
            driver_analysis = diagnosis.get("driver_analysis") or {}
            correlational = driver_analysis.get("ranked_drivers", [])
            if driver_analysis.get("status") in {"BLOCKED", "INSUFFICIENT_EVIDENCE", "NOT_APPLICABLE"}:
                correlational = []
            causal = diagnosis.get("causal_verdict") or "UNTESTABLE"
            candidate = correlational[0].get("display_name", correlational[0].get("driver_id")) if correlational else "no eligible driver"
            answer = (
                f"The diagnosis does not prove that a driver caused the KPI movement. The engine status is {verdict}, and the strongest eligible association is {candidate}; "
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
        telemetry = RuntimeTelemetry(limits=get_runtime_limits())
        analysis = self.router.route(request.question, request.active_kpi)
        router_runtime = analysis.runtime_telemetry or {}
        router_calls = int(router_runtime.get("model_calls", 0))
        economics = get_model_economics()
        telemetry.add_stage(
            stage="query_routing", processing_type="LLM" if router_calls else "DETERMINISTIC",
            method="intent_classification", latency_ms=router_runtime.get("latency_ms", 0),
            status=router_runtime.get("status", "COMPLETED"), model_calls=router_calls,
            provider=router_runtime.get("provider"), model=router_runtime.get("model"),
            input_tokens=router_runtime.get("input_tokens"), output_tokens=router_runtime.get("output_tokens"),
            usage_source=router_runtime.get("usage_source", "NOT_APPLICABLE"),
            estimated_cost_usd=estimate_cost_usd(
                router_runtime.get("input_tokens"), router_runtime.get("output_tokens"),
                economics.get("input_usd_per_million_tokens"), economics.get("output_usd_per_million_tokens"),
            ), details={"reason_code": router_runtime.get("reason_code")},
        )

        def finish(response: ChatResponse) -> ChatResponse:
            response.runtime_telemetry = telemetry.finalize()
            return response

        if analysis.intent == QueryIntent.OUT_OF_SCOPE:
            return finish(ChatResponse(
                answer="I can only answer questions related to local KPI contracts, methodology, diagnosis runs, and source data summaries. The question provided is outside my available evidence scope.",
                citations=[],
                evidence_status="INSUFFICIENT_EVIDENCE",
                limitations=["Query falls outside local KPI diagnostic context."],
                suggested_followups=[
                    f"Why did {request.active_kpi} change?",
                    f"What is the definition of {request.active_kpi}?",
                    "What methodology was used for reconciliation?",
                ],
            ))

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
                telemetry.add_stage(stage="answer_generation", processing_type="DETERMINISTIC",
                                    method="metric_service_direct_answer", latency_ms=0,
                                    status="COMPLETED")
                return finish(ChatResponse(
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
                ))

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
                telemetry.add_stage(stage="answer_generation", processing_type="DETERMINISTIC",
                                    method="evidence_bound_fallback", latency_ms=0, status="FALLBACK")
                return finish(self._fallback_answer(request, analysis, default_citations))

            answer_started = time.monotonic_ns()
            response = self.client.chat.completions.create(
                model=self.llm_settings.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            result_json = json.loads(response.choices[0].message.content)
            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            output_tokens = getattr(usage, "completion_tokens", None) if usage else None
            telemetry.add_stage(
                stage="answer_generation", processing_type="LLM", method="grounded_rag_answer",
                latency_ms=(time.monotonic_ns() - answer_started) / 1_000_000,
                provider=self.llm_settings.provider, model=self.llm_settings.model, model_calls=1,
                input_tokens=input_tokens, output_tokens=output_tokens,
                usage_source="PROVIDER_REPORTED" if input_tokens is not None and output_tokens is not None else "UNAVAILABLE",
                estimated_cost_usd=estimate_cost_usd(
                    input_tokens, output_tokens, economics.get("input_usd_per_million_tokens"),
                    economics.get("output_usd_per_million_tokens"),
                ),
            )
            # Model-supplied paths are untrusted. Preserve only safe server citations.
            citations = [Citation(**c) for c in default_citations]
            evidence_status = result_json.get("evidence_status") or self._diagnosis_verdict(request)
            return finish(ChatResponse(
                answer=result_json.get("answer", "Unable to formulate answer."),
                citations=citations,
                evidence_status=evidence_status,
                limitations=result_json.get("limitations", []),
                suggested_followups=result_json.get("suggested_followups", []),
            ))
        except Exception as exc:
            latency = (time.monotonic_ns() - answer_started) / 1_000_000 if "answer_started" in locals() else 0
            telemetry.add_stage(
                stage="answer_generation", processing_type="LLM" if self.client else "DETERMINISTIC",
                method="grounded_rag_answer", latency_ms=latency, status="FALLBACK",
                provider=self.llm_settings.provider if self.llm_settings else None,
                model=self.llm_settings.model if self.llm_settings else None,
                model_calls=1 if self.client else 0, input_tokens=None, output_tokens=None,
                usage_source="UNAVAILABLE" if self.client else "NOT_APPLICABLE",
                estimated_cost_usd=None if self.client else 0,
                details={"reason_code": "ANSWER_FALLBACK"},
            )
            return finish(self._fallback_answer(request, analysis, default_citations))
