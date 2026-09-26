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
import hashlib
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import pandas as pd
import numpy as np

from kpi_engine.access import AccessController
from kpi_engine.contracts import KPIRegistry
from kpi_engine.contracts.metrics import daily_values, prepare_metric_request
from kpi_engine.pipeline import KPIEnginePipeline
from kpi_engine.query.catalog import SourceCatalog
from kpi_engine.query.service import QueryService

from backend.config import ACCESS_CSV, DEFAULT_CATEGORY, DEFAULT_DATE, DEFAULT_PERSONA, DEFAULT_REGION, ENGINE_REGISTRY_DIR, EVIDENCE_CSV, FEEDBACK_LOG_PATH, MARKETING_CSV, SALES_CSV
from backend.storage import find_diagnosis_run, get_run, list_diagnosis_runs, list_feedback, save_diagnosis_run

SUPPORTED_PERSONAS = ("CFO", "marketing_manager")
DEMO_IDENTITIES = {"demo-cfo": "CFO", "demo-marketing": "marketing_manager"}
ENGINE_VERSION = "kpi-engine-b89bfd5-integration"


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


def _source_data_version() -> str:
    catalog = SourceCatalog()
    versions = []
    for source_id, source in sorted(catalog.sources.items()):
        path = Path(source.file_path)
        if path.exists():
            stat = path.stat()
            versions.append((source_id, str(path.resolve()), stat.st_size, stat.st_mtime_ns))
    return hashlib.sha256(repr(versions).encode("utf-8")).hexdigest()


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

    source_version = _source_data_version()
    pipeline = _build_pipeline()
    results: Dict[str, Any] = {}
    pending: list[str] = []
    dimension_slice = {key: value for key, value in effective_scope.items() if key not in {"target_date", "date", "as_of", "persona"}}
    cache_scope = {
        **dimension_slice,
        "target_date": effective_scope["target_date"],
        "persona": persona,
        **({"as_of": effective_scope.get("as_of")} if effective_scope.get("as_of") else {}),
    }
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
        )
        if cached is not None:
            results[kpi_id] = cached["result"]
            continue
        pending.append(kpi_id)
    prepared_requests = _prepare_requested_kpis(pending, effective_scope["target_date"], effective_scope, as_of=effective_scope.get("as_of")) if pending else {}
    for kpi_id in pending:
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
        result["engine_version"] = ENGINE_VERSION
        result["source_data_version"] = source_version
        result["contract_version"] = registry.get(kpi_id).version
        results[kpi_id] = result
        save_diagnosis_run(
            result,
            scope=cache_scope,
            access_context={"role": persona, "authorized": True, "identity": "server-demo"},
        )

    return {"results": results}


