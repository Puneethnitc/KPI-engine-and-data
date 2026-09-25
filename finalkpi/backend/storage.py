# IMPLEMENTATION HANDOFF — persisted runs and conversations
# Current: SQLite stores JSON runs, chat and feedback. Run created_at is copied
# from as_of; engine_version and source_data_version are fixed strings.
# Next: actual execution time, source snapshot/hash, contract/policy hash and query
# lineage must come from the prepared run. Preserve old records with an explicit
# schema migration. Keep transactional storage here while DuckDB serves analytics.
# Check: two source versions remain distinguishable; replay uses saved context;
# callers authorize saved-run/conversation reads and do not trust claimed tags.

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from backend.config import DB_PATH


def _connect() -> sqlite3.Connection:
    db_path = Path(DB_PATH)
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _stable_hash(value: Any) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _runtime_metadata(result: Dict[str, Any], scope: Dict[str, Any]) -> Dict[str, Any]:
    telemetry = result.get("telemetry") if isinstance(result.get("telemetry"), dict) else {}
    source_snapshot = result.get("source_snapshot") if isinstance(result.get("source_snapshot"), dict) else {}
    comparison_scope = result.get("comparison_scope") if isinstance(result.get("comparison_scope"), dict) else {}
    policy = result.get("policy") if isinstance(result.get("policy"), dict) else {}
    contract = result.get("contract") if isinstance(result.get("contract"), dict) else {}
    query_provenance = result.get("query_provenance") if isinstance(result.get("query_provenance"), dict) else {}

    if not comparison_scope and isinstance(result.get("resolved_scope"), dict):
        comparison_scope = result["resolved_scope"]
    if not comparison_scope:
        comparison_scope = {
            key: value for key, value in (scope or {}).items() if key not in {"persona", "as_of", "target_date"}
        }

    comparison_period = result.get("comparison_period")
    if isinstance(comparison_period, dict):
        pass
    elif isinstance(result.get("comparison_plan"), dict):
        comparison_period = result["comparison_plan"]
    elif comparison_scope:
        comparison_period = {
            "target_date": result.get("target_date") or scope.get("target_date"),
            "resolved_scope": comparison_scope,
            "history_days": result.get("history_days") or result.get("comparison_history_days"),
        }
    else:
        comparison_period = {
            "target_date": result.get("target_date") or scope.get("target_date"),
            "resolved_scope": comparison_scope,
        }

    execution_ms = (
        telemetry.get("execution_ms")
        or telemetry.get("execution_time_ms")
        or result.get("execution_ms")
        or result.get("execution_time_ms")
        or 0
    )
    executed_at = result.get("executed_at") or result.get("created_at") or datetime.now(timezone.utc).isoformat()
    as_of_cutoff = result.get("as_of_cutoff") or result.get("as_of") or scope.get("as_of") or scope.get("target_date")
    if not query_provenance and isinstance(telemetry.get("query_provenance"), dict):
        query_provenance = telemetry["query_provenance"]
    if not source_snapshot and isinstance(result.get("source_snapshot_metadata"), dict):
        source_snapshot = result["source_snapshot_metadata"]
    if not source_snapshot and isinstance(result.get("source_snapshot"), str):
        source_snapshot = {"id": result["source_snapshot"]}
    if not source_snapshot and isinstance(result.get("source_data"), dict):
        source_snapshot = result["source_data"]

    contract_version = (
        result.get("contract_version")
        or contract.get("version")
        or contract.get("contract_version")
        or "unknown"
    )
    contract_hash = (
        result.get("contract_hash")
        or _stable_hash(contract or {"kpi_id": result.get("kpi_id"), "source": result.get("source"), "aggregation": result.get("aggregation")})
        or "unknown"
    )
    policy_version = (
        result.get("policy_version")
        or policy.get("version")
        or policy.get("policy_version")
        or "unknown"
    )
    policy_hash = (
        result.get("policy_hash")
        or _stable_hash(policy or result.get("policy_snapshot") or result.get("movement_assessment") or result.get("causal_verification") or {})
        or "unknown"
    )
    source_snapshot_id = (
        source_snapshot.get("id")
        or source_snapshot.get("snapshot_id")
        or result.get("source_snapshot_id")
        or "unknown"
    )
    source_snapshot_hash = (
        source_snapshot.get("hash")
        or source_snapshot.get("snapshot_hash")
        or result.get("source_snapshot_hash")
        or _stable_hash(source_snapshot)
        or "unknown"
    )

    metadata = {
        "executed_at": executed_at,
        "execution_ms": int(execution_ms),
        "contract_version": contract_version,
        "contract_hash": contract_hash,
        "policy_version": policy_version,
        "policy_hash": policy_hash,
        "source_snapshot_id": source_snapshot_id,
        "source_snapshot_hash": source_snapshot_hash,
        "as_of_cutoff": as_of_cutoff,
        "comparison_scope": comparison_scope,
        "comparison_period": comparison_period,
        "query_provenance": query_provenance,
    }
    result["execution_metadata"] = metadata
    result["executed_at"] = executed_at
    result["as_of_cutoff"] = as_of_cutoff
    result["comparison_scope"] = comparison_scope
    result["comparison_period"] = comparison_period
    result["query_provenance"] = query_provenance
    result["resolved_scope"] = {
        key: value for key, value in (scope or {}).items() if key not in {"persona", "as_of"}
    }
    if telemetry is not None:
        telemetry["execution_ms"] = int(execution_ms)
        telemetry["query_provenance"] = query_provenance
        result["telemetry"] = telemetry
    if source_snapshot:
        result["source_snapshot"] = source_snapshot
    if policy:
        result["policy"] = policy
    if contract:
        result["contract"] = contract
    return metadata


