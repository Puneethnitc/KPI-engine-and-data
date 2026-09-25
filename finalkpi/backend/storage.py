from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

from backend.config import DB_PATH


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_db() -> None:
    conn = _connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS diagnosis_runs (
                run_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                kpi_id TEXT NOT NULL,
                target_date TEXT NOT NULL,
                as_of TEXT NOT NULL,
                persona TEXT NOT NULL,
                region TEXT,
                category TEXT,
                scope_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                engine_version TEXT NOT NULL,
                source_data_version TEXT NOT NULL,
                access_context TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                context_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversation_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                message TEXT NOT NULL,
                citations_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                kpi_id TEXT NOT NULL,
                feedback_type TEXT NOT NULL,
                comments TEXT,
                created_at TEXT NOT NULL,
                metadata_json TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def save_diagnosis_run(result: Dict[str, Any], *, scope: Dict[str, Any], access_context: Dict[str, Any]) -> Dict[str, Any]:
    initialize_db()
    conn = _connect()
    try:
        run_id = result.get("run_id")
        payload = {
            "run_id": run_id,
            "created_at": result.get("as_of") or result.get("target_date"),
            "kpi_id": result.get("kpi_id"),
            "target_date": result.get("target_date"),
            "as_of": result.get("as_of"),
            "persona": result.get("persona"),
            "region": scope.get("region"),
            "category": scope.get("category"),
            "scope_json": json.dumps(scope, sort_keys=True),
            "result_json": json.dumps(result, sort_keys=True),
            "engine_version": "kpi-engine-v1",
            "source_data_version": "sales_daily:2023-01-01..2024-12-30",
            "access_context": json.dumps(access_context, sort_keys=True),
        }
        conn.execute(
            """
            INSERT OR REPLACE INTO diagnosis_runs (
                run_id, created_at, kpi_id, target_date, as_of, persona,
                region, category, scope_json, result_json, engine_version,
                source_data_version, access_context
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["run_id"],
                payload["created_at"],
                payload["kpi_id"],
                payload["target_date"],
                payload["as_of"],
                payload["persona"],
                payload["region"],
                payload["category"],
                payload["scope_json"],
                payload["result_json"],
                payload["engine_version"],
                payload["source_data_version"],
                payload["access_context"],
            ),
        )
        conn.commit()
        return result
    finally:
        conn.close()


def get_run(run_id: str) -> Dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM diagnosis_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        payload = dict(row)
        payload["scope"] = json.loads(payload["scope_json"])
        payload["result"] = json.loads(payload["result_json"])
        payload["access_context"] = json.loads(payload["access_context"])
        return payload
    finally:
        conn.close()


def get_runs_for_kpi(kpi_id: str) -> List[Dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM diagnosis_runs WHERE kpi_id = ? ORDER BY created_at DESC",
            (kpi_id,),
        ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "kpi_id": row["kpi_id"],
                "target_date": row["target_date"],
                "as_of": row["as_of"],
                "persona": row["persona"],
                "scope": json.loads(row["scope_json"]),
                "result": json.loads(row["result_json"]),
            }
            for row in rows
        ]
    finally:
        conn.close()


def create_conversation(run_id: str, user_id: str, context: Dict[str, Any]) -> str:
    initialize_db()
    import uuid

    conversation_id = f"conv-{uuid.uuid4().hex[:12]}"
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO conversations (conversation_id, run_id, user_id, created_at, updated_at, context_json) VALUES (?, ?, ?, datetime('now'), datetime('now'), ?)",
            (conversation_id, run_id, user_id, json.dumps(context, sort_keys=True)),
        )
        conn.commit()
        return conversation_id
    finally:
        conn.close()


def append_message(conversation_id: str, role: str, message: str, citations: List[Dict[str, Any]] | None = None) -> None:
    conn = _connect()
    try:
        safe_citations = []
        for item in citations or []:
            if hasattr(item, "model_dump"):
                safe_citations.append(item.model_dump())
            elif isinstance(item, dict):
                safe_citations.append(item)
            else:
                safe_citations.append({"source_path": str(item)})

        conn.execute(
            "INSERT INTO conversation_messages (conversation_id, role, message, citations_json, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
            (conversation_id, role, message, json.dumps(safe_citations, sort_keys=True)),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = datetime('now') WHERE conversation_id = ?",
            (conversation_id,),
        )
        conn.commit()
    finally:
        conn.close()


def get_conversation(conversation_id: str) -> Dict[str, Any] | None:
    conn = _connect()
    try:
        conversation = conn.execute(
            "SELECT * FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if conversation is None:
            return None
        rows = conn.execute(
            "SELECT * FROM conversation_messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()
        return {
            "conversation_id": conversation["conversation_id"],
            "run_id": conversation["run_id"],
            "user_id": conversation["user_id"],
            "context": json.loads(conversation["context_json"]),
            "messages": [
                {
                    "role": row["role"],
                    "message": row["message"],
                    "citations": json.loads(row["citations_json"] or "[]"),
                    "created_at": row["created_at"],
                }
                for row in rows
            ],
        }
    finally:
        conn.close()


def save_feedback(run_id: str, user_id: str, kpi_id: str, feedback_type: str, comments: str, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
    initialize_db()
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO feedback (run_id, user_id, kpi_id, feedback_type, comments, created_at, metadata_json) VALUES (?, ?, ?, ?, ?, datetime('now'), ?)",
            (run_id, user_id, kpi_id, feedback_type, comments, json.dumps(metadata or {}, sort_keys=True)),
        )
        conn.commit()
        return {"status": "stored", "run_id": run_id, "feedback_type": feedback_type}
    finally:
        conn.close()