def build_marketing_brief(results: Dict[str, Dict[str, Any]], scope: Dict[str, Any], persona: str = "marketing_manager") -> Dict[str, Any]:
    funnel = [
        ("traffic_total", "Traffic", "Acquisition"),
        ("conversion_rate", "Conversion rate", "Conversion"),
        ("orders", "Orders", "Purchase"),
        ("units_sold", "Units sold", "Units"),
        ("net_sales_revenue", "Net sales revenue", "Value"),
    ]
    stages = []
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
            candidates.append((2 if item["material"] and direction == "down" else 1 if direction == "down" else 0, item))

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
        confidence = result.get("confidence") or {}
        insights.append({
            **item,
            "scope": {key: scope.get(key) for key in ("region", "category", "target_date") if scope.get(key) is not None},
            "confidence_status": confidence.get("status", "NOT_ASSESSED"),
            "source_freshness": result.get("as_of", "unavailable"),
            "narrative": result.get("narrative", ""),
            "recommended_action": next((card for card in result.get("decision_cards", []) if card.get("recommendation")), None),
        })
    action = next((entry["recommended_action"] for entry in insights if entry.get("recommended_action")), None)
    uncertainty = []
    for result in results.values():
        confidence = result.get("confidence") or {}
        uncertainty.extend(confidence.get("reasons", [])[:1])
        reconciliation = result.get("reconciliation_verdict") or {}
        if reconciliation.get("status") == "CONTRADICTED":
            uncertainty.append("Source reconciliation is contradicted; pause causal interpretation.")
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
            "business_impact": f"Net sales movement: {revenue_stage['delta']}" if revenue_stage and revenue_stage["delta"] is not None else "Revenue impact unavailable",
            "evidence_strength": "material movement" if material_declines else "observed movement",
            "confidence_status": (results.get("net_sales_revenue", {}).get("confidence") or {}).get("status", "NOT_ASSESSED"),
            "recommended_action": action,
            "causal_boundary": "Connected movement is not additive causal contribution.",
        })
    for item in positive:
        stories.append({"id": f"POSITIVE_SIGNAL_{item['kpi_id']}", "title": "Positive signal", "what_changed": f"{item['label']} moved up by {item['delta']} in its declared unit.", "affected_kpis": [item["kpi_id"]], "business_impact": "Directional opportunity; no incremental impact estimated.", "evidence_strength": "material movement" if item["material"] else "observed movement", "confidence_status": (results.get(item["kpi_id"], {}).get("confidence") or {}).get("status", "NOT_ASSESSED"), "recommended_action": None, "causal_boundary": "Observed improvement does not establish marketing attribution."})
    if uncertainty or any((result.get("reconciliation_verdict") or {}).get("status") != "RECONCILED" for result in results.values()):
        stories.append({"id": "VERIFICATION_REQUIRED", "title": "Verification required", "what_changed": "Review source reconciliation, availability and comparison design before assigning a cause.", "affected_kpis": [item["kpi_id"] for item in material_declines], "business_impact": "Decision risk; impact not quantified.", "evidence_strength": "limited or conflicting", "confidence_status": "NOT_ASSESSED", "recommended_action": action, "causal_boundary": "Do not infer causality from correlation."})
    return {
        "persona": persona,
        "scope": {key: scope.get(key) for key in ("region", "category", "target_date", "as_of") if scope.get(key) is not None},
        "summary": summary,
        "first_weak_stage": weakest,
        "funnel": stages,
        "ranked_insights": insights,
        "stories": stories[:5],
        "positive_opportunity": bool(positive),
        "recommended_action": action,
        "uncertainty": list(dict.fromkeys(uncertainty))[:5],
        "method": "deterministic movement ordering; statistical materiality from the KPI engine; correlated indicators remain non-causal",
    }


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


def get_timeseries(kpi_id: str, region: str, category: str, *, user_id: str = "demo-marketing", start_date: str | None = None, end_date: str | None = None) -> Dict[str, Any]:
    registry = KPIRegistry(ENGINE_REGISTRY_DIR)
    if kpi_id not in registry.list_ids():
        raise ValueError(f"Unsupported KPI: {kpi_id}")
    authorize_scope(user_id, region, category)
    contract = registry.get(kpi_id)
    data_version = _source_data_version()
    return _build_timeseries_points(kpi_id, region, category, contract.version, data_version, start_date, end_date)


@lru_cache(maxsize=32)
def _build_timeseries_points(kpi_id: str, region: str, category: str, contract_version: int, data_version: str, start_date: str | None = None, end_date: str | None = None) -> Dict[str, Any]:
    """Build one governed series without running the full detector per point."""
    contract = KPIRegistry(ENGINE_REGISTRY_DIR).get(kpi_id)
    scoped = QueryService(SourceCatalog()).load_source(contract.source, scope={"region": region, "category": category})
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


def get_marketing(region: str, category: str, as_of: str | None = None) -> Dict[str, Any]:
    _validate_scope(scope={"target_date": DEFAULT_DATE, "region": region, "category": category}, persona=DEFAULT_PERSONA)
    cutoff = pd.Timestamp(as_of) if as_of else None
    if cutoff is not None and cutoff == cutoff.normalize():
        cutoff += pd.Timedelta(days=1, hours=12)
    scoped = QueryService(SourceCatalog()).load_source("marketing_weekly", scope={"region": region, "category": category}, as_of=cutoff.isoformat() if cutoff is not None else None)
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
        run = get_run(item["run_id"])
        if run is None:
            continue
        if persona == "CFO" or run.get("persona") == persona:
            items.append(item)
    accepted = sum(item["status"] == "ACCEPTED" for item in items)
    return {"items": items, "metrics": {"feedback_volume": len(items), "accepted_corrections": accepted, "rejected_feedback": sum(item["status"] == "REJECTED" for item in items), "pending_review": sum(item["status"] == "PENDING_REVIEW" for item in items), "abstention_rate": "not yet evaluated", "narrative_usefulness": "not yet evaluated"}}
