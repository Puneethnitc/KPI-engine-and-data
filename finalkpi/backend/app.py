from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.chat import grounded_chat
from backend.config import CORS_ORIGINS
from backend.ingest import ingest_kb
from backend.rag_pipeline import DynamicRAGPipeline
from backend.query_router import DynamicQueryRouter
from backend.retrieval import ContextBuilder
from backend.schemas import ChatRequest as RagChatRequest
from backend.service import DEMO_IDENTITY_MODE, authorize_scope, build_marketing_brief, diagnose_scope, get_available_filters, get_authorized_candidate_artifact, get_authorized_diagnosis, get_authorized_feedback_run, get_authorized_feedback_record, get_authorized_improvement_proposal, get_authorized_improvement_proposals, get_authorized_proposal_evaluation, get_current_kpi_contract, get_diagnosis, get_evidence, get_feedback, get_feedback_aggregations, get_investigations, get_insights, get_marketing, get_registered_kpis, get_run_kpi_contract, get_timeseries, identity_persona
from backend.domain_policy import require_domain, retrieval_tags_for_persona
from backend.response_projection import project_diagnosis, project_evidence, project_saved_run
from backend.feedback_learning import aggregate_feedback_records, build_improvement_proposal, proposal_change_idempotency_key
from backend.offline_learning import SUPPORTED_CANDIDATE_TYPES, broad_outcome_for_run, build_candidate_artifact, evaluation_gate_plan, required_holdout_claim_type, run_deterministic_evaluation
from backend.demo_scenarios import execute_demo_scenario, list_scenarios, validate_catalog
from backend.storage import append_feedback_event, append_improvement_proposal_event, append_message, append_security_audit_event, create_candidate_artifact, create_conversation, create_feedback_submission, create_improvement_proposal, find_improvement_proposal, get_candidate_artifact, get_candidate_for_proposal, get_conversation, get_feedback_submission, get_legacy_feedback, get_improvement_proposal, get_proposal_evaluation, get_runs_for_kpi, list_candidate_artifacts, list_proposal_evaluations, list_security_audit_events, record_proposal_evaluation, rollback_candidate_artifact, verify_security_audit_chain

