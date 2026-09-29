# IMPLEMENTATION HANDOFF — engine/API boundary
# Current: discovers registry IDs but loads bundled CSVs per KPI, validates fixed
# region/category/date filters, and accepts only the configured demo persona.
# Next: accept dataset/catalog, generic dimensions and as-of; prepare one source
# snapshot per request and share query-service outputs. Reject mixed unknown KPI
# IDs explicitly rather than silently dropping them. Derive filters from allowed,
# available data. See ../kpi_engine/IMPLEMENTATION_HANDOFF.md and duckdb/README.md.
# Check: new configured KPI/dimensions work without editing API allowlists and
# metadata does not expose unavailable or unauthorized slices.
# DEMO_IDENTITIES includes a category-restricted role (Stage 1, F-S4) to
# exercise column/domain-level, not just row/region-level, security.
# get_movements (Stage 2, F-D4) is a separate fast detection-only scan
# (kpi_engine/scan.py); movement_priority's formula also replaces
# build_marketing_brief's old material/decline/other bucket ordering.

from __future__ import annotations

import os
import hashlib
import copy
import time
from datetime import date
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pandas as pd
import numpy as np

from kpi_engine.access import AccessController
from kpi_engine.llm_narrator import executive_summary
from kpi_engine.attribution import AttributionEngine
from kpi_engine.contracts.registry import resolve_driver_id
from kpi_engine.contracts import KPIRegistry
from kpi_engine.contracts.metrics import daily_values, prepare_metric_request
from kpi_engine.pipeline import KPIEnginePipeline
from kpi_engine.scan import MovementScanner, revenue_equivalent_delta
from kpi_engine.query.catalog import SourceCatalog
from kpi_engine.query.service import QueryService

from backend.config import ACCESS_CSV, DEFAULT_CATEGORY, DEFAULT_DATE, DEFAULT_PERSONA, DEFAULT_REGION, ENGINE_REGISTRY_DIR, EVIDENCE_CSV, FEEDBACK_LOG_PATH, MARKETING_CSV, SALES_CSV
from kpi_engine.evidence import SourceEvidenceBuilder
from backend.feedback_learning import aggregate_feedback_records
from backend.domain_policy import require_domain
from backend.llm_config import get_model_economics, get_runtime_limits
from backend.runtime_telemetry import RuntimeTelemetry, estimate_cost_usd
from backend.response_projection import project_diagnosis, project_semantic_contract
from backend.storage import find_diagnosis_run, get_feedback_submission, get_legacy_feedback, get_run, get_run_access_metadata, get_run_contract_metadata, list_diagnosis_runs, list_feedback, list_feedback_submissions, save_diagnosis_run
from backend.storage import get_improvement_proposal, list_improvement_proposals
from backend.storage import get_candidate_artifact, get_proposal_evaluation

SUPPORTED_PERSONAS = ("CFO", "marketing_manager", "regional_manager_north")
DEMO_IDENTITY_MODE = "DEMO_SIMULATED"
DEMO_IDENTITIES = {
    "demo-cfo": "CFO",
    "demo-marketing": "marketing_manager",
    "demo-regional-north": "regional_manager_north",
    # F-S4 (plan §1.9): a category-restricted role, to exercise the
    # column/domain-level security requirement (every other role currently
    # has can_view_categories = ALL).
    "demo-category-manager-north-electronics": "category_manager_north_electronics",
}
ENGINE_VERSION = "kpi-engine-summary-caps-v1"
from kpi_engine.verification.registry import resolve_governed_design


def identity_persona(user_id: str) -> str:
    try:
        return DEMO_IDENTITIES[user_id]
    except KeyError as exc:
        raise ValueError("Unknown demo identity") from exc


def authorize_scope(user_id: str, region: str, category: str) -> str:
    persona = identity_persona(user_id)
    if not _build_pipeline().access_controller.check(persona, {"region": region, "category": category}).allowed:
        raise PermissionError("Requested scope is not authorized.")
    return persona


def _build_pipeline() -> KPIEnginePipeline:
    return KPIEnginePipeline(
        registry_dir=ENGINE_REGISTRY_DIR,
        evidence_csv=EVIDENCE_CSV,
        access_csv=ACCESS_CSV,
        feedback_log_path=FEEDBACK_LOG_PATH,
        groq_api_key=os.getenv("GROQ_API_KEY"),
    )


def _catalog_with_files(source_files: Dict[str, str] | None = None) -> SourceCatalog:
    catalog = SourceCatalog()
    for source_id, file_path in (source_files or {}).items():
        source = catalog.sources.get(source_id)
        if source is None:
            continue
        catalog.sources[source_id] = replace(source, file_path=str(file_path))
    return catalog


def _registry_with_catalog(catalog: SourceCatalog | None = None) -> KPIRegistry:
    configured_catalog = catalog or SourceCatalog()
    return KPIRegistry(ENGINE_REGISTRY_DIR, source_catalog=configured_catalog)


def _source_data_version(source_files: Dict[str, str] | None = None) -> str:
    catalog = _catalog_with_files(source_files)
    versions = []
    for source_id, source in sorted(catalog.sources.items()):
        path = Path(source.file_path)
        if path.exists():
            stat = path.stat()
            versions.append((source_id, str(path.resolve()), stat.st_size, stat.st_mtime_ns))
    return hashlib.sha256(repr(versions).encode("utf-8")).hexdigest()


def _bind_source_evidence_metadata(
    result: Dict[str, Any],
    *,
    source_version: str,
    contract_version: int | str,
    source_files: Dict[str, str] | None,
) -> None:
    evidence = result.get("source_evidence")
    if not isinstance(evidence, dict):
        return
    evidence["source_data_version"] = source_version
    evidence["contract_version"] = str(contract_version)
    evidence["source_mode"] = "demo_fixture" if source_files else "production"
    evidence["snapshot_status"] = "CAPTURED_AT_EXECUTION"
    for item in evidence.get("lineage") or []:
        item["contract_version"] = str(contract_version)
        if not item.get("query_identifier"):
            item["query_identifier"] = f"source-version:{source_version}"


def _authorized_contract_context(
    user_id: str,
    region: str | None,
    category: str | None,
) -> tuple[str, KPIRegistry, list[str]]:
    persona = identity_persona(user_id)
    require_domain(persona, "KPI_CONTRACT")
    scope = {key: value for key, value in {"region": region, "category": category}.items() if value is not None}
    decision = AccessController(ACCESS_CSV).check(persona, scope)
    if not decision.allowed:
        raise PermissionError(decision.reason)
    registry = _registry_with_catalog(SourceCatalog())
    roles = sorted(set(AccessController(ACCESS_CSV).df["owner_role"].astype(str)))
    return persona, registry, roles


