from __future__ import annotations

import glob
import os
from typing import Any, Dict, List

import pandas as pd
import yaml

try:
    import chromadb
    from chromadb.utils import embedding_functions
except Exception:  # pragma: no cover
    chromadb = None
    embedding_functions = None

from backend.config import ENGINE_REGISTRY_DIR, EVIDENCE_CSV, ROOT


class KBIndexer:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(ROOT / "backend" / "data" / "chroma")
        if chromadb is None:
            self.client = None
            self.collection = None
            return
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
                "source": file_path,
                "evidence_type": "kpi_contract",
                "kpi": kpi_id,
                "access_tags": "public,internal",
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
                    "source": file_path,
                    "evidence_type": "methodology_doc",
                    "line_ref": f"paragraph_{index + 1}",
                    "kpi": "all",
                    "access_tags": "public,internal",
                    "timestamp": "2026-01-01T00:00:00Z",
                })
        if chunks:
            self.collection.upsert(documents=chunks, ids=ids, metadatas=metadatas)

    def process_csv_summaries(self, dir_path: str):
        if self.collection is None:
            return
        csv_files = glob.glob(os.path.join(dir_path, "**/*.csv"), recursive=True)
        chunks, ids, metadatas = [], [], []
        for file_path in csv_files:
            try:
                df = pd.read_csv(file_path, nrows=200)
                summary = (
                    f"Dataset Summary: {os.path.basename(file_path)}\n"
                    f"Columns: {', '.join(df.columns)}\n"
                    f"Scanned Sample Rows: {len(df)}\n"
                    f"Stats Overview:\n{df.describe(include='all').to_string()[:800]}"
                )
                chunks.append(summary)
                ids.append(f"csv_{os.path.basename(file_path)}")
                metadatas.append({
                    "source": file_path,
                    "evidence_type": "data_summary",
                    "kpi": "all",
                    "access_tags": "internal",
                    "timestamp": "2026-01-01T00:00:00Z",
                })
            except Exception:
                continue
        if chunks:
            self.collection.upsert(documents=chunks, ids=ids, metadatas=metadatas)


def ingest_kb() -> Dict[str, Any]:
    indexer = KBIndexer()
    indexer.process_yaml_contracts(ENGINE_REGISTRY_DIR)
    indexer.process_markdown_docs(str(ROOT / "docs"))
    indexer.process_csv_summaries(str(ROOT / "data"))
    return {"status": "ok", "collection": "kpi_knowledge_base", "retrieval_ready": indexer.collection is not None}


if __name__ == "__main__":
    print(ingest_kb())
