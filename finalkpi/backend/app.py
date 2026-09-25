from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.chat import grounded_chat
from backend.ingest import ingest_kb
from backend.rag_pipeline import DynamicRAGPipeline
from backend.query_router import DynamicQueryRouter
from backend.retrieval import ContextBuilder
from backend.schemas import ChatRequest as RagChatRequest
from backend.service import diagnose_scope, get_available_filters, get_diagnosis, get_registered_kpis
from backend.storage import append_message, create_conversation, get_conversation, save_feedback

app = FastAPI(title="KPI Engine Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

router = DynamicQueryRouter()
context_builder = ContextBuilder(vector_db_path="./backend/data/chroma")
pipeline = DynamicRAGPipeline(router=router, context_builder=context_builder)


class DiagnosisRequest(BaseModel):
    kpis: List[str] = Field(default_factory=lambda: ["all"])
    target_date: Optional[str] = None
    region: Optional[str] = None
    category: Optional[str] = None
    persona: str = "CFO"
    scope: Optional[Dict[str, Any]] = Field(default_factory=dict)
    as_of: Optional[str] = None


class ChatRequest(BaseModel):
    run_id: Optional[str] = None
    conversation_id: Optional[str] = None
    question: str
    user_id: str = "demo-user"
    persona: str = "CFO"
    diagnosis_json: Optional[Dict[str, Any]] = None
    active_kpi: Optional[str] = None
    active_date: Optional[str] = None
    active_region: Optional[str] = None
    active_category: Optional[str] = None
    scope: Optional[Dict[str, Any]] = Field(default_factory=dict)
    user_access_tags: List[str] = Field(default_factory=lambda: ["public", "internal"])
    as_of_timestamp: Optional[str] = None
    as_of: Optional[str] = None


class FeedbackRequest(BaseModel):
    run_id: str
    user_id: str = "demo-user"
    kpi_id: str
    feedback_type: str
    comments: str = ""
    metadata: Optional[Dict[str, Any]] = None


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


@app.get("/api/kpis")
def api_kpis() -> Dict[str, Any]:
    return {"items": get_registered_kpis()}


@app.get("/api/filters")
def api_filters() -> Dict[str, Any]:
    return get_available_filters()


@app.post("/api/diagnoses")
def api_diagnoses(payload: DiagnosisRequest) -> Dict[str, Any]:
    try:
        return diagnose_scope(
            kpis=payload.kpis,
            target_date=payload.target_date,
            region=payload.region,
            category=payload.category,
            persona=payload.persona,
            scope=payload.scope,
            as_of=payload.as_of,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/diagnoses/{run_id}")
def api_diagnosis_run(run_id: str) -> Dict[str, Any]:
    result = get_diagnosis(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Diagnosis run not found")
    return result


@app.post("/api/chat")
def api_chat(payload: ChatRequest) -> Dict[str, Any]:
    try:
        if payload.run_id:
            saved = get_diagnosis(payload.run_id)
            if saved is None:
                raise ValueError(f"Unknown diagnosis run_id: {payload.run_id}")
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

        if not active_kpi or not active_date:
            raise ValueError("A valid active_kpi and active_date are required for grounded chat.")

        request = RagChatRequest(
            question=payload.question,
            diagnosis_json=diagnosis_json,
            active_kpi=active_kpi,
            active_date=active_date,
            active_region=active_region,
            active_category=active_category,
            user_persona=payload.persona,
            user_access_tags=payload.user_access_tags,
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
                "persona": payload.persona,
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
def api_conversation(conversation_id: str) -> Dict[str, Any]:
    result = get_conversation(conversation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return result


@app.post("/api/feedback")
def api_feedback(payload: FeedbackRequest) -> Dict[str, Any]:
    try:
        return save_feedback(
            run_id=payload.run_id,
            user_id=payload.user_id,
            kpi_id=payload.kpi_id,
            feedback_type=payload.feedback_type,
            comments=payload.comments,
            metadata=payload.metadata,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=False)
