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
from uuid import uuid4

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
        or telemetry.get("total_latency_ms")
        or result.get("execution_ms")
        or result.get("execution_time_ms")
        or 0
    )
    executed_at = result.get("executed_at") or telemetry.get("completed_at") or result.get("created_at") or datetime.now(timezone.utc).isoformat()
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
        "contract_snapshot_json": "TEXT",
    }
    for name, sqlite_type in additions.items():
        if name not in columns:
            try:
                conn.execute(f"ALTER TABLE diagnosis_runs ADD COLUMN {name} {sqlite_type}")
            except sqlite3.OperationalError as error:
                if "duplicate column name" not in str(error).lower():
                    raise


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

            CREATE TABLE IF NOT EXISTS feedback_submissions (
                feedback_id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                run_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                persona TEXT NOT NULL,
                kpi_id TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                scope_json TEXT NOT NULL,
                target_date TEXT,
                source_data_version TEXT,
                source_snapshot_id TEXT,
                source_snapshot_hash TEXT,
                contract_version TEXT,
                contract_hash TEXT,
                policy_version TEXT,
                policy_hash TEXT,
                run_snapshot_hash TEXT NOT NULL,
                rating TEXT,
                reason_code TEXT,
                comment TEXT,
                action_taken TEXT,
                outcome_observation TEXT,
                issue_category TEXT,
                correction_type TEXT,
                proposed_correction TEXT,
                rationale TEXT,
                evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                original_payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS feedback_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                feedback_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                from_state TEXT,
                to_state TEXT NOT NULL,
                actor_user_id TEXT NOT NULL,
                actor_persona TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (feedback_id) REFERENCES feedback_submissions(feedback_id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS improvement_proposals (
                proposal_id TEXT PRIMARY KEY,
                aggregation_key TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                kpi_id TEXT NOT NULL,
                scope_json TEXT NOT NULL,
                target_artifact_type TEXT NOT NULL,
                before_version TEXT NOT NULL,
                before_version_hash TEXT,
                created_by TEXT NOT NULL,
                created_persona TEXT NOT NULL,
                created_at TEXT NOT NULL,
                proposal_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS improvement_proposal_feedback (
                proposal_id TEXT NOT NULL,
                feedback_id TEXT NOT NULL,
                linked_at TEXT NOT NULL,
                PRIMARY KEY (proposal_id, feedback_id),
                FOREIGN KEY (proposal_id) REFERENCES improvement_proposals(proposal_id) ON DELETE RESTRICT,
                FOREIGN KEY (feedback_id) REFERENCES feedback_submissions(feedback_id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS improvement_proposal_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                from_state TEXT,
                to_state TEXT NOT NULL,
                actor_user_id TEXT NOT NULL,
                actor_persona TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (proposal_id) REFERENCES improvement_proposals(proposal_id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS candidate_artifacts (
                candidate_artifact_id TEXT PRIMARY KEY,
                proposal_id TEXT NOT NULL UNIQUE,
                artifact_type TEXT NOT NULL,
                kpi_id TEXT NOT NULL,
                scope_json TEXT NOT NULL,
                base_version TEXT NOT NULL,
                candidate_version TEXT NOT NULL UNIQUE,
                base_payload_json TEXT NOT NULL,
                validated_change_json TEXT NOT NULL,
                candidate_payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                activation_status TEXT NOT NULL CHECK (activation_status = 'EVALUATION_ONLY'),
                rollback_of TEXT,
                supersedes TEXT,
                FOREIGN KEY (proposal_id) REFERENCES improvement_proposals(proposal_id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS candidate_artifact_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_artifact_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor_user_id TEXT NOT NULL,
                actor_persona TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (candidate_artifact_id) REFERENCES candidate_artifacts(candidate_artifact_id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS proposal_evaluation_runs (
                evaluation_run_id TEXT PRIMARY KEY,
                proposal_id TEXT NOT NULL,
                candidate_artifact_id TEXT NOT NULL,
                baseline_artifact_version TEXT NOT NULL,
                candidate_artifact_version TEXT NOT NULL,
                affected_cases_json TEXT NOT NULL,
                holdout_cases_json TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                gates_json TEXT NOT NULL,
                baseline_results_json TEXT NOT NULL,
                candidate_results_json TEXT NOT NULL,
                case_differences_json TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                evaluator_method TEXT NOT NULL,
                evaluator_version TEXT NOT NULL,
                final_result TEXT NOT NULL CHECK (final_result IN ('VERIFIED', 'FAILED_VERIFICATION')),
                failure_reasons_json TEXT NOT NULL,
                inputs_hash TEXT NOT NULL,
                FOREIGN KEY (proposal_id) REFERENCES improvement_proposals(proposal_id) ON DELETE RESTRICT,
                FOREIGN KEY (candidate_artifact_id) REFERENCES candidate_artifacts(candidate_artifact_id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS evaluation_case_results (
                evaluation_run_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                case_kind TEXT NOT NULL,
                input_run_id TEXT NOT NULL,
                input_snapshot_hash TEXT NOT NULL,
                as_of TEXT,
                baseline_result_json TEXT NOT NULL,
                candidate_result_json TEXT NOT NULL,
                differences_json TEXT NOT NULL,
                gate_results_json TEXT NOT NULL,
                PRIMARY KEY (evaluation_run_id, case_id),
                FOREIGN KEY (evaluation_run_id) REFERENCES proposal_evaluation_runs(evaluation_run_id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS security_audit_events (
                event_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                audit_event_id TEXT NOT NULL UNIQUE,
                occurred_at TEXT NOT NULL,
                actor_user_id TEXT NOT NULL,
                actor_persona TEXT NOT NULL,
                identity_mode TEXT NOT NULL,
                action TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id TEXT,
                scope_json TEXT NOT NULL,
                decision TEXT NOT NULL CHECK (decision IN ('ALLOW', 'DENY')),
                reason_code TEXT NOT NULL,
                outcome_status INTEGER,
                correlation_id TEXT,
                metadata_json TEXT NOT NULL,
                previous_event_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL UNIQUE
            );

            CREATE INDEX IF NOT EXISTS idx_feedback_submissions_run
                ON feedback_submissions(run_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_feedback_submissions_user
                ON feedback_submissions(user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_feedback_events_feedback
                ON feedback_events(feedback_id, event_id);

            CREATE INDEX IF NOT EXISTS idx_improvement_proposals_scope
                ON improvement_proposals(kpi_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_improvement_proposal_events
                ON improvement_proposal_events(proposal_id, event_id);
            CREATE INDEX IF NOT EXISTS idx_improvement_proposal_feedback_id
                ON improvement_proposal_feedback(feedback_id);
            CREATE INDEX IF NOT EXISTS idx_candidate_artifacts_proposal
                ON candidate_artifacts(proposal_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_proposal_evaluation_proposal
                ON proposal_evaluation_runs(proposal_id, started_at);
            CREATE INDEX IF NOT EXISTS idx_security_audit_actor
                ON security_audit_events(actor_user_id, occurred_at);
            CREATE INDEX IF NOT EXISTS idx_security_audit_resource
                ON security_audit_events(resource_type, resource_id, occurred_at);

            CREATE TRIGGER IF NOT EXISTS feedback_submissions_immutable_update
            BEFORE UPDATE ON feedback_submissions
            BEGIN
                SELECT RAISE(ABORT, 'feedback submissions are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS feedback_submissions_immutable_delete
            BEFORE DELETE ON feedback_submissions
            BEGIN
                SELECT RAISE(ABORT, 'feedback submissions are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS feedback_events_immutable_update
            BEFORE UPDATE ON feedback_events
            BEGIN
                SELECT RAISE(ABORT, 'feedback events are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS feedback_events_immutable_delete
            BEFORE DELETE ON feedback_events
            BEGIN
                SELECT RAISE(ABORT, 'feedback events are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS improvement_proposals_immutable_update
            BEFORE UPDATE ON improvement_proposals
            BEGIN
                SELECT RAISE(ABORT, 'improvement proposals are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS improvement_proposals_immutable_delete
            BEFORE DELETE ON improvement_proposals
            BEGIN
                SELECT RAISE(ABORT, 'improvement proposals are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS improvement_proposal_feedback_immutable_update
            BEFORE UPDATE ON improvement_proposal_feedback
            BEGIN
                SELECT RAISE(ABORT, 'improvement proposal links are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS improvement_proposal_feedback_immutable_delete
            BEFORE DELETE ON improvement_proposal_feedback
            BEGIN
                SELECT RAISE(ABORT, 'improvement proposal links are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS improvement_proposal_events_immutable_update
            BEFORE UPDATE ON improvement_proposal_events
            BEGIN
                SELECT RAISE(ABORT, 'improvement proposal events are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS improvement_proposal_events_immutable_delete
            BEFORE DELETE ON improvement_proposal_events
            BEGIN
                SELECT RAISE(ABORT, 'improvement proposal events are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS candidate_artifacts_immutable_update
            BEFORE UPDATE ON candidate_artifacts
            BEGIN
                SELECT RAISE(ABORT, 'candidate artifacts are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS candidate_artifacts_immutable_delete
            BEFORE DELETE ON candidate_artifacts
            BEGIN
                SELECT RAISE(ABORT, 'candidate artifacts are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS candidate_artifact_events_immutable_update
            BEFORE UPDATE ON candidate_artifact_events
            BEGIN
                SELECT RAISE(ABORT, 'candidate artifact events are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS candidate_artifact_events_immutable_delete
            BEFORE DELETE ON candidate_artifact_events
            BEGIN
                SELECT RAISE(ABORT, 'candidate artifact events are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS proposal_evaluation_runs_immutable_update
            BEFORE UPDATE ON proposal_evaluation_runs
            BEGIN
                SELECT RAISE(ABORT, 'proposal evaluation runs are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS proposal_evaluation_runs_immutable_delete
            BEFORE DELETE ON proposal_evaluation_runs
            BEGIN
                SELECT RAISE(ABORT, 'proposal evaluation runs are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS evaluation_case_results_immutable_update
            BEFORE UPDATE ON evaluation_case_results
            BEGIN
                SELECT RAISE(ABORT, 'evaluation case results are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS evaluation_case_results_immutable_delete
            BEFORE DELETE ON evaluation_case_results
            BEGIN
                SELECT RAISE(ABORT, 'evaluation case results are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS security_audit_events_immutable_update
            BEFORE UPDATE ON security_audit_events
            BEGIN
                SELECT RAISE(ABORT, 'security audit events are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS security_audit_events_immutable_delete
            BEFORE DELETE ON security_audit_events
            BEGIN
                SELECT RAISE(ABORT, 'security audit events are append-only');
            END;
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
            "contract_snapshot_json": json.dumps(result.get("contract_snapshot"), sort_keys=True)
            if result.get("contract_snapshot") is not None else None,
        }
        columns = [
            "run_id", "created_at", "kpi_id", "target_date", "as_of", "persona",
            "region", "category", "scope_json", "result_json", "engine_version",
            "source_data_version", "access_context", "executed_at", "execution_ms",
            "contract_version", "contract_hash", "policy_version", "policy_hash",
            "source_snapshot_id", "source_snapshot_hash", "as_of_cutoff",
            "comparison_scope_json", "query_provenance_json", "contract_snapshot_json",
        ]
        placeholders = ", ".join(["?"] * len(columns))
        update_columns = [column for column in columns if column != "run_id"]
        assignments = ", ".join(f"{column} = excluded.{column}" for column in update_columns)
        conn.execute(
            f"INSERT INTO diagnosis_runs ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT(run_id) DO UPDATE SET {assignments}",
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
        if "contract_snapshot_json" in payload and payload["contract_snapshot_json"] is not None:
            payload["contract_snapshot"] = json.loads(payload["contract_snapshot_json"])
            payload["result"].setdefault("contract_snapshot", payload["contract_snapshot"])
        if "execution_ms" in payload:
            payload["execution_ms"] = payload["execution_ms"]
        return payload
    finally:
        conn.close()


def get_run_access_metadata(run_id: str) -> Dict[str, Any] | None:
    """Load only identity and row-scope fields needed to authorize a run read."""
    initialize_db()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT run_id, kpi_id, persona, scope_json FROM diagnosis_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "run_id": row["run_id"],
            "kpi_id": row["kpi_id"],
            "persona": row["persona"],
            "scope": json.loads(row["scope_json"]),
        }
    finally:
        conn.close()


def get_run_contract_metadata(run_id: str) -> Dict[str, Any] | None:
    """Load only persisted contract fields after identity/scope authorization."""
    initialize_db()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT run_id, kpi_id, contract_version, contract_hash, contract_snapshot_json "
            "FROM diagnosis_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "run_id": row["run_id"],
            "kpi_id": row["kpi_id"],
            "contract_version": row["contract_version"],
            "contract_hash": row["contract_hash"],
            "contract_snapshot": json.loads(row["contract_snapshot_json"])
            if row["contract_snapshot_json"] else None,
        }
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


def list_diagnosis_runs(*, limit: int = 100, offset: int = 0, persona: str | None = None) -> Dict[str, Any]:
    initialize_db()
    conn = _connect()
    try:
        where = "WHERE persona = ?" if persona else ""
        args: list[Any] = [persona] if persona else []
        # Newest analysis date first; for the same date, the most recently executed run first.
        rows = conn.execute(f"SELECT * FROM diagnosis_runs {where} ORDER BY created_at DESC, executed_at DESC, rowid DESC", args).fetchall()
        run_ids = [row["run_id"] for row in rows]
        feedback_states: dict[str, str] = {}
        if run_ids:
            placeholders = ",".join("?" for _ in run_ids)
            feedback_rows = conn.execute(f"SELECT run_id, review_status FROM feedback WHERE run_id IN ({placeholders}) ORDER BY id DESC", run_ids).fetchall()
            for feedback_row in feedback_rows:
                feedback_states.setdefault(feedback_row["run_id"], feedback_row["review_status"])
        items = []
        seen: set[tuple[Any, ...]] = set()
        for row in rows:
            scope = json.loads(row["scope_json"])
            fingerprint = (
                row["kpi_id"], row["persona"], _canonical_json(scope), row["engine_version"],
                row["source_data_version"], row["contract_version"] if "contract_version" in row.keys() else None,
                row["policy_hash"] if "policy_hash" in row.keys() else None,
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            result = json.loads(row["result_json"])
            profile = result.get("confidence_profile") or {}
            confidence_status = (profile.get("overall") or {}).get("status") or (result.get("confidence") or {}).get("status")
            movement = result.get("movement_assessment") or {}
            action_status = next((card.get("status") for card in result.get("decision_cards", []) if card.get("status")), None)
            items.append({"run_id": row["run_id"], "kpi_id": row["kpi_id"], "target_date": row["target_date"], "created_at": row["created_at"], "persona": row["persona"], "scope": scope, "engine_version": row["engine_version"], "source_data_version": row["source_data_version"], "result": result, "actual": movement.get("actual_value"), "expected": movement.get("expected_value"), "delta": movement.get("delta"), "is_material": movement.get("is_material", False), "detector_agreement": movement.get("detector_agreement"), "reconciliation_status": (result.get("reconciliation_verdict") or {}).get("status"), "verdict": result.get("verdict"), "confidence_status": confidence_status, "review_state": feedback_states.get(row["run_id"], action_status or "UNREVIEWED"), "owner": (result.get("decision_cards") or [{}])[0].get("owner", "Analytics")})
        return {"items": items, "total": len(items), "limit": limit, "offset": offset}
    finally:
        conn.close()


def find_diagnosis_run(*, kpi_id: str, target_date: str, persona: str, scope: Dict[str, Any], engine_version: str, source_data_version: str, contract_version: int | str | None = None, contract_hash: str | None = None) -> Dict[str, Any] | None:
    initialize_db()
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM diagnosis_runs WHERE kpi_id = ? AND target_date = ? AND persona = ? AND scope_json = ? AND engine_version = ? AND source_data_version = ? ORDER BY created_at DESC", (kpi_id, target_date, persona, json.dumps(scope, sort_keys=True), engine_version, source_data_version)).fetchall()
        row = next((candidate for candidate in row
                    if (contract_version is None or "contract_version" not in candidate.keys()
                        or str(candidate["contract_version"]) == str(contract_version))
                    and (contract_hash is None or "contract_hash" not in candidate.keys()
                         or candidate["contract_hash"] == contract_hash)), None)
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
    raise ValueError("Legacy feedback rows are read-only; use the append-only feedback event lifecycle")


def _feedback_events(conn: sqlite3.Connection, feedback_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM feedback_events WHERE feedback_id = ? ORDER BY event_id",
        (feedback_id,),
    ).fetchall()
    return [{
        "event_id": row["event_id"],
        "feedback_id": row["feedback_id"],
        "event_type": row["event_type"],
        "from_state": row["from_state"],
        "to_state": row["to_state"],
        "actor_user_id": row["actor_user_id"],
        "actor_persona": row["actor_persona"],
        "reason": row["reason"],
        "created_at": row["created_at"],
    } for row in rows]


def _feedback_submission(conn: sqlite3.Connection, row: sqlite3.Row) -> Dict[str, Any]:
    feedback_id = row["feedback_id"]
    events = _feedback_events(conn, feedback_id)
    state = events[-1]["to_state"] if events else "CAPTURED"
    return {
        "feedback_id": feedback_id,
        "mode": row["mode"],
        "run_id": row["run_id"],
        "user_id": row["user_id"],
        "persona": row["persona"],
        "kpi_id": row["kpi_id"],
        "target_type": row["target_type"],
        "target_id": row["target_id"],
        "scope": json.loads(row["scope_json"]),
        "target_date": row["target_date"],
        "versions": {
            "source_data_version": row["source_data_version"],
            "source_snapshot_id": row["source_snapshot_id"],
            "source_snapshot_hash": row["source_snapshot_hash"],
            "contract_version": row["contract_version"],
            "contract_hash": row["contract_hash"],
            "policy_version": row["policy_version"],
            "policy_hash": row["policy_hash"],
            "run_snapshot_hash": row["run_snapshot_hash"],
        },
        "rating": row["rating"],
        "reason_code": row["reason_code"],
        "comment": row["comment"],
        "action_taken": row["action_taken"],
        "outcome_observation": row["outcome_observation"],
        "issue_category": row["issue_category"],
        "correction_type": row["correction_type"],
        "proposed_correction": row["proposed_correction"],
        "rationale": row["rationale"],
        "evidence_refs": json.loads(row["evidence_refs_json"]),
        "original_payload": json.loads(row["original_payload_json"]),
        "created_at": row["created_at"],
        "events": events,
        "state": state,
        "message": "Feedback captured" if state == "CAPTURED" else f"Feedback {state.lower().replace('_', ' ')}",
    }


def create_feedback_submission(
    *,
    payload: Dict[str, Any],
    run: Dict[str, Any],
    user_id: str,
    persona: str,
) -> Dict[str, Any]:
    """Persist immutable feedback and its initial event in one transaction."""
    initialize_db()
    result = run.get("result") if isinstance(run.get("result"), dict) else {}
    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    feedback_id = f"fb-{uuid4().hex}"
    created_at = datetime.now(timezone.utc).isoformat()
    versions = {
        "source_data_version": run.get("source_data_version"),
        "source_snapshot_id": run.get("source_snapshot_id"),
        "source_snapshot_hash": run.get("source_snapshot_hash"),
        "contract_version": run.get("contract_version"),
        "contract_hash": run.get("contract_hash"),
        "policy_version": run.get("policy_version"),
        "policy_hash": run.get("policy_hash"),
        "run_snapshot_hash": _stable_hash(result) or "unknown",
    }
    fields = (
        "rating", "reason_code", "comment", "action_taken", "outcome_observation",
        "issue_category", "correction_type", "proposed_correction", "rationale",
    )
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO feedback_submissions (feedback_id, mode, run_id, user_id, persona, kpi_id, target_type, target_id, scope_json, target_date, source_data_version, source_snapshot_id, source_snapshot_hash, contract_version, contract_hash, policy_version, policy_hash, run_snapshot_hash, rating, reason_code, comment, action_taken, outcome_observation, issue_category, correction_type, proposed_correction, rationale, evidence_refs_json, original_payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                feedback_id, payload["mode"], run["run_id"], user_id, persona,
                run["kpi_id"], payload["target_type"], payload["target_id"],
                _canonical_json(scope), run.get("target_date"),
                versions["source_data_version"], versions["source_snapshot_id"],
                versions["source_snapshot_hash"], versions["contract_version"],
                versions["contract_hash"], versions["policy_version"],
                versions["policy_hash"], versions["run_snapshot_hash"],
                *(payload.get(field) for field in fields),
                _canonical_json(payload.get("evidence_refs") or []),
                _canonical_json(payload), created_at,
            ),
        )
        conn.execute(
            "INSERT INTO feedback_events (feedback_id, event_type, from_state, to_state, actor_user_id, actor_persona, reason, created_at) VALUES (?, 'SUBMITTED', NULL, 'CAPTURED', ?, ?, NULL, ?)",
            (feedback_id, user_id, persona, created_at),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM feedback_submissions WHERE feedback_id = ?",
            (feedback_id,),
        ).fetchone()
        return _feedback_submission(conn, row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_feedback_submission(feedback_id: str) -> Dict[str, Any] | None:
    initialize_db()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM feedback_submissions WHERE feedback_id = ?",
            (feedback_id,),
        ).fetchone()
        return _feedback_submission(conn, row) if row else None
    finally:
        conn.close()


def list_feedback_submissions() -> List[Dict[str, Any]]:
    initialize_db()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM feedback_submissions ORDER BY created_at DESC, feedback_id DESC"
        ).fetchall()
        return [_feedback_submission(conn, row) for row in rows]
    finally:
        conn.close()


def append_feedback_event(
    feedback_id: str,
    event_type: str,
    actor_user_id: str,
    actor_persona: str,
    reason: str | None = None,
) -> Dict[str, Any] | None:
    allowed_transitions = {
        ("CAPTURED", "TRIAGED"): "TRIAGED",
        ("CAPTURED", "REJECTED"): "REJECTED",
        ("TRIAGED", "REJECTED"): "REJECTED",
    }
    initialize_db()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        exists = conn.execute(
            "SELECT feedback_id FROM feedback_submissions WHERE feedback_id = ?",
            (feedback_id,),
        ).fetchone()
        if exists is None:
            conn.rollback()
            return None
        latest = conn.execute(
            "SELECT to_state FROM feedback_events WHERE feedback_id = ? ORDER BY event_id DESC LIMIT 1",
            (feedback_id,),
        ).fetchone()
        current_state = latest["to_state"] if latest else "CAPTURED"
        transition = (current_state, event_type)
        if transition not in allowed_transitions:
            raise ValueError(f"Feedback transition {current_state} to {event_type} is not allowed")
        to_state = allowed_transitions[transition]
        conn.execute(
            "INSERT INTO feedback_events (feedback_id, event_type, from_state, to_state, actor_user_id, actor_persona, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (feedback_id, event_type, current_state, to_state, actor_user_id, actor_persona, reason, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM feedback_submissions WHERE feedback_id = ?",
            (feedback_id,),
        ).fetchone()
        return _feedback_submission(conn, row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_legacy_feedback(feedback_id: int) -> Dict[str, Any] | None:
    initialize_db()
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
        if row is None:
            return None
        return {
            "feedback_id": str(row["id"]), "legacy": True,
            "run_id": row["run_id"], "user_id": row["user_id"],
            "kpi_id": row["kpi_id"], "feedback_type": row["feedback_type"],
            "comments": row["comments"], "created_at": row["created_at"],
            "state": row["review_status"], "reviewer": row["reviewer"],
            "reviewed_at": row["reviewed_at"], "target_type": row["target_type"],
            "target_id": row["target_id"], "snapshot": json.loads(row["snapshot_json"] or "{}"),
            "metadata": json.loads(row["metadata_json"] or "{}"), "events": [],
        }
    finally:
        conn.close()


def _proposal_events(conn: sqlite3.Connection, proposal_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM improvement_proposal_events WHERE proposal_id = ? ORDER BY event_id",
        (proposal_id,),
    ).fetchall()
    return [{
        "event_id": row["event_id"],
        "proposal_id": row["proposal_id"],
        "event_type": row["event_type"],
        "from_state": row["from_state"],
        "to_state": row["to_state"],
        "actor_user_id": row["actor_user_id"],
        "actor_persona": row["actor_persona"],
        "reason": row["reason"],
        "created_at": row["created_at"],
    } for row in rows]


def _improvement_proposal(conn: sqlite3.Connection, row: sqlite3.Row) -> Dict[str, Any]:
    from backend.offline_learning import SUPPORTED_CANDIDATE_TYPES

    proposal_id = row["proposal_id"]
    proposal = json.loads(row["proposal_json"])
    links = conn.execute(
        "SELECT feedback_id FROM improvement_proposal_feedback WHERE proposal_id = ? ORDER BY feedback_id",
        (proposal_id,),
    ).fetchall()
    events = _proposal_events(conn, proposal_id)
    candidate_row = conn.execute(
        "SELECT * FROM candidate_artifacts WHERE proposal_id = ?",
        (proposal_id,),
    ).fetchone()
    evaluation_rows = conn.execute(
        "SELECT evaluation_run_id, final_result, completed_at FROM proposal_evaluation_runs WHERE proposal_id = ? ORDER BY started_at",
        (proposal_id,),
    ).fetchall()
    state = events[-1]["to_state"] if events else "PROPOSED"
    return {
        **proposal,
        "proposal_id": proposal_id,
        "source_feedback_ids": [link["feedback_id"] for link in links],
        "events": events,
        "state": state,
        "application_support": "SUPPORTED" if proposal.get("proposal_type") in SUPPORTED_CANDIDATE_TYPES else "APPLICATION_NOT_SUPPORTED",
        "candidate_state": "NOT_APPLIED" if candidate_row is None else ("ROLLED_BACK" if state == "ROLLED_BACK" else state),
        "candidate_artifact_id": candidate_row["candidate_artifact_id"] if candidate_row else None,
        "candidate_version": candidate_row["candidate_version"] if candidate_row else None,
        "activation_status": candidate_row["activation_status"] if candidate_row else "EVALUATION_ONLY",
        "evaluation_run_ids": [item["evaluation_run_id"] for item in evaluation_rows],
        "latest_evaluation_result": evaluation_rows[-1]["final_result"] if evaluation_rows else None,
        "application_status": "ROLLED_BACK" if state == "ROLLED_BACK" else "APPLIED TO EVALUATION WORKSPACE" if state in {"APPLIED", "VERIFIED", "FAILED_VERIFICATION"} else "Not yet applied",
        "verification_status": "Verified offline" if state == "VERIFIED" else "Failed offline verification" if state == "FAILED_VERIFICATION" else "Not yet verified",
        "applied": state in {"APPLIED", "VERIFIED", "FAILED_VERIFICATION", "ROLLED_BACK"},
        "verified": state == "VERIFIED",
        "deployed": False,
        "evaluation_only": True,
        "rollback_status": "ROLLED_BACK" if state == "ROLLED_BACK" else "NOT_ROLLED_BACK",
        "message": (
            "Verified in offline evaluation; not deployed to the live engine."
            if state == "VERIFIED" else
            "Candidate failed offline verification; not deployed to the live engine."
            if state == "FAILED_VERIFICATION" else
            "Candidate rolled back from evaluation consideration; live engine unchanged."
            if state == "ROLLED_BACK" else
            "Candidate applied to evaluation workspace only; not live."
            if state == "APPLIED" else
            "Proposal accepted; not yet applied or verified"
            if state == "ACCEPTED" else
            "Improvement proposed"
            if state == "PROPOSED" else
            "Proposal rejected; not applied or verified"
        ),
    }


def find_improvement_proposal(aggregation_key: str, idempotency_key: str) -> Dict[str, Any] | None:
    initialize_db()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM improvement_proposals WHERE aggregation_key = ? AND idempotency_key = ?",
            (aggregation_key, idempotency_key),
        ).fetchone()
        return _improvement_proposal(conn, row) if row else None
    finally:
        conn.close()


def create_improvement_proposal(
    *,
    aggregation_key: str,
    idempotency_key: str,
    proposal: Dict[str, Any],
    feedback_ids: List[str],
    created_by: str,
    created_persona: str,
) -> Dict[str, Any]:
    initialize_db()
    conn = _connect()
    proposal_id = f"proposal-{uuid4().hex}"
    created_at = datetime.now(timezone.utc).isoformat()
    immutable_payload = {**proposal, "proposal_id": proposal_id, "aggregation_key": aggregation_key, "created_by": created_by, "created_at": created_at}
    source_ids = sorted(set(feedback_ids))
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM improvement_proposals WHERE aggregation_key = ? AND idempotency_key = ?",
            (aggregation_key, idempotency_key),
        ).fetchone()
        if existing is not None:
            conn.rollback()
            return {**_improvement_proposal(conn, existing), "idempotent_replay": True}

        placeholders = ",".join("?" for _ in source_ids)
        linked = conn.execute(
            f"SELECT links.feedback_id, proposals.proposal_id, COALESCE((SELECT to_state FROM improvement_proposal_events WHERE proposal_id = proposals.proposal_id ORDER BY event_id DESC LIMIT 1), 'PROPOSED') AS state FROM improvement_proposal_feedback AS links JOIN improvement_proposals AS proposals ON proposals.proposal_id = links.proposal_id WHERE links.feedback_id IN ({placeholders})",
            source_ids,
        ).fetchall()
        if any(link["state"] in {"PROPOSED", "ACCEPTED"} for link in linked):
            raise ValueError("A feedback record already supports an active proposal")
        proposal_payload = _canonical_json(immutable_payload)
        conn.execute(
            "INSERT INTO improvement_proposals (proposal_id, aggregation_key, idempotency_key, kpi_id, scope_json, target_artifact_type, before_version, before_version_hash, created_by, created_persona, created_at, proposal_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                proposal_id, aggregation_key, idempotency_key, proposal["kpi_id"],
                _canonical_json(proposal["scope"]), proposal["target_artifact_type"],
                proposal["before_version"], proposal.get("before_version_hash"),
                created_by, created_persona, created_at, proposal_payload,
            ),
        )
        conn.executemany(
            "INSERT INTO improvement_proposal_feedback (proposal_id, feedback_id, linked_at) VALUES (?, ?, ?)",
            [(proposal_id, feedback_id, created_at) for feedback_id in source_ids],
        )
        conn.execute(
            "INSERT INTO improvement_proposal_events (proposal_id, event_type, from_state, to_state, actor_user_id, actor_persona, reason, created_at) VALUES (?, 'PROPOSED', NULL, 'PROPOSED', ?, ?, NULL, ?)",
            (proposal_id, created_by, created_persona, created_at),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM improvement_proposals WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        return _improvement_proposal(conn, row)
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        if "idempotency_key" in str(exc):
            existing = conn.execute(
                "SELECT * FROM improvement_proposals WHERE aggregation_key = ? AND idempotency_key = ?",
                (aggregation_key, idempotency_key),
            ).fetchone()
            if existing is not None:
                return {**_improvement_proposal(conn, existing), "idempotent_replay": True}
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_improvement_proposal(proposal_id: str) -> Dict[str, Any] | None:
    initialize_db()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM improvement_proposals WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        return _improvement_proposal(conn, row) if row else None
    finally:
        conn.close()


def list_improvement_proposals() -> List[Dict[str, Any]]:
    initialize_db()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM improvement_proposals ORDER BY created_at DESC, proposal_id DESC"
        ).fetchall()
        return [_improvement_proposal(conn, row) for row in rows]
    finally:
        conn.close()


def append_improvement_proposal_event(
    proposal_id: str,
    event_type: str,
    actor_user_id: str,
    actor_persona: str,
    reason: str | None = None,
) -> Dict[str, Any] | None:
    aggregatable_states = {"CAPTURED", "TRIAGED"}
    if event_type not in {"ACCEPTED", "REJECTED"}:
        raise ValueError("Proposal event must be ACCEPTED or REJECTED")
    initialize_db()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM improvement_proposals WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        if row is None:
            conn.rollback()
            return None
        latest = conn.execute(
            "SELECT to_state FROM improvement_proposal_events WHERE proposal_id = ? ORDER BY event_id DESC LIMIT 1",
            (proposal_id,),
        ).fetchone()
        current_state = latest["to_state"] if latest else "PROPOSED"
        if current_state != "PROPOSED":
            raise ValueError(f"Proposal transition from {current_state} is not allowed")
        links = conn.execute(
            "SELECT feedback_id FROM improvement_proposal_feedback WHERE proposal_id = ? ORDER BY feedback_id",
            (proposal_id,),
        ).fetchall()
        linked_states = []
        for link in links:
            feedback_id = link["feedback_id"]
            feedback_event = conn.execute(
                "SELECT to_state FROM feedback_events WHERE feedback_id = ? ORDER BY event_id DESC LIMIT 1",
                (feedback_id,),
            ).fetchone()
            state = feedback_event["to_state"] if feedback_event else "CAPTURED"
            linked_states.append((feedback_id, state))
        if event_type == "ACCEPTED" and any(state not in aggregatable_states for _, state in linked_states):
            raise ValueError("Linked feedback is no longer eligible for proposal acceptance")

        created_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO improvement_proposal_events (proposal_id, event_type, from_state, to_state, actor_user_id, actor_persona, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (proposal_id, event_type, current_state, event_type, actor_user_id, actor_persona, reason, created_at),
        )
        feedback_to_state = event_type
        for feedback_id, state in linked_states:
            if state in aggregatable_states:
                conn.execute(
                    "INSERT INTO feedback_events (feedback_id, event_type, from_state, to_state, actor_user_id, actor_persona, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (feedback_id, event_type, state, feedback_to_state, actor_user_id, actor_persona, reason, created_at),
                )
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM improvement_proposals WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        return _improvement_proposal(conn, updated)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _candidate_artifact(conn: sqlite3.Connection, row: sqlite3.Row) -> Dict[str, Any]:
    artifact_id = row["candidate_artifact_id"]
    events = conn.execute(
        "SELECT * FROM candidate_artifact_events WHERE candidate_artifact_id = ? ORDER BY event_id",
        (artifact_id,),
    ).fetchall()
    evaluation_rows = conn.execute(
        "SELECT evaluation_run_id, final_result, completed_at FROM proposal_evaluation_runs WHERE candidate_artifact_id = ? ORDER BY started_at",
        (artifact_id,),
    ).fetchall()
    proposal_event = conn.execute(
        "SELECT to_state FROM improvement_proposal_events WHERE proposal_id = ? ORDER BY event_id DESC LIMIT 1",
        (row["proposal_id"],),
    ).fetchone()
    proposal_state = proposal_event["to_state"] if proposal_event else "PROPOSED"
    rollback_status = "ROLLED_BACK" if any(event["event_type"] == "ROLLED_BACK" for event in events) else "NOT_ROLLED_BACK"
    return {
        "candidate_artifact_id": artifact_id,
        "proposal_id": row["proposal_id"],
        "artifact_type": row["artifact_type"],
        "kpi_id": row["kpi_id"],
        "scope": json.loads(row["scope_json"]),
        "base_version": row["base_version"],
        "candidate_version": row["candidate_version"],
        "base_payload": json.loads(row["base_payload_json"]),
        "validated_change": json.loads(row["validated_change_json"]),
        "candidate_payload": json.loads(row["candidate_payload_json"]),
        "payload_hash": row["payload_hash"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "activation_status": row["activation_status"],
        "rollback_of": row["rollback_of"],
        "supersedes": row["supersedes"],
        "events": [{
            "event_id": event["event_id"], "event_type": event["event_type"],
            "actor_user_id": event["actor_user_id"], "actor_persona": event["actor_persona"],
            "reason": event["reason"], "created_at": event["created_at"],
        } for event in events],
        "evaluation_run_ids": [evaluation["evaluation_run_id"] for evaluation in evaluation_rows],
        "applied": True,
        "verified": any(evaluation["final_result"] == "VERIFIED" for evaluation in evaluation_rows),
        "deployed": False,
        "evaluation_only": True,
        "rollback_status": rollback_status,
        "proposal_state": proposal_state,
        "candidate_state": "ROLLED_BACK" if rollback_status == "ROLLED_BACK" else proposal_state,
        "message": "Candidate rolled back; live engine unchanged." if rollback_status == "ROLLED_BACK" else "Candidate exists in evaluation workspace only; not deployed to the live engine.",
    }


def create_candidate_artifact(
    *,
    proposal_id: str,
    artifact: Dict[str, Any],
    actor_user_id: str,
    actor_persona: str,
) -> Dict[str, Any]:
    initialize_db()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        proposal = conn.execute(
            "SELECT * FROM improvement_proposals WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        if proposal is None:
            conn.rollback()
            return {"status": "NOT_FOUND"}
        current = conn.execute(
            "SELECT to_state FROM improvement_proposal_events WHERE proposal_id = ? ORDER BY event_id DESC LIMIT 1",
            (proposal_id,),
        ).fetchone()
        proposal_state = current["to_state"] if current else "PROPOSED"
        if proposal_state != "ACCEPTED":
            raise ValueError("Only an ACCEPTED proposal may be applied to an evaluation candidate")
        existing = conn.execute(
            "SELECT * FROM candidate_artifacts WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        if existing:
            conn.rollback()
            return {**_candidate_artifact(conn, existing), "idempotent_replay": True}
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO candidate_artifacts (candidate_artifact_id, proposal_id, artifact_type, kpi_id, scope_json, base_version, candidate_version, base_payload_json, validated_change_json, candidate_payload_json, payload_hash, created_by, created_at, activation_status, rollback_of, supersedes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'EVALUATION_ONLY', ?, ?)",
            (
                artifact["candidate_artifact_id"], proposal_id, artifact["artifact_type"],
                artifact["kpi_id"], _canonical_json(artifact["scope"]), artifact["base_version"],
                artifact["candidate_version"], _canonical_json(artifact["base_payload"]),
                _canonical_json(artifact["validated_change"]), _canonical_json(artifact["candidate_payload"]),
                artifact["payload_hash"], actor_user_id, now, artifact.get("rollback_of"), artifact.get("supersedes"),
            ),
        )
        conn.execute(
            "INSERT INTO candidate_artifact_events (candidate_artifact_id, event_type, actor_user_id, actor_persona, reason, created_at) VALUES (?, 'CREATED', ?, ?, 'Materialized in evaluation workspace only', ?)",
            (artifact["candidate_artifact_id"], actor_user_id, actor_persona, now),
        )
        conn.execute(
            "INSERT INTO improvement_proposal_events (proposal_id, event_type, from_state, to_state, actor_user_id, actor_persona, reason, created_at) VALUES (?, 'APPLIED', 'ACCEPTED', 'APPLIED', ?, ?, ?, ?)",
            (proposal_id, actor_user_id, actor_persona, _canonical_json({"candidate_artifact_id": artifact["candidate_artifact_id"]}), now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM candidate_artifacts WHERE candidate_artifact_id = ?",
            (artifact["candidate_artifact_id"],),
        ).fetchone()
        return _candidate_artifact(conn, row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_candidate_artifact(candidate_artifact_id: str) -> Dict[str, Any] | None:
    initialize_db()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM candidate_artifacts WHERE candidate_artifact_id = ?",
            (candidate_artifact_id,),
        ).fetchone()
        return _candidate_artifact(conn, row) if row else None
    finally:
        conn.close()


def get_candidate_for_proposal(proposal_id: str) -> Dict[str, Any] | None:
    initialize_db()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM candidate_artifacts WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        return _candidate_artifact(conn, row) if row else None
    finally:
        conn.close()


def list_candidate_artifacts() -> List[Dict[str, Any]]:
    initialize_db()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM candidate_artifacts ORDER BY created_at DESC, candidate_artifact_id DESC"
        ).fetchall()
        return [_candidate_artifact(conn, row) for row in rows]
    finally:
        conn.close()


def record_proposal_evaluation(
    *,
    evaluation: Dict[str, Any],
    cases: List[Dict[str, Any]],
    actor_user_id: str,
    actor_persona: str,
) -> Dict[str, Any]:
    initialize_db()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        proposal_id = evaluation["proposal_id"]
        proposal = conn.execute(
            "SELECT to_state FROM improvement_proposal_events WHERE proposal_id = ? ORDER BY event_id DESC LIMIT 1",
            (proposal_id,),
        ).fetchone()
        current_state = proposal["to_state"] if proposal else "PROPOSED"
        if current_state != "APPLIED":
            raise ValueError("Only an APPLIED candidate can be evaluated")
        if any(event["event_type"] == "ROLLED_BACK" for event in conn.execute(
            "SELECT event_type FROM candidate_artifact_events WHERE candidate_artifact_id = ?",
            (evaluation["candidate_artifact_id"],),
        ).fetchall()):
            raise ValueError("A rolled-back candidate cannot be evaluated")
        evaluation_id = evaluation["evaluation_run_id"]
        conn.execute(
            "INSERT INTO proposal_evaluation_runs (evaluation_run_id, proposal_id, candidate_artifact_id, baseline_artifact_version, candidate_artifact_version, affected_cases_json, holdout_cases_json, metrics_json, gates_json, baseline_results_json, candidate_results_json, case_differences_json, started_at, completed_at, evaluator_method, evaluator_version, final_result, failure_reasons_json, inputs_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                evaluation_id, proposal_id, evaluation["candidate_artifact_id"],
                evaluation["baseline_artifact_version"], evaluation["candidate_artifact_version"],
                _canonical_json(evaluation["affected_cases"]), _canonical_json(evaluation["holdout_cases"]),
                _canonical_json(evaluation["metrics"]), _canonical_json(evaluation["gates"]),
                _canonical_json(evaluation["baseline_results"]), _canonical_json(evaluation["candidate_results"]),
                _canonical_json(evaluation["case_differences"]), evaluation["started_at"], evaluation["completed_at"],
                evaluation["evaluator_method"], evaluation["evaluator_version"], evaluation["final_result"],
                _canonical_json(evaluation["failure_reasons"]), evaluation["inputs_hash"],
            ),
        )
        conn.executemany(
            "INSERT INTO evaluation_case_results (evaluation_run_id, case_id, case_kind, input_run_id, input_snapshot_hash, as_of, baseline_result_json, candidate_result_json, differences_json, gate_results_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(
                evaluation_id, case["case_id"], case["case_kind"], case["input_run_id"], case["input_snapshot_hash"],
                case.get("as_of"), _canonical_json(case["baseline_result"]), _canonical_json(case["candidate_result"]),
                _canonical_json(case["differences"]), _canonical_json(case["gate_results"]),
            ) for case in cases],
        )
        final_state = evaluation["final_result"]
        conn.execute(
            "INSERT INTO improvement_proposal_events (proposal_id, event_type, from_state, to_state, actor_user_id, actor_persona, reason, created_at) VALUES (?, ?, 'APPLIED', ?, ?, ?, ?, ?)",
            (proposal_id, final_state, final_state, actor_user_id, actor_persona, _canonical_json({"evaluation_run_id": evaluation_id, "failed_gates": evaluation["failure_reasons"]}), evaluation["completed_at"]),
        )
        conn.execute(
            "INSERT INTO candidate_artifact_events (candidate_artifact_id, event_type, actor_user_id, actor_persona, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (evaluation["candidate_artifact_id"], final_state, actor_user_id, actor_persona, _canonical_json({"evaluation_run_id": evaluation_id}), evaluation["completed_at"]),
        )
        conn.commit()
        return get_proposal_evaluation(evaluation_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_proposal_evaluation(evaluation_run_id: str) -> Dict[str, Any] | None:
    initialize_db()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM proposal_evaluation_runs WHERE evaluation_run_id = ?",
            (evaluation_run_id,),
        ).fetchone()
        if row is None:
            return None
        cases = conn.execute(
            "SELECT * FROM evaluation_case_results WHERE evaluation_run_id = ? ORDER BY case_kind, case_id",
            (evaluation_run_id,),
        ).fetchall()
        proposal_event = conn.execute(
            "SELECT to_state FROM improvement_proposal_events WHERE proposal_id = ? ORDER BY event_id DESC LIMIT 1",
            (row["proposal_id"],),
        ).fetchone()
        candidate_event = conn.execute(
            "SELECT 1 FROM candidate_artifact_events WHERE candidate_artifact_id = ? AND event_type = 'ROLLED_BACK' LIMIT 1",
            (row["candidate_artifact_id"],),
        ).fetchone()
        proposal_state = proposal_event["to_state"] if proposal_event else row["final_result"]
        rolled_back = candidate_event is not None
        return {
            "evaluation_run_id": row["evaluation_run_id"], "proposal_id": row["proposal_id"],
            "candidate_artifact_id": row["candidate_artifact_id"],
            "baseline_artifact_version": row["baseline_artifact_version"],
            "candidate_artifact_version": row["candidate_artifact_version"],
            "affected_cases": json.loads(row["affected_cases_json"]),
            "holdout_cases": json.loads(row["holdout_cases_json"]),
            "metrics": json.loads(row["metrics_json"]), "gates": json.loads(row["gates_json"]),
            "baseline_results": json.loads(row["baseline_results_json"]),
            "candidate_results": json.loads(row["candidate_results_json"]),
            "case_differences": json.loads(row["case_differences_json"]),
            "started_at": row["started_at"], "completed_at": row["completed_at"],
            "evaluator_method": row["evaluator_method"], "evaluator_version": row["evaluator_version"],
            "final_result": row["final_result"], "proposal_state": proposal_state,
            "candidate_state": "ROLLED_BACK" if rolled_back else proposal_state,
            "applied": True, "verified": row["final_result"] == "VERIFIED",
            "failure_reasons": json.loads(row["failure_reasons_json"]), "inputs_hash": row["inputs_hash"],
            "case_results": [{
                "case_id": case["case_id"], "case_kind": case["case_kind"], "input_run_id": case["input_run_id"],
                "input_snapshot_hash": case["input_snapshot_hash"], "as_of": case["as_of"],
                "baseline_result": json.loads(case["baseline_result_json"]),
                "candidate_result": json.loads(case["candidate_result_json"]),
                "differences": json.loads(case["differences_json"]),
                "gate_results": json.loads(case["gate_results_json"]),
            } for case in cases],
            "deployed": False, "evaluation_only": True,
            "rollback_status": "ROLLED_BACK" if rolled_back else "NOT_ROLLED_BACK",
            "message": "Candidate rolled back after offline evaluation; live engine unchanged." if rolled_back else "Verified in offline evaluation; not deployed to the live engine." if row["final_result"] == "VERIFIED" else "Candidate failed offline verification; not deployed to the live engine.",
        }
    finally:
        conn.close()


def list_proposal_evaluations(proposal_id: str) -> List[Dict[str, Any]]:
    initialize_db()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT evaluation_run_id FROM proposal_evaluation_runs WHERE proposal_id = ? ORDER BY started_at",
            (proposal_id,),
        ).fetchall()
        return [get_proposal_evaluation(row["evaluation_run_id"]) for row in rows]
    finally:
        conn.close()


def rollback_candidate_artifact(
    *,
    proposal_id: str,
    candidate_artifact_id: str,
    actor_user_id: str,
    actor_persona: str,
    reason: str,
) -> Dict[str, Any] | None:
    initialize_db()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        latest = conn.execute(
            "SELECT to_state FROM improvement_proposal_events WHERE proposal_id = ? ORDER BY event_id DESC LIMIT 1",
            (proposal_id,),
        ).fetchone()
        current_state = latest["to_state"] if latest else "PROPOSED"
        if current_state not in {"APPLIED", "VERIFIED", "FAILED_VERIFICATION"}:
            raise ValueError(f"Proposal state {current_state} cannot be rolled back")
        artifact = conn.execute(
            "SELECT * FROM candidate_artifacts WHERE candidate_artifact_id = ? AND proposal_id = ?",
            (candidate_artifact_id, proposal_id),
        ).fetchone()
        if artifact is None:
            conn.rollback()
            return None
        prior_rollback = conn.execute(
            "SELECT 1 FROM candidate_artifact_events WHERE candidate_artifact_id = ? AND event_type = 'ROLLED_BACK'",
            (candidate_artifact_id,),
        ).fetchone()
        if prior_rollback:
            conn.rollback()
            return _candidate_artifact(conn, artifact)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO candidate_artifact_events (candidate_artifact_id, event_type, actor_user_id, actor_persona, reason, created_at) VALUES (?, 'ROLLED_BACK', ?, ?, ?, ?)",
            (candidate_artifact_id, actor_user_id, actor_persona, reason, now),
        )
        conn.execute(
            "INSERT INTO improvement_proposal_events (proposal_id, event_type, from_state, to_state, actor_user_id, actor_persona, reason, created_at) VALUES (?, 'ROLLED_BACK', ?, 'ROLLED_BACK', ?, ?, ?, ?)",
            (proposal_id, current_state, actor_user_id, actor_persona, _canonical_json({"candidate_artifact_id": candidate_artifact_id, "reason": reason}), now),
        )
        conn.commit()
        return _candidate_artifact(conn, artifact)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_AUDIT_METADATA_KEYS = {
    "method", "endpoint", "scenario_id", "kpi_id", "target_date",
    "source_mode", "event_type", "candidate_type", "result", "count",
}


def _safe_audit_metadata(metadata: Dict[str, Any] | None) -> Dict[str, Any]:
    """Keep audit context useful without persisting prompts, data values, or paths."""
    safe: Dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        if key not in _AUDIT_METADATA_KEYS:
            continue
        if value is None or isinstance(value, (str, int, float, bool)):
            safe[key] = value
    return safe


def append_security_audit_event(
    *,
    actor_user_id: str,
    actor_persona: str,
    action: str,
    resource_type: str,
    decision: str,
    reason_code: str,
    resource_id: str | None = None,
    scope: Dict[str, Any] | None = None,
    outcome_status: int | None = None,
    correlation_id: str | None = None,
    identity_mode: str = "DEMO_SIMULATED",
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Append one immutable, hash-chained security decision record."""
    normalized_decision = decision.upper()
    if normalized_decision not in {"ALLOW", "DENY"}:
        raise ValueError("Audit decision must be ALLOW or DENY")
    initialize_db()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        prior = conn.execute(
            "SELECT event_hash FROM security_audit_events ORDER BY event_sequence DESC LIMIT 1"
        ).fetchone()
        previous_hash = prior["event_hash"] if prior else "0" * 64
        event = {
            "audit_event_id": f"audit-{uuid4()}",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "actor_user_id": actor_user_id,
            "actor_persona": actor_persona,
            "identity_mode": identity_mode,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "scope": scope or {},
            "decision": normalized_decision,
            "reason_code": reason_code,
            "outcome_status": outcome_status,
            "correlation_id": correlation_id,
            "metadata": _safe_audit_metadata(metadata),
            "previous_event_hash": previous_hash,
        }
        event_hash = hashlib.sha256(
            (previous_hash + _canonical_json(event)).encode("utf-8")
        ).hexdigest()
        conn.execute(
            """INSERT INTO security_audit_events (
                audit_event_id, occurred_at, actor_user_id, actor_persona,
                identity_mode, action, resource_type, resource_id, scope_json,
                decision, reason_code, outcome_status, correlation_id,
                metadata_json, previous_event_hash, event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event["audit_event_id"], event["occurred_at"], actor_user_id,
                actor_persona, identity_mode, action, resource_type, resource_id,
                _canonical_json(event["scope"]), normalized_decision, reason_code,
                outcome_status, correlation_id, _canonical_json(event["metadata"]),
                previous_hash, event_hash,
            ),
        )
        sequence = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        return {**event, "event_sequence": sequence, "event_hash": event_hash}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_security_audit_events(*, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    initialize_db()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM security_audit_events ORDER BY event_sequence DESC LIMIT ? OFFSET ?",
            (max(1, min(limit, 500)), max(0, offset)),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["scope"] = json.loads(item.pop("scope_json"))
            item["metadata"] = json.loads(item.pop("metadata_json"))
            items.append(item)
        return items
    finally:
        conn.close()


def verify_security_audit_chain() -> Dict[str, Any]:
    initialize_db()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM security_audit_events ORDER BY event_sequence"
        ).fetchall()
        previous_hash = "0" * 64
        for row in rows:
            event = {
                "audit_event_id": row["audit_event_id"],
                "occurred_at": row["occurred_at"],
                "actor_user_id": row["actor_user_id"],
                "actor_persona": row["actor_persona"],
                "identity_mode": row["identity_mode"],
                "action": row["action"],
                "resource_type": row["resource_type"],
                "resource_id": row["resource_id"],
                "scope": json.loads(row["scope_json"]),
                "decision": row["decision"],
                "reason_code": row["reason_code"],
                "outcome_status": row["outcome_status"],
                "correlation_id": row["correlation_id"],
                "metadata": json.loads(row["metadata_json"]),
                "previous_event_hash": row["previous_event_hash"],
            }
            calculated = hashlib.sha256(
                (previous_hash + _canonical_json(event)).encode("utf-8")
            ).hexdigest()
            if row["previous_event_hash"] != previous_hash or row["event_hash"] != calculated:
                return {"valid": False, "event_count": len(rows), "failed_sequence": row["event_sequence"]}
            previous_hash = row["event_hash"]
        return {"valid": True, "event_count": len(rows), "failed_sequence": None}
    finally:
        conn.close()
