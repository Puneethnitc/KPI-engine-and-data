from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Tuple

try:
    import chromadb
    from chromadb.utils import embedding_functions
except Exception:  # pragma: no cover
    chromadb = None
    embedding_functions = None

from backend.config import EVIDENCE_CSV, ROOT
from backend.schemas import ChatRequest, QueryIntent, RouterAnalysis


class ContextBuilder:
    def __init__(self, vector_db_path: str = "./backend/data/chroma"):
        self.client = None
        self.collection = None
        if chromadb is not None:
            self.client = chromadb.PersistentClient(path=vector_db_path)
            self.collection = self.client.get_or_create_collection(
                name="kpi_knowledge_base",
                embedding_function=(embedding_functions.DefaultEmbeddingFunction() if embedding_functions is not None else None),
            )

    def extract_priority_one_diagnosis(self, request: ChatRequest) -> Tuple[str, List[Dict[str, Any]]]:
        diagnosis = request.diagnosis_json or {}
        formatted_diag = f"""=== PRIORITY 1 CONTEXT: ACTIVE DIAGNOSIS RUN ===
Metadata:
  - KPI ID: {request.active_kpi}
  - Target Date: {request.active_date}
  - Region: {request.active_region}
  - Category: {request.active_category}
  - User Persona: {request.user_persona}
  - As-Of Timestamp: {request.as_of_timestamp}

Verdict & Movement:
  - Overall Verdict: {diagnosis.get('verdict', 'UNKNOWN')}
  - Actual: {diagnosis.get('movement_assessment', {}).get('actual_value')} | Expected Baseline: {diagnosis.get('movement_assessment', {}).get('expected_value')} | Delta: {diagnosis.get('movement_assessment', {}).get('delta')}
  - Is Material: {diagnosis.get('movement_assessment', {}).get('is_material')}

Reconciliation & Decomposition:
  - Reconciliation Status: {diagnosis.get('reconciliation_verdict', {}).get('status')}
  - Reconciliation Reason: {diagnosis.get('reconciliation_verdict', {}).get('details', {}).get('reason')}
  - Accounting Decomposition: {json.dumps(diagnosis.get('decomposition', {}))}
  - Identity Status: {diagnosis.get('decomposition_status')}

Correlational & Causal Analysis:
  - Correlational Candidates: {json.dumps(diagnosis.get('correlational_candidates', []))}
  - Exclusions: {json.dumps(diagnosis.get('driver_exclusions', []))}
  - Causal Verification Verdict: {diagnosis.get('causal_verdict')}
  - Causal Verification Reason: {diagnosis.get('causal_verification', {}).get('reason') if isinstance(diagnosis.get('causal_verification'), dict) else diagnosis.get('causal_verification')}
  - Evidence Status: {diagnosis.get('grounding_passed')}

Quality & Cards:
  - Narrative: {diagnosis.get('narrative')}
  - Decision Cards: {json.dumps(diagnosis.get('decision_cards', []))}
  - Grounding Status: {diagnosis.get('grounding_passed')}
"""
        citations = [{
            "source_path": f"engine/diagnosis_runs/{request.active_kpi}_{request.active_date}.json",
            "evidence_type": "diagnosis_json",
            "line_or_row_ref": "root",
            "kpi": request.active_kpi,
        }]
        return formatted_diag, citations

    def retrieve_vector_chunks(self, request: ChatRequest, analysis: RouterAnalysis, top_k: int = 4) -> Tuple[str, List[Dict[str, Any]]]:
        if self.collection is None:
            return "", []

        search_term = analysis.reformulated_query or request.question
        where_filter = None
        if analysis.intent == QueryIntent.KPI_CONTRACT:
            where_filter = {"evidence_type": "kpi_contract"}
        elif analysis.intent == QueryIntent.METHODOLOGY:
            where_filter = {"evidence_type": "methodology_doc"}

        results = self.collection.query(
            query_texts=[search_term],
            n_results=top_k,
            where=where_filter,
        )

        retrieved_text = []
        citations = []
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        for idx, doc in enumerate(documents):
            meta = metadatas[idx] if idx < len(metadatas) else {}
            chunk_tags = str(meta.get("access_tags", "public")).split(",")
            if not set(chunk_tags).intersection(set(request.user_access_tags)) and "public" not in chunk_tags:
                continue
            if meta.get("timestamp") and request.as_of_timestamp and meta["timestamp"] > request.as_of_timestamp:
                continue
            retrieved_text.append(f"--- RETRIEVED CHUNK [{meta.get('evidence_type')}] ---\nSource: {meta.get('source')}\n{doc}")
            citations.append({
                "source_path": meta.get("source"),
                "evidence_type": meta.get("evidence_type"),
                "line_or_row_ref": meta.get("line_ref", "N/A"),
                "kpi": meta.get("kpi"),
            })
        return "\n\n".join(retrieved_text), citations

    def build_dynamic_context(self, request: ChatRequest, analysis: RouterAnalysis) -> Tuple[str, List[Dict[str, Any]]]:
        context_parts = []
        all_citations = []

        if analysis.requires_diagnosis_json or analysis.intent == QueryIntent.DIAGNOSIS_EXPLANATION:
            diag_text, diag_cites = self.extract_priority_one_diagnosis(request)
            context_parts.append(diag_text)
            all_citations.extend(diag_cites)

        if analysis.requires_vector_docs and analysis.intent != QueryIntent.OUT_OF_SCOPE:
            vec_text, vec_cites = self.retrieve_vector_chunks(request, analysis)
            if vec_text:
                context_parts.append(f"=== RETRIEVED KNOWLEDGE BASE CONTEXT ===\n{vec_text}")
                all_citations.extend(vec_cites)

        return "\n\n".join(context_parts), all_citations