def _safe_contract_snapshot(
    registry: KPIRegistry,
    kpi_id: str,
    persona: str,
    roles: list[str],
) -> Dict[str, Any]:
    return project_semantic_contract(
        registry.semantic_snapshot(kpi_id, allowed_roles=roles), persona,
    )


def get_registered_kpis(
    user_id: str = "demo-marketing",
    *,
    region: str | None = None,
    category: str | None = None,
) -> List[Dict[str, Any]]:
    persona, registry, roles = _authorized_contract_context(user_id, region, category)
    payload: List[Dict[str, Any]] = []
    for kpi_id in registry.list_ids():
        contract = registry.get(kpi_id)
        snapshot = _safe_contract_snapshot(registry, kpi_id, persona, roles)
        payload.append({
            **snapshot,
            "kpi_id": contract.kpi_id,
            "version": contract.version,
            "definition": contract.definition,
            "unit": contract.unit,
            "grain": contract.grain,
            "dimensions": contract.dimensions,
            "reconciliation_config": snapshot["reconciliation"],
            "decomposition_config": snapshot["decomposition"],
            "candidate_drivers": snapshot["drivers"]["candidate_drivers"],
            "capabilities": snapshot["capabilities"],
        })
    return payload


def get_current_kpi_contract(
    kpi_id: str,
    user_id: str,
    *,
    region: str | None = None,
    category: str | None = None,
) -> Dict[str, Any]:
    persona, registry, roles = _authorized_contract_context(user_id, region, category)
    return _safe_contract_snapshot(registry, kpi_id, persona, roles)


def get_run_kpi_contract(
    run_id: str,
    user_id: str,
) -> Dict[str, Any] | None:
    persona = identity_persona(user_id)
    require_domain(persona, "KPI_CONTRACT")
    access_metadata = get_run_access_metadata(run_id)
    if access_metadata is None:
        return None
    if access_metadata.get("persona") != persona:
        raise PermissionError("Contract snapshot is not available to this identity.")
    access = AccessController(ACCESS_CSV).check(persona, access_metadata.get("scope", {}))
    if not access.allowed:
        raise PermissionError("Contract snapshot is not available to this scope.")
    saved = get_run_contract_metadata(run_id)
    if saved is None:
        raise PermissionError("Contract snapshot disappeared before authorized retrieval.")
    snapshot = saved.get("contract_snapshot")
    registry = _registry_with_catalog(SourceCatalog())
    roles = sorted(set(AccessController(ACCESS_CSV).df["owner_role"].astype(str)))
    try:
        current = _safe_contract_snapshot(registry, saved["kpi_id"], persona, roles)
    except KeyError:
        current = None
    safe_saved = project_semantic_contract(snapshot, persona) if isinstance(snapshot, dict) else None
    if safe_saved is None:
        comparison = {
            "snapshot_status": "MISSING",
            "same_version": None,
            "same_hash": None,
            "changed_since_run": None,
        }
    else:
        saved_governance = safe_saved.get("governance") or {}
        current_governance = (current or {}).get("governance") or {}
        same_version = safe_saved.get("identity", {}).get("version") == (current or {}).get("identity", {}).get("version")
        same_hash = saved_governance.get("contract_hash") == current_governance.get("contract_hash") if current else False
        comparison = {
            "snapshot_status": "CAPTURED",
            "same_version": same_version,
            "same_hash": same_hash,
            "changed_since_run": not same_hash,
        }
    return {
        "run_id": run_id,
        "kpi_id": saved["kpi_id"],
        "contract_snapshot": safe_saved,
        "current_contract": current,
        "comparison": comparison,
    }


def _resolve_scope(
    *,
    scope: Dict[str, Any] | None = None,
    target_date: str | None = None,
    region: str | None = None,
    category: str | None = None,
    as_of: str | None = None,
) -> Dict[str, Any]:
    effective: Dict[str, Any] = dict(scope or {})
    if target_date is not None:
        effective["target_date"] = target_date
    if region is not None:
        effective["region"] = region
    if category is not None:
        effective["category"] = category
    if as_of is not None:
        effective["as_of"] = as_of
    if "date" in effective and "target_date" not in effective:
        effective["target_date"] = effective["date"]
    if "target_date" not in effective:
        effective["target_date"] = DEFAULT_DATE

    # "ALL" is an explicit aggregate request: the dimension key is dropped from
    # the slice (AccessController treats an absent key as unrestricted and only
    # allows it for ALL-scoped roles, so every other role fails closed).
    aggregate = {key for key in ("region", "category") if str(effective.get(key, "")).strip().upper() == "ALL"}
    for key in aggregate:
        del effective[key]

    allowed_dims = _get_allowed_dimensions()
    legacy_defaults = {"region": DEFAULT_REGION, "category": DEFAULT_CATEGORY}
    for key, fallback in legacy_defaults.items():
        if key in allowed_dims and key not in effective and key not in aggregate:
            effective[key] = fallback
    return effective


def _get_allowed_dimensions(
    kpis: Sequence[str] | None = None,
    *,
    catalog: SourceCatalog | None = None,
    registry: KPIRegistry | None = None,
) -> set[str]:
    configured_catalog = catalog or SourceCatalog()
    configured_registry = registry or _registry_with_catalog(configured_catalog)
    selected = list(kpis) if kpis else configured_registry.list_ids()
    allowed: set[str] = set()
    for kpi_id in selected:
        if kpi_id not in configured_registry._contracts:
            continue
        contract = configured_registry.get(kpi_id)
        allowed.update(contract.dimensions)
        source = configured_catalog.sources.get(contract.source)
        if source is not None:
            allowed.update(source.dimensions)
    allowed.update({"region", "category"})
    return allowed


def _get_allowed_filter_values(
    *,
    catalog: SourceCatalog | None = None,
    registry: KPIRegistry | None = None,
) -> Dict[str, list[str]]:
    values: Dict[str, list[str]] = {}
    configured_catalog = catalog or SourceCatalog()
    configured_registry = registry or _registry_with_catalog(configured_catalog)
    for source in configured_catalog.sources.values():
        csv_path = Path(source.file_path)
        if not csv_path.exists():
            continue
        try:
            frame = pd.read_csv(csv_path, keep_default_na=False)
        except Exception:
            continue
        for dimension in source.dimensions:
            if dimension not in frame.columns:
                continue
            parsed = frame[dimension].replace({"": None}).dropna().astype(str).unique().tolist()
            values.setdefault(dimension, [])
            values[dimension] = sorted(set(values[dimension]) | set(parsed))
    for contract in configured_registry._contracts.values():
        for dimension in contract.dimensions:
            values.setdefault(dimension, [])
    order = ["date", "region", "category"]
    for key in sorted(values):
        if key not in order:
            order.append(key)
    return {key: sorted(set(values.get(key, []))) for key in order}


