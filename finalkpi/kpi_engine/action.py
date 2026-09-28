# Stage 3 (F-R2/F-R3): driver_analysis.ranked_drivers now carries a statistical
# contribution/explained_share per driver (kpi_engine/attribution.py). This
# module deliberately still does not read them into expected_impact: a
# regression contribution is not a validated causal or monetary estimate, and
# turning it into one here would be exactly the kind of overclaim this module
# exists to prevent. expected_impact stays NOT_ESTIMATED until a validated
# deterministic method is configured.
"""Deterministic, evidence-limited action recommendations."""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class DecisionCard:
    action_id: str
    kind: str
    status: str
    driver_id: str | None
    driver_rank: int | None
    driver_relationship: str
    controllability: str
    lever: str
    recommendation: str
    owner: str
    owner_source: str
    decision_right: str
    approval_required: bool
    expected_impact: None = None
    expected_impact_unit: None = None
    impact_method: str = "NOT_ESTIMATED"
    impact_explanation: str = "Impact is not estimated: no validated deterministic method is configured, and correlation is not converted into business impact."
    evidence_status: str = "NOT_ASSESSED"
    confidence_status: str = "NOT_ASSESSED"
    evidence_references: tuple[dict[str, Any], ...] = ()
    constraints: tuple[str, ...] = ()
    monitoring_plan: str = ""
    success_metric: str = ""
    review_window: str = ""
    stop_conditions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    evidence_paths: tuple[str, ...] = ()