def _client():
    if chromadb is None:
        return None
    try:
        return chromadb.PersistentClient(path=str(ROOT / "backend" / "data" / "chroma"))
    except Exception:
        return None


def retrieval_available() -> bool:
    return _client() is not None


def _document_rows() -> List[Dict[str, Any]]:
    try:
        import pandas as pd

        df = pd.read_csv(EVIDENCE_CSV)
    except Exception:
        return []
    rows: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        text = str(row.get("text") or row.get("evidence_text") or row.get("summary") or row.get("content") or "").strip()
        if not text:
            continue
        rows.append(
            {
                "id": str(row.get("doc_id") or row.get("id") or row.get("source_id") or f"doc-{hashlib.sha1(text.encode()).hexdigest()[:12]}"),
                "text": text,
                "source": str(row.get("source") or row.get("document_name") or row.get("doc_id") or "unstructured_evidence"),
                "document_version": str(row.get("document_version") or "v1"),
                "evidence_type": str(row.get("evidence_type") or "evidence"),
                "kpi_id": str(row.get("kpi_id") or "all"),
                "region": str(row.get("region") or "ALL"),
                "category": str(row.get("category") or "ALL"),
                "date": str(row.get("date") or row.get("as_of") or ""),
            }
        )
    return rows


def ingest_documents(force: bool = False) -> Dict[str, Any]:
    client = _client()
    if chromadb is None or client is None:
        return {
            "status": "skipped",
            "retrieval_ready": False,
            "message": "ChromaDB is not installed in this environment.",
            "count": 0,
        }

    collection = client.get_or_create_collection(name="kpi_retrieval")
    rows = _document_rows()
    if not rows:
        return {"status": "ok", "retrieval_ready": True, "count": 0, "message": "No evidence rows were available."}

    ids = []
    docs = []
    metas = []
    for row in rows:
        stable_id = row["id"]
        ids.append(stable_id)
        docs.append(row["text"])
        metas.append({
            "source": row["source"],
            "document_version": row["document_version"],
            "evidence_type": row["evidence_type"],
            "kpi_id": row["kpi_id"],
            "region": row["region"],
            "category": row["category"],
            "date": row["date"],
        })

    existing = set(collection.get(include=["ids"]).get("ids", []))
    if force:
        collection.delete(where={})
    elif existing:
        collection.delete(ids=list(existing - set(ids)))
    if ids:
        collection.upsert(ids=ids, documents=docs, metadatas=metas)

    return {"status": "ok", "retrieval_ready": True, "count": len(rows), "message": "Ingestion completed."}


def retrieve_relevant_documents(*, query: str, kpi_id: str | None = None, region: str | None = None, category: str | None = None, date: str | None = None, limit: int = 5) -> List[Dict[str, Any]]:
    client = _client()
    if chromadb is None or client is None:
        return []
    collection = client.get_or_create_collection(name="kpi_retrieval")
    filters: Dict[str, Any] = {}
    if kpi_id:
        filters["kpi_id"] = {"$in": [kpi_id, "all"]}
    if region and region != "ALL":
        filters["region"] = {"$in": [region, "ALL"]}
    if category and category != "ALL":
        filters["category"] = {"$in": [category, "ALL"]}
    if date:
        filters["date"] = {"$in": [date, ""]}

    results = collection.query(query_texts=[query], n_results=limit, where=filters or None)
    ids = results.get("ids", [[]])[0]
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    entries = []
    for idx, _id in enumerate(ids):
        entries.append({
            "id": _id,
            "text": docs[idx],
            "metadata": metas[idx] if idx < len(metas) else {},
            "distance": distances[idx] if idx < len(distances) else None,
        })
    return entries