def _ensure_diagnosis_runs_schema(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(diagnosis_runs)").fetchall()}
    additions = {
        "executed_at": "TEXT",
        "execution_ms": "INTEGER",
        "contract_version": "TEXT",
        "contract_hash": "TEXT",
        "policy_version": "TEXT",
        "policy_hash": "TEXT",
        "source_snapshot_id": "TEXT",
        "source_snapshot_hash": "TEXT",
        "as_of_cutoff": "TEXT",
        "comparison_scope_json": "TEXT",
        "query_provenance_json": "TEXT",
    }
    for name, sqlite_type in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE diagnosis_runs ADD COLUMN {name} {sqlite_type}")


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
        _ensure_diagnosis_runs_schema(conn)
        conn.commit()
    finally:
        conn.close()


def save_diagnosis_run(result: Dict[str, Any], *, scope: Dict[str, Any], access_context: Dict[str, Any]) -> Dict[str, Any]:
    initialize_db()
    conn = _connect()
    try:
        _ensure_diagnosis_runs_schema(conn)
        metadata = _runtime_metadata(result, scope)
        run_id = result.get("run_id")
        payload = {
            "run_id": run_id,
            "created_at": result.get("as_of") or result.get("target_date") or metadata["executed_at"],
            "kpi_id": result.get("kpi_id"),
            "target_date": result.get("target_date"),
            "as_of": result.get("as_of") or metadata["as_of_cutoff"],
            "persona": result.get("persona"),
            "region": scope.get("region"),
            "category": scope.get("category"),
            "scope_json": json.dumps(scope, sort_keys=True),
            "result_json": json.dumps(result, sort_keys=True),
            "engine_version": result.get("engine_version") or "kpi-engine-v1",
            "source_data_version": result.get("source_data_version") or "sales_daily:unknown",
            "access_context": json.dumps(access_context, sort_keys=True),
            "executed_at": metadata["executed_at"],
            "execution_ms": metadata["execution_ms"],
            "contract_version": metadata["contract_version"],
            "contract_hash": metadata["contract_hash"],
            "policy_version": metadata["policy_version"],
            "policy_hash": metadata["policy_hash"],
            "source_snapshot_id": metadata["source_snapshot_id"],
            "source_snapshot_hash": metadata["source_snapshot_hash"],
            "as_of_cutoff": metadata["as_of_cutoff"],
            "comparison_scope_json": json.dumps(metadata["comparison_scope"], sort_keys=True),
            "query_provenance_json": json.dumps(metadata["query_provenance"], sort_keys=True),
        }
        columns = [
            "run_id", "created_at", "kpi_id", "target_date", "as_of", "persona",
            "region", "category", "scope_json", "result_json", "engine_version",
            "source_data_version", "access_context", "executed_at", "execution_ms",
            "contract_version", "contract_hash", "policy_version", "policy_hash",
            "source_snapshot_id", "source_snapshot_hash", "as_of_cutoff",
            "comparison_scope_json", "query_provenance_json",
        ]
        placeholders = ", ".join(["?"] * len(columns))
        conn.execute(
            f"INSERT OR REPLACE INTO diagnosis_runs ({', '.join(columns)}) VALUES ({placeholders})",
            tuple(payload[column] for column in columns),
        )
        conn.commit()
        return result
    finally:
        conn.close()


def get_run(run_id: str) -> Dict[str, Any] | None:
    initialize_db()
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
        if "comparison_scope_json" in payload and payload["comparison_scope_json"] is not None:
            payload["comparison_scope"] = json.loads(payload["comparison_scope_json"])
        if "query_provenance_json" in payload and payload["query_provenance_json"] is not None:
            payload["query_provenance"] = json.loads(payload["query_provenance_json"])
        if "execution_ms" in payload:
            payload["execution_ms"] = payload["execution_ms"]
        return payload
    finally:
        conn.close()


def get_runs_for_kpi(kpi_id: str) -> List[Dict[str, Any]]:
    initialize_db()
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
                "execution_ms": row["execution_ms"] if "execution_ms" in row.keys() else None,
                "contract_version": row["contract_version"] if "contract_version" in row.keys() else None,
                "source_snapshot_id": row["source_snapshot_id"] if "source_snapshot_id" in row.keys() else None,
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
