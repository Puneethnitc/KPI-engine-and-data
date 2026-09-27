from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from kpi_engine.contracts.models import KPIContract
from kpi_engine.query.models import SourceCatalogEntry

SOURCE_CATALOG_VERSION = "1"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def semantic_contract_projection(
    contract: KPIContract,
    source: SourceCatalogEntry,
    *,
    allowed_roles: list[str],
    comparison_source: SourceCatalogEntry | None = None,
) -> dict[str, Any]:
    """Safe immutable semantic projection generated from executable metadata."""
    calculation = contract.resolved_calculation()
    projected_fields = {
        calculation.value_column,
        calculation.numerator_column,
        calculation.denominator_column,
        calculation.weight_column,
        *contract.decomposition.values(),
        *[
            driver.get("column")
            for driver in contract.candidate_drivers
            if driver.get("source") == source.source_id
        ],
    }
    source_fields = [
        {
            "name": field.name,
            "type": field.field_type,
            "required": field.required,
            "nullable": field.nullable,
            "unit": field.unit,
            "description": field.description,
        }
        for _, field in sorted(source.fields.items())
        if field.required or field.name in projected_fields
    ]
    comparison = contract.reconciliation
    reconciliation = {
        "applicable": comparison is not None,
        "comparison_source_id": comparison.get("finance_source", "finance_monthly") if comparison else None,
        "comparison_metric": comparison.get("finance_column") if comparison else None,
        "unit": comparison.get("unit") if comparison else None,
        "keys": list(comparison.get("keys") or []) if comparison else [],
        "mode": comparison.get("mode") if comparison else None,
        "tolerance": comparison.get("tolerance_pct") if comparison else None,
        "contradiction_threshold": comparison.get("contradiction_multiple") if comparison else None,
        "coverage_rule": "require matching coverage" if comparison and comparison.get("require_matching_coverage", True) else None,
        "availability_rule": "closed-month posting available by run as-of cutoff" if comparison else None,
    }
    decomposition = contract.decomposition or None
    capabilities = {
        "movement_detection": "SUPPORTED",
        "decomposition": "SUPPORTED" if decomposition else "NOT_APPLICABLE",
        "driver_ranking": "SUPPORTED" if contract.candidate_drivers else "NOT_APPLICABLE",
        "reconciliation": "SUPPORTED" if comparison else "NOT_APPLICABLE",
        "causal_verification": "CONDITIONAL" if contract.candidate_drivers else "NOT_SUPPORTED",
    }
    snapshot: dict[str, Any] = {
        "schema_version": 1,
        "identity": {
            "kpi_id": contract.kpi_id,
            "display_name": contract.display_name or contract.kpi_id.replace("_", " ").title(),
            "version": contract.version,
            "status": contract.status,
            "definition": contract.definition,
            "business_purpose": contract.business_purpose or contract.definition,
            "owner": contract.owner,
            "steward": contract.steward,
            "tags": list(contract.tags),
        },
        "calculation": {
            "operator": calculation.operator.upper(),
            "formula": calculation.formula or contract.formula,
            "numerator_column": calculation.numerator_column,
            "denominator_column": calculation.denominator_column,
            "value_column": calculation.value_column,
            "weight_column": calculation.weight_column,
            "unit": contract.unit,
            "precision": contract.precision,
            "null_policy": contract.null_policy or (contract.missing_data_policy.null_policy if contract.missing_data_policy else "reject"),
            "zero_policy": contract.zero_policy or ("valid zero; zero denominator is missing" if calculation.operator == "ratio_of_sums" else "zero is valid"),
            "aggregation_notes": list(contract.aggregation_notes),
            "executable_method": calculation.operator,
        },
        "grain_and_scope": {
            "native_grain": contract.grain,
            "supported_rollups": list(contract.supported_rollups or contract.dimensions),
            "dimensions": list(contract.dimensions),
            "calendar": contract.calendar,
            "timezone": contract.timezone,
            "comparison_policy": asdict(contract.comparison_policy) if contract.comparison_policy else None,
            "minimum_history_periods": contract.min_history_periods,
        },
        "source": {
            "primary_source_id": source.source_id,
            "source_table": source.table_name,
            "source_grain": source.grain,
            "event_time_field": source.date_column,
            "availability_time_field": source.availability_column,
            "natural_key": list(source.natural_key),
            "required_fields": source_fields,
            "refresh_cadence": source.refresh_cadence,
            "access_classification": source.access_classification,
            "lineage_reference": source.lineage_reference,
            "catalog_version": source.version,
            "comparison_source": ({
                "source_id": comparison_source.source_id,
                "source_table": comparison_source.table_name,
                "source_grain": comparison_source.grain,
                "event_time_field": comparison_source.date_column,
                "availability_time_field": comparison_source.availability_column,
                "natural_key": list(comparison_source.natural_key),
                "refresh_cadence": comparison_source.refresh_cadence,
                "access_classification": comparison_source.access_classification,
                "lineage_reference": comparison_source.lineage_reference,
                "catalog_version": comparison_source.version,
            } if comparison_source else None),
        },
        "materiality": {
            "statistical_method": contract.statistical_method,
            "statistical_thresholds": {"z_threshold": contract.materiality.z_threshold},
            "business_thresholds": {"absolute_change": contract.materiality.abs_threshold, "unit": contract.unit},
            "detector_agreement_rule": contract.detector_agreement_rule,
            "threshold_status": contract.threshold_status,
            "calibration_reference": contract.calibration_reference,
        },
        "drivers": {
            "candidate_drivers": [
                {
                    "driver_id": item["id"],
                    "display_name": item.get("display_name", item["id"].replace("_", " ").title()),
                    "source_id": item["source"],
                    "column": item["column"],
                    "grain": item["grain"],
                    "aggregation": item.get("aggregation", "mean").upper(),
                    "unit": item.get("unit"),
                    "controllability": item.get("controllability", "contextual").upper(),
                    "expected_direction": item.get("expected_direction"),
                    "expected_direction_by_scope": item.get("expected_direction_by_scope"),
                    "allowed_lags": item.get("allowed_lags"),
                    "minimum_pairs": item.get("min_pairs"),
                    "minimum_coverage": item.get("minimum_coverage"),
                    # No fallback to the KPI owner (F-A2): a driver without its
                    # own declared owner resolves through action.py's lever
                    # catalog instead, so e.g. a marketing lever is never
                    # assigned to the KPI's regional/ops owner.
                    "owner": item.get("owner"),
                }
                for item in contract.candidate_drivers
            ],
            "method": contract.driver_method,
            "limitations": list(contract.driver_limitations),
        },
        "reconciliation": reconciliation,
        "decomposition": {
            "applicable": decomposition is not None,
            "method": "exact product-by-segment accounting identity" if decomposition else None,
            "quantity_column": (decomposition or {}).get("quantity_column"),
            "rate_column": None,
            "reference_rate_label": (decomposition or {}).get("reference_rate_column"),
            "derived_rate_formula": (
                f"sum({contract.value_column}) / sum({(decomposition or {}).get('quantity_column')})"
                if decomposition else None
            ),
            "identity": f"sum({contract.value_column}) = sum({((decomposition or {}).get('quantity_column'))}) × derived rate" if decomposition else None,
            "limitations": list(contract.decomposition_limitations) + ([
                "The bridge derives rate from period totals; reference_rate_label is presentation metadata, not a source input column.",
                "Displayed rate field is not read by decomposition; unit prices are revenue sums divided by quantity sums."
            ] if decomposition else []),
        },
        "security": {
            "access_tags": list(contract.access_tags),
            "allowed_roles": sorted(set(allowed_roles)),
            "row_scope_dimensions": list(contract.dimensions),
            "restricted_fields": [reconciliation["comparison_metric"]] if reconciliation["applicable"] else [],
            "sensitive": source.access_classification == "restricted" or reconciliation["applicable"],
            "policy_reference": contract.policy_reference,
        },
        "governance": {
            "contract_hash": "",
            "effective_from": contract.effective_from,
            "effective_to": contract.effective_to,
            "approved_by": contract.approved_by,
            "change_reason": contract.change_reason,
            "source_catalog_version": contract.source_catalog_version or SOURCE_CATALOG_VERSION,
            "validation_status": "VALID",
            "validation_errors": [],
        },
        "capabilities": capabilities,
    }
    digest_payload = json.loads(json.dumps(snapshot))
    digest_payload["governance"].pop("contract_hash", None)
    snapshot["governance"]["contract_hash"] = hashlib.sha256(canonical_json(digest_payload).encode("utf-8")).hexdigest()
    return snapshot


def redact_contract_projection(snapshot: dict[str, Any], persona: str) -> dict[str, Any]:
    """Return a safe role-specific copy; never redact the saved canonical snapshot."""
    import copy

    result = copy.deepcopy(snapshot)
    if persona.strip().lower() in {"cfo", "finance_owner"}:
        return result
    reconciliation = result.get("reconciliation") or {}
    if reconciliation.get("applicable"):
        reconciliation["comparison_metric"] = None
        reconciliation["unit"] = None
        reconciliation["keys"] = []
        reconciliation["redacted"] = True
        reconciliation["redaction_reason"] = "Restricted finance comparison metadata is visible only to finance-authorized roles."
        source = result.get("source") or {}
        source["comparison_source"] = {
            "source_id": reconciliation.get("comparison_source_id"),
            "source_grain": "monthly",
            "access_classification": "restricted",
            "redacted": True,
        }
    security = result.get("security") or {}
    security["restricted_fields"] = []
    return result
