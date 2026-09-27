"""Governed reviewer scenarios. Catalog owns scope; the engine still decides."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from kpi_engine.processing_transparency import build_processing_transparency

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "data" / "demo_fixtures"

REQUIRED_SCENARIO_IDS = (
    "material-multi-driver",
    "low-confidence-abstention",
    "contradictory-sources",
    "sparse-history-new-launch",
    "unauthorized-scope",
    "non-material-baseline",
    "category-restricted-scope",
)


@dataclass(frozen=True)
class DemoScenario:
    scenario_id: str
    title: str
    purpose: str
    demonstration_category: str
    persona: str
    user_id: str
    kpis: tuple[str, ...]
    primary_kpi: str
    region: str
    category: str
    target_date: str
    as_of: str | None
    source_mode: str
    fixture_id: str | None
    expected_broad_outcome: str

    def source_files(self) -> Dict[str, str] | None:
        if self.source_mode != "demo_fixture" or not self.fixture_id:
            return None
        folder = FIXTURE_ROOT / self.fixture_id
        return {
            "sales_daily": str(folder / "sales_daily.csv"),
            "marketing_weekly": str(folder / "marketing_weekly.csv"),
            "finance_monthly": str(folder / "finance_monthly.csv"),
        }

    def public_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "title": self.title,
            "purpose": self.purpose,
            "demonstration_category": self.demonstration_category,
            "persona": self.persona,
            "user_id": self.user_id,
            "kpis": list(self.kpis),
            "primary_kpi": self.primary_kpi,
            "region": self.region,
            "category": self.category,
            "target_date": self.target_date,
            "as_of": self.as_of,
            "source_mode": self.source_mode,
            "fixture_id": self.fixture_id,
            "uses_demo_fixture": self.source_mode == "demo_fixture",
            "fixture_label": "Simulated demonstration data" if self.source_mode == "demo_fixture" else None,
            "expected_broad_outcome": self.expected_broad_outcome,
        }


# Scopes were confirmed against the current engine before this catalog was frozen.
_SCENARIOS: tuple[DemoScenario, ...] = (
    DemoScenario(
        scenario_id="material-multi-driver",
        title="Material multi-driver movement",
        purpose="Show a material KPI movement, an accounting contribution bridge, and more than one plausible diagnostic driver without asserting a cause.",
        demonstration_category="material_multi_driver",
        persona="CFO",
        user_id="demo-cfo",
        kpis=("all",),
        primary_kpi="net_sales_revenue",
        region="North",
        category="Electronics",
        target_date="2023-07-24",
        as_of=None,
        source_mode="production",
        fixture_id=None,
        expected_broad_outcome="MATERIAL",
    ),
    DemoScenario(
        scenario_id="low-confidence-abstention",
        title="Low-confidence / abstention",
        purpose="Show movement evidence while the engine abstains from causal attribution and from action-impact estimates.",
        demonstration_category="low_confidence_abstention",
        persona="CFO",
        user_id="demo-cfo",
        kpis=("all",),
        primary_kpi="net_sales_revenue",
        region="North",
        category="Electronics",
        target_date="2023-07-22",
        as_of=None,
        source_mode="production",
        fixture_id=None,
        expected_broad_outcome="ABSTAIN",
    ),
    DemoScenario(
        scenario_id="contradictory-sources",
        title="Contradictory sources",
        purpose="Show conflicting sales and finance evidence on an explicit demonstration fixture and stop unsupported attribution.",
        demonstration_category="contradictory_sources",
        persona="CFO",
        user_id="demo-cfo",
        kpis=("net_sales_revenue",),
        primary_kpi="net_sales_revenue",
        region="North",
        category="Electronics",
        target_date="2023-07-31",
        as_of="2023-08-06T12:00:00",
        source_mode="demo_fixture",
        fixture_id="contradicted_july_2023",
        expected_broad_outcome="CONTRADICTED",
    ),
    DemoScenario(
        scenario_id="sparse-history-new-launch",
        title="Sparse history / new launch",
        purpose="Show a newly launched category that lacks the required history and therefore does not receive a normal driver ranking.",
        demonstration_category="sparse_history",
        persona="CFO",
        user_id="demo-cfo",
        kpis=("all",),
        primary_kpi="net_sales_revenue",
        region="North",
        category="Beauty",
        target_date="2024-12-15",
        as_of=None,
        source_mode="production",
        fixture_id=None,
        expected_broad_outcome="INSUFFICIENT_HISTORY",
    ),
    DemoScenario(
        scenario_id="unauthorized-scope",
        title="Unauthorized scope",
        purpose="Demonstrate a real authorization denial when a regional role requests a region outside its entitlement.",
        demonstration_category="unauthorized_scope",
        persona="regional_manager_north",
        user_id="demo-regional-north",
        kpis=("all",),
        primary_kpi="net_sales_revenue",
        region="South",
        category="Electronics",
        target_date="2023-07-24",
        as_of=None,
        source_mode="production",
        fixture_id=None,
        expected_broad_outcome="ACCESS_DENIED",
    ),
    DemoScenario(
        scenario_id="non-material-baseline",
        title="Non-material baseline",
        purpose="Show that the engine does not escalate ordinary within-threshold variation.",
        demonstration_category="non_material_baseline",
        persona="CFO",
        user_id="demo-cfo",
        kpis=("all",),
        primary_kpi="net_sales_revenue",
        region="North",
        category="Electronics",
        # F-D5 (plan §1.10): 2023-08-13 was the last day of the real EVT01
        # marketing-cut window, so it wasn't a genuine "nothing happened"
        # baseline. 2023-05-22 (a Monday, well before EVT01 starts on
        # 2023-07-20) is a verified quiet date confirmed NO_MATERIAL_MOVEMENT
        # by the Stage 0 ground-truth harness (data/labels/eval_cases.csv).
        target_date="2023-05-22",
        as_of=None,
        source_mode="production",
        fixture_id=None,
        expected_broad_outcome="NO_MATERIAL_MOVEMENT",
    ),
    DemoScenario(
        scenario_id="category-restricted-scope",
        title="Category-restricted scope",
        purpose=(
            "Demonstrate column/domain-level (not just row/region-level) security: "
            "a role scoped to a single category is denied a different category in "
            "its own authorized region (F-S4)."
        ),
        demonstration_category="category_restricted_scope",
        persona="category_manager_north_electronics",
        user_id="demo-category-manager-north-electronics",
        kpis=("all",),
        primary_kpi="net_sales_revenue",
        region="North",
        category="Home",
        target_date="2023-07-24",
        as_of=None,
        source_mode="production",
        fixture_id=None,
        expected_broad_outcome="ACCESS_DENIED",
    ),
)

SCENARIOS: Dict[str, DemoScenario] = {item.scenario_id: item for item in _SCENARIOS}


def list_scenarios() -> list[Dict[str, Any]]:
    return [SCENARIOS[scenario_id].public_dict() for scenario_id in REQUIRED_SCENARIO_IDS]


def get_scenario(scenario_id: str) -> DemoScenario:
    try:
        return SCENARIOS[scenario_id]
    except KeyError as exc:
        raise KeyError(f"Unknown demo scenario: {scenario_id}") from exc


def classify_broad_outcome(result: Mapping[str, Any] | None) -> str:
    payload = result or {}
    verdict = payload.get("verdict")
    if verdict == "ACCESS_DENIED":
        return "ACCESS_DENIED"
    if verdict == "CONTRADICTED":
        return "CONTRADICTED"
    if verdict == "INSUFFICIENT_HISTORY":
        return "INSUFFICIENT_HISTORY"
    if verdict == "NO_MATERIAL_MOVEMENT":
        return "NO_MATERIAL_MOVEMENT"
    if verdict == "SEASONAL_REVIEW":
        return "ABSTAIN"
    if verdict == "MATERIAL_CAUSE_UNVERIFIED":
        return "MATERIAL"
    return str(verdict or "UNKNOWN")


def expected_outcome_observed(expected: str, observed: str) -> bool:
    return expected == observed


def _sanitize_access_denied(result: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "run_id": result.get("run_id"),
        "kpi_id": result.get("kpi_id"),
        "target_date": result.get("target_date"),
        "as_of": result.get("as_of"),
        "persona": result.get("persona"),
        "segment": result.get("segment") or {},
        "verdict": "ACCESS_DENIED",
        "narrative": result.get("narrative") or "Access to the requested KPI slice was denied; no diagnostic evidence is shown.",
        "movement_assessment": None,
        "reconciliation_verdict": None,
        "decomposition": None,
        "decomposition_status": "NOT_EVALUATED",
        "correlational_candidates": [],
        "driver_exclusions": [],
        "driver_analysis": None,
        "causal_verdict": None,
        "causal_verification": None,
        "confidence": None,
        "decision_cards": [],
        "grounding_passed": result.get("grounding_passed", True),
        "narrative_method": result.get("narrative_method"),
        "telemetry": None,
        "processing_transparency": build_processing_transparency({"verdict": "ACCESS_DENIED"}),
    }


def execute_demo_scenario(scenario_id: str, user_id: str | None = None) -> Dict[str, Any]:
    from backend.service import DEMO_IDENTITY_MODE, build_marketing_brief, diagnose_scope, identity_persona
    from backend.response_projection import project_diagnosis

    scenario = get_scenario(scenario_id)
    if not user_id or not user_id.strip():
        raise ValueError("A demo identity is required to execute this scenario.")
    requested_id = user_id
    persona = identity_persona(requested_id)
    if requested_id != scenario.user_id or persona != scenario.persona:
        raise PermissionError("The requesting identity is not the governed identity for this scenario.")

    source_files = scenario.source_files()
    if source_files:
        missing = [path for path in source_files.values() if not Path(path).is_file()]
        if missing:
            raise ValueError(f"Demo fixture files are missing: {missing}")

    response = diagnose_scope(
        kpis=list(scenario.kpis),
        target_date=scenario.target_date,
        region=scenario.region,
        category=scenario.category,
        persona=persona,
        as_of=scenario.as_of,
        source_files=source_files,
        cache_extra={"demo_scenario_id": scenario.scenario_id, "source_mode": scenario.source_mode},
    )
    results: Dict[str, Any] = dict(response.get("results") or {})
    primary = results.get(scenario.primary_kpi) or next(iter(results.values()), {})
    observed = classify_broad_outcome(primary)
    matched = expected_outcome_observed(scenario.expected_broad_outcome, observed)

    if observed == "ACCESS_DENIED":
        results = {kpi_id: _sanitize_access_denied(item) for kpi_id, item in results.items()}
        primary = results.get(scenario.primary_kpi) or next(iter(results.values()), {})
        marketing_brief = None
    else:
        marketing_brief = build_marketing_brief(
            results,
            {
                "region": scenario.region,
                "category": scenario.category,
                "target_date": scenario.target_date,
                "as_of": scenario.as_of,
            },
            persona=persona,
        )

    results = {
        kpi_id: project_diagnosis(item, persona)
        for kpi_id, item in results.items()
    }
    primary = results.get(scenario.primary_kpi) or next(iter(results.values()), {})

    history = (primary.get("movement_assessment") or {}) if primary else {}
    contract_required = None
    if observed == "INSUFFICIENT_HISTORY":
        from kpi_engine.contracts import KPIRegistry
        from backend.config import ENGINE_REGISTRY_DIR

        contract_required = KPIRegistry(ENGINE_REGISTRY_DIR).get(scenario.primary_kpi).min_history_periods

    return {
        "scenario": scenario.public_dict(),
        "resolved_scope": {
            "persona": persona,
            "user_id": requested_id,
            "identity_mode": DEMO_IDENTITY_MODE,
            "kpis": list(scenario.kpis),
            "primary_kpi": scenario.primary_kpi,
            "region": scenario.region,
            "category": scenario.category,
            "target_date": scenario.target_date,
            "as_of": scenario.as_of,
            "source_mode": scenario.source_mode,
        },
        "results": results,
        "marketing_brief": marketing_brief,
        "engine_result": primary,
        "observed_broad_outcome": observed,
        "expected_broad_outcome": scenario.expected_broad_outcome,
        "expected_outcome_observed": matched,
        "uses_demo_fixture": scenario.source_mode == "demo_fixture",
        "history": {
            "baseline_count": history.get("baseline_count"),
            "required_observation_count": contract_required,
        },
    }


def validate_catalog() -> None:
    if tuple(SCENARIOS) != REQUIRED_SCENARIO_IDS and set(SCENARIOS) != set(REQUIRED_SCENARIO_IDS):
        missing = set(REQUIRED_SCENARIO_IDS) - set(SCENARIOS)
        extra = set(SCENARIOS) - set(REQUIRED_SCENARIO_IDS)
        raise ValueError(f"Scenario catalog mismatch: missing={sorted(missing)} extra={sorted(extra)}")
    for scenario in SCENARIOS.values():
        if not scenario.scenario_id or not scenario.title or not scenario.purpose:
            raise ValueError(f"Incomplete scenario metadata: {scenario.scenario_id}")
        if scenario.source_mode not in {"production", "demo_fixture"}:
            raise ValueError(f"Invalid source_mode for {scenario.scenario_id}")
        files = scenario.source_files()
        if files:
            missing = [path for path in files.values() if not Path(path).is_file()]
            if missing:
                raise ValueError(f"Missing fixture files for {scenario.scenario_id}: {missing}")
