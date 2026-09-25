from __future__ import annotations

import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import pandas as pd

from kpi_engine.contracts import KPIRegistry
from kpi_engine.pipeline import KPIEnginePipeline

from backend.config import ACCESS_CSV, DEFAULT_CATEGORY, DEFAULT_DATE, DEFAULT_PERSONA, DEFAULT_REGION, ENGINE_REGISTRY_DIR, EVIDENCE_CSV, FEEDBACK_LOG_PATH, MARKETING_CSV, SALES_CSV
from backend.storage import find_diagnosis_run, get_run, list_diagnosis_runs, list_feedback, save_diagnosis_run

SUPPORTED_PERSONAS = ("CFO", "marketing_manager")
DEMO_IDENTITIES = {"demo-cfo": "CFO", "demo-marketing": "marketing_manager"}
ENGINE_VERSION = "kpi-engine-v1"
SOURCE_DATA_VERSION = "sales_daily:2023-01-01..2024-12-30"


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


def get_available_filters() -> Dict[str, list[str]]:
    sales = pd.read_csv(SALES_CSV)
    regions = sorted(sales["region"].dropna().unique().tolist())
    categories = sorted(sales["category"].dropna().unique().tolist())
    dates = sorted(pd.to_datetime(sales["date"]).dt.strftime("%Y-%m-%d").dropna().unique().tolist())
    return {
        "regions": regions,
        "categories": categories,
        "dates": dates,
        "persona": list(SUPPORTED_PERSONAS),
        "default": {
            "region": DEFAULT_REGION,
            "category": DEFAULT_CATEGORY,
            "date": DEFAULT_DATE,
            "persona": DEFAULT_PERSONA,
        },
    }


def _validate_scope(target_date: str, region: str, category: str, persona: str) -> None:
    try:
        date.fromisoformat(target_date)
    except ValueError as exc:
        raise ValueError("target_date must be in YYYY-MM-DD format") from exc

    filters = get_available_filters()
    if region not in filters["regions"]:
        raise ValueError(f"Unsupported region: {region}")
    if category not in filters["categories"]:
        raise ValueError(f"Unsupported category: {category}")
    if target_date not in filters["dates"]:
        raise ValueError(f"Unsupported target_date: {target_date}")
    if persona not in SUPPORTED_PERSONAS:
        raise ValueError(f"Unsupported persona: {persona}")


def diagnose_scope(
    *,
    kpis: Sequence[str] | None = None,
    target_date: str = DEFAULT_DATE,
    region: str = DEFAULT_REGION,
    category: str = DEFAULT_CATEGORY,
    persona: str = DEFAULT_PERSONA,
) -> Dict[str, Any]:
    _validate_scope(target_date, region, category, persona)

    registry = KPIRegistry(ENGINE_REGISTRY_DIR)
    selected = registry.list_ids() if not kpis or "all" in kpis else [k for k in kpis if k in registry._contracts]
    if not selected:
        raise ValueError("No valid KPI IDs supplied")

    pipeline = _build_pipeline()
    results: Dict[str, Any] = {}
    for kpi_id in selected:
        cached = find_diagnosis_run(kpi_id=kpi_id, target_date=target_date, persona=persona, region=region, category=category, engine_version=ENGINE_VERSION, source_data_version=SOURCE_DATA_VERSION)
        if cached is not None:
            results[kpi_id] = cached["result"]
            continue
        result = pipeline.run_diagnosis(
            kpi_id=kpi_id,
            target_date=target_date,
            sales_csv=SALES_CSV,
            marketing_csv=str(Path(SALES_CSV).with_name("marketing_weekly.csv")),
            finance_csv=str(Path(SALES_CSV).with_name("finance_monthly.csv")),
            persona=persona,
            dimension_slice={"region": region, "category": category},
        )
        results[kpi_id] = result
        save_diagnosis_run(
            result,
            scope={"region": region, "category": category, "target_date": target_date, "persona": persona},
            access_context={"role": persona, "authorized": True, "identity": "server-demo"},
        )

    return {"results": results}


def get_diagnosis(run_id: str) -> Dict[str, Any] | None:
    return get_run(run_id)


