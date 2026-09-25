# IMPLEMENTATION HANDOFF — evidence-quality diagnostics
# Current: maps verification verdicts and reports window coverage, temporal
# precedence and interval precision; there is no calibrated causal probability.
# Next: use the SAME resolved verification policy for coverage denominators
# (currently 14 pre/7 post) and expose that policy in result provenance.
# Check: changing verification minima also changes diagnostic coverage; missing
# evidence stays unknown rather than becoming a zero-confidence probability.

"""Transparent evidence diagnostics, not a calibrated causal probability."""

from dataclasses import dataclass
from math import isfinite

from kpi_engine.verification.models import CausalVerificationResult, VerificationPolicy


@dataclass(frozen=True)
class EvidenceQualityAssessment:
    status: str  # NOT_ASSESSED | INSUFFICIENT | CONFLICTING | INCONCLUSIVE | CONDITIONAL_SUPPORT
    claim_type: str
    sub_scores: dict[str, float | None]
    reasons: tuple[str, ...]
    calibrated_probability: None = None


class ConfidenceEngine:
    """Describe what an observational design supports, without averaging gates."""

    @staticmethod
    def assess(verification: CausalVerificationResult) -> EvidenceQualityAssessment:
        if not isinstance(verification, CausalVerificationResult):
            raise TypeError("A CausalVerificationResult is required")

        policy = verification.policy or VerificationPolicy()
        if hasattr(policy, "validate"):
            policy.validate()

        min_pre_days = getattr(policy, "min_pre_days", VerificationPolicy.min_pre_days)
        min_post_days = getattr(policy, "min_post_days", VerificationPolicy.min_post_days)

        # These are descriptive diagnostics, not empirical probabilities.
        coverage = (
            min(1.0, verification.pre_days / min_pre_days,
                verification.post_days / min_post_days)
            if verification.pre_days and verification.post_days else None
        )
        temporal = (float(verification.temporal_precedence_passed)
                    if verification.temporal_precedence_passed is not None else None)
        precision = None
        if verification.did_effect is not None and verification.confidence_interval is not None:
            low, high = verification.confidence_interval
            effect = verification.did_effect
            if all(isfinite(value) for value in (low, high, effect)) and low <= high:
                half_width = (high - low) / 2
                # 0 when the interval contains zero; otherwise a bounded
                # signal-to-interval-width diagnostic. Not statistical power.
                precision = (0.0 if low <= 0 <= high else
                             min(1.0, abs(effect) / (abs(effect) + half_width)))

        status = {
            "SUPPORTED_CONDITIONAL": "CONDITIONAL_SUPPORT",
            "REJECTED": "CONFLICTING",
            "INCONCLUSIVE": "INCONCLUSIVE",
            "UNTESTABLE": "INSUFFICIENT" if verification.reason_code != "NO_DESIGN" else "NOT_ASSESSED",
        }.get(verification.verdict)
        if status is None:
            raise ValueError(f"Unknown verification verdict: {verification.verdict}")
        reasons = (verification.reason_code, verification.reason)
        return EvidenceQualityAssessment(
            status=status,
            claim_type="OBSERVATIONAL_EVIDENCE_QUALITY",
            sub_scores={
                "outcome_window_coverage": coverage,
                "temporal_precedence": temporal,
                "did_interval_precision": precision,
            },
            reasons=reasons,
        )