app = FastAPI(title="KPI Engine Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

router = DynamicQueryRouter()
context_builder = ContextBuilder()
pipeline = DynamicRAGPipeline(router=router, context_builder=context_builder)


class DiagnosisRequest(BaseModel):
    kpis: List[str] = Field(default_factory=lambda: ["all"])
    target_date: Optional[str] = None
    region: Optional[str] = None
    category: Optional[str] = None
    persona: Optional[str] = None
    user_id: Optional[str] = None
    scope: Optional[Dict[str, Any]] = Field(default_factory=dict)
    as_of: Optional[str] = None
    scenario_id: Optional[str] = None


class DemoScenarioExecuteRequest(BaseModel):
    user_id: Optional[str] = None


class ChatRequest(BaseModel):
    run_id: Optional[str] = None
    conversation_id: Optional[str] = None
    question: str
    user_id: Optional[str] = None
    persona: Optional[str] = None
    diagnosis_json: Optional[Dict[str, Any]] = None
    active_kpi: Optional[str] = None
    active_date: Optional[str] = None
    active_region: Optional[str] = None
    active_category: Optional[str] = None
    scope: Optional[Dict[str, Any]] = Field(default_factory=dict)
    user_access_tags: List[str] = Field(default_factory=lambda: ["public", "internal"])
    as_of_timestamp: Optional[str] = None
    as_of: Optional[str] = None


class FeedbackMode(str, Enum):
    BUSINESS_FEEDBACK = "BUSINESS_FEEDBACK"
    ANALYST_CORRECTION = "ANALYST_CORRECTION"


class FeedbackTargetType(str, Enum):
    RUN = "RUN"
    KPI = "KPI"
    MOVEMENT = "MOVEMENT"
    RECONCILIATION = "RECONCILIATION"
    DRIVER = "DRIVER"
    CONTRIBUTION = "CONTRIBUTION"
    CONFIDENCE = "CONFIDENCE"
    NARRATIVE_CLAIM = "NARRATIVE_CLAIM"
    ACTION = "ACTION"


class BusinessRating(str, Enum):
    USEFUL = "USEFUL"
    NOT_USEFUL = "NOT_USEFUL"


class BusinessReason(str, Enum):
    ACTIONABLE = "ACTIONABLE"
    NOT_ACTIONABLE = "NOT_ACTIONABLE"
    INCORRECT = "INCORRECT"
    UNCLEAR = "UNCLEAR"
    TOO_LATE = "TOO_LATE"
    ALREADY_KNOWN = "ALREADY_KNOWN"
    OTHER = "OTHER"


class ActionTaken(str, Enum):
    YES = "YES"
    NO = "NO"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


class AnalystIssueCategory(str, Enum):
    DATA = "DATA"
    KPI_CONTRACT = "KPI_CONTRACT"
    BUSINESS_RULE = "BUSINESS_RULE"
    DRIVER = "DRIVER"
    ANALYTICAL_METHOD = "ANALYTICAL_METHOD"
    CONFIDENCE = "CONFIDENCE"
    NARRATIVE = "NARRATIVE"
    ACTION = "ACTION"
    ACCESS_POLICY = "ACCESS_POLICY"


class FeedbackSubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: FeedbackMode
    run_id: str = Field(min_length=1, max_length=128)
    user_id: Optional[str] = None
    target_type: FeedbackTargetType
    target_id: str = Field(min_length=1, max_length=200)
    rating: Optional[BusinessRating] = None
    reason_code: Optional[BusinessReason] = None
    comment: Optional[str] = Field(default=None, max_length=1000)
    action_taken: Optional[ActionTaken] = None
    outcome_observation: Optional[str] = Field(default=None, max_length=1000)
    issue_category: Optional[AnalystIssueCategory] = None
    correction_type: Optional[str] = Field(default=None, min_length=1, max_length=64)
    proposed_correction: Optional[str] = Field(default=None, min_length=1, max_length=2000)
    rationale: Optional[str] = Field(default=None, min_length=1, max_length=2000)
    evidence_refs: List[str] = Field(default_factory=list, max_length=50)

    @field_validator("comment", "outcome_observation", "proposed_correction", "rationale", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("target_id", mode="before")
    @classmethod
    def normalize_target_id(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("correction_type", mode="before")
    @classmethod
    def normalize_correction_type(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_mode_fields(self) -> "FeedbackSubmissionRequest":
        business_fields = (self.rating, self.reason_code, self.comment, self.action_taken, self.outcome_observation)
        analyst_fields = (self.issue_category, self.correction_type, self.proposed_correction, self.rationale)
        if self.mode == FeedbackMode.BUSINESS_FEEDBACK:
            if self.rating is None or any(value is not None for value in analyst_fields) or self.evidence_refs:
                raise ValueError("Business feedback requires a rating and cannot include analyst correction fields")
        else:
            if any(value is not None for value in business_fields) or any(value is None for value in analyst_fields):
                raise ValueError("Analyst correction requires issue category, correction type, proposed correction, and rationale")
        if any(not isinstance(ref, str) or not ref.strip() or len(ref) > 300 for ref in self.evidence_refs):
            raise ValueError("Evidence references must be non-blank paths of at most 300 characters")
        self.evidence_refs = [ref.strip() for ref in self.evidence_refs]
        return self


class FeedbackEventType(str, Enum):
    TRIAGED = "TRIAGED"
    REJECTED = "REJECTED"


class FeedbackEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: FeedbackEventType
    reason: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip() or None
        return value


class ImprovementProposalType(str, Enum):
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    KPI_CONTRACT_CHANGE = "KPI_CONTRACT_CHANGE"
    DATA_QUALITY_FIX = "DATA_QUALITY_FIX"
    DRIVER_CONFIGURATION_CHANGE = "DRIVER_CONFIGURATION_CHANGE"
    BUSINESS_RULE_CHANGE = "BUSINESS_RULE_CHANGE"
    ANALYTICAL_METHOD_REVIEW = "ANALYTICAL_METHOD_REVIEW"
    CONFIDENCE_POLICY_CHANGE = "CONFIDENCE_POLICY_CHANGE"
    NARRATIVE_TEMPLATE_CHANGE = "NARRATIVE_TEMPLATE_CHANGE"
    ACTION_POLICY_CHANGE = "ACTION_POLICY_CHANGE"
    ACCESS_POLICY_REVIEW = "ACCESS_POLICY_REVIEW"
    EVALUATION_CASE_ADDITION = "EVALUATION_CASE_ADDITION"


class ImprovementProposalCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: Optional[str] = None
    aggregation_key: Optional[str] = Field(default=None, min_length=1, max_length=80)
    feedback_ids: List[str] = Field(default_factory=list, max_length=100)
    proposal_type: ImprovementProposalType
    title: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1, max_length=2000)
    proposed_change: Optional[Dict[str, Any]] = None
    expected_improvement: str = Field(min_length=1, max_length=1000)
    affected_evaluation_cases: List[str] = Field(default_factory=list, max_length=50)
    rollback_plan: str = Field(min_length=1, max_length=1000)

    @field_validator("title", "rationale", "expected_improvement", "rollback_plan", mode="before")
    @classmethod
    def normalize_proposal_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_selection(self) -> "ImprovementProposalCreateRequest":
        if bool(self.aggregation_key) == bool(self.feedback_ids):
            raise ValueError("Provide exactly one aggregation_key or non-empty feedback_ids")
        if len(set(self.feedback_ids)) != len(self.feedback_ids):
            raise ValueError("feedback_ids must not contain duplicates")
        if any(not item.strip() or len(item) > 128 for item in self.feedback_ids):
            raise ValueError("feedback_ids must be non-blank bounded identifiers")
        if any(not item.strip() or len(item) > 128 for item in self.affected_evaluation_cases):
            raise ValueError("Evaluation case references must be non-blank bounded identifiers")
        if any(not value.strip() for value in (self.title, self.rationale, self.expected_improvement, self.rollback_plan)):
            raise ValueError("Proposal text fields must not be blank")
        self.affected_evaluation_cases = [item.strip() for item in self.affected_evaluation_cases]
        return self


class ImprovementProposalEventType(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ImprovementProposalEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: ImprovementProposalEventType
    reason: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_event_reason(cls, value: Any) -> Any:
        return value.strip() or None if isinstance(value, str) else value


class CandidateRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_rollback_reason(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


def _persona(user_id: Optional[str], requested: Optional[str] = None) -> str:
    try:
        if not user_id or not user_id.strip():
            raise ValueError("Missing demo identity")
        actual = identity_persona(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="A demo identity is required.") from exc
    if requested and requested != actual:
        raise HTTPException(status_code=403, detail="Persona is not authorized for this identity.")
    return actual


def _audit_security(
    *, user_id: Optional[str], persona: str, action: str, resource_type: str,
    decision: str, reason_code: str, resource_id: Optional[str] = None,
    scope: Optional[Dict[str, Any]] = None, status: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Audit failures never change the user operation, but remain test-visible."""
    try:
        append_security_audit_event(
            actor_user_id=user_id or "anonymous",
            actor_persona=persona,
            identity_mode=DEMO_IDENTITY_MODE,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            scope=scope or {},
            decision=decision,
            reason_code=reason_code,
            outcome_status=status,
            metadata=metadata,
        )
    except Exception:
        pass


def _execute_governed_scenario(scenario_id: str, user_id: Optional[str]) -> Dict[str, Any]:
    try:
        validate_catalog()
        payload = execute_demo_scenario(scenario_id, user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        if "demo identity" in str(exc).lower():
            raise HTTPException(status_code=401, detail="A demo identity is required.") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.get("observed_broad_outcome") == "ACCESS_DENIED":
        raise HTTPException(status_code=403, detail=payload)
    return payload


@app.on_event("startup")
async def startup_event() -> None:
    try:
        ingest_kb()
    except Exception:
        pass


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "retrieval_ready": False,
        "message": "Diagnosis backend ready; retrieval and chat use staged prototype fallback.",
    }


@app.get("/api/security-audit")
def api_security_audit(
    user_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """Reviewer-only, metadata-safe view of the append-only security trail."""
    persona = _persona(user_id)
    if persona != "CFO":
        _audit_security(
            user_id=user_id, persona=persona, action="AUDIT_READ",
            resource_type="SECURITY_AUDIT", decision="DENY",
            reason_code="REVIEWER_ROLE_REQUIRED", status=404,
        )
        raise HTTPException(status_code=404, detail="Audit records not found.")
    require_domain(persona, "FEEDBACK_REVIEW")
    items = list_security_audit_events(limit=limit, offset=offset)
    integrity = verify_security_audit_chain()
    _audit_security(
        user_id=user_id, persona=persona, action="AUDIT_READ",
        resource_type="SECURITY_AUDIT", decision="ALLOW",
        reason_code="AUTHORIZED_REVIEWER", status=200,
        metadata={"count": len(items)},
    )
    return {
        "items": items,
        "integrity": integrity,
        "identity_mode": DEMO_IDENTITY_MODE,
        "message": "Metadata-only audit view; business values and prompts are excluded.",
    }


@app.get("/api/kpis")
def api_kpis(
    user_id: Optional[str] = None,
    region: Optional[str] = None,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        _persona(user_id)
        return {"items": get_registered_kpis(user_id, region=region, category=category)}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        if "Unknown demo identity" in str(exc):
            raise HTTPException(status_code=401, detail="Demo authentication is required.") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/kpis/{kpi_id}/contract")
def api_kpi_contract(
    kpi_id: str,
    user_id: Optional[str] = None,
    region: Optional[str] = None,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        _persona(user_id)
        return get_current_kpi_contract(kpi_id, user_id, region=region, category=category)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="KPI contract not found") from exc
    except ValueError as exc:
        if "demo identity" in str(exc).lower():
            raise HTTPException(status_code=401, detail="A demo identity is required.") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/filters")
def api_filters() -> Dict[str, Any]:
    return get_available_filters()


@app.get("/api/demo-scenarios")
def api_demo_scenarios() -> Dict[str, Any]:
    validate_catalog()
    return {
        "items": list_scenarios(),
        "standard_view": {
            "scenario_id": None,
            "title": "Standard view",
            "purpose": "Choose region, category, date and persona manually. The engine still runs on production sources.",
        },
    }


@app.post("/api/demo-scenarios/{scenario_id}/execute")
def api_demo_scenario_execute(scenario_id: str, payload: DemoScenarioExecuteRequest = DemoScenarioExecuteRequest()) -> Dict[str, Any]:
    return _execute_governed_scenario(scenario_id, payload.user_id)


@app.post("/api/diagnoses")
def api_diagnoses(payload: DiagnosisRequest) -> Dict[str, Any]:
    try:
        if payload.scenario_id:
            return _execute_governed_scenario(payload.scenario_id, payload.user_id)
        persona = _persona(payload.user_id, payload.persona)
        response = diagnose_scope(
            kpis=payload.kpis,
            target_date=payload.target_date,
            region=payload.region,
            category=payload.category,
            persona=persona,
            scope=payload.scope,
            as_of=payload.as_of,
        )
        first_result = next(iter(response["results"].values()), {})
        segment = first_result.get("segment", {})
        response["marketing_brief"] = None if first_result.get("verdict") == "ACCESS_DENIED" else build_marketing_brief(response["results"], {
            "region": segment.get("region", payload.region),
            "category": segment.get("category", payload.category),
            "target_date": first_result.get("target_date", payload.target_date),
            "as_of": first_result.get("as_of", payload.as_of),
        }, persona=persona)
        response["results"] = {
            kpi_id: project_diagnosis(result, persona)
            for kpi_id, result in response["results"].items()
        }
        response["identity_mode"] = DEMO_IDENTITY_MODE
        _audit_security(
            user_id=payload.user_id, persona=persona, action="DIAGNOSIS_EXECUTE",
            resource_type="DIAGNOSIS", decision="ALLOW", reason_code="AUTHORIZED_SCOPE",
            scope={"region": payload.region, "category": payload.category}, status=200,
            metadata={"kpi_id": ",".join(payload.kpis), "target_date": payload.target_date},
        )
        return response
    except HTTPException as exc:
        _audit_security(
            user_id=payload.user_id, persona=payload.persona or "UNKNOWN",
            action="DIAGNOSIS_EXECUTE", resource_type="DIAGNOSIS", decision="DENY",
            reason_code="AUTHORIZATION_FAILED", scope={"region": payload.region, "category": payload.category},
            status=exc.status_code,
        )
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/diagnoses/{run_id}")
def api_diagnosis_run(run_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        _persona(user_id)
        result = get_authorized_diagnosis(run_id, user_id)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="A demo identity is required.") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Diagnosis run not found")
    return project_saved_run(result, identity_persona(user_id))


@app.get("/api/diagnoses/{run_id}/contract")
def api_diagnosis_contract(run_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        result = get_run_kpi_contract(run_id, user_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="Diagnosis contract not found") from exc
    except ValueError as exc:
        if "demo identity" in str(exc).lower():
            raise HTTPException(status_code=401, detail="A demo identity is required.") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Diagnosis run not found")
    return result


@app.get("/api/investigations")
def api_investigations(limit: int = 100, offset: int = 0, persona: Optional[str] = None, user_id: Optional[str] = None) -> Dict[str, Any]:
    _persona(user_id, persona)
    return get_investigations(limit=min(limit, 200), offset=max(offset, 0), user_id=user_id)


@app.get("/api/kpis/{kpi_id}/timeseries")
def api_timeseries(kpi_id: str, region: str = "North", category: str = "Electronics", user_id: Optional[str] = None, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
    try:
        _persona(user_id)
        return get_timeseries(kpi_id, region, category, user_id=user_id, start_date=start_date, end_date=end_date)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/diagnoses/{run_id}/evidence")
def api_evidence(run_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    persona = _persona(user_id)
    require_domain(persona, "CHAT_EVIDENCE")
    if get_authorized_diagnosis(run_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Evidence not found.")
    try: return project_evidence(get_evidence(run_id), persona)
    except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/insights")
def api_insights(limit: int = 50, offset: int = 0, persona: Optional[str] = None, user_id: Optional[str] = None) -> Dict[str, Any]:
    _persona(user_id, persona)
    return get_insights(limit=min(limit, 200), offset=max(offset, 0), user_id=user_id)


@app.get("/api/marketing")
def api_marketing(region: str = "North", category: str = "Electronics", user_id: Optional[str] = None, as_of: Optional[str] = None) -> Dict[str, Any]:
    try:
        persona = _persona(user_id)
        require_domain(persona, "MARKETING")
        authorize_scope(user_id, region, category)
        return get_marketing(region, category, as_of=as_of)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/chat")
def api_chat(payload: ChatRequest) -> Dict[str, Any]:
    try:
        actual_persona = _persona(payload.user_id, payload.persona)
        require_domain(actual_persona, "CHAT_EVIDENCE")
        if payload.run_id:
            saved = get_authorized_diagnosis(payload.run_id, payload.user_id)
            if saved is None:
                raise HTTPException(status_code=403, detail="Diagnosis run is not available to this identity.")
            run_record = saved.get("result", {})
            diagnosis_json = run_record if run_record else saved.get("diagnosis_json")
            active_kpi = payload.active_kpi or run_record.get("kpi_id") or saved.get("kpi_id")
            active_date = payload.active_date or run_record.get("target_date") or saved.get("target_date")
            active_region = payload.active_region or saved.get("scope", {}).get("region") or run_record.get("segment", {}).get("region") or (payload.scope or {}).get("region") or "ALL"
            active_category = payload.active_category or saved.get("scope", {}).get("category") or run_record.get("segment", {}).get("category") or (payload.scope or {}).get("category") or "ALL"
            as_of_timestamp = payload.as_of_timestamp or payload.as_of or run_record.get("as_of") or (payload.scope or {}).get("as_of") or "2023-07-25T12:00:00"
        else:
            diagnosis_json = payload.diagnosis_json
            if diagnosis_json is None:
                raise ValueError("Either run_id or diagnosis_json is required.")
            active_kpi = payload.active_kpi or diagnosis_json.get("kpi_id")
            active_date = payload.active_date or diagnosis_json.get("target_date")
            active_region = payload.active_region or diagnosis_json.get("segment", {}).get("region") or (payload.scope or {}).get("region") or "ALL"
            active_category = payload.active_category or diagnosis_json.get("segment", {}).get("category") or (payload.scope or {}).get("category") or "ALL"
            as_of_timestamp = payload.as_of_timestamp or payload.as_of or diagnosis_json.get("as_of") or (payload.scope or {}).get("as_of") or "2023-07-25T12:00:00"

            if active_region in {None, "ALL", "all"} or active_category in {None, "ALL", "all"}:
                raise ValueError("Runless chat requires an explicit authorized region and category.")
            authorize_scope(payload.user_id, str(active_region), str(active_category))

        diagnosis_json = project_diagnosis(diagnosis_json or {}, actual_persona)

        if not active_kpi or not active_date:
            raise ValueError("A valid active_kpi and active_date are required for grounded chat.")

        request = RagChatRequest(
            question=payload.question,
            diagnosis_json=diagnosis_json,
            active_kpi=active_kpi,
            active_date=active_date,
            active_region=active_region,
            active_category=active_category,
            user_persona=actual_persona,
            user_access_tags=retrieval_tags_for_persona(actual_persona),
            as_of_timestamp=as_of_timestamp,
            chat_history=[],
            run_id=payload.run_id,
            conversation_id=payload.conversation_id,
        )
        response = pipeline.run(request)

        if payload.run_id:
            conversation_id = payload.conversation_id or create_conversation(payload.run_id, payload.user_id, {
                "kpi_id": active_kpi,
                "region": active_region,
                "category": active_category,
                "as_of": as_of_timestamp,
                "persona": actual_persona,
            })
            append_message(conversation_id, "user", payload.question, response.citations)
            append_message(conversation_id, "assistant", response.answer, response.citations)
            response_dict = response.model_dump()
            response_dict["conversation_id"] = conversation_id
            response_dict["run_id"] = payload.run_id
            return response_dict
        return response.model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/conversations/{conversation_id}")
def api_conversation(conversation_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    _persona(user_id)
    result = get_conversation(conversation_id)
    if result is None or result.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if result.get("run_id") and get_authorized_diagnosis(result["run_id"], user_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return result


def _feedback_resolve_path(payload: Any, path: str) -> tuple[bool, Any]:
    current = payload
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdecimal() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False, None
    return True, current


def _feedback_target_exists(run: Dict[str, Any], target_type: FeedbackTargetType, target_id: str) -> bool:
    result = run.get("result") if isinstance(run.get("result"), dict) else {}
    if target_type == FeedbackTargetType.RUN:
        return target_id == run.get("run_id")
    if target_type == FeedbackTargetType.KPI:
        return target_id == run.get("kpi_id")
    if target_type == FeedbackTargetType.DRIVER:
        driver_ids = set()
        for path in ("driver_analysis.ranked_drivers", "driver_analysis.excluded_drivers", "correlational_candidates", "driver_exclusions"):
            found, entries = _feedback_resolve_path(result, path)
            if found and isinstance(entries, list):
                driver_ids.update(entry.get("driver_id") for entry in entries if isinstance(entry, dict))
        return target_id in driver_ids
    if target_type == FeedbackTargetType.ACTION:
        found, actions = _feedback_resolve_path(result, "decision_cards")
        if not found or not isinstance(actions, list):
            return False
        return any(
            isinstance(action, dict) and action.get("action_id") == target_id
            for action in actions
        ) or (target_id.isdecimal() and int(target_id) < len(actions))
    if target_type == FeedbackTargetType.NARRATIVE_CLAIM:
        found, claims = _feedback_resolve_path(result, "narrative_claims")
        if not found or not isinstance(claims, list):
            return False
        path = target_id if target_id.startswith("narrative_claims.") else f"narrative_claims.{target_id}"
        claim_found, claim = _feedback_resolve_path(result, path)
        return claim_found and isinstance(claim, dict)

    roots = {
        FeedbackTargetType.MOVEMENT: ("movement_assessment",),
        FeedbackTargetType.RECONCILIATION: ("reconciliation_verdict",),
        FeedbackTargetType.CONTRIBUTION: ("decomposition", "decomposition_status"),
        FeedbackTargetType.CONFIDENCE: ("confidence_profile", "confidence"),
    }[target_type]
    for root in roots:
        path = target_id if target_id == root or target_id.startswith(f"{root}.") else f"{root}.{target_id}"
        found, value = _feedback_resolve_path(result, path)
        if found and value is not None:
            return True
    return False


@app.post("/api/feedback")
def api_feedback(payload: FeedbackSubmissionRequest) -> Dict[str, Any]:
    try:
        persona = _persona(payload.user_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    run = get_authorized_diagnosis(payload.run_id, payload.user_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Feedback target not found.")
    if payload.mode == FeedbackMode.ANALYST_CORRECTION and persona != "CFO":
        raise HTTPException(status_code=404, detail="Feedback target not found.")
    if not _feedback_target_exists(run, payload.target_type, payload.target_id):
        raise HTTPException(status_code=422, detail="Feedback target is not present in the saved diagnosis.")
    if any(not _feedback_resolve_path(run.get("result", {}), reference)[0] for reference in payload.evidence_refs):
        raise HTTPException(status_code=422, detail="An evidence reference is not present in the saved diagnosis.")
    original_payload = payload.model_dump(mode="json", exclude={"user_id"})
    return create_feedback_submission(
        payload=original_payload,
        run=run,
        user_id=payload.user_id,
        persona=persona,
    )


@app.get("/api/feedback")
def api_feedback_list(user_id: Optional[str] = None) -> Dict[str, Any]:
    _persona(user_id)
    return get_feedback(user_id)


@app.get("/api/feedback/aggregations")
def api_feedback_aggregations(user_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        _persona(user_id)
    except HTTPException as exc:
        if exc.status_code == 401:
            raise
        raise HTTPException(status_code=404, detail="Feedback aggregations not found.") from exc
    return {"items": get_feedback_aggregations(user_id), "message": "Feedback aggregated"}


@app.get("/api/feedback/{feedback_id}")
def api_feedback_get(feedback_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    _persona(user_id)
    record = get_authorized_feedback_record(feedback_id, user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Feedback not found.")
    return record


@app.post("/api/feedback/{feedback_id}/events")
@app.patch("/api/feedback/{feedback_id}")
def api_feedback_review(feedback_id: str, payload: FeedbackEventRequest, user_id: Optional[str] = None) -> Dict[str, Any]:
    persona = _persona(user_id)
    try:
        require_domain(persona, "FEEDBACK_REVIEW")
    except PermissionError:
        raise HTTPException(status_code=404, detail="Feedback not found.")
    record = get_feedback_submission(feedback_id)
    if record is None:
        legacy_id = int(feedback_id) if feedback_id.isdecimal() else None
        legacy = get_legacy_feedback(legacy_id) if legacy_id is not None else None
        if legacy is None or get_authorized_feedback_run(legacy["run_id"], user_id) is None:
            raise HTTPException(status_code=404, detail="Feedback not found.")
        raise HTTPException(status_code=409, detail="Legacy feedback has no append-only lifecycle.")
    if get_authorized_feedback_run(record["run_id"], user_id) is None:
        raise HTTPException(status_code=404, detail="Feedback not found.")
    try:
        updated = append_feedback_event(
            feedback_id,
            payload.event_type.value,
            user_id,
            persona,
            payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Feedback not found.")
    return updated


def _normalized_proposal_change(payload: ImprovementProposalCreateRequest) -> Dict[str, Any] | None:
    if payload.proposal_type == ImprovementProposalType.REVIEW_REQUIRED:
        return {"review_question": "Review recurring feedback; no production change is proposed."}
    return payload.proposed_change


def _proposal_idempotent_replay(
    aggregation_key: str,
    payload: ImprovementProposalCreateRequest,
) -> Dict[str, Any] | None:
    proposed_change = _normalized_proposal_change(payload)
    if proposed_change is None:
        return None
    key = proposal_change_idempotency_key(
        aggregation_key, payload.proposal_type.value, proposed_change
    )
    existing = find_improvement_proposal(aggregation_key, key)
    if existing is None:
        return None
    authorized = get_authorized_improvement_proposal(existing["proposal_id"], payload.user_id)
    return {**authorized, "idempotent_replay": True} if authorized is not None else None


@app.post("/api/improvement-proposals")
def api_improvement_proposal_create(payload: ImprovementProposalCreateRequest) -> Dict[str, Any]:
    try:
        persona = _persona(payload.user_id)
    except HTTPException as exc:
        if exc.status_code == 401:
            raise
        raise HTTPException(status_code=404, detail="Proposal sources not found.") from exc
    if persona != "CFO":
        raise HTTPException(status_code=404, detail="Proposal sources not found.")
    require_domain(persona, "FEEDBACK_REVIEW")

    if payload.aggregation_key:
        replay = _proposal_idempotent_replay(payload.aggregation_key, payload)
        if replay is not None:
            return replay
        aggregation = next((
            item for item in get_feedback_aggregations(payload.user_id)
            if item["aggregation_key"] == payload.aggregation_key
        ), None)
        if aggregation is None:
            raise HTTPException(status_code=404, detail="Proposal sources not found.")
        feedback_ids = aggregation["source_feedback_ids"]
        records = [get_authorized_feedback_record(feedback_id, payload.user_id) for feedback_id in feedback_ids]
    else:
        feedback_ids = sorted(payload.feedback_ids)
        records = [get_authorized_feedback_record(feedback_id, payload.user_id) for feedback_id in feedback_ids]
        if any(record is None for record in records):
            raise HTTPException(status_code=404, detail="Proposal sources not found.")
        grouping_records = [{**record, "state": "CAPTURED"} for record in records]
        possible_aggregations = aggregate_feedback_records(grouping_records)
        if len(possible_aggregations) != 1 or possible_aggregations[0]["feedback_count"] != len(feedback_ids):
            raise HTTPException(status_code=422, detail="Selected feedback is not compatible for one proposal.")
        aggregation = possible_aggregations[0]

    if any(record is None for record in records):
        raise HTTPException(status_code=404, detail="Proposal sources not found.")
    try:
        proposal_payload, idempotency_key = build_improvement_proposal(
            proposal_type=payload.proposal_type.value,
            aggregation=aggregation,
            records=records,
            title=payload.title,
            rationale=payload.rationale,
            proposed_change=payload.proposed_change,
            expected_improvement=payload.expected_improvement,
            affected_evaluation_cases=payload.affected_evaluation_cases,
            rollback_plan=payload.rollback_plan,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    existing = _proposal_idempotent_replay(aggregation["aggregation_key"], payload)
    if existing is not None:
        return existing
    if any(record.get("state") not in {"CAPTURED", "TRIAGED"} for record in records):
        raise HTTPException(status_code=409, detail="Feedback is not available for a new proposal.")
    current_aggregations = aggregate_feedback_records(records)
    if len(current_aggregations) != 1 or current_aggregations[0]["aggregation_key"] != aggregation["aggregation_key"]:
        raise HTTPException(status_code=422, detail="Selected feedback is not compatible for one proposal.")
    try:
        created = create_improvement_proposal(
            aggregation_key=aggregation["aggregation_key"],
            idempotency_key=idempotency_key,
            proposal=proposal_payload,
            feedback_ids=feedback_ids,
            created_by=payload.user_id,
            created_persona=persona,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return created


@app.get("/api/improvement-proposals")
def api_improvement_proposal_list(user_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        persona = _persona(user_id)
    except HTTPException as exc:
        if exc.status_code == 401:
            raise
        raise HTTPException(status_code=404, detail="Proposals not found.") from exc
    if persona != "CFO":
        raise HTTPException(status_code=404, detail="Proposals not found.")
    require_domain(persona, "FEEDBACK_REVIEW")
    return {
        "items": get_authorized_improvement_proposals(user_id),
        "message": "Improvement proposals",
        "application_status": "Not yet applied",
        "verification_status": "Not yet verified",
    }


@app.get("/api/improvement-proposals/{proposal_id}")
def api_improvement_proposal_get(proposal_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        persona = _persona(user_id)
    except HTTPException as exc:
        if exc.status_code == 401:
            raise
        raise HTTPException(status_code=404, detail="Proposal not found.") from exc
    if persona != "CFO":
        raise HTTPException(status_code=404, detail="Proposal not found.")
    require_domain(persona, "FEEDBACK_REVIEW")
    proposal = get_authorized_improvement_proposal(proposal_id, user_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    return proposal


@app.post("/api/improvement-proposals/{proposal_id}/events")
def api_improvement_proposal_event(
    proposal_id: str,
    payload: ImprovementProposalEventRequest,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        persona = _persona(user_id)
    except HTTPException as exc:
        if exc.status_code == 401:
            raise
        raise HTTPException(status_code=404, detail="Proposal not found.") from exc
    if persona != "CFO":
        raise HTTPException(status_code=404, detail="Proposal not found.")
    require_domain(persona, "FEEDBACK_REVIEW")
    if get_authorized_improvement_proposal(proposal_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    try:
        proposal = append_improvement_proposal_event(
            proposal_id,
            payload.event_type.value,
            user_id,
            persona,
            payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    return proposal


def _proposal_source_runs(proposal: Dict[str, Any], user_id: str) -> list[Dict[str, Any]]:
    records = [get_authorized_feedback_record(feedback_id, user_id) for feedback_id in proposal.get("source_feedback_ids", [])]
    if not records or any(record is None or record.get("state") != "ACCEPTED" for record in records):
        raise HTTPException(status_code=409, detail="Accepted source feedback is no longer available.")
    run_ids = sorted(set(proposal.get("source_run_ids") or []))
    runs = [get_authorized_feedback_run(run_id, user_id) for run_id in run_ids]
    if not runs or any(run is None for run in runs):
        raise HTTPException(status_code=404, detail="Proposal sources not found.")
    expected_versions = proposal.get("current_artifact_versions") or {}
    expected_contract = expected_versions.get("contract") or {}
    expected_policy = expected_versions.get("policy") or {}
    expected_sources = set(expected_versions.get("source_data_versions") or [])
    if proposal.get("proposal_type") == "NARRATIVE_TEMPLATE_CHANGE":
        if proposal.get("before_version") != "approved_narrative_templates_v1":
            raise HTTPException(status_code=409, detail="Proposal base narrative template version changed.")
    elif proposal.get("proposal_type") == "EVALUATION_CASE_ADDITION":
        expected_before = ",".join(sorted(expected_sources)) or "UNKNOWN"
        if proposal.get("before_version") != expected_before:
            raise HTTPException(status_code=409, detail="Proposal base source version changed.")
    for run in runs:
        if run.get("kpi_id") != proposal.get("kpi_id") or run.get("scope") != proposal.get("scope"):
            raise HTTPException(status_code=409, detail="Proposal source scope changed.")
        if expected_contract.get("version") is not None and str(run.get("contract_version")) != str(expected_contract["version"]):
            raise HTTPException(status_code=409, detail="Proposal base contract version changed.")
        if expected_contract.get("hash") is not None and run.get("contract_hash") != expected_contract["hash"]:
            raise HTTPException(status_code=409, detail="Proposal base contract hash changed.")
        if expected_policy.get("version") is not None and str(run.get("policy_version")) != str(expected_policy["version"]):
            raise HTTPException(status_code=409, detail="Proposal base policy version changed.")
        if expected_policy.get("hash") is not None and run.get("policy_hash") != expected_policy["hash"]:
            raise HTTPException(status_code=409, detail="Proposal base policy hash changed.")
        if expected_sources and run.get("source_data_version") not in expected_sources:
            raise HTTPException(status_code=409, detail="Proposal source data version changed.")
    return runs


def _require_cfo(user_id: Optional[str]) -> str:
    try:
        persona = _persona(user_id)
    except HTTPException as exc:
        if exc.status_code == 401:
            raise
        raise HTTPException(status_code=404, detail="Candidate not found.") from exc
    if persona != "CFO":
        raise HTTPException(status_code=404, detail="Candidate not found.")
    return persona


def _same_scope_case_runs(proposal: Dict[str, Any], user_id: str, requested_ids: List[str]) -> list[Dict[str, Any]]:
    if not requested_ids:
        raise HTTPException(status_code=422, detail="At least one affected saved case is required.")
    if len(set(requested_ids)) != len(requested_ids):
        raise HTTPException(status_code=422, detail="Affected case IDs must be unique.")
    cases = []
    versions = proposal.get("current_artifact_versions") or {}
    contract = versions.get("contract") or {}
    policy = versions.get("policy") or {}
    source_versions = set(versions.get("source_data_versions") or [])
    for run_id in requested_ids:
        run = get_authorized_feedback_run(run_id, user_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Evaluation cases not found.")
        if run.get("kpi_id") != proposal.get("kpi_id") or run.get("scope") != proposal.get("scope"):
            raise HTTPException(status_code=422, detail="Evaluation cases must match the proposal KPI and governed scope.")
        if contract.get("version") is not None and str(run.get("contract_version")) != str(contract["version"]):
            raise HTTPException(status_code=409, detail="Evaluation case contract version does not match the proposal base.")
        if contract.get("hash") is not None and run.get("contract_hash") != contract["hash"]:
            raise HTTPException(status_code=409, detail="Evaluation case contract hash does not match the proposal base.")
        if policy.get("version") is not None and str(run.get("policy_version")) != str(policy["version"]):
            raise HTTPException(status_code=409, detail="Evaluation case policy version does not match the proposal base.")
        if policy.get("hash") is not None and run.get("policy_hash") != policy["hash"]:
            raise HTTPException(status_code=409, detail="Evaluation case policy hash does not match the proposal base.")
        if source_versions and run.get("source_data_version") not in source_versions:
            raise HTTPException(status_code=409, detail="Evaluation case source data version does not match the proposal base.")
        cases.append(run)
    return cases


def _select_holdout_runs(proposal: Dict[str, Any], user_id: str, excluded_ids: set[str], artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    target_claim_type = required_holdout_claim_type(artifact)
    available = []
    for run in get_runs_for_kpi(proposal["kpi_id"]):
        if run.get("run_id") in excluded_ids:
            continue
        try:
            authorized = _same_scope_case_runs(proposal, user_id, [run["run_id"]])[0]
        except HTTPException:
            continue
        if target_claim_type:
            claims = (_run_result(authorized).get("narrative_claims") or [])
            if not any(isinstance(claim, dict) and claim.get("claim_type") == target_claim_type for claim in claims):
                continue
        available.append(authorized)
    available.sort(key=lambda item: (item.get("target_date") or "", item.get("run_id") or ""))
    return available[:1]


def _run_result(run: Dict[str, Any]) -> Dict[str, Any]:
    result = run.get("result")
    return result if isinstance(result, dict) else {}


def _evaluation_case_context(proposal: Dict[str, Any], artifact: Dict[str, Any], user_id: str) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    requested_ids = proposal.get("affected_evaluation_cases") or proposal.get("source_run_ids") or []
    if proposal["proposal_type"] == "EVALUATION_CASE_ADDITION" and artifact["candidate_payload"]["input_run_id"] not in requested_ids:
        raise HTTPException(status_code=409, detail="Candidate evaluation case is not included in the declared affected cases.")
    affected_runs = _same_scope_case_runs(proposal, user_id, requested_ids)
    holdout_runs = _select_holdout_runs(proposal, user_id, {run["run_id"] for run in affected_runs}, artifact)
    return affected_runs, holdout_runs


def _evaluation_plan(proposal: Dict[str, Any], artifact: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    affected_runs, holdout_runs = _evaluation_case_context(proposal, artifact, user_id)

    def case_reference(run: Dict[str, Any]) -> Dict[str, Any]:
        result = _run_result(run)
        return {
            "run_id": run["run_id"],
            "target_date": result.get("target_date") or run.get("target_date"),
            "as_of": result.get("as_of") or run.get("as_of"),
        }

    return {
        "affected_cases": [case_reference(run) for run in affected_runs],
        "holdout_cases": [case_reference(run) for run in holdout_runs],
        "gates": evaluation_gate_plan(artifact),
        "evaluator_method": "frozen_saved_run_candidate_comparison",
        "evaluator_version": "1.0",
        "input_policy": "Baseline and candidate use the same immutable saved diagnosis snapshot and as-of timestamp.",
        "llm_gate_decision": False,
        "evaluation_only": True,
        "deployed": False,
    }


def _validate_narrative_candidate_source(proposal: Dict[str, Any], user_id: str, source_runs: List[Dict[str, Any]]) -> None:
    change = proposal.get("proposed_change") or {}
    record = get_authorized_feedback_record(change.get("source_feedback_id", ""), user_id)
    if record is None or record.get("mode") != "ANALYST_CORRECTION" or record.get("issue_category") != "NARRATIVE":
        raise ValueError("Narrative candidate needs an authorized narrative correction source")
    if record.get("proposed_correction") != change.get("proposed_wording"):
        raise ValueError("Candidate wording must match the accepted source correction")
    source_run = next((run for run in source_runs if run.get("run_id") == record.get("run_id")), None)
    if source_run is None or record.get("target_type") != "NARRATIVE_CLAIM":
        raise ValueError("Narrative correction target does not match the accepted proposal source")
    target_id = str(record.get("target_id") or "")
    index_text = target_id.rsplit(".", 1)[-1]
    if not index_text.isdecimal():
        raise ValueError("Narrative claim target cannot be resolved in the saved run")
    claims = _run_result(source_run).get("narrative_claims") or []
    index = int(index_text)
    if index >= len(claims) or not isinstance(claims[index], dict):
        raise ValueError("Narrative claim target cannot be resolved in the saved run")
    if claims[index].get("claim_type") != change.get("template_target"):
        raise ValueError("Candidate template target does not match the corrected narrative claim")


@app.post("/api/improvement-proposals/{proposal_id}/apply")
def api_apply_improvement_proposal(proposal_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    persona = _require_cfo(user_id)
    proposal = get_authorized_improvement_proposal(proposal_id, user_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    existing = get_candidate_for_proposal(proposal_id)
    if existing is not None:
        proposal_state = (get_authorized_improvement_proposal(proposal_id, user_id) or {}).get("state")
        if existing.get("rollback_status") == "ROLLED_BACK":
            return {
                **existing,
                "status": "ROLLED_BACK",
                "proposal_state": "ROLLED_BACK",
                "candidate_state": "ROLLED_BACK",
                "applied": True,
                "verified": existing.get("verified", False),
                "deployed": False,
                "evaluation_only": True,
                "message": "Candidate rolled back from evaluation consideration; live engine unchanged.",
                "idempotent_replay": True,
            }
        return {
            **existing,
            "status": "APPLIED",
            "proposal_state": proposal_state,
            "candidate_state": existing.get("candidate_state", proposal_state),
            "applied": True,
            "verified": proposal_state == "VERIFIED",
            "deployed": False,
            "evaluation_only": True,
            "message": "Candidate exists in evaluation workspace only; not deployed to the live engine.",
            "idempotent_replay": True,
        }
    if proposal.get("state") != "ACCEPTED":
        raise HTTPException(status_code=409, detail="Only an ACCEPTED proposal may be applied.")
    if proposal.get("proposal_type") not in SUPPORTED_CANDIDATE_TYPES:
        return {
            "status": "APPLICATION_NOT_SUPPORTED",
            "proposal_id": proposal_id,
            "proposal_state": "ACCEPTED",
            "candidate_state": "NOT_APPLIED",
            "applied": False,
            "verified": False,
            "deployed": False,
            "evaluation_only": True,
            "rollback_status": "NOT_ROLLED_BACK",
            "message": "Application is not supported for this proposal type; it remains ACCEPTED and unchanged.",
        }

    source_runs = _proposal_source_runs(proposal, user_id)
    if proposal["proposal_type"] == "EVALUATION_CASE_ADDITION":
        requested_ids = proposal.get("affected_evaluation_cases") or [source_runs[0]["run_id"]]
        affected_runs = _same_scope_case_runs(proposal, user_id, requested_ids)
        candidate_source_runs = [affected_runs[0]]
    else:
        requested_ids = proposal.get("affected_evaluation_cases") or proposal.get("source_run_ids") or []
        affected_runs = _same_scope_case_runs(proposal, user_id, requested_ids)
        candidate_source_runs = source_runs
    try:
        if proposal["proposal_type"] == "NARRATIVE_TEMPLATE_CHANGE":
            _validate_narrative_candidate_source(proposal, user_id, source_runs)
        artifact = build_candidate_artifact(proposal, candidate_source_runs)
        candidate = create_candidate_artifact(
            proposal_id=proposal_id,
            artifact=artifact,
            actor_user_id=user_id,
            actor_persona=persona,
        )
    except NotImplementedError:
        return {
            "status": "APPLICATION_NOT_SUPPORTED", "proposal_id": proposal_id,
            "proposal_state": "ACCEPTED", "candidate_state": "NOT_APPLIED", "applied": False, "verified": False,
            "deployed": False, "evaluation_only": True, "rollback_status": "NOT_ROLLED_BACK",
            "message": "Application is not supported for this proposal type; it remains ACCEPTED and unchanged.",
        }
    except Exception as exc:
        return {
            "status": "APPLICATION_FAILED", "proposal_id": proposal_id,
            "proposal_state": "ACCEPTED", "candidate_state": "NOT_APPLIED", "applied": False, "verified": False,
            "deployed": False, "evaluation_only": True, "rollback_status": "NOT_ROLLED_BACK",
            "failure_reason": str(exc) if isinstance(exc, ValueError) else "Candidate validation or persistence failed.",
            "message": "Candidate application failed; no APPLIED event or partial artifact was recorded.",
        }
    return {
        **candidate,
        "status": "APPLIED",
        "proposal_state": "APPLIED",
        "candidate_state": "APPLIED",
        "applied": True,
        "verified": False,
        "deployed": False,
        "evaluation_only": True,
        "rollback_status": "NOT_ROLLED_BACK",
        "message": "Candidate applied to evaluation workspace only; not deployed to the live engine.",
    }


@app.post("/api/improvement-proposals/{proposal_id}/evaluate")
def api_evaluate_improvement_proposal(proposal_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    persona = _require_cfo(user_id)
    proposal = get_authorized_improvement_proposal(proposal_id, user_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    if proposal.get("state") == "ROLLED_BACK":
        raise HTTPException(status_code=409, detail="A rolled-back candidate cannot be evaluated.")
    if proposal.get("state") in {"VERIFIED", "FAILED_VERIFICATION"}:
        prior_runs = list_proposal_evaluations(proposal_id)
        if prior_runs:
            return {**prior_runs[-1], "idempotent_replay": True}
        raise HTTPException(status_code=409, detail="Proposal is not eligible for evaluation.")
    if proposal.get("state") != "APPLIED":
        raise HTTPException(status_code=409, detail="Only an APPLIED candidate may be evaluated.")
    artifact = get_candidate_artifact(proposal.get("candidate_artifact_id") or "")
    if artifact is None or artifact.get("rollback_status") == "ROLLED_BACK":
        raise HTTPException(status_code=409, detail="Candidate is unavailable for evaluation.")
    _proposal_source_runs(proposal, user_id)
    affected_runs, holdout_runs = _evaluation_case_context(proposal, artifact, user_id)
    evaluation = run_deterministic_evaluation(
        proposal=proposal,
        artifact=artifact,
        affected_runs=affected_runs,
        holdout_runs=holdout_runs,
    )
    try:
        return record_proposal_evaluation(
            evaluation=evaluation,
            cases=evaluation["case_results"],
            actor_user_id=user_id,
            actor_persona=persona,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/candidate-artifacts")
def api_candidate_artifact_list(user_id: Optional[str] = None) -> Dict[str, Any]:
    _require_cfo(user_id)
    visible = []
    for artifact in list_candidate_artifacts():
        proposal = get_authorized_improvement_proposal(artifact["proposal_id"], user_id)
        if proposal is not None:
            visible.append(artifact)
    return {"items": visible, "deployed": False, "evaluation_only": True}


@app.get("/api/candidate-artifacts/{candidate_artifact_id}")
def api_candidate_artifact_get(candidate_artifact_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    _require_cfo(user_id)
    artifact = get_authorized_candidate_artifact(candidate_artifact_id, user_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    proposal = get_authorized_improvement_proposal(artifact["proposal_id"], user_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    return {**artifact, "proposal_state": proposal["state"], "evaluation_plan": _evaluation_plan(proposal, artifact, user_id)}


@app.get("/api/proposal-evaluations/{evaluation_run_id}")
def api_proposal_evaluation_get(evaluation_run_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    _require_cfo(user_id)
    evaluation = get_authorized_proposal_evaluation(evaluation_run_id, user_id)
    if evaluation is None:
        raise HTTPException(status_code=404, detail="Evaluation not found.")
    return evaluation


@app.post("/api/improvement-proposals/{proposal_id}/rollback")
def api_rollback_candidate(
    proposal_id: str,
    payload: CandidateRollbackRequest,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    persona = _require_cfo(user_id)
    proposal = get_authorized_improvement_proposal(proposal_id, user_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    candidate_id = proposal.get("candidate_artifact_id")
    if not candidate_id:
        raise HTTPException(status_code=409, detail="Proposal has no candidate to roll back.")
    try:
        candidate = rollback_candidate_artifact(
            proposal_id=proposal_id,
            candidate_artifact_id=candidate_id,
            actor_user_id=user_id,
            actor_persona=persona,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    return {
        **candidate,
        "proposal_state": "ROLLED_BACK",
        "candidate_state": "ROLLED_BACK",
        "applied": True,
        "verified": candidate.get("verified", False),
        "deployed": False,
        "evaluation_only": True,
        "rollback_status": "ROLLED_BACK",
        "message": "Candidate rolled back from evaluation consideration; live engine unchanged.",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=False)
