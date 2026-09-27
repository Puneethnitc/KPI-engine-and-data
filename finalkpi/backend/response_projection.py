"""Deterministic, copy-only API projections for demo personas."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from backend.domain_policy import domains_for_persona, has_domain

_FINANCE_SOURCE_IDS = {"finance_monthly", "finance", "monthly_finance"}
_SOURCE_DOMAINS = {
    "sales_daily": "SALES",
    "marketing_weekly": "MARKETING",
    "finance_monthly": "FINANCE",
}
_PATH_FIELDS = {"file_path", "filepath", "physical_path", "lineage_reference", "policy_reference"}


def _is_finance_source(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() in _FINANCE_SOURCE_IDS


def _source_visible(source_id: Any, persona: str) -> bool:
    if not isinstance(source_id, str):
        return False
    domain = _SOURCE_DOMAINS.get(source_id.strip().lower())
    return bool(domain and has_domain(persona, domain))


def _without_physical_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_physical_paths(item)
            for key, item in value.items()
            if key.lower() not in _PATH_FIELDS
        }
    if isinstance(value, list):
        return [_without_physical_paths(item) for item in value]
    if isinstance(value, tuple):
        return [_without_physical_paths(item) for item in value]
    if isinstance(value, str) and (value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", value)):
        return None
    return value


def project_semantic_contract(snapshot: dict[str, Any], persona: str) -> dict[str, Any]:
    """Return a role projection without mutating the saved canonical snapshot."""
    domains_for_persona(persona)
    copied = deepcopy(snapshot)
    if has_domain(persona, "FINANCE"):
        return _without_physical_paths(copied)

    identity = copied.get("identity") or {}
    calculation = copied.get("calculation") or {}
    grain = copied.get("grain_and_scope") or {}
    materiality = copied.get("materiality") or {}
    drivers = copied.get("drivers") or {}
    reconciliation = copied.get("reconciliation") or {}
    decomposition = copied.get("decomposition") or {}
    source = copied.get("source") or {}
    candidate_drivers = []
    for item in drivers.get("candidate_drivers") or []:
        if not isinstance(item, dict):
            continue
        candidate_drivers.append({
            key: item[key]
            for key in ("display_name", "unit", "controllability", "expected_direction")
            if key in item
        })

    return {
        "schema_version": copied.get("schema_version"),
        "identity": {
            key: identity[key]
            for key in ("kpi_id", "display_name", "version", "status", "definition", "business_purpose")
            if key in identity
        } | {"owner": "", "steward": None, "tags": []},
        "calculation": {
            "numerator_column": None,
            "denominator_column": None,
            "value_column": None,
            "weight_column": None,
            "executable_method": "",
            **{
                key: calculation[key]
                for key in ("operator", "formula", "unit", "precision", "null_policy", "zero_policy", "aggregation_notes")
                if key in calculation
            },
        },
        "grain_and_scope": {
            "comparison_policy": None,
            **{
                key: grain[key]
                for key in ("native_grain", "supported_rollups", "dimensions", "calendar", "timezone", "minimum_history_periods")
                if key in grain
            },
        },
        "source": {
            "primary_source_id": "",
            "source_table": "",
            "source_grain": source.get("source_grain", ""),
            "event_time_field": "",
            "availability_time_field": "",
            "natural_key": [],
            "required_fields": [],
            "refresh_cadence": source.get("refresh_cadence"),
            "access_classification": "",
            "lineage_reference": None,
            "catalog_version": "",
            "comparison_source": None,
        },
        "materiality": {
            key: materiality[key]
            for key in (
                "statistical_method", "statistical_thresholds", "business_thresholds",
                "detector_agreement_rule", "threshold_status",
            )
            if key in materiality
        },
        "drivers": {
            "candidate_drivers": [{
                "driver_id": item.get("display_name", ""),
                "display_name": item.get("display_name", ""),
                "source_id": "",
                "column": "",
                "grain": "",
                "aggregation": "",
                "unit": item.get("unit"),
                "controllability": item.get("controllability", ""),
                "expected_direction": item.get("expected_direction"),
                "allowed_lags": None,
                "minimum_pairs": None,
                "minimum_coverage": None,
                "owner": "",
            } for item in candidate_drivers],
            "method": "",
            "limitations": [],
        },
        "reconciliation": {
            "applicable": bool(reconciliation.get("applicable")),
            "comparison_source_id": None,
            "comparison_metric": None,
            "unit": None,
            "keys": [],
            "mode": reconciliation.get("mode"),
            "tolerance": None,
            "contradiction_threshold": None,
            "coverage_rule": None,
            "availability_rule": None,
            "redacted": bool(reconciliation.get("applicable")),
            "redaction_reason": "Restricted finance comparison metadata is not visible for this persona." if reconciliation.get("applicable") else None,
        },
        "decomposition": {
            "applicable": bool(decomposition.get("applicable")),
            "method": decomposition.get("method"),
            "quantity_column": None,
            "rate_column": None,
            "reference_rate_label": None,
            "derived_rate_formula": None,
            "identity": None,
            "limitations": [],
        },
        "security": {
            "access_tags": [],
            "allowed_roles": [],
            "row_scope_dimensions": [],
            "restricted_fields": [],
            "sensitive": bool((copied.get("security") or {}).get("sensitive")),
            "policy_reference": "",
        },
        "governance": {
            "effective_from": None,
            "effective_to": None,
            "approved_by": None,
            "change_reason": None,
            "source_catalog_version": "",
            "validation_errors": [],
            **{
                key: (copied.get("governance") or {})[key]
                for key in ("contract_hash", "validation_status")
                if key in (copied.get("governance") or {})
            },
        },
        "capabilities": deepcopy(copied.get("capabilities") or {}),
    }


def _project_reconciliation(reconciliation: Any, persona: str) -> Any:
    if not isinstance(reconciliation, dict) or has_domain(persona, "FINANCE"):
        return reconciliation
    details = reconciliation.get("details") or {}
    status = reconciliation.get("status", "NOT_ASSESSED")
    applicable = status != "NOT_APPLICABLE"
    return {
        "status": status,
        "gap_pct": None,
        "applicable": applicable,
        "blocking": status == "CONTRADICTED",
        "comparison_basis": details.get("mode") or reconciliation.get("comparison_basis"),
        "reason": "Restricted finance evidence was used but its values are not visible." if applicable else "No restricted finance comparison applies.",
        "quality_status": details.get("quality_flag") or reconciliation.get("quality_status"),
        "details": {
            "mode": details.get("mode") or reconciliation.get("comparison_basis"),
            "quality_flag": details.get("quality_flag"),
            "reason": "Restricted finance evidence was used but its values are not visible." if applicable else "No restricted finance comparison applies.",
        },
        "restricted_evidence_hidden": applicable,
    }


def project_evidence(evidence: dict[str, Any], persona: str) -> dict[str, Any]:
    """Project evidence fields according to explicit source-domain access."""
    domains_for_persona(persona)
    copied = deepcopy(evidence)
    if has_domain(persona, "FINANCE"):
        return copied

    readiness = copied.get("source_readiness")
    if isinstance(readiness, dict):
        for key in ("required_sources", "available_sources"):
            if isinstance(readiness.get(key), list):
                readiness[key] = [item for item in readiness[key] if _source_visible(item, persona)]
        readiness["limitations"] = _safe_evidence_limitations(readiness.get("limitations"), persona)
    sources = copied.get("sources")
    if isinstance(sources, list):
        copied["sources"] = [
            item for item in sources
            if not isinstance(item, dict)
            or _source_visible(item.get("source_id"), persona) and item.get("access_classification") != "restricted"
        ]
    alignment = copied.get("alignment")
    if isinstance(alignment, list):
        copied["alignment"] = [
            item for item in alignment
            if not isinstance(item, dict) or _source_visible(item.get("source_id"), persona)
        ]
    lineage = copied.get("lineage")
    if isinstance(lineage, list):
        copied["lineage"] = [
            item for item in lineage
            if not isinstance(item, dict)
            or _source_visible(item.get("source_id"), persona) and item.get("access_classification") != "restricted"
        ]
    copied["reconciliation"] = _project_reconciliation(copied.get("reconciliation"), persona)
    copied["limitations"] = _safe_evidence_limitations(copied.get("limitations"), persona)
    claim_evidence = copied.get("narrative_claim_evidence")
    if isinstance(claim_evidence, list):
        copied["narrative_claim_evidence"] = [item for item in claim_evidence if not _contains_unavailable_source(item, persona)]
    copied["restricted_evidence_hidden"] = bool(
        (evidence.get("reconciliation") or {}).get("applicable")
        or any(not _source_visible(item.get("source_id"), persona) for item in evidence.get("sources", []) if isinstance(item, dict))
    )
    if copied["restricted_evidence_hidden"]:
        copied["limitations"] = list(copied.get("limitations") or [])
        finance_hidden = bool(
            (evidence.get("reconciliation") or {}).get("applicable")
            or any(_is_finance_source(item.get("source_id")) for item in evidence.get("sources", []) if isinstance(item, dict))
        )
        notice = (
            "Restricted finance evidence exists but is not visible for this persona."
            if finance_hidden else "Evidence from an unavailable domain exists but is not visible for this persona."
        )
        if notice not in copied["limitations"]:
            copied["limitations"].append(notice)
    return copied


def _safe_evidence_limitations(value: Any, persona: str) -> list[Any]:
    if not isinstance(value, list):
        return []
    safe = []
    finance_notice = "Restricted finance evidence exists but is not visible for this persona."
    marketing_notice = "Marketing-domain evidence exists but is not visible for this persona."
    for entry in value:
        hidden_notice = None
        if isinstance(entry, str) and "finance" in entry.lower() and not has_domain(persona, "FINANCE"):
            hidden_notice = finance_notice
        elif isinstance(entry, str) and "marketing" in entry.lower() and not has_domain(persona, "MARKETING"):
            hidden_notice = marketing_notice
        if hidden_notice:
            if hidden_notice not in safe:
                safe.append(hidden_notice)
        else:
            safe.append(entry)
    return safe


def project_diagnosis(result: dict[str, Any], persona: str) -> dict[str, Any]:
    """Deep-copy a diagnosis and project finance/contract fields for the caller."""
    domains_for_persona(persona)
    copied = deepcopy(result)
    if copied.get("verdict") == "ACCESS_DENIED":
        allowed = (
            "run_id", "kpi_id", "target_date", "as_of", "persona", "segment", "treated_slice",
            "verdict", "narrative", "decomposition_status", "grounding_passed", "narrative_method",
            "processing_transparency",
        )
        return {key: copied[key] for key in allowed if key in copied}

    finance_allowed = has_domain(persona, "FINANCE")
    if not has_domain(persona, "MARKETING") and isinstance(copied.get("source_coverage"), dict):
        copied["source_coverage"] = {
            key: value for key, value in copied["source_coverage"].items() if key == "sales_rows"
        }
    if isinstance(copied.get("reconciliation_verdict"), dict):
        copied["reconciliation_verdict"] = _project_reconciliation(copied["reconciliation_verdict"], persona)
    if isinstance(copied.get("source_evidence"), dict):
        copied["source_evidence"] = project_evidence(copied["source_evidence"], persona)
    if isinstance(copied.get("contract_snapshot"), dict):
        copied["contract_snapshot"] = project_semantic_contract(copied["contract_snapshot"], persona)
    if not finance_allowed:
        copied.pop("query_provenance", None)
        execution_metadata = copied.get("execution_metadata")
        if isinstance(execution_metadata, dict):
            execution_metadata.pop("query_provenance", None)
        telemetry = copied.get("telemetry")
        if isinstance(telemetry, dict):
            telemetry.pop("query_provenance", None)
        _project_confidence_evidence(copied.get("confidence_profile"), persona)
        _project_confidence_evidence(copied.get("evidence_profile"), persona)
        _project_confidence_evidence(copied.get("processing_transparency"), persona)
        _project_confidence_evidence(copied.get("narrative_claims"), persona)
    return copied


def _project_confidence_evidence(value: Any, persona: str) -> None:
    if isinstance(value, dict):
        for key, item in list(value.items()):
            if key in {"source_entries", "sources"} and isinstance(item, list):
                value[key] = [
                    entry for entry in item
                    if not isinstance(entry, dict)
                    or _source_visible(entry.get("source_id"), persona) and entry.get("access_classification") != "restricted"
                ]
            elif key in {"required_sources", "available_sources"} and isinstance(item, list):
                value[key] = [entry for entry in item if _source_visible(entry, persona)]
            elif key == "evidence_refs" and isinstance(item, list):
                value[key] = [
                    ref for ref in item
                    if not isinstance(ref, str) or "reconcil" not in ref.lower() and "source_evidence.sources" not in ref.lower()
                ]
            elif key in {"evidence_paths", "query_identifier", "row_or_period_reference"}:
                if _contains_unavailable_source(item, persona):
                    value.pop(key, None)
                else:
                    _project_confidence_evidence(item, persona)
            else:
                _project_confidence_evidence(item, persona)
    elif isinstance(value, list):
        for item in value:
            _project_confidence_evidence(item, persona)


def _contains_unavailable_source(value: Any, persona: str) -> bool:
    if isinstance(value, str):
        normalized = value.lower()
        for source_id, domain in _SOURCE_DOMAINS.items():
            if not has_domain(persona, domain) and source_id in normalized:
                return True
        return "finance_ledger" in normalized and not has_domain(persona, "FINANCE")
    if isinstance(value, dict):
        return any(_contains_unavailable_source(key, persona) or _contains_unavailable_source(item, persona) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_unavailable_source(item, persona) for item in value)
    return False


def project_saved_run(run: dict[str, Any], persona: str) -> dict[str, Any]:
    """Project a saved-run envelope without mutating its persisted snapshot."""
    copied = deepcopy(run)
    for key in ("result_json", "scope_json", "contract_snapshot_json", "comparison_scope_json", "query_provenance_json"):
        copied.pop(key, None)
    copied["identity_mode"] = "DEMO_SIMULATED"
    if isinstance(copied.get("result"), dict):
        copied["result"] = project_diagnosis(copied["result"], persona)
        if not has_domain(persona, "FINANCE"):
            copied.pop("query_provenance", None)
            copied.pop("access_context", None)
            telemetry = copied["result"].get("telemetry")
            if isinstance(telemetry, dict):
                telemetry.pop("query_provenance", None)
    if isinstance(copied.get("contract_snapshot"), dict):
        copied["contract_snapshot"] = project_semantic_contract(copied["contract_snapshot"], persona)
    return copied