def get_authorized_diagnosis(run_id: str, user_id: str) -> Dict[str, Any] | None:
    persona = identity_persona(user_id)
    run = get_run(run_id)
    if run is None or run.get("persona") != persona:
        return None
    decision = _build_pipeline().access_controller.check(persona, run.get("scope", {}))
    return run if decision.allowed else None


def get_investigations(*, limit: int = 100, offset: int = 0, persona: str | None = None) -> Dict[str, Any]:
    payload = list_diagnosis_runs(persona=persona)
    priority = {"CONTRADICTED": 0, "MATERIAL_CAUSE_UNVERIFIED": 1, "CONDITIONAL_SUPPORT": 2, "SEASONAL_REVIEW": 3, "INSUFFICIENT_HISTORY": 4, "NO_MATERIAL_MOVEMENT": 5}
    payload["items"].sort(key=lambda item: (priority.get(item.get("verdict"), 6), not item.get("is_material", False)))
    payload["total"] = len(payload["items"])
    payload["items"] = payload["items"][offset:offset + limit]
    payload["limit"] = limit
    payload["offset"] = offset
    return payload


def get_insights(*, limit: int = 50, offset: int = 0, persona: str | None = None) -> Dict[str, Any]:
    payload = list_diagnosis_runs(persona=persona)
    payload["total"] = len(payload["items"])
    payload["items"] = payload["items"][offset:offset + limit]
    payload["limit"] = limit
    payload["offset"] = offset
    return payload


def get_timeseries(kpi_id: str, region: str, category: str) -> Dict[str, Any]:
    registry = KPIRegistry(ENGINE_REGISTRY_DIR)
    if kpi_id not in registry.list_ids():
        raise ValueError(f"Unsupported KPI: {kpi_id}")
    _validate_scope(DEFAULT_DATE, region, category, DEFAULT_PERSONA)
    contract = registry.get(kpi_id)
    return _build_timeseries_points(kpi_id, region, category, contract.version, SOURCE_DATA_VERSION)


@lru_cache(maxsize=32)
def _build_timeseries_points(kpi_id: str, region: str, category: str, contract_version: int, data_version: str) -> Dict[str, Any]:
    """Build one governed series without running the full detector per point."""
    contract = KPIRegistry(ENGINE_REGISTRY_DIR).get(kpi_id)
    sales = pd.read_csv(SALES_CSV, usecols=lambda column: column in {
        "date", "region", "category", "available_at", contract.value_column,
        contract.numerator_column or "", contract.denominator_column or "",
    })
    scoped = sales[(sales["region"] == region) & (sales["category"] == category)].copy()
    scoped["date"] = pd.to_datetime(scoped["date"])
    if contract.aggregation == "ratio_of_sums":
        grouped = scoped.groupby("date", as_index=False).agg(
            numerator=(contract.numerator_column, "sum"),
            denominator=(contract.denominator_column, "sum"),
            source_available_at=("available_at", "max"),
        )
        grouped["actual"] = grouped["numerator"] / grouped["denominator"].replace(0, pd.NA)
    else:
        grouped = scoped.groupby("date", as_index=False).agg(
            actual=(contract.value_column, "sum"),
            source_available_at=("available_at", "max"),
        )
    grouped = grouped.sort_values("date").set_index("date")
    window = f"{max(30, contract.min_history_periods)}D"
    prior = grouped["actual"].rolling(window, closed="left", min_periods=1)
    grouped["baseline_count"] = prior.count()
    grouped["expected"] = prior.mean()
    grouped["baseline_median"] = grouped["actual"].rolling(window, closed="left", min_periods=1).median()
    grouped["std"] = grouped["actual"].rolling(window, closed="left", min_periods=1).std()
    grouped["delta"] = grouped["actual"] - grouped["expected"]
    grouped["z_score"] = grouped["delta"] / grouped["std"].replace(0, pd.NA)
    statistical = grouped["z_score"].abs() >= contract.materiality.z_threshold
    business = grouped["delta"].abs() >= contract.materiality.abs_threshold
    eligible = grouped["baseline_count"] >= contract.min_history_periods
    material = statistical & business & eligible
    points = []
    for observation_date, row in grouped.iterrows():
        points.append({
            "observation_date": observation_date.date().isoformat(),
            "actual": None if pd.isna(row.actual) else float(row.actual),
            "expected": None if pd.isna(row.expected) or not eligible.loc[observation_date] else float(row.expected),
            "lower": None,
            "upper": None,
            "delta": None if pd.isna(row.delta) or not eligible.loc[observation_date] else float(row.delta),
            "material_event": bool(material.loc[observation_date]),
            "baseline_count": int(row.baseline_count) if not pd.isna(row.baseline_count) else 0,
            "source_available_at": str(row.source_available_at),
        })
    return {"kpi_id": kpi_id, "region": region, "category": category, "points": points, "source": "sales_daily.csv", "method": "prior-history rolling governed baseline", "data_version": data_version}


