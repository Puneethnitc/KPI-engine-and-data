"""Deterministic feedback aggregation and proposal validation helpers."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable


AGGREGATABLE_STATES = {"CAPTURED", "TRIAGED"}
PROPOSAL_TYPES = {
    "REVIEW_REQUIRED",
    "KPI_CONTRACT_CHANGE",
    "DATA_QUALITY_FIX",
    "DRIVER_CONFIGURATION_CHANGE",
    "BUSINESS_RULE_CHANGE",
    "ANALYTICAL_METHOD_REVIEW",
    "CONFIDENCE_POLICY_CHANGE",
    "NARRATIVE_TEMPLATE_CHANGE",
    "ACTION_POLICY_CHANGE",
    "ACCESS_POLICY_REVIEW",
    "EVALUATION_CASE_ADDITION",
}

ISSUE_TO_PROPOSAL = {
    "KPI_CONTRACT": "KPI_CONTRACT_CHANGE",
    "DATA": "DATA_QUALITY_FIX",
    "DRIVER": "DRIVER_CONFIGURATION_CHANGE",
    "BUSINESS_RULE": "BUSINESS_RULE_CHANGE",
    "ANALYTICAL_METHOD": "ANALYTICAL_METHOD_REVIEW",
    "CONFIDENCE": "CONFIDENCE_POLICY_CHANGE",
    "NARRATIVE": "NARRATIVE_TEMPLATE_CHANGE",
    "ACTION": "ACTION_POLICY_CHANGE",
    "ACCESS_POLICY": "ACCESS_POLICY_REVIEW",
}

PROPOSAL_ARTIFACT_TYPES = {
    "REVIEW_REQUIRED": "REVIEW_ONLY",
    "KPI_CONTRACT_CHANGE": "KPI_CONTRACT",
    "DATA_QUALITY_FIX": "SOURCE_DATA_QUALITY_RULE",
    "DRIVER_CONFIGURATION_CHANGE": "DRIVER_CONFIGURATION",
    "BUSINESS_RULE_CHANGE": "BUSINESS_RULE",
    "ANALYTICAL_METHOD_REVIEW": "ANALYTICAL_METHOD",
    "CONFIDENCE_POLICY_CHANGE": "CONFIDENCE_POLICY",
    "NARRATIVE_TEMPLATE_CHANGE": "APPROVED_NARRATIVE_TEMPLATE",
    "ACTION_POLICY_CHANGE": "ACTION_POLICY",
    "ACCESS_POLICY_REVIEW": "ACCESS_POLICY",
    "EVALUATION_CASE_ADDITION": "EVALUATION_CASE",
}

PROPOSED_VALUE_FIELDS = {
    "KPI_CONTRACT_CHANGE": ("KPI_CONTRACT", "contract_field", "proposed_value"),
    "DATA_QUALITY_FIX": ("DATA", "data_target", "recommended_resolution"),
    "DRIVER_CONFIGURATION_CHANGE": ("DRIVER", "driver_id", "proposed_configuration"),
    "BUSINESS_RULE_CHANGE": ("BUSINESS_RULE", "rule_target", "proposed_rule"),
    "ANALYTICAL_METHOD_REVIEW": ("ANALYTICAL_METHOD", "method_target", "review_question"),
    "CONFIDENCE_POLICY_CHANGE": ("CONFIDENCE", "policy_target", "proposed_policy"),
    "NARRATIVE_TEMPLATE_CHANGE": ("NARRATIVE", "template_target", "proposed_wording"),
    "ACTION_POLICY_CHANGE": ("ACTION", "action_target", "proposed_policy"),
    "ACCESS_POLICY_REVIEW": ("ACCESS_POLICY", "policy_target", "review_question"),
}


def compatible_proposal_options(mode: str, issue_category: str | None, feedback_count: int) -> list[Dict[str, Any]]:
    options: list[Dict[str, Any]] = []
    if mode == "BUSINESS_FEEDBACK":
        if feedback_count >= 2:
            options.extend([
                {"proposal_type": "REVIEW_REQUIRED", "target_artifact_type": "REVIEW_ONLY", "fields": []},
                {"proposal_type": "EVALUATION_CASE_ADDITION", "target_artifact_type": "EVALUATION_CASE", "fields": [
                    {"name": "case_description", "label": "Case description", "max_length": 1200},
                    {"name": "expected_outcome", "label": "Expected outcome", "options": ["MATERIAL", "ABSTAIN", "CONTRADICTED", "INSUFFICIENT_HISTORY", "NO_MATERIAL_MOVEMENT", "ACCESS_DENIED"]},
                ]},
            ])
        return options

    proposal_type = ISSUE_TO_PROPOSAL.get(issue_category or "")
    schema = PROPOSED_VALUE_FIELDS.get(proposal_type or "")
    if schema:
        _, target_field, value_field = schema
        options.append({
            "proposal_type": proposal_type,
            "target_artifact_type": PROPOSAL_ARTIFACT_TYPES[proposal_type],
            "fields": [
                {"name": target_field, "label": target_field.replace("_", " ").title(), "max_length": 200},
                {"name": value_field, "label": value_field.replace("_", " ").title(), "max_length": 2000, "source": "analyst_correction"},
            ],
        })
    options.append({"proposal_type": "EVALUATION_CASE_ADDITION", "target_artifact_type": "EVALUATION_CASE", "fields": [
        {"name": "case_description", "label": "Case description", "max_length": 1200},
        {"name": "expected_outcome", "label": "Expected outcome", "options": ["MATERIAL", "ABSTAIN", "CONTRADICTED", "INSUFFICIENT_HISTORY", "NO_MATERIAL_MOVEMENT", "ACCESS_DENIED"]},
    ]})
    return options


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _group_fields(record: Dict[str, Any]) -> Dict[str, Any]:
    versions = record.get("versions") or {}
    scope = record.get("scope") or {}
    return {
        "kpi_id": record.get("kpi_id"),
        "scope": scope,
        "persona": record.get("persona"),
        "target_type": record.get("target_type"),
        "target_id": record.get("target_id"),
        "contract_version": versions.get("contract_version"),
        "contract_hash": versions.get("contract_hash"),
        "policy_version": versions.get("policy_version"),
        "policy_hash": versions.get("policy_hash"),
        "mode": record.get("mode"),
        "reason_code": record.get("reason_code"),
        "issue_category": record.get("issue_category"),
        "correction_type": record.get("correction_type"),
    }


def _time_key(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def aggregate_feedback_records(records: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """Group already-authorized typed records using only stable structured fields."""
    groups: dict[str, list[Dict[str, Any]]] = defaultdict(list)
    fields_by_key: dict[str, Dict[str, Any]] = {}
    for record in records:
        if record.get("state") not in AGGREGATABLE_STATES:
            continue
        fields = _group_fields(record)
        key = f"agg-{_digest(fields)}"
        groups[key].append(record)
        fields_by_key[key] = fields

    aggregations = []
    for aggregation_key in sorted(groups):
        group = groups[aggregation_key]
        group.sort(key=lambda item: (item.get("created_at", ""), item.get("feedback_id", "")))
        business = [item for item in group if item.get("mode") == "BUSINESS_FEEDBACK"]
        analyst = [item for item in group if item.get("mode") == "ANALYST_CORRECTION"]
        reasons = Counter(item["reason_code"] for item in business if item.get("reason_code"))
        issues = Counter(item["issue_category"] for item in analyst if item.get("issue_category"))
        corrections = Counter(item["correction_type"] for item in analyst if item.get("correction_type"))
        actions = Counter(item["action_taken"] for item in business if item.get("action_taken"))
        versions = [item.get("versions") or {} for item in group]
        current_artifact_versions = {
            "contract": {
                "version": fields_by_key[aggregation_key]["contract_version"],
                "hash": fields_by_key[aggregation_key]["contract_hash"],
            },
            "policy": {
                "version": fields_by_key[aggregation_key]["policy_version"],
                "hash": fields_by_key[aggregation_key]["policy_hash"],
            },
            "source_data_versions": sorted({value.get("source_data_version") for value in versions if value.get("source_data_version")}),
            "source_snapshots": [json.loads(item) for item in sorted({
                _canonical({"id": value.get("source_snapshot_id"), "hash": value.get("source_snapshot_hash")})
                for value in versions if value.get("source_snapshot_id") or value.get("source_snapshot_hash")
            })],
        }
        aggregations.append({
            "aggregation_key": aggregation_key,
            **fields_by_key[aggregation_key],
            "feedback_count": len(group),
            "business_feedback_count": len(business),
            "analyst_correction_count": len(analyst),
            "useful_count": sum(item.get("rating") == "USEFUL" for item in business),
            "not_useful_count": sum(item.get("rating") == "NOT_USEFUL" for item in business),
            "reason_counts": dict(sorted(reasons.items())),
            "issue_category_counts": dict(sorted(issues.items())),
            "correction_type_counts": dict(sorted(corrections.items())),
            "action_taken_counts": dict(sorted(actions.items())),
            "unique_authorized_submitter_count": len({item.get("user_id") for item in group}),
            "earliest_created_at": min((item["created_at"] for item in group), key=_time_key),
            "latest_created_at": max((item["created_at"] for item in group), key=_time_key),
            "source_feedback_ids": sorted(item["feedback_id"] for item in group),
            "affected_run_ids": sorted({item["run_id"] for item in group}),
            "current_artifact_versions": current_artifact_versions,
            "proposal_type_options": compatible_proposal_options(
                fields_by_key[aggregation_key]["mode"],
                fields_by_key[aggregation_key]["issue_category"],
                len(group),
            ),
            "message": "Feedback aggregated",
        })
    return aggregations


def proposal_change_idempotency_key(aggregation_key: str, proposal_type: str, proposed_change: Dict[str, Any]) -> str:
    return _digest({
        "aggregation_key": aggregation_key,
        "proposal_type": proposal_type,
        "proposed_change": proposed_change,
    })


def validate_proposed_change(
    proposal_type: str,
    proposed_change: Dict[str, Any] | None,
    records: list[Dict[str, Any]],
) -> Dict[str, Any]:
    if proposal_type == "REVIEW_REQUIRED":
        if any(record.get("mode") != "BUSINESS_FEEDBACK" for record in records):
            raise ValueError("REVIEW_REQUIRED proposals are only for business feedback")
        if proposed_change not in (None, {}):
            raise ValueError("REVIEW_REQUIRED proposals cannot contain a production change")
        return {"review_question": "Review recurring feedback; no production change is proposed."}

    if proposal_type == "EVALUATION_CASE_ADDITION":
        change = proposed_change or {}
        if set(change) != {"case_description", "expected_outcome"}:
            raise ValueError("Evaluation case proposals require case_description and expected_outcome only")
        description = change.get("case_description")
        expected = change.get("expected_outcome")
        allowed = {"MATERIAL", "ABSTAIN", "CONTRADICTED", "INSUFFICIENT_HISTORY", "NO_MATERIAL_MOVEMENT", "ACCESS_DENIED"}
        if not isinstance(description, str) or not description.strip() or len(description) > 1200 or expected not in allowed:
            raise ValueError("Evaluation case proposal fields are invalid")
        return {"case_description": description.strip(), "expected_outcome": expected}

    schema = PROPOSED_VALUE_FIELDS.get(proposal_type)
    if schema is None:
        raise ValueError("Unsupported proposal type")
    issue_category, target_field, value_field = schema
    change = proposed_change or {}
    if set(change) != {"source_feedback_id", target_field, value_field}:
        raise ValueError(f"{proposal_type} requires source_feedback_id, {target_field}, and {value_field} only")
    source_id = change.get("source_feedback_id")
    source = next((item for item in records if item.get("feedback_id") == source_id), None)
    if source is None or source.get("mode") != "ANALYST_CORRECTION":
        raise ValueError("A selected analyst correction must support the proposed change")
    if source.get("issue_category") != issue_category:
        raise ValueError("Proposal type does not match the analyst issue category")
    target_value = change.get(target_field)
    proposed_value = change.get(value_field)
    if not isinstance(target_value, str) or not target_value.strip() or len(target_value) > 200:
        raise ValueError("Proposal target must be a bounded non-blank string")
    if not isinstance(proposed_value, str) or not proposed_value.strip() or len(proposed_value) > 2000:
        raise ValueError("Proposed content must be a bounded non-blank string")
    if proposed_value != source.get("proposed_correction"):
        raise ValueError("Proposed content must match the selected analyst correction")
    return {"source_feedback_id": source_id, target_field: target_value.strip(), value_field: proposed_value.strip()}


def before_version_for_proposal(proposal_type: str, aggregation: Dict[str, Any]) -> tuple[str, str | None]:
    versions = aggregation["current_artifact_versions"]
    if proposal_type in {"REVIEW_REQUIRED"}:
        return "NOT_APPLICABLE", None
    if proposal_type == "NARRATIVE_TEMPLATE_CHANGE":
        reference = {"version": "approved_narrative_templates_v1", "hash": _digest({"renderer": "NarrativeEngine", "template_family": "approved_claim_variants_v1"})}
        return str(reference["version"]), reference["hash"]
    if proposal_type in {"KPI_CONTRACT_CHANGE", "DRIVER_CONFIGURATION_CHANGE"}:
        reference = versions["contract"]
    elif proposal_type == "DATA_QUALITY_FIX":
        source_versions = versions["source_data_versions"]
        reference = {"version": source_versions[0] if len(source_versions) == 1 else ",".join(source_versions), "hash": None}
    elif proposal_type == "EVALUATION_CASE_ADDITION":
        source_versions = versions["source_data_versions"]
        reference = {"version": source_versions[0] if len(source_versions) == 1 else ",".join(source_versions), "hash": None}
    else:
        reference = versions["policy"]
    return str(reference.get("version") or "UNKNOWN"), reference.get("hash")


def build_improvement_proposal(
    *,
    proposal_type: str,
    aggregation: Dict[str, Any],
    records: list[Dict[str, Any]],
    title: str,
    rationale: str,
    proposed_change: Dict[str, Any] | None,
    expected_improvement: str,
    affected_evaluation_cases: list[str],
    rollback_plan: str,
) -> tuple[Dict[str, Any], str]:
    if proposal_type not in PROPOSAL_TYPES:
        raise ValueError("Unsupported proposal type")
    modes = {record.get("mode") for record in records}
    if modes == {"BUSINESS_FEEDBACK"}:
        if aggregation["feedback_count"] < 2:
            raise ValueError("Business-only proposals require repeated compatible feedback")
        if proposal_type not in {"REVIEW_REQUIRED", "EVALUATION_CASE_ADDITION"}:
            raise ValueError("Business-only feedback cannot propose a technical configuration change")
    elif modes == {"ANALYST_CORRECTION"}:
        categories = {record.get("issue_category") for record in records}
        if proposal_type == "REVIEW_REQUIRED":
            raise ValueError("REVIEW_REQUIRED is reserved for business-only feedback")
        if proposal_type != "EVALUATION_CASE_ADDITION":
            if len(categories) != 1 or ISSUE_TO_PROPOSAL.get(next(iter(categories))) != proposal_type:
                raise ValueError("Proposal type does not match the analyst issue category")
    else:
        raise ValueError("Selected feedback must share one typed feedback mode")

    change = validate_proposed_change(proposal_type, proposed_change, records)
    before_version, before_hash = before_version_for_proposal(proposal_type, aggregation)
    artifact_type = PROPOSAL_ARTIFACT_TYPES[proposal_type]
    payload = {
        "proposal_type": proposal_type,
        "title": title.strip(),
        "rationale": rationale.strip(),
        "kpi_id": aggregation["kpi_id"],
        "scope": aggregation["scope"],
        "target_type": aggregation["target_type"],
        "target_id": aggregation["target_id"],
        "source_feedback_ids": aggregation["source_feedback_ids"],
        "source_run_ids": aggregation["affected_run_ids"],
        "issue_reason_summary": {
            "reason_counts": aggregation["reason_counts"],
            "issue_category_counts": aggregation["issue_category_counts"],
            "correction_type_counts": aggregation["correction_type_counts"],
        },
        "target_artifact_type": artifact_type,
        "before_version": before_version,
        "before_version_hash": before_hash,
        "current_artifact_versions": aggregation["current_artifact_versions"],
        "proposed_change": change,
        "expected_improvement": expected_improvement.strip(),
        "affected_evaluation_cases": sorted(set(affected_evaluation_cases)),
        "rollback_plan": rollback_plan.strip(),
        "supporting_feedback_summary": {
            "feedback_count": aggregation["feedback_count"],
            "business_feedback_count": aggregation["business_feedback_count"],
            "analyst_correction_count": aggregation["analyst_correction_count"],
            "useful_count": aggregation["useful_count"],
            "not_useful_count": aggregation["not_useful_count"],
            "reason_counts": aggregation["reason_counts"],
            "issue_category_counts": aggregation["issue_category_counts"],
            "action_taken_counts": aggregation["action_taken_counts"],
        },
        "supporting_evidence_refs": [
            {"feedback_id": record["feedback_id"], "evidence_refs": record.get("evidence_refs") or []}
            for record in records if record.get("evidence_refs")
        ],
        "aggregation_key": aggregation["aggregation_key"],
    }
    idempotency_key = proposal_change_idempotency_key(
        aggregation["aggregation_key"], proposal_type, change
    )
    return payload, idempotency_key
