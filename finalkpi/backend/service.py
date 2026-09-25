# IMPLEMENTATION HANDOFF — engine/API boundary
# Current: discovers registry IDs but loads bundled CSVs per KPI, validates fixed
# region/category/date filters, and accepts only the configured demo persona.
# Next: accept dataset/catalog, generic dimensions and as-of; prepare one source
# snapshot per request and share query-service outputs. Reject mixed unknown KPI
# IDs explicitly rather than silently dropping them. Derive filters from allowed,
# available data. See ../kpi_engine/IMPLEMENTATION_HANDOFF.md and duckdb/README.md.
# Check: new configured KPI/dimensions work without editing API allowlists and
# metadata does not expose unavailable or unauthorized slices.

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import pandas as pd

from kpi_engine.access import AccessController
from kpi_engine.contracts import KPIRegistry
from kpi_engine.contracts.metrics import prepare_metric_request
from kpi_engine.pipeline import KPIEnginePipeline
from kpi_engine.query.catalog import SourceCatalog
from kpi_engine.query.service import QueryService

from backend.config import ACCESS_CSV, DEFAULT_CATEGORY, DEFAULT_DATE, DEFAULT_PERSONA, DEFAULT_REGION, ENGINE_REGISTRY_DIR, EVIDENCE_CSV, FEEDBACK_LOG_PATH, SALES_CSV
from backend.storage import get_run, save_diagnosis_run


def _build_pipeline() -> KPIEnginePipeline:
    return KPIEnginePipeline(
        registry_dir=ENGINE_REGISTRY_DIR,
        evidence_csv=EVIDENCE_CSV,
        access_csv=ACCESS_CSV,
        feedback_log_path=FEEDBACK_LOG_PATH,
        groq_api_key=os.getenv("GROQ_API_KEY"),
    )


def get_registered_kpis() -> List[Dict[str, Any]]:
    registry = KPIRegistry(ENGINE_REGISTRY_DIR)
    payload: List[Dict[str, Any]] = []
    for kpi_id in registry.list_ids():
        contract = registry.get(kpi_id)
        payload.append(
            {
                "kpi_id": contract.kpi_id,
                "version": contract.version,
                "definition": contract.definition,
                "unit": contract.unit,
                "source": contract.source,
                "grain": contract.grain,
                "dimensions": contract.dimensions,
                "aggregation": contract.aggregation,
                "owner": contract.owner,
                "access_tags": contract.access_tags,
                "reconciliation": contract.reconciliation,
                "decomposition": contract.decomposition,
                "candidate_drivers": contract.candidate_drivers,
                "capabilities": {
                    "supports_reconciliation": contract.reconciliation is not None,
                    "supports_decomposition": bool(contract.decomposition),
                    "supports_driver_ranking": bool(contract.candidate_drivers),
                },
            }
        )
    return payload


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

    allowed_dims = _get_allowed_dimensions()
    legacy_defaults = {"region": DEFAULT_REGION, "category": DEFAULT_CATEGORY}
    for key, fallback in legacy_defaults.items():
        if key in allowed_dims and key not in effective:
            effective[key] = fallback
    return effective


def _get_allowed_dimensions(kpis: Sequence[str] | None = None) -> set[str]:
    registry = KPIRegistry(ENGINE_REGISTRY_DIR)
    catalog = SourceCatalog()
    selected = list(kpis) if kpis else registry.list_ids()
    allowed: set[str] = set()
    for kpi_id in selected:
        if kpi_id not in registry._contracts:
            continue
        contract = registry.get(kpi_id)
        allowed.update(contract.dimensions)
        source = catalog.sources.get(contract.source)
        if source is not None:
            allowed.update(source.dimensions)
    allowed.update({"region", "category"})
    return allowed


def _get_allowed_filter_values() -> Dict[str, list[str]]:
    values: Dict[str, list[str]] = {}
    catalog = SourceCatalog()
    for source in catalog.sources.values():
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
    registry = KPIRegistry(ENGINE_REGISTRY_DIR)
    for contract in registry._contracts.values():
        for dimension in contract.dimensions:
            values.setdefault(dimension, [])
    order = ["date", "region", "category"]
    for key in sorted(values):
        if key not in order:
            order.append(key)
    return {key: sorted(set(values.get(key, []))) for key in order}