class ActionRecommendationEngine:
    """Create review artifacts only; never execute or estimate an action."""

    # Keyed by the current driver id (plan §1.3 rename); LEGACY_DRIVER_IDS in
    # kpi_engine/contracts/registry.py is the single place the old spelling
    # resolves to these. traffic_drop is gone: traffic is a KPI/bridge
    # component (Stage 3), never an actionable driver (F-R2).
    LEVERS = {
        "checkout_latency": (
            "Checkout performance", "engineering_lead",
            "Review checkout latency traces and recent releases before proposing a remediation.",
            "Assess a checkout performance remediation plan and rollback criteria.",
            "Engineering change review",
        ),
        "competitor_price_index": (
            "Pricing", "pricing_lead",
            "Validate the competitor-price observation and compare affected products.",
            "Assess a targeted pricing response and its margin implications.",
            "Pricing and margin approval",
        ),
        "marketing_spend": (
            "Marketing", "marketing_lead",
            "Check weekly spend publication and campaign changes for the affected slice.",
            "Assess a campaign-budget adjustment and its guardrails.",
            "Marketing budget approval",
        ),
        "stock_availability": (
            "Availability", "operations_lead",
            "Check inventory and lost-unit records for the affected slice.",
            "Assess a replenishment response and operational capacity.",
            "Operations capacity approval",
        ),
        "price_discount": (
            "Pricing/Promotions", "pricing_lead",
            "Validate the discount depth observation and compare against the promo calendar.",
            "Assess a targeted discount adjustment and its margin implications.",
            "Pricing and margin approval",
        ),
        "promo_flag": (
            "Pricing/Promotions", "pricing_lead",
            "Validate the promotion window observation and compare against the promo calendar.",
            "Assess a promotion timing or scope adjustment.",
            "Pricing and margin approval",
        ),
        "weather_temp": (
            "Contextual", "merchandising_lead",
            "Review the weather observation and its expected category-level effect.",
            "Assess inventory and merchandising plan adjustments; weather is not controllable.",
            "Merchandising plan review",
        ),
    }

    @classmethod
    def _driver_specs(cls, result: dict[str, Any]) -> dict[str, dict[str, Any]]:
        drivers = ((result.get("contract_snapshot") or {}).get("drivers") or {}).get("candidate_drivers") or []
        return {item.get("driver_id"): item for item in drivers if item.get("driver_id")}

    @classmethod
    def _confidence_status(cls, result: dict[str, Any]) -> str:
        overall = ((result.get("confidence_profile") or {}).get("overall") or {})
        return overall.get("status") or (result.get("confidence") or {}).get("status", "NOT_ASSESSED")

    @classmethod
    def _evidence_status(cls, result: dict[str, Any]) -> str:
        source = ((result.get("confidence_profile") or {}).get("source") or {})
        return source.get("status") or ((result.get("reconciliation_verdict") or {}).get("status", "NOT_ASSESSED"))

    @classmethod
    def _blocked(cls, result: dict[str, Any]) -> bool:
        profile = result.get("confidence_profile") or {}
        source = profile.get("source") or {}
        overall = profile.get("overall") or {}
        reconciliation = result.get("reconciliation_verdict") or {}
        return (
            result.get("verdict") == "CONTRADICTED"
            or reconciliation.get("status") == "CONTRADICTED"
            or reconciliation.get("blocking") is True
            or source.get("status") == "CONFLICTING_EVIDENCE"
            or source.get("blocking") is True
            or overall.get("status") == "CONFLICTING_EVIDENCE"
        )

    @classmethod
    def _ranked_drivers(cls, result: dict[str, Any]) -> list[dict[str, Any]]:
        analysis = result.get("driver_analysis")
        return list(analysis.get("ranked_drivers") or []) if isinstance(analysis, dict) else list(result.get("correlational_candidates") or [])

    @classmethod
    def _build_card(cls, result: dict[str, Any], *, kind: str, driver: dict[str, Any] | None,
                    lever: str, recommendation: str, fallback_owner: str, owner_source: str,
                    decision_right: str, approval_required: bool, evidence_paths: tuple[str, ...],
                    limitations: tuple[str, ...] = ()) -> dict[str, Any]:
        driver_id = driver.get("driver_id") if driver else None
        spec = cls._driver_specs(result).get(driver_id, {})
        owner = spec.get("owner") or fallback_owner
        resolved_owner_source = "contract.candidate_drivers.owner" if spec.get("owner") else owner_source
        rank = driver.get("rank") if driver else None
        source_id = (driver or {}).get("source_id") or spec.get("source_id") or spec.get("source")
        period = result.get("target_date") or result.get("as_of")
        references = tuple({
            "evidence_type": "ranked_driver" if driver else "source_verification",
            "path": path,
            "driver_id": driver_id,
            "driver_rank": rank,
            "source_id": source_id,
            "period": period,
            "method": driver.get("alignment_method", "governed association") if driver else "source reconciliation",
        } for path in evidence_paths)
        monitor = f"Monitor {spec.get('display_name') or lever} ({driver_id or 'source verification'}) and the declared KPI at the governed native grain."
        stops = (
            "Stop the review if the driver is excluded, source coverage falls below its governed minimum, or reconciliation becomes contradictory.",
            "Do not roll out a change without independent verification and approval.",
        )
        limits = (*limitations, "Expected impact is not estimated without a validated deterministic method.")
        if kind == "ACTION_PROPOSAL":
            limits = (*limits, "Conditional observational support is not proof of causality.")
        return asdict(DecisionCard(
            action_id=f"ACTION_{driver_id or 'EVIDENCE_COLLECTION'}_{kind}", kind=kind,
            status="AWAITING_APPROVAL" if approval_required else "AWAITING_REVIEW",
            driver_id=driver_id, driver_rank=rank,
            driver_relationship="CONDITIONAL_CAUSAL_SUPPORT" if kind == "ACTION_PROPOSAL" else "ASSOCIATION" if driver else "EVIDENCE_GATHERING",
            controllability=(driver or {}).get("controllability") or spec.get("controllability", "contextual"),
            lever=lever, recommendation=recommendation, owner=owner, owner_source=resolved_owner_source,
            decision_right=decision_right, approval_required=approval_required,
            evidence_status=cls._evidence_status(result), confidence_status=cls._confidence_status(result),
            evidence_references=references, constraints=("Association is diagnostic only; no causal or monetary impact is established.",),
            monitoring_plan=monitor, success_metric=f"Verify the declared {spec.get('display_name') or lever} signal before any rollout.",
            review_window="Review after the next governed observation window and source validation.",
            stop_conditions=stops, limitations=limits, evidence_paths=evidence_paths,
        ))

    @classmethod
    def recommend(cls, result: dict[str, Any]) -> list[dict[str, Any]]:
        if result.get("verdict") == "ACCESS_DENIED":
            return []
        if cls._blocked(result):
            return [cls._build_card(result, kind="NEXT_CHECK", driver=None, lever="Source integrity",
                recommendation="Reconcile sales and finance postings before investigating drivers.",
                fallback_owner="finance_owner", owner_source="validated_source_integrity_rule",
                decision_right="Source reconciliation review", approval_required=False,
                evidence_paths=("reconciliation_verdict.status",),
                limitations=("Contradictory evidence blocks all operational action proposals.",))]
        if result.get("verdict") not in {"MATERIAL_CAUSE_UNVERIFIED", "EVENT_ASSESSED_CAUSE_UNVERIFIED"}:
            return []
        confidence_status = cls._confidence_status(result)
        verification = result.get("causal_verification") or {}
        verified_driver = verification.get("driver_id")
        analysis = result.get("driver_analysis")
        if isinstance(analysis, dict) and analysis.get("status") == "BLOCKED":
            return []
        ranked = cls._ranked_drivers(result)
        ranked_ids = {item.get("driver_id") for item in ranked}
        if analysis is None and verification.get("verdict") == "SUPPORTED_CONDITIONAL" and verified_driver in cls.LEVERS:
            ranked.append({"driver_id": verified_driver, "claim_type": "CONDITIONAL_CAUSAL_SUPPORT"})
            ranked_ids.add(verified_driver)
        if verified_driver in cls.LEVERS and verified_driver in ranked_ids:
            driver = next(item for item in ranked if item.get("driver_id") == verified_driver)
            lever, fallback_owner, check, proposal, decision_right = cls.LEVERS[verified_driver]
            if verification.get("verdict") == "SUPPORTED_CONDITIONAL":
                if confidence_status in {"LOW", "INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE"}:
                    return [cls._build_card(result, kind="NEXT_CHECK", driver=driver, lever=lever,
                        recommendation=check, fallback_owner=fallback_owner, owner_source="validated_action_catalog",
                        decision_right=decision_right, approval_required=False,
                        evidence_paths=("causal_verification.verdict", "causal_verification.driver_id"),
                        limitations=("Confidence is insufficient for an operational proposal.",))]
                return [cls._build_card(result, kind="ACTION_PROPOSAL", driver=driver, lever=lever,
                    recommendation=proposal, fallback_owner=fallback_owner, owner_source="validated_action_catalog",
                    decision_right=decision_right, approval_required=True,
                    evidence_paths=("causal_verification.verdict", "causal_verification.driver_id"))]
            if verification.get("verdict") in {"INCONCLUSIVE", "UNTESTABLE"}:
                return [cls._build_card(result, kind="NEXT_CHECK", driver=driver, lever=lever,
                    recommendation=check, fallback_owner=fallback_owner, owner_source="validated_action_catalog",
                    decision_right=decision_right, approval_required=False,
                    evidence_paths=("causal_verification.verdict", "causal_verification.driver_id"))]
        if ranked:
            candidate = ranked[0]
            driver_id = candidate.get("driver_id")
            if driver_id in cls.LEVERS and not (verification.get("verdict") == "REJECTED" and driver_id == verified_driver):
                lever, fallback_owner, check, _, decision_right = cls.LEVERS[driver_id]
                return [cls._build_card(result, kind="NEXT_CHECK", driver=candidate, lever=lever,
                    recommendation=check, fallback_owner=fallback_owner, owner_source="validated_action_catalog",
                    decision_right=decision_right, approval_required=False,
                    evidence_paths=("driver_analysis.ranked_drivers", "correlational_candidates"),
                    limitations=("The ranked relationship is associative and requires verification before action.",))]
        return [cls._build_card(result, kind="NEXT_CHECK", driver=None, lever="Evidence collection",
            recommendation="Review the event timeline and identify a valid comparison group before proposing action.",
            fallback_owner="analyst", owner_source="validated_evidence_collection_rule",
            decision_right="Evidence review", approval_required=False, evidence_paths=("causal_verification",))]
