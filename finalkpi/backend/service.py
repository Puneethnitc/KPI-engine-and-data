from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import pandas as pd

from kpi_engine.contracts import KPIRegistry
from kpi_engine.pipeline import KPIEnginePipeline

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


def get_available_filters() -> Dict[str, list[str]]:
    sales = pd.read_csv(SALES_CSV)
    regions = sorted(sales["region"].dropna().unique().tolist())
    categories = sorted(sales["category"].dropna().unique().tolist())
    dates = sorted(pd.to_datetime(sales["date"]).dt.strftime("%Y-%m-%d").dropna().unique().tolist())
    return {
        "regions": regions,
        "categories": categories,
        "dates": dates,
        "persona": [DEFAULT_PERSONA],
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
    if persona != DEFAULT_PERSONA:
        raise ValueError("Demo backend enforces the default server-side identity as CFO")


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
            access_context={"role": persona, "authorized": True},
        )

    return {"results": results}


def get_diagnosis(run_id: str) -> Dict[str, Any] | None:
    return get_run(run_id)