def get_available_filters() -> Dict[str, Any]:
    catalog = SourceCatalog()
    registry = _registry_with_catalog(catalog)
    date_values: set[str] = set()
    for source_id, source in catalog.sources.items():
        if source_id != "sales_daily":
            continue
        csv_path = Path(source.file_path)
        if not csv_path.exists():
            continue
        try:
            frame = pd.read_csv(csv_path, keep_default_na=False)
        except Exception:
            continue
        for column in (source.date_column, *[candidate for candidate in ("date", "week_start", "month_start", "month_end") if candidate != source.date_column]):
            if column not in frame.columns:
                continue
            parsed = pd.to_datetime(frame[column].replace({"": None}), errors="coerce").dropna().dt.strftime("%Y-%m-%d").unique().tolist()
            date_values.update(parsed)
    dimensions = sorted(_get_allowed_dimensions(catalog=catalog, registry=registry))
    allowed_values = _get_allowed_filter_values(catalog=catalog, registry=registry)
    legacy_regions = allowed_values.get("region", [])
    legacy_categories = allowed_values.get("category", [])
    return {
        "regions": legacy_regions,
        "categories": legacy_categories,
        "dates": sorted(date_values),
        "dimensions": dimensions,
        "allowed_values": allowed_values,
        "persona": list(SUPPORTED_PERSONAS),
        "default": {
            "region": DEFAULT_REGION if "region" in dimensions else None,
            "category": DEFAULT_CATEGORY if "category" in dimensions else None,
            "date": DEFAULT_DATE,
            "persona": DEFAULT_PERSONA,
        },
    }


def _validate_scope(
    *,
    scope: Dict[str, Any],
    persona: str,
    kpis: Sequence[str] | None = None,
    check_access: bool = True,
) -> None:
    if not persona or not str(persona).strip():
        raise ValueError("A valid persona is required.")
    require_domain(persona, "SALES")

    allowed_dimensions = _get_allowed_dimensions(kpis=kpis)
    for key, value in scope.items():
        if key in {"persona", "as_of", "target_date", "date"}:
            continue
        if key not in allowed_dimensions:
            raise ValueError(f"Unsupported dimension: {key}")

    requested_dims = {key: value for key, value in scope.items() if key in {"region", "category"}}
    if check_access:
        access = AccessController(ACCESS_CSV).check(persona, requested_dims)
        if not access.allowed:
            raise ValueError(access.reason)

    target_date = scope.get("target_date") or scope.get("date") or DEFAULT_DATE
    try:
        date.fromisoformat(target_date)
    except ValueError as exc:
        raise ValueError("target_date must be in YYYY-MM-DD format") from exc
    if target_date not in get_available_filters()["dates"]:
        raise ValueError(f"Unsupported target_date: {target_date}")


