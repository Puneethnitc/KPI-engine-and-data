"""Human-review recommendations from a closed, non-executing lever library."""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class DecisionCard:
    kind: str  # NEXT_CHECK | ACTION_PROPOSAL
    driver_id: str | None
    lever: str
    recommendation: str
    owner: str
    status: str  # AWAITING_REVIEW | AWAITING_APPROVAL
    evidence_paths: tuple[str, ...]
    expected_impact: None = None


class ActionRecommendationEngine:
    """Never executes actions or estimates recovery from a correlation."""

    LEVERS = {
        "checkout_latency_spike": (
            "Checkout performance", "engineering_lead",
            "Review checkout latency traces and recent releases before proposing a remediation.",
            "Assess a checkout performance remediation plan and rollback criteria.",
        ),
        "competitor_price_cut": (
            "Pricing", "pricing_lead",
            "Validate the competitor-price observation and compare affected products.",
            "Assess a targeted pricing response and its margin implications.",
        ),
        "ad_spend_drop": (
            "Marketing", "marketing_lead",
            "Check weekly spend publication and campaign changes for the affected slice.",
            "Assess a campaign-budget adjustment and its guardrails.",
        ),
        "stockout": (
            "Availability", "operations_lead",
            "Check inventory and lost-unit records for the affected slice.",
            "Assess a replenishment response and operational capacity.",
        ),
        "traffic_drop": (
            "Acquisition", "growth_lead",
            "Check traffic instrumentation and channel-level movement.",
            "Assess a channel recovery plan and measurement safeguards.",
        ),
    }

    @classmethod
    def recommend(cls, result: dict[str, Any]) -> list[dict[str, Any]]:
        verdict = result.get("verdict")
        if verdict == "ACCESS_DENIED":
            return []
        if verdict == "CONTRADICTED":
            return [asdict(DecisionCard(
                "NEXT_CHECK", None, "Source integrity",
                "Reconcile sales and finance postings before investigating drivers.",
                "finance_owner", "AWAITING_REVIEW",
                ("reconciliation_verdict.status",),
            ))]
        if verdict not in {"MATERIAL_CAUSE_UNVERIFIED", "EVENT_ASSESSED_CAUSE_UNVERIFIED"}:
            return []

        verification = result.get("causal_verification") or {}
        verified_driver = verification.get("driver_id")
        if verification.get("verdict") == "SUPPORTED_CONDITIONAL" and verified_driver in cls.LEVERS:
            lever, owner, _, proposal = cls.LEVERS[verified_driver]
            return [asdict(DecisionCard(
                "ACTION_PROPOSAL", verified_driver, lever, proposal, owner,
                "AWAITING_APPROVAL",
                ("causal_verification.verdict", "causal_verification.driver_id"),
            ))]
        if verified_driver in cls.LEVERS and verification.get("verdict") in {"INCONCLUSIVE", "UNTESTABLE"}:
            lever, owner, check, _ = cls.LEVERS[verified_driver]
            return [asdict(DecisionCard(
                "NEXT_CHECK", verified_driver, lever, check, owner,
                "AWAITING_REVIEW",
                ("causal_verification.verdict", "causal_verification.driver_id"),
            ))]
        candidates = result.get("correlational_candidates") or []
        if candidates:
            candidate = candidates[0]
            driver = candidate.get("driver_id")
            if (candidate.get("claim_type") == "CORRELATIONAL" and driver in cls.LEVERS
                    and not (verification.get("verdict") == "REJECTED"
                             and driver == verified_driver)):
                lever, owner, check, _ = cls.LEVERS[driver]
                return [asdict(DecisionCard(
                    "NEXT_CHECK", driver, lever, check, owner,
                    "AWAITING_REVIEW",
                    ("correlational_candidates.0.driver_id",
                     "correlational_candidates.0.claim_type"),
                ))]
        return [asdict(DecisionCard(
            "NEXT_CHECK", None, "Evidence collection",
            "Review the event timeline and identify a valid comparison group before proposing action.",
            "analyst", "AWAITING_REVIEW", ("causal_verdict",),
        ))]
