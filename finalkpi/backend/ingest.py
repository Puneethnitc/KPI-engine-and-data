from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd
import yaml

try:
    import chromadb
    from chromadb.utils import embedding_functions
except Exception:  # pragma: no cover
    chromadb = None
    embedding_functions = None

from backend.config import CHROMA_DIR, ENGINE_REGISTRY_DIR, EVIDENCE_CSV, ROOT


def _tag_string(value: Any) -> str:
    """Normalise a semicolon- or comma-separated tag list to Chroma's CSV form."""
    tags = [tag.strip().lower() for tag in str(value or "").replace(";", ",").split(",") if tag.strip()]
    return ",".join(sorted(set(tags)))


class KBIndexer:
    def __init__(self, db_path: str | None = None):
        # Stage 6-lite: ingest and retrieval previously wrote to two different
        # folders (backend/data/chroma and config.CHROMA_DIR), so every document
        # this class indexed was invisible to ContextBuilder. There is now one
        # store, config.CHROMA_DIR, and an explicit db_path may still override it
        # for tests and alternate deployments.
        self.db_path = db_path or str(CHROMA_DIR)
        if chromadb is None:
            self.client = None
            self.collection = None
            return
        Path(self.db_path).mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=self.db_path)
        self.ef = embedding_functions.DefaultEmbeddingFunction() if embedding_functions is not None else None
        self.collection = self.client.get_or_create_collection(
            name="kpi_knowledge_base",
            embedding_function=self.ef,
        )

    def process_yaml_contracts(self, dir_path: str):
        if self.collection is None:
            return
        yaml_files = glob.glob(os.path.join(dir_path, "**/*.yaml"), recursive=True) + glob.glob(os.path.join(dir_path, "**/*.yml"), recursive=True)
        chunks, ids, metadatas = [], [], []
        for file_path in yaml_files:
            with open(file_path, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
            kpi_id = str(data.get("kpi_id", os.path.basename(file_path).split(".")[0]))
            content = (
                f"KPI Contract: {data.get('name', kpi_id)}\n"
                f"ID: {kpi_id}\n"
                f"Definition: {data.get('definition', '')}\n"
                f"Formula: {data.get('formula', '')}\n"
                f"Unit: {data.get('unit', '')}\n"
                f"Aggregation Method: {data.get('aggregation_method', '')}\n"
                f"Materiality Thresholds: {data.get('materiality_thresholds', '')}\n"
                f"Source and Grain: {data.get('source_and_grain', '')}\n"
                f"Dimensions and Owner: {data.get('dimensions', '')}, Owner: {data.get('owner', '')}\n"
                f"Decomposition Spec: {data.get('decomposition_spec', '')}\n"
                f"Reconciliation Policy: {data.get('reconciliation_policy', '')}\n"
                f"Known Limitations: {data.get('limitations', '')}"
            )
            chunks.append(content)
            ids.append(f"contract_{kpi_id}")
            metadatas.append({
                "source": f"contract:{kpi_id}",
                "evidence_type": "kpi_contract",
                "kpi": kpi_id,
                "region": "ALL",
                "category": "ALL",
                "access_tags": "kpi_contract",
                "timestamp": "2026-01-01T00:00:00Z",
            })
        if chunks:
            self.collection.upsert(documents=chunks, ids=ids, metadatas=metadatas)

    def process_markdown_docs(self, dir_path: str):
        if self.collection is None:
            return
        md_files = glob.glob(os.path.join(dir_path, "**/*.md"), recursive=True)
        chunks, ids, metadatas = [], [], []
        for file_path in md_files:
            with open(file_path, "r", encoding="utf-8") as handle:
                text = handle.read()
            paragraphs = [part.strip() for part in text.split("\n\n") if len(part.strip()) > 30]
            for index, paragraph in enumerate(paragraphs):
                chunks.append(paragraph)
                ids.append(f"doc_{os.path.basename(file_path)}_{index}")
                metadatas.append({
                    "source": f"methodology:{os.path.basename(file_path)}:{index + 1}",
                    "evidence_type": "methodology_doc",
                    "line_ref": f"paragraph_{index + 1}",
                    "kpi": "all",
                    "region": "ALL",
                    "category": "ALL",
                    "access_tags": "public",
                    "timestamp": "2026-01-01T00:00:00Z",
                })
        if chunks:
            self.collection.upsert(documents=chunks, ids=ids, metadatas=metadatas)

    def process_csv_summaries(self, dir_path: str):
        # Raw CSV-wide summaries can cross KPI, region, and business-domain boundaries.
        # Governed diagnosis/query services remain the quantitative source for chat.
        return

    def process_evidence_documents(self, evidence_csv: str = EVIDENCE_CSV) -> Dict[str, Any]:
        """Stage 6-lite: index data/unstructured_evidence.csv into the shared store.

        The same availability, scope and entitlement columns the engine's
        EvidenceCorroborator filters on are carried into metadata, so
        retrieve_vector_chunks can apply the identical filter chain to the chat
        path. Injection-bearing documents are indexed too: they are still
        retrieved and then dropped by the filter, which is what makes that filter
        observable. A prompt-injection document is untrusted input to be
        excluded, not a secret to be hidden from the index.
        """
        if self.collection is None:
            return {"status": "skipped", "indexed": 0, "reason": "chromadb unavailable"}
        frame = pd.read_csv(evidence_csv, dtype=str).fillna("")
        required = {"doc_id", "date", "source_type", "region", "category", "text", "available_at", "access_tags", "driver_tags", "stance"}
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(
                f"{evidence_csv} is missing {missing}; run data/patches/enrich_evidence.py first"
            )

        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[Dict[str, Any]] = []
        for row in frame.to_dict("records"):
            doc_id = str(row["doc_id"]).strip()
            available_at = pd.to_datetime(row["available_at"], errors="coerce")
            if pd.isna(available_at):
                raise ValueError(f"Evidence document {doc_id} has an unparseable available_at")
            tags = _tag_string(row["access_tags"]) or "public"
            ids.append(doc_id)
            documents.append(str(row["text"]))
            metadatas.append({
                "source": f"evidence:{doc_id}",
                "evidence_type": "unstructured_evidence",
                "line_ref": str(row["source_type"]),
                "kpi": "all",
                "region": str(row["region"] or "ALL"),
                "category": str(row["category"] or "ALL"),
                # A document with no declared entitlement is readable by nobody.
                # Marking it public would silently grant access to every persona.
                "access_tags": tags if tags != "public" or str(row["access_tags"]).strip() else "unentitled",
                "timestamp": f"{available_at.date().isoformat()}T00:00:00Z",
                "available_at": str(row["available_at"]),
                "document_date": str(row["date"]),
                "driver_tags": _tag_string(row["driver_tags"]),
                "stance": str(row["stance"] or "neutral"),
            })
        if ids:
            self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        return {"status": "ok", "indexed": len(ids)}


def ingest_kb() -> Dict[str, Any]:
    indexer = KBIndexer()
    indexer.process_yaml_contracts(ENGINE_REGISTRY_DIR)
    indexer.process_markdown_docs(str(ROOT / "docs"))
    indexer.process_csv_summaries(str(ROOT / "data"))
    evidence = indexer.process_evidence_documents(EVIDENCE_CSV)
    return {
        "status": "ok",
        "collection": "kpi_knowledge_base",
        "chroma_dir": indexer.db_path,
        "evidence_documents": evidence,
        "retrieval_ready": indexer.collection is not None,
    }


if __name__ == "__main__":
    print(ingest_kb())