def get_available_filters() -> Dict[str, Any]:
    catalog = SourceCatalog()
    date_values: set[str] = set()
    for source in catalog.sources.values():
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
    dimensions = sorted(_get_allowed_dimensions())
    allowed_values = _get_allowed_filter_values()
    legacy_regions = allowed_values.get("region", [])
    legacy_categories = allowed_values.get("category", [])
    return {
        "regions": legacy_regions,
        "categories": legacy_categories,
        "dates": sorted(date_values),
        "dimensions": dimensions,
        "allowed_values": allowed_values,
        "persona": [DEFAULT_PERSONA],
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
) -> None:
    if not persona or not str(persona).strip():
        raise ValueError("A valid persona is required.")

    allowed_dimensions = _get_allowed_dimensions(kpis=kpis)
    for key, value in scope.items():
        if key in {"persona", "as_of", "target_date", "date"}:
            continue
        if key not in allowed_dimensions:
            raise ValueError(f"Unsupported dimension: {key}")

    requested_dims = {key: value for key, value in scope.items() if key in {"region", "category"}}
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
) -> Dict[str, Any]:
    registry = KPIRegistry(ENGINE_REGISTRY_DIR)
    catalog = SourceCatalog()
    service = QueryService(catalog)
    prepared: Dict[str, Any] = {}
    dimension_slice = {key: value for key, value in scope.items() if key not in {"target_date", "date", "as_of", "persona"}}

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


def diagnose_scope(
    *,
    kpis: Sequence[str] | None = None,
    target_date: str | None = None,
    region: str | None = None,
    category: str | None = None,
    persona: str = DEFAULT_PERSONA,
    scope: Dict[str, Any] | None = None,
    as_of: str | None = None,
) -> Dict[str, Any]:
    registry = KPIRegistry(ENGINE_REGISTRY_DIR)
    selected = registry.list_ids() if not kpis or "all" in kpis else list(kpis)
    unknown = [kpi_id for kpi_id in selected if kpi_id not in registry._contracts]
    if unknown:
        unknown_text = ", ".join(unknown)
        raise ValueError(f"Unknown KPI ID(s): {unknown_text}")
    if not selected:
        raise ValueError("No valid KPI IDs supplied")

    effective_scope = _resolve_scope(scope=scope, target_date=target_date, region=region, category=category, as_of=as_of)
    _validate_scope(scope=effective_scope, persona=persona, kpis=selected)

    prepared_requests = _prepare_requested_kpis(selected, effective_scope["target_date"], effective_scope, as_of=effective_scope.get("as_of"))
    pipeline = _build_pipeline()
    results: Dict[str, Any] = {}
    for kpi_id in selected:
        dimension_slice = {key: value for key, value in effective_scope.items() if key not in {"target_date", "date", "as_of", "persona"}}
        result = pipeline.run_diagnosis(
            kpi_id=kpi_id,
            target_date=effective_scope["target_date"],
            sales_csv=SALES_CSV,
            marketing_csv=str(Path(SALES_CSV).with_name("marketing_weekly.csv")),
            finance_csv=str(Path(SALES_CSV).with_name("finance_monthly.csv")),
            persona=persona,
            dimension_slice=dimension_slice,
            prepared_request=prepared_requests[kpi_id],
            as_of=effective_scope.get("as_of"),
        )
        results[kpi_id] = result
        save_diagnosis_run(
            result,
            scope={
                **dimension_slice,
                "target_date": effective_scope["target_date"],
                "persona": persona,
                **({"as_of": effective_scope.get("as_of")} if effective_scope.get("as_of") else {}),
            },
            access_context={"role": persona, "authorized": True},
        )

    return {"results": results}


def get_diagnosis(run_id: str) -> Dict[str, Any] | None:
    return get_run(run_id)