def get_evidence(run_id: str) -> Dict[str, Any]:
    run = get_run(run_id)
    if run is None: raise ValueError("Diagnosis run not found")
    result = run["result"]
    evidence = pd.read_csv(EVIDENCE_CSV)
    scope = run.get("scope", {})
    target = pd.Timestamp(run["target_date"]); cutoff = pd.Timestamp(run["as_of"])
    scoped = evidence[(evidence["region"].isin([scope.get("region"), "ALL"])) & (evidence["category"].isin([scope.get("category"), "ALL"])) & (pd.to_datetime(evidence["date"], errors="coerce") <= cutoff)].copy()
    items = []
    for claim in result.get("narrative_claims", []):
        paths = claim.get("evidence_paths", [])
        for path in paths:
            items.append({"claim": claim.get("text"), "evidence_path": path, "source_name": "unavailable", "source_grain": "unavailable", "source_freshness": "unavailable", "row_reference": "unavailable", "analytical_method": result.get("narrative_method", "unavailable"), "claim_type": claim.get("claim_type", "unavailable"), "access_classification": "unavailable", "inclusion_reason": "engine claim path"})
    for row in scoped.to_dict("records"):
        items.append({"claim": "unstructured evidence available for this scoped date", "evidence_path": row["doc_id"], "source_name": row["source_type"], "source_grain": "unavailable", "source_freshness": "unavailable", "row_reference": f"{row['doc_id']}:{row['date']}", "analytical_method": "unavailable", "claim_type": "source context", "access_classification": "unavailable", "inclusion_reason": "region/category/date/as-of filter"})
    return {"run_id": run_id, "items": items}


def get_marketing(region: str, category: str) -> Dict[str, Any]:
    _validate_scope(DEFAULT_DATE, region, category, DEFAULT_PERSONA)
    marketing = pd.read_csv(MARKETING_CSV)
    scoped = marketing[(marketing["region"] == region) & (marketing["category"] == category)].copy()
    if scoped.empty:
        return {"items": [], "source": "marketing_weekly.csv", "status": "MISSING_REPORT"}
    scoped["week_end"] = pd.to_datetime(scoped["week_end"])
    scoped["available_at"] = pd.to_datetime(scoped["available_at"])
    latest = scoped.sort_values("week_end").iloc[-1]
    complete = latest["available_at"].normalize() >= latest["week_end"]
    return {"items": scoped.to_dict("records"), "source": "marketing_weekly.csv", "status": "AVAILABLE", "grain": "weekly", "freshness_field": "available_at", "latest_period": {"week_start": latest["week_start"], "week_end": latest["week_end"].date().isoformat(), "available_at": latest["available_at"].isoformat(), "coverage": "COMPLETE" if complete else "PARTIAL"}}


def get_feedback(user_id: str = "demo-marketing") -> Dict[str, Any]:
    persona = identity_persona(user_id)
    items = []
    for item in list_feedback():
        run = get_run(item["run_id"])
        if run is None:
            continue
        if persona == "CFO" or run.get("persona") == persona:
            items.append(item)
    accepted = sum(item["status"] == "ACCEPTED" for item in items)
    return {"items": items, "metrics": {"feedback_volume": len(items), "accepted_corrections": accepted, "rejected_feedback": sum(item["status"] == "REJECTED" for item in items), "pending_review": sum(item["status"] == "PENDING_REVIEW" for item in items), "abstention_rate": "not yet evaluated", "narrative_usefulness": "not yet evaluated"}}