def _prepare_requested_kpis(
    selected: Sequence[str],
    target_date: str,
    scope: Dict[str, Any],
    as_of: str | None = None,
    source_files: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    catalog = _catalog_with_files(source_files)
    registry = _registry_with_catalog(catalog)
    service = QueryService(catalog)
    prepared: Dict[str, Any] = {}
    dimension_slice = {key: value for key, value in scope.items() if key not in {"target_date", "date", "as_of", "persona"} and value is not None}

    for kpi_id in selected:
        contract = registry.get(kpi_id)
        frame = service.load_source(contract.source, scope=dimension_slice, as_of=as_of)
        prepared[kpi_id] = prepare_metric_request(
            frame,
            contract,
            target_date,
            dimension_slice=dimension_slice,
            as_of=as_of,
        )
    return prepared


def get_movements(date: str, user_id: str, kpis: Sequence[str] | None = None) -> Dict[str, Any]:
    """Stage 2 (F-D4): a fast, detection-only, priority-ranked scan across
    every KPI/slice the caller's identity is authorised to see. Never runs
    driver ranking, reconciliation or narrative -- a movement worth
    investigating still needs a follow-up diagnose_scope call.
    """
    persona = identity_persona(user_id)
    registry = _registry_with_catalog()
    selected = registry.list_ids() if not kpis else list(kpis)
    unknown = [kpi_id for kpi_id in selected if kpi_id not in registry._contracts]
    if unknown:
        raise ValueError(f"Unknown KPI ID(s): {', '.join(unknown)}")
    scanner = MovementScanner(ENGINE_REGISTRY_DIR, ACCESS_CSV)
    movements = scanner.scan(date=date, persona=persona, kpis=selected, sales_csv=SALES_CSV)
    return {"date": date, "persona": persona, "movements": movements}


def diagnose_scope(
    *,
    kpis: Sequence[str] | None = None,
    target_date: str | None = None,
    region: str | None = None,
    category: str | None = None,
    persona: str = DEFAULT_PERSONA,
    scope: Dict[str, Any] | None = None,
    as_of: str | None = None,
    source_files: Dict[str, str] | None = None,
    cache_extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    require_domain(persona, "SALES")
    catalog = _catalog_with_files(source_files)
    registry = _registry_with_catalog(catalog)
    selected = registry.list_ids() if not kpis or "all" in kpis else list(kpis)
    unknown = [kpi_id for kpi_id in selected if kpi_id not in registry._contracts]
    if unknown:
        unknown_text = ", ".join(unknown)
        raise ValueError(f"Unknown KPI ID(s): {unknown_text}")
    if not selected:
        raise ValueError("No valid KPI IDs supplied")

    effective_scope = _resolve_scope(scope=scope, target_date=target_date, region=region, category=category, as_of=as_of)
    _validate_scope(scope=effective_scope, persona=persona, kpis=selected, check_access=False)

    source_version = _source_data_version(source_files)
    pipeline = _build_pipeline()
    results: Dict[str, Any] = {}
    pending: list[str] = []
    dimension_slice = {key: value for key, value in effective_scope.items() if key not in {"target_date", "date", "as_of", "persona"} and value is not None}
    access = AccessController(ACCESS_CSV).check(persona, {key: dimension_slice.get(key) for key in ("region", "category") if key in dimension_slice})
    cache_scope = {
        **dimension_slice,
        "target_date": effective_scope["target_date"],
        "persona": persona,
        **({"as_of": effective_scope.get("as_of")} if effective_scope.get("as_of") else {}),
        **(cache_extra or {}),
    }
    sales_csv = (source_files or {}).get("sales_daily", SALES_CSV)
    marketing_csv = (source_files or {}).get("marketing_weekly", str(Path(SALES_CSV).with_name("marketing_weekly.csv")))
    finance_csv = (source_files or {}).get("finance_monthly", str(Path(SALES_CSV).with_name("finance_monthly.csv")))

    if not access.allowed:
        for kpi_id in selected:
            result = pipeline.run_diagnosis(
                kpi_id=kpi_id,
                target_date=effective_scope["target_date"],
                sales_csv=sales_csv,
                marketing_csv=marketing_csv,
                finance_csv=finance_csv,
                persona=persona,
                dimension_slice=dimension_slice,
                as_of=effective_scope.get("as_of"),
            )
            result["engine_version"] = ENGINE_VERSION
            result["source_data_version"] = source_version
            result["contract_version"] = registry.get(kpi_id).version
            result.pop("_runtime_stages", None)
            _bind_source_evidence_metadata(
                result,
                source_version=source_version,
                contract_version=registry.get(kpi_id).version,
                source_files=source_files,
            )
            results[kpi_id] = result
        return {"results": results}

    for kpi_id in selected:
        contract = registry.get(kpi_id)
        cached = find_diagnosis_run(
            kpi_id=kpi_id,
            target_date=effective_scope["target_date"],
            persona=persona,
            scope=cache_scope,
            engine_version=ENGINE_VERSION,
            source_data_version=source_version,
            contract_version=contract.version,
            contract_hash=registry.semantic_snapshot(
                kpi_id,
                allowed_roles=sorted(set(AccessController(ACCESS_CSV).df["owner_role"].astype(str))),
            )["governance"]["contract_hash"],
        )
        if cached is not None:
            # Runs created before source evidence was persisted cannot safely
            # power the evidence workspace. Recompute them with the current
            # engine/source version instead of silently attaching today's
            # production inventory to an older or fixture-backed result.
            if isinstance(cached.get("result", {}).get("source_evidence"), dict):
                cached_result = copy.deepcopy(cached["result"])
                request_telemetry = RuntimeTelemetry(limits=get_runtime_limits())
                request_telemetry.add_stage(
                    stage="diagnosis_cache", processing_type="DETERMINISTIC",
                    method="versioned_saved_run_lookup", latency_ms=0,
                    cache_status="HIT",
                )
                cached_result["telemetry"] = request_telemetry.finalize()
                results[kpi_id] = cached_result
                continue
        pending.append(kpi_id)
    prepared_requests = _prepare_requested_kpis(
        pending,
        effective_scope["target_date"],
        effective_scope,
        as_of=effective_scope.get("as_of"),
        source_files=source_files,
    ) if pending else {}
    for kpi_id in pending:
        request_telemetry = RuntimeTelemetry(limits=get_runtime_limits())
        governed_design = resolve_governed_design(
            kpi_id,
            effective_scope["target_date"],
            dimension_slice.get("region"),
            dimension_slice.get("category"),
        )
        with request_telemetry.stage(
            stage="diagnosis_pipeline", processing_type="DETERMINISTIC",
            method="governed_hybrid_pipeline", cache_status="MISS",
        ):
            result = pipeline.run_diagnosis(
                kpi_id=kpi_id,
                target_date=effective_scope["target_date"],
                sales_csv=sales_csv,
                marketing_csv=marketing_csv,
                finance_csv=finance_csv,
                persona=persona,
                dimension_slice=dimension_slice,
                prepared_request=prepared_requests[kpi_id],
                as_of=effective_scope.get("as_of"),
                verification_design=governed_design,
                approved_causal_design=governed_design is not None,
            )
        narrative_runtime = result.pop("narrative_runtime", None) or {}
        for stage in result.pop("_runtime_stages", []):
            request_telemetry.add_stage(**stage)
        if narrative_runtime.get("attempted"):
            economics = get_model_economics()
            request_telemetry.add_stage(
                stage="narrative_generation", processing_type="LLM",
                method="approved_wording_selection",
                latency_ms=narrative_runtime.get("latency_ms", 0),
                status="FALLBACK" if result.get("llm_status") == "ERROR_FALLBACK" else "COMPLETED",
                provider=narrative_runtime.get("provider"), model=narrative_runtime.get("model"),
                model_calls=narrative_runtime.get("model_calls", 1),
                input_tokens=narrative_runtime.get("input_tokens"),
                output_tokens=narrative_runtime.get("output_tokens"),
                usage_source=narrative_runtime.get("usage_source", "UNAVAILABLE"),
                estimated_cost_usd=estimate_cost_usd(
                    narrative_runtime.get("input_tokens"), narrative_runtime.get("output_tokens"),
                    economics.get("input_usd_per_million_tokens"),
                    economics.get("output_usd_per_million_tokens"),
                ),
                details={"reason_code": result.get("llm_status")},
            )
        result["telemetry"] = request_telemetry.finalize()
        result["engine_version"] = ENGINE_VERSION
        result["source_data_version"] = source_version
        result["contract_version"] = registry.get(kpi_id).version
        _bind_source_evidence_metadata(
            result,
            source_version=source_version,
            contract_version=registry.get(kpi_id).version,
            source_files=source_files,
        )
        results[kpi_id] = result
        save_diagnosis_run(
            result,
            scope=cache_scope,
            access_context={
                "role": persona,
                "authorized": True,
                "identity": "server-demo",
                "identity_mode": DEMO_IDENTITY_MODE,
            },
        )

    return {"results": results}


def build_executive_summary(story: Dict[str, Any] | None, results: Dict[str, Any], persona: str) -> Dict[str, Any] | None:
    """LLM-written, guard-checked summary of the KPI story, with its own telemetry."""
    summary = executive_summary(story, results, persona, api_key=os.getenv("GROQ_API_KEY"))
    if summary is None:
        return None
    runtime = summary.pop("runtime")
    telemetry = RuntimeTelemetry(limits=get_runtime_limits())
    if runtime.get("attempted"):
        economics = get_model_economics()
        telemetry.add_stage(
            stage="executive_summary", processing_type="LLM", method="fact_sheet_narration",
            latency_ms=runtime["latency_ms"], status="COMPLETED" if summary["status"] == "LLM" else "FALLBACK",
            cache_status=runtime["cache_status"], provider=runtime["provider"], model=runtime["model"],
            model_calls=runtime["model_calls"], input_tokens=runtime["input_tokens"], output_tokens=runtime["output_tokens"],
            usage_source=runtime["usage_source"],
            estimated_cost_usd=estimate_cost_usd(runtime["input_tokens"], runtime["output_tokens"],
                                                 economics.get("input_usd_per_million_tokens"), economics.get("output_usd_per_million_tokens")),
            details={"reason_code": summary["status"]},
        )
    else:
        telemetry.add_stage(stage="executive_summary", processing_type="DETERMINISTIC",
                            method="cached_summary" if runtime["cache_status"] == "HIT" else "deterministic_template",
                            latency_ms=0, cache_status=runtime["cache_status"])
    summary["telemetry"] = telemetry.finalize()
    return summary


def movement_priority(movement: Dict[str, Any], contract_snapshot: Optional[Dict[str, Any]], baseline: Optional[Dict[str, float]] = None) -> float:
    """Revenue-equivalent change × capped alert multiple × governed KPI weight."""
    delta = movement.get("delta")
    score = movement.get("robust_score")
    if delta is None or score is None:
        return 0.0
    materiality = ((contract_snapshot or {}).get("materiality")) or {}
    z_threshold = (materiality.get("statistical_thresholds") or {}).get("z_threshold") or 1.0
    kpi_weight = materiality.get("kpi_weight") or 1.0
    contract = contract_snapshot or {}
    impact = revenue_equivalent_delta(
        delta, (contract.get("identity") or {}).get("kpi_id", ""),
        materiality.get("impact_to_revenue"), baseline or {},
    )
    return impact * min(abs(score) / z_threshold, 3.0) * kpi_weight


def build_persona_brief(results: Dict[str, Dict[str, Any]], scope: Dict[str, Any], persona: str = "marketing_manager") -> Dict[str, Any]:
    def confidence_status(result: Dict[str, Any]) -> str:
        profile = result.get("confidence_profile") or {}
        return (profile.get("overall") or {}).get("status") or (result.get("confidence") or {}).get("status", "NOT_ASSESSED")

    funnel = [
        ("traffic_total", "Traffic", "Acquisition"),
        ("conversion_rate", "Conversion rate", "Conversion"),
        ("orders", "Orders", "Purchase"),
        ("units_sold", "Units sold", "Units"),
        ("net_sales_revenue", "Net sales revenue", "Value"),
    ]
    stages = []
    baseline_values = {
        kpi_id: movement["expected_value"]
        for kpi_id, result in results.items()
        if (movement := result.get("movement_assessment") or {}).get("expected_value") is not None
    }
    material_declines = []
    declines = []
    positive = []
    candidates = []
    for kpi_id, label, stage in funnel:
        result = results.get(kpi_id) or {}
        movement = result.get("movement_assessment") or {}
        delta = movement.get("delta")
        available = movement.get("status") == "OK" and delta is not None
        direction = "up" if available and delta > 0 else "down" if available and delta < 0 else "flat" if available else "unavailable"
        item = {
            "kpi_id": kpi_id,
            "label": label,
            "stage": stage,
            "actual": movement.get("actual_value"),
            "expected": movement.get("expected_value"),
            "delta": delta,
            "direction": direction,
            "material": bool(movement.get("is_material")),
            "status": movement.get("status", result.get("verdict", "UNAVAILABLE")),
            "claim_type": "observed movement",
        }
        stages.append(item)
        if direction == "down":
            declines.append(item)
            if item["material"]:
                material_declines.append(item)
        elif direction == "up":
            positive.append(item)
        if available:
            item["priority"] = movement_priority(movement, result.get("contract_snapshot"), baseline_values)
            candidates.append((item["priority"], item))

    weakest = next((stage for stage in stages[:2] if stage["material"] and stage["direction"] == "down"), None)
    if weakest is None:
        weakest = next((stage for stage in stages[:2] if stage["direction"] == "down"), None)
    movement_names = [item["label"].lower() for item in declines]
    if not declines and positive:
        summary = "The selected scope shows positive observed movement across the assessed marketing funnel metrics."
    elif not declines:
        summary = "The selected scope does not have enough comparable movement evidence to establish a funnel trend."
    elif any(item["kpi_id"] == "traffic_total" and item["direction"] == "up" for item in stages) and any(item["kpi_id"] == "conversion_rate" and item["direction"] == "down" for item in stages):
        summary = "Traffic increased while conversion rate declined in the same scope and period; acquisition volume improved, while conversion efficiency weakened. This is a concurrent diagnostic pattern, not proof of cause."
    elif len(declines) > 1:
        summary = f"{', '.join(movement_names[:-1])}{' and ' if len(movement_names) > 1 else ''}{movement_names[-1]} declined together in the selected scope and period. Downstream movements are supporting signals, not additive causes. This co-movement is not proof of cause."
    else:
        summary = f"{movement_names[0].capitalize()} declined in the selected scope and period; the available evidence does not establish a cause."

    ranked = [item for _, item in sorted(candidates, key=lambda entry: entry[0], reverse=True)]
    insights = []
    for item in ranked[:5]:
        result = results[item["kpi_id"]]
        insights.append({
            **item,
            "scope": {key: scope.get(key) for key in ("region", "category", "target_date") if scope.get(key) is not None},
            "confidence_status": confidence_status(result),
            "source_freshness": result.get("as_of", "unavailable"),
            "narrative": result.get("narrative", ""),
            "recommended_action": next((card for card in result.get("decision_cards", []) if card.get("recommendation")), None),
        })
    action = next((entry["recommended_action"] for entry in insights if entry.get("recommended_action")), None)
    uncertainty = []
    for result in results.values():
        overall_reasons = ((result.get("confidence_profile") or {}).get("overall") or {}).get("reasons")
        uncertainty.extend(overall_reasons[:1] if overall_reasons else (result.get("confidence") or {}).get("reasons", [])[:1])
        reconciliation = result.get("reconciliation_verdict") or {}
        if reconciliation.get("status") == "CONTRADICTED":
            uncertainty.append("Source reconciliation is contradicted; pause causal interpretation.")
        elif reconciliation.get("status") == "DRIFT":
            uncertainty.append("Source comparison shows drift beyond tolerance; conclusions are qualified.")
    if persona == "CFO":
        movement_summary = summary
        material_labels = [item["label"].lower() for item in stages if item["material"]]
        summary = (f"Financial review: {movement_summary} Material KPI movements: {', '.join(material_labels) if material_labels else 'none identified'}. Treat contribution, reconciliation and source-quality checks as separate evidence; no causal attribution is established.")
    stories = []
    if len(declines) > 1:
        revenue_stage = next((item for item in stages if item["kpi_id"] == "net_sales_revenue"), None)
        stories.append({
            "id": "FUNNEL_SLOWDOWN",
            "title": "Funnel slowdown",
            "what_changed": summary,
            "affected_kpis": [item["kpi_id"] for item in declines],
            "business_impact": f"Net sales movement: {revenue_stage['delta']:+.2f}" if revenue_stage and revenue_stage["delta"] is not None else "Revenue impact unavailable",
            "evidence_strength": "material movement" if material_declines else "observed movement",
            "confidence_status": confidence_status(results.get("net_sales_revenue", {})),
            "recommended_action": action,
            "causal_boundary": "Connected movement is not additive causal contribution.",
        })
    if len(positive) > 1:
        positive_kpis = [item["kpi_id"] for item in positive]
        revenue_stage = next((item for item in positive if item["kpi_id"] == "net_sales_revenue"), None)
        impact_text = (
            f"Observed revenue uplift (+{revenue_stage['delta']:.2f} INR); connected funnel movements must not be summed as independent impact."
            if revenue_stage and revenue_stage["delta"] is not None
            else "Observed funnel uplift; channel contribution and incrementality were not assessed."
        )
        stories.append({
            "id": "FUNNEL_GROWTH",
            "title": "Positive funnel movement",
            "what_changed": f"Connected positive movement observed across {', '.join(item['label'].lower() for item in positive)}.",
            "affected_kpis": positive_kpis,
            "business_impact": impact_text,
            "evidence_strength": "material movement" if any(item["material"] for item in positive) else "observed movement",
            "confidence_status": confidence_status(results.get(positive[0]["kpi_id"], {})),
            "recommended_action": None,
            "causal_boundary": "Observed funnel improvement does not establish causal marketing attribution.",
        })
    else:
        for item in positive:
            impact_text = (
                f"Traffic increased by {item['delta']:.2f} visits; channel contribution and incrementality were not assessed."
                if item["kpi_id"] == "traffic_total" else
                f"Conversion rate improved by {item['delta']:.4f}; verify whether the change is sustained and attributable before acting."
                if item["kpi_id"] == "conversion_rate" else
                f"Observed {item['label'].lower()} uplift (+{item['delta']:.2f}); connected funnel movements must not be summed as independent impact."
            )
            stories.append({
                "id": f"POSITIVE_SIGNAL_{item['kpi_id']}",
                "title": f"Positive signal ({item['label']})",
                "what_changed": f"{item['label']} moved up by {item['delta']} in its declared unit.",
                "affected_kpis": [item["kpi_id"]],
                "business_impact": impact_text,
                "evidence_strength": "material movement" if item["material"] else "observed movement",
                "confidence_status": confidence_status(results.get(item["kpi_id"], {})),
                "recommended_action": None,
                "causal_boundary": "Observed improvement does not establish marketing attribution.",
            })
    has_actionable_source_warning = any(
        (result.get("reconciliation_verdict") or {}).get("status") in ("DRIFT", "CONTRADICTED")
        for result in results.values()
    )
    if uncertainty or has_actionable_source_warning:
        stories.append({"id": "VERIFICATION_REQUIRED", "title": "Verification required", "what_changed": "Review source reconciliation, availability and comparison design before assigning a cause.", "affected_kpis": [item["kpi_id"] for item in material_declines], "business_impact": "Decision risk; impact not quantified.", "evidence_strength": "limited or conflicting", "confidence_status": "NOT_ASSESSED", "recommended_action": action, "causal_boundary": "Do not infer causality from correlation."})
    return {
        "persona": persona,
        "scope": {key: scope.get(key) for key in ("region", "category", "target_date", "as_of") if scope.get(key) is not None},
        "summary": summary,
        "first_weak_stage": weakest,
        "funnel": stages,
        "ranked_insights": insights,
        "stories": stories[:5],
        "positive_opportunity": any(item["material"] for item in positive),
        "recommended_action": action,
        "uncertainty": list(dict.fromkeys(uncertainty))[:5],
        "method": "deterministic movement ordering; statistical materiality from the KPI engine; correlated indicators remain non-causal",
    }


build_marketing_brief = build_persona_brief  # keep old name as alias


def get_diagnosis(run_id: str) -> Dict[str, Any] | None:
    return get_run(run_id)


def get_authorized_diagnosis(run_id: str, user_id: str) -> Dict[str, Any] | None:
    persona = identity_persona(user_id)
    run = get_run(run_id)
    if run is None or run.get("persona") != persona:
        return None
    decision = _build_pipeline().access_controller.check(persona, run.get("scope", {}))
    return run if decision.allowed else None


def _authorized_saved_run_items(user_id: str) -> list[Dict[str, Any]]:
    """Filter saved rows by mapped persona and region/category policy, not KPI entitlement."""
    persona = identity_persona(user_id)
    access_controller = AccessController(ACCESS_CSV)
    rows = list_diagnosis_runs(persona=persona)["items"]
    authorized = [
        item for item in rows
        if item.get("persona") == persona
        and access_controller.check(persona, item.get("scope", {})).allowed
    ]
    for item in authorized:
        if isinstance(item.get("result"), dict):
            item["result"] = project_diagnosis(item["result"], persona)
    return authorized


def _latest_runs(items: list[Dict[str, Any]], engine_version: str = ENGINE_VERSION) -> list[Dict[str, Any]]:
    """Keep one saved run per KPI, scope, date, as-of and persona.

    Every ENGINE_VERSION bump saves a fresh run for the same question, so the raw
    history contains several copies of one investigation. Prefer the run from the
    current engine version, otherwise the first (most recently executed) one;
    older copies stay in storage and are only hidden from the queue.
    """
    groups: Dict[str, list[Dict[str, Any]]] = {}
    for item in items:
        scope = {key: value for key, value in (item.get("scope") or {}).items() if key not in {"persona", "target_date", "date"}}
        key = repr((item.get("kpi_id"), item.get("target_date"), item.get("persona"), sorted(scope.items())))
        groups.setdefault(key, []).append(item)
    latest = []
    for runs in groups.values():
        chosen = next((run for run in runs if run.get("engine_version") == engine_version), runs[0])
        latest.append({**chosen, "superseded_runs": len(runs) - 1})
    return latest


def get_investigations(*, user_id: str, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    items = _latest_runs(_authorized_saved_run_items(user_id))
    priority = {"CONTRADICTED": 0, "MATERIAL_CAUSE_UNVERIFIED": 1, "CONDITIONAL_SUPPORT": 2, "SEASONAL_REVIEW": 3, "INSUFFICIENT_HISTORY": 4, "NO_MATERIAL_MOVEMENT": 5}
    items.sort(key=lambda item: (priority.get(item.get("verdict"), 6), not item.get("is_material", False)))
    return {"items": items[offset:offset + limit], "total": len(items), "limit": limit, "offset": offset}


def get_insights(*, user_id: str, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    items = _latest_runs(_authorized_saved_run_items(user_id))
    return {"items": items[offset:offset + limit], "total": len(items), "limit": limit, "offset": offset}


def get_timeseries(kpi_id: str, region: str, category: str, *, user_id: str = "demo-marketing", start_date: str | None = None, end_date: str | None = None) -> Dict[str, Any]:
    require_domain(identity_persona(user_id), "SALES")
    registry = _registry_with_catalog(SourceCatalog())
    if kpi_id not in registry.list_ids():
        raise ValueError(f"Unsupported KPI: {kpi_id}")
    authorize_scope(user_id, region, category)
    contract = registry.get(kpi_id)
    data_version = _source_data_version()
    before = _build_timeseries_points.cache_info()
    telemetry = RuntimeTelemetry(limits={"cache_max_entries": before.maxsize})
    started = time.monotonic_ns()
    payload = copy.deepcopy(_build_timeseries_points(
        kpi_id, region, category, contract.version, data_version, start_date, end_date,
    ))
    after = _build_timeseries_points.cache_info()
    telemetry.add_stage(
        stage="timeseries_query", processing_type="DETERMINISTIC",
        method="governed_metric_series", latency_ms=(time.monotonic_ns() - started) / 1_000_000,
        cache_status="HIT" if after.hits > before.hits else "MISS",
    )
    payload["telemetry"] = telemetry.finalize()
    return payload


def get_driver_series(kpi_id: str, driver_id: str, region: str, category: str, *, user_id: str = "demo-marketing", end_date: str | None = None, as_of: str | None = None, days: int = 60) -> Dict[str, Any]:
    """Daily (or weekly) values of one candidate driver from its governed source."""
    require_domain(identity_persona(user_id), "SALES")
    registry = _registry_with_catalog(SourceCatalog())
    if kpi_id not in registry.list_ids():
        raise ValueError(f"Unsupported KPI: {kpi_id}")
    authorize_scope(user_id, region, category)
    contract = registry.get(kpi_id)
    driver_id = resolve_driver_id(driver_id)
    spec = next((item for item in contract.candidate_drivers if item.get("id") == driver_id), None)
    if spec is None:
        raise ValueError(f"Unsupported driver for {kpi_id}: {driver_id}")
    catalog = SourceCatalog()
    frame = QueryService(catalog).load_source(spec["source"], scope={key: value for key, value in (("region", region), ("category", category)) if str(value).upper() != "ALL"}, as_of=as_of)
    grain = spec.get("grain", "daily")
    date_column = "week_start" if grain == "weekly" else "date"
    if date_column not in frame or frame.empty:
        return {"kpi_id": kpi_id, "driver_id": driver_id, "region": region, "category": category, "grain": grain, "unit": spec.get("unit"), "display_name": spec.get("display_name", driver_id), "points": []}
    frame = frame.copy()
    frame[date_column] = pd.to_datetime(frame[date_column])
    calendar = pd.DatetimeIndex(sorted(frame[date_column].unique()))
    series, _, status = AttributionEngine._driver_series(frame, driver_id, spec, None, calendar)
    points = []
    if series is not None:
        end = pd.Timestamp(end_date) if end_date else series.index.max()
        series = series[(series.index <= end) & (series.index > end - pd.Timedelta(days=days))]
        points = [{"observation_date": index.date().isoformat(), "value": None if pd.isna(value) else float(value)} for index, value in series.items()]
    return {"kpi_id": kpi_id, "driver_id": driver_id, "region": region, "category": category, "grain": grain, "unit": spec.get("unit"), "display_name": spec.get("display_name", driver_id), "status": status, "points": points, "source": spec["source"], "end_date": end_date, "as_of": as_of}


@lru_cache(maxsize=32)
def _build_timeseries_points(kpi_id: str, region: str, category: str, contract_version: int, data_version: str, start_date: str | None = None, end_date: str | None = None) -> Dict[str, Any]:
    """Build one governed series without running the full detector per point."""
    catalog = SourceCatalog()
    contract = _registry_with_catalog(catalog).get(kpi_id)
    scoped = QueryService(catalog).load_source(contract.source, scope={key: value for key, value in (("region", region), ("category", category)) if str(value).upper() != "ALL"})
    scoped["date"] = pd.to_datetime(scoped["date"])
    series = daily_values(scoped, contract).sort_index()
    availability = scoped.groupby("date")["available_at"].max() if "available_at" in scoped else pd.Series(dtype="object")
    grouped = pd.DataFrame({"actual": series})
    window = f"{max(30, contract.min_history_periods)}D"
    prior = grouped["actual"].rolling(window, closed="left", min_periods=1)
    grouped["baseline_count"] = prior.count()
    grouped["expected"] = prior.mean()
    baseline = grouped["actual"].rolling(window, closed="left", min_periods=1)
    grouped["baseline_median"] = baseline.median()
    grouped["mad"] = baseline.apply(lambda values: float(1.4826 * np.median(np.abs(values - np.median(values)))), raw=True)
    grouped["iqr"] = baseline.apply(lambda values: float((np.percentile(values, 75) - np.percentile(values, 25)) / 1.349), raw=True)
    grouped["std"] = grouped["actual"].rolling(window, closed="left", min_periods=1).std()
    grouped["delta"] = grouped["actual"] - grouped["expected"]
    scale = grouped["mad"].where(grouped["mad"] >= 1e-4, grouped["iqr"])
    scale = scale.where(scale >= 1e-4, grouped["std"])
    score = (grouped["actual"] - grouped["baseline_median"]) / scale.replace(0, pd.NA)
    statistical = score.abs() >= contract.materiality.z_threshold
    business = grouped["delta"].abs() >= contract.materiality.abs_threshold
    eligible = grouped["baseline_count"] >= contract.min_history_periods
    material = statistical & business & eligible
    points = []
    for observation_date, row in grouped.iterrows():
        day = observation_date.date().isoformat()
        if start_date and day < start_date or end_date and day > end_date:
            continue
        points.append({
            "observation_date": day,
            "actual": None if pd.isna(row.actual) else float(row.actual),
            "expected": None if pd.isna(row.expected) or not eligible.loc[observation_date] else float(row.expected),
            "lower": None,
            "upper": None,
            "delta": None if pd.isna(row.delta) or not eligible.loc[observation_date] else float(row.delta),
            "material_event": bool(material.loc[observation_date]),
            "baseline_count": int(row.baseline_count) if not pd.isna(row.baseline_count) else 0,
            "source_available_at": str(availability.get(observation_date, "unavailable")),
        })
    return {"kpi_id": kpi_id, "region": region, "category": category, "points": points, "source": contract.source, "method": "prior-history rolling governed baseline", "data_version": data_version, "start_date": start_date, "end_date": end_date}


def get_evidence(run_id: str) -> Dict[str, Any]:
    run = get_run(run_id)
    if run is None: raise ValueError("Diagnosis run not found")
    result = run["result"]
    scope = run.get("scope", {})

    if "source_evidence" in result:
        return result["source_evidence"]

    # If a historical snapshot cannot be reconstructed, state that explicitly.
    # Never silently substitute current production files.
    return {
        "run_id": run_id,
        "source_readiness": {
            "status": "MISSING",
            "required_sources": [],
            "available_sources": [],
            "limitations": ["Historical source evidence snapshot cannot be reconstructed for this run."],
        },
        "sources": [],
        "alignment": [],
        "reconciliation": {
            "status": "NOT_APPLICABLE",
            "applicable": False,
            "blocking": False,
            "primary_source": None,
            "comparison_source": None,
            "reason": "Historical reconciliation data unavailable.",
        },
        "lineage": [],
    }


def get_marketing(region: str, category: str, as_of: str | None = None) -> Dict[str, Any]:
    _validate_scope(scope={"target_date": DEFAULT_DATE, "region": region, "category": category}, persona=DEFAULT_PERSONA)
    cutoff = pd.Timestamp(as_of) if as_of else None
    if cutoff is not None and cutoff == cutoff.normalize():
        cutoff += pd.Timedelta(days=1, hours=12)
    scoped = QueryService(SourceCatalog()).load_source("marketing_weekly", scope={key: value for key, value in (("region", region), ("category", category)) if str(value).upper() != "ALL"}, as_of=cutoff.isoformat() if cutoff is not None else None)
    if scoped.empty:
        return {"items": [], "source": "marketing_weekly.csv", "status": "MISSING_REPORT"}
    scoped["week_end"] = pd.to_datetime(scoped["week_end"])
    scoped["available_at"] = pd.to_datetime(scoped["available_at"])
    latest = scoped.sort_values("week_end").iloc[-1]
    cutoff = pd.Timestamp(as_of).normalize() if as_of else pd.Timestamp.max.normalize()
    complete = latest["week_end"].normalize() <= cutoff
    return {"items": scoped.to_dict("records"), "source": "marketing_weekly.csv", "status": "AVAILABLE", "grain": "weekly", "freshness_field": "available_at", "latest_period": {"week_start": latest["week_start"], "week_end": latest["week_end"].date().isoformat(), "available_at": latest["available_at"].isoformat(), "coverage": "COMPLETE" if complete else "PARTIAL"}}


def get_feedback(user_id: str = "demo-marketing") -> Dict[str, Any]:
    persona = identity_persona(user_id)
    items = []
    for item in list_feedback():
        run = get_authorized_feedback_run(item["run_id"], user_id)
        if run is None or (persona != "CFO" and item["user_id"] != user_id):
            continue
        items.append({**item, "feedback_id": str(item["id"]), "legacy": True, "events": []})
    for item in list_feedback_submissions():
        run = get_authorized_feedback_run(item["run_id"], user_id)
        if run is None or (persona != "CFO" and item["user_id"] != user_id):
            continue
        items.append({
            **item,
            "status": item["state"],
            "feedback_type": item["mode"],
            "comments": item.get("comment") or item.get("rationale"),
        })
    items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    accepted = sum(item["status"] == "ACCEPTED" for item in items)
    return {"items": items, "metrics": {"feedback_volume": len(items), "accepted_corrections": accepted, "rejected_feedback": sum(item.get("state", item.get("status")) == "REJECTED" for item in items), "pending_review": sum(item.get("state", item.get("status")) in {"PENDING_REVIEW", "CAPTURED", "TRIAGED"} for item in items), "abstention_rate": "not yet evaluated", "narrative_usefulness": "not yet evaluated"}}


def get_authorized_feedback_run(run_id: str, user_id: str) -> Dict[str, Any] | None:
    """Return a run only when this identity can review its saved scope."""
    persona = identity_persona(user_id)
    run = get_run(run_id)
    if run is None or (persona != "CFO" and run.get("persona") != persona):
        return None
    decision = AccessController(ACCESS_CSV).check(persona, run.get("scope", {}))
    return run if decision.allowed else None


def get_authorized_feedback_record(feedback_id: str, user_id: str) -> Dict[str, Any] | None:
    persona = identity_persona(user_id)
    record = get_feedback_submission(feedback_id)
    if record is None and feedback_id.isdecimal():
        record = get_legacy_feedback(int(feedback_id))
    if record is None or (persona != "CFO" and record.get("user_id") != user_id):
        return None
    if get_authorized_feedback_run(record["run_id"], user_id) is None:
        return None
    return record


def get_feedback_aggregations(user_id: str) -> list[Dict[str, Any]]:
    persona = identity_persona(user_id)
    authorized = []
    for record in list_feedback_submissions():
        if record.get("state") not in {"CAPTURED", "TRIAGED"}:
            continue
        if persona != "CFO" and record.get("user_id") != user_id:
            continue
        if get_authorized_feedback_run(record["run_id"], user_id) is not None:
            authorized.append(record)
    return aggregate_feedback_records(authorized)


def _proposal_visible(proposal: Dict[str, Any], user_id: str) -> bool:
    if identity_persona(user_id) != "CFO":
        return False
    source_runs = proposal.get("source_run_ids") or []
    return bool(source_runs) and all(
        get_authorized_feedback_run(run_id, user_id) is not None
        for run_id in source_runs
    )


def get_authorized_improvement_proposal(proposal_id: str, user_id: str) -> Dict[str, Any] | None:
    proposal = get_improvement_proposal(proposal_id)
    return proposal if proposal is not None and _proposal_visible(proposal, user_id) else None


def get_authorized_improvement_proposals(user_id: str) -> list[Dict[str, Any]]:
    identity_persona(user_id)
    return [
        proposal for proposal in list_improvement_proposals()
        if _proposal_visible(proposal, user_id)
    ]

def get_authorized_candidate_artifact(candidate_artifact_id: str, user_id: str) -> Dict[str, Any] | None:
    artifact = get_candidate_artifact(candidate_artifact_id)
    if artifact is None or not _proposal_visible(
        get_improvement_proposal(artifact["proposal_id"]) or {}, user_id
    ):
        return None
    return artifact

def get_authorized_proposal_evaluation(evaluation_run_id: str, user_id: str) -> Dict[str, Any] | None:
    evaluation = get_proposal_evaluation(evaluation_run_id)
    if evaluation is None or not _proposal_visible(
        get_improvement_proposal(evaluation["proposal_id"]) or {}, user_id
    ):
        return None
    return evaluation
