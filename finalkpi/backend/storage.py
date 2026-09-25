from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

from backend.config import DB_PATH


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
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
                metadata_json TEXT,
                review_status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
                reviewer TEXT,
                reviewed_at TEXT,
                target_type TEXT NOT NULL DEFAULT 'diagnosis',
                target_id TEXT,
                snapshot_json TEXT NOT NULL DEFAULT '{}'
            );
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(feedback)").fetchall()}
        if "review_status" not in columns:
            conn.execute("ALTER TABLE feedback ADD COLUMN review_status TEXT NOT NULL DEFAULT 'PENDING_REVIEW'")
        if "reviewer" not in columns:
            conn.execute("ALTER TABLE feedback ADD COLUMN reviewer TEXT")
        if "reviewed_at" not in columns:
            conn.execute("ALTER TABLE feedback ADD COLUMN reviewed_at TEXT")
        if "target_type" not in columns:
            conn.execute("ALTER TABLE feedback ADD COLUMN target_type TEXT NOT NULL DEFAULT 'diagnosis'")
        if "target_id" not in columns:
            conn.execute("ALTER TABLE feedback ADD COLUMN target_id TEXT")
        if "snapshot_json" not in columns:
            conn.execute("ALTER TABLE feedback ADD COLUMN snapshot_json TEXT NOT NULL DEFAULT '{}'")
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


def list_diagnosis_runs(*, limit: int = 100, offset: int = 0, persona: str | None = None) -> Dict[str, Any]:
    initialize_db()
    conn = _connect()
    try:
        where = "WHERE persona = ?" if persona else ""
        args: list[Any] = [persona] if persona else []
        total = conn.execute(f"SELECT COUNT(*) FROM diagnosis_runs {where}", args).fetchone()[0]
        rows = conn.execute(f"SELECT * FROM diagnosis_runs {where} ORDER BY created_at DESC", args).fetchall()
        run_ids = [row["run_id"] for row in rows]
        feedback_states: dict[str, str] = {}
        if run_ids:
            placeholders = ",".join("?" for _ in run_ids)
            feedback_rows = conn.execute(f"SELECT run_id, review_status FROM feedback WHERE run_id IN ({placeholders}) ORDER BY id DESC", run_ids).fetchall()
            feedback_states = {row["run_id"]: row["review_status"] for row in feedback_rows}
        items = []
        seen: set[tuple[Any, ...]] = set()
        for row in rows:
            fingerprint = (row["kpi_id"], row["persona"], row["region"], row["category"], row["target_date"], row["engine_version"], row["source_data_version"])
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            result = json.loads(row["result_json"])
            movement = result.get("movement_assessment") or {}
            action_status = next((card.get("status") for card in result.get("decision_cards", []) if card.get("status")), None)
            items.append({"run_id": row["run_id"], "kpi_id": row["kpi_id"], "target_date": row["target_date"], "created_at": row["created_at"], "persona": row["persona"], "scope": json.loads(row["scope_json"]), "engine_version": row["engine_version"], "source_data_version": row["source_data_version"], "result": result, "actual": movement.get("actual_value"), "expected": movement.get("expected_value"), "delta": movement.get("delta"), "is_material": movement.get("is_material", False), "detector_agreement": movement.get("detector_agreement"), "reconciliation_status": (result.get("reconciliation_verdict") or {}).get("status"), "verdict": result.get("verdict"), "confidence_status": (result.get("confidence") or {}).get("status"), "review_state": feedback_states.get(row["run_id"], action_status or "UNREVIEWED"), "owner": (result.get("decision_cards") or [{}])[0].get("owner", "Analytics")})
        return {"items": items, "total": total, "limit": limit, "offset": offset}
    finally:
        conn.close()


def find_diagnosis_run(*, kpi_id: str, target_date: str, persona: str, region: str, category: str, engine_version: str, source_data_version: str) -> Dict[str, Any] | None:
    initialize_db()
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM diagnosis_runs WHERE kpi_id = ? AND target_date = ? AND persona = ? AND region = ? AND category = ? AND engine_version = ? AND source_data_version = ? ORDER BY created_at DESC LIMIT 1", (kpi_id, target_date, persona, region, category, engine_version, source_data_version)).fetchone()
        if row is None:
            return None
        payload = dict(row); payload["scope"] = json.loads(payload["scope_json"]); payload["result"] = json.loads(payload["result_json"]); payload["access_context"] = json.loads(payload["access_context"])
        return payload
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


def save_feedback(run_id: str, user_id: str, kpi_id: str, feedback_type: str, comments: str, metadata: Dict[str, Any] | None = None, target_type: str = "diagnosis", target_id: str | None = None, snapshot: Dict[str, Any] | None = None) -> Dict[str, Any]:
    initialize_db()
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO feedback (run_id, user_id, kpi_id, feedback_type, comments, created_at, metadata_json, target_type, target_id, snapshot_json) VALUES (?, ?, ?, ?, ?, datetime('now'), ?, ?, ?, ?)",
            (run_id, user_id, kpi_id, feedback_type, comments, json.dumps(metadata or {}, sort_keys=True), target_type, target_id, json.dumps(snapshot or {}, sort_keys=True)),
        )
        conn.commit()
        feedback_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return {"id": feedback_id, "status": "PENDING_REVIEW", "run_id": run_id, "feedback_type": feedback_type}
    finally:
        conn.close()


def list_feedback() -> List[Dict[str, Any]]:
    initialize_db()
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM feedback ORDER BY id DESC").fetchall()
        return [{"id": row["id"], "run_id": row["run_id"], "user_id": row["user_id"], "kpi_id": row["kpi_id"], "feedback_type": row["feedback_type"], "comments": row["comments"], "created_at": row["created_at"], "status": row["review_status"], "reviewer": row["reviewer"], "reviewed_at": row["reviewed_at"], "target_type": row["target_type"], "target_id": row["target_id"], "snapshot": json.loads(row["snapshot_json"] or "{}"), "metadata": json.loads(row["metadata_json"] or "{}")} for row in rows]
    finally:
        conn.close()


def review_feedback(feedback_id: int, status: str, reviewer: str) -> Dict[str, Any] | None:
    if status not in {"ACCEPTED", "REJECTED"}:
        raise ValueError("Review status must be ACCEPTED or REJECTED")
    initialize_db()
    conn = _connect()
    try:
        cursor = conn.execute("UPDATE feedback SET review_status = ?, reviewer = ?, reviewed_at = datetime('now') WHERE id = ?", (status, reviewer, feedback_id))
        conn.commit()
        return {"id": feedback_id, "status": status, "reviewer": reviewer} if cursor.rowcount else None
    finally:
        conn.close()
