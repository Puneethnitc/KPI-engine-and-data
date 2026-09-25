from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EngineLabel(str, Enum):
    CORRELATIONAL = "CORRELATIONAL"
    NOT_RECONCILED = "NOT_RECONCILED"
    INCONCLUSIVE = "INCONCLUSIVE"
    MATERIAL_CAUSE_UNVERIFIED = "MATERIAL_CAUSE_UNVERIFIED"
    RECONCILED = "RECONCILED"
    CAUSAL_VERIFIED = "CAUSAL_VERIFIED"
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class QueryIntent(str, Enum):
    DIAGNOSIS_EXPLANATION = "DIAGNOSIS_EXPLANATION"
    KPI_CONTRACT = "KPI_CONTRACT"
    METHODOLOGY = "METHODOLOGY"
    SCOPED_DATA_QUERY = "SCOPED_DATA_QUERY"
    ACTION_RECOMMENDATION = "ACTION_RECOMMENDATION"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class Citation(BaseModel):
    source_path: str = Field(..., description="Path or identifier of the retrieved context item.")
    evidence_type: str = Field(..., description="diagnosis_json | kpi_contract | methodology_doc | data_summary")
    line_or_row_ref: Optional[str] = Field(None, description="Specific row number, line range, or section heading.")
    kpi: Optional[str] = Field(None, description="Associated KPI ID.")


class RouterAnalysis(BaseModel):
    intent: QueryIntent
    reformulated_query: str = Field(..., description="Optimized query string for vector similarity search.")
    target_kpi: Optional[str] = Field(None, description="Extracted KPI ID if referenced in query.")
    requires_diagnosis_json: bool = True
    requires_vector_docs: bool = True
    requires_data_rows: bool = False


class ChatRequest(BaseModel):
    question: str = Field(..., description="User question directed to the assistant.")
    diagnosis_json: Optional[Dict[str, Any]] = Field(default=None, description="Active diagnosis run object from the KPI engine.")
    active_kpi: str = Field(..., description="Active KPI identifier.")
    active_date: str = Field(..., description="Target date in YYYY-MM-DD format.")
    active_region: Optional[str] = Field(default="ALL")
    active_category: Optional[str] = Field(default="ALL")
    user_persona: Optional[str] = Field(default="analyst")
    user_access_tags: List[str] = Field(default_factory=lambda: ["public", "internal"])
    as_of_timestamp: str = Field(..., description="Cutoff timestamp for data availability (ISO 8601).")
    chat_history: Optional[List[Dict[str, str]]] = Field(default_factory=list)
    run_id: Optional[str] = Field(default=None, description="Saved diagnosis run identifier used to load the active diagnosis.")
    conversation_id: Optional[str] = Field(default=None, description="Existing conversation to append to.")


class ChatResponse(BaseModel):
    answer: str = Field(..., description="Grounded explanation adhering strictly to boundaries.")
    citations: List[Citation] = Field(..., description="Full list of local evidence sources used.")
    evidence_status: str = Field(..., description="Exact engine status label verbatim.")
    limitations: List[str] = Field(..., description="Known risks, gaps, or verification constraints.")
    suggested_followups: List[str] = Field(..., description="Safe, context-relevant follow-up prompts.")
