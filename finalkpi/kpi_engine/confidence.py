# IMPLEMENTATION HANDOFF — calibrated confidence and uncertainty
# Current: run-bound movement/source/driver/causal dimensions use deterministic
# engine outputs; numeric scores remain null because outcome calibration is absent.
# Stage 3 (F-R3): the driver dimension's reasoning text now cites the
# strongest driver's contribution/explained_share (AttributionEngine), not a
# correlation score; MODERATE/LOW is still keyed off stability_status alone.
# Next: validate probability calibration on reviewed labelled outcomes before
# exposing any numeric score; keep analysis thresholds in their owning policies.
# Check: sparse/conflicting evidence abstains, NOT_APPLICABLE stays neutral, and
# no association or accounting identity is upgraded to a causal claim.

"""Transparent evidence diagnostics, not a calibrated causal probability."""

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any

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

    @staticmethod
    def build_profile(
        result: dict[str, Any],
        *,
        causal_design_approved: bool = False,
    ) -> dict[str, Any]:
        """Build a run-bound evidence conclusion; numeric scores stay uncalibrated."""
        evaluated_at = datetime.now(timezone.utc).isoformat()
        no_score = "No probability or numeric confidence score is emitted: calibration against labelled outcomes has not been validated."
        no_score_interpretation = "Use the categorical status and its stated gates; this is not a probability."

        def dimension(
            status: str,
            method: str,
            inputs: dict[str, Any],
            reasons: list[str],
            limitations: list[str],
            applicable: bool = True,
            blocking: bool = False,
            evidence_refs: list[str] | None = None,
        ) -> dict[str, Any]:
            return {
                "status": status,
                "score": None,
                "score_scale": no_score,
                "score_interpretation": no_score_interpretation,
                "method": method,
                "inputs": inputs,
                "reasons": reasons,
                "limitations": limitations,
                "evaluated_at": evaluated_at,
                "applicable": applicable,
                "blocking": blocking,
                "evidence_refs": evidence_refs or [],
            }

        if result.get("verdict") == "ACCESS_DENIED":
            hidden = dimension(
                "NOT_ASSESSED", "WITHHELD_FOR_ACCESS_CONTROL", {},
                ["Confidence evidence is withheld for an unauthorized scope."], [],
                applicable=False,
            )
            dimensions = {key: dict(hidden) for key in ("movement", "source", "driver", "causal")}
            return {
                "version": "1.0",
                "evaluated_at": evaluated_at,
                "overall": {
                    "status": "NOT_ASSESSED",
                    "method": "BLOCKING_GATES_V1",
                    "reasons": ["No protected evidence was evaluated or returned."],
                    "blocking_dimensions": [],
                },
                **dimensions,
            }

        movement = result.get("movement_assessment") or {}
        movement_reasons: list[str] = []
        movement_limits: list[str] = []
        movement_status = "INSUFFICIENT_EVIDENCE"
        movement_refs = ["movement_assessment"] if movement else []
        if movement.get("status") == "OK":
            statistical = bool(movement.get("is_statistically_significant"))
            material = bool(movement.get("is_business_material"))
            agreement = movement.get("detector_agreement", "NEITHER")
            if statistical:
                movement_reasons.append("The movement passed the configured statistical-significance gate.")
            else:
                movement_reasons.append("The movement did not pass the configured statistical-significance gate.")
            if material:
                movement_reasons.append("The movement passed the configured business-materiality gate.")
            else:
                movement_reasons.append("The movement did not pass the configured business-materiality gate.")
            if statistical and material and agreement == "BOTH":
                movement_status = "HIGH"
            elif statistical and material and agreement == "ROBUST_ONLY":
                movement_status = "MODERATE"
                movement_limits.append("The seasonal forecast detector did not agree with the robust detector.")
            else:
                movement_status = "LOW"
                movement_limits.append(f"Detector agreement is {agreement}; independent confirmation is limited.")
            if movement.get("baseline_count") is not None:
                movement_reasons.append(f"Baseline uses {movement['baseline_count']} observations.")
            if movement.get("seasonal_status") or movement.get("forecast_status"):
                movement_reasons.append("Forecast/anomaly diagnostics are retained in the movement inputs.")
        else:
            movement_reasons.append("The baseline/history gate did not produce an assessable movement.")
            movement_limits.append("Sparse or unavailable history prevents movement assessment.")
        movement_inputs = {
            key: movement.get(key) for key in (
                "status", "actual_value", "expected_value", "delta", "z_score",
                "is_statistically_significant", "is_business_material",
                "detector_agreement", "baseline_count", "method",
                "policy", "robust_score", "sustained_score", "seasonal_status",
                "seasonal_score", "seasonal_expected", "seasonal_calibration_count",
            ) if key in movement
        }
        movement_dimension = dimension(
            movement_status,
            movement.get("method", "ROBUST_AND_SEASONAL_MOVEMENT_GATES"),
            movement_inputs,
            movement_reasons,
            movement_limits,
            applicable=True,
            evidence_refs=movement_refs,
        )

        source_evidence = result.get("source_evidence") or {}
        source_ready = source_evidence.get("source_readiness") or {}
        recon = result.get("reconciliation_verdict") or source_evidence.get("reconciliation") or {}
        recon_status = recon.get("status", "NOT_ASSESSED")
        readiness = source_ready.get("status", "NOT_ASSESSED")
        source_reasons: list[str] = []
        source_limits = list(source_ready.get("limitations") or [])
        source_blocking = recon_status == "CONTRADICTED" or bool(recon.get("blocking"))
        if source_blocking:
            source_status = "CONFLICTING_EVIDENCE"
            source_reasons.append("Independent source evidence contradicts the primary measure; downstream claims are blocked.")
        elif readiness in ("MISSING", "QUALITY_FAILED") or recon_status == "DRIFT" and (recon.get("details") or {}).get("quality_flag"):
            source_status = "INSUFFICIENT_EVIDENCE"
            source_reasons.append(f"Required-source readiness is {readiness}.")
        elif readiness in ("PARTIAL", "STALE") or recon_status in ("DRIFT", "NOT_AVAILABLE_FOR_PERIOD"):
            source_status = "LOW"
            source_reasons.append(f"Source readiness/reconciliation needs review ({readiness}; {recon_status}).")
        elif readiness == "READY" and recon_status in ("AGREED", "NOT_APPLICABLE", "PENDING_CLOSE"):
            source_status = "HIGH"
            if recon_status == "AGREED":
                source_reasons.append("Required sources are ready and independent reconciliation agrees.")
            elif recon_status == "PENDING_CLOSE":
                source_reasons.append("Required sources are ready; the finance comparator is not yet due and is neutral.")
            else:
                source_reasons.append("Required sources are ready; reconciliation is not applicable and is neutral.")
        else:
            source_status = "INSUFFICIENT_EVIDENCE"
            source_reasons.append("Required-source readiness or reconciliation was not established.")
        source_refs = []
        if source_evidence:
            source_refs.extend(["source_evidence.source_readiness", "source_evidence.sources"])
        if recon:
            source_refs.append("reconciliation_verdict")
        source_inputs = {
            "required_sources": source_ready.get("required_sources", []),
            "available_sources": source_ready.get("available_sources", []),
            "readiness": readiness,
            "source_entries": source_evidence.get("sources", []),
            "reconciliation_status": recon_status,
            "reconciliation_applicable": recon.get("applicable", recon_status != "NOT_APPLICABLE"),
            "target_period_coverage": {
                "primary_observation_present": movement.get("actual_value") is not None,
                "driver_coverage": result.get("source_coverage"),
                "sources": [
                    {key: source.get(key) for key in ("source_id", "coverage_status", "coverage_start", "coverage_end")}
                    for source in source_evidence.get("sources", [])
                ],
            },
            "quality_flag": (recon.get("details") or {}).get("quality_flag"),
        }
        source_dimension = dimension(
            source_status, "REQUIRED_SOURCE_READINESS_COVERAGE_FRESHNESS_QUALITY_AND_RECONCILIATION",
            source_inputs, source_reasons, source_limits, blocking=source_blocking,
            evidence_refs=source_refs,
        )

        driver_analysis = result.get("driver_analysis") or {}
        candidates = driver_analysis.get("ranked_drivers") or []
        exclusions = driver_analysis.get("excluded_drivers") or []
        driver_reasons: list[str] = []
        driver_limits = [
            "Association only, not a causal estimate.",
            "Accounting decomposition is separate and does not derive monetary contribution from driver association.",
        ]
        if source_blocking:
            driver_status = "CONFLICTING_EVIDENCE"
            driver_reasons.append("Driver interpretation is blocked by contradictory source evidence.")
        elif candidates:
            strongest = candidates[0]
            driver_status = "MODERATE" if strongest.get("stability_status") == "STABLE" else "LOW"
            driver_reasons.append(
                f"{strongest.get('display_name', strongest.get('driver_id', 'A ranked driver'))} ranked first by "
                f"{strongest.get('method', 'the governed attribution method')} "
                f"(contribution={strongest.get('contribution')}, explained_share={strongest.get('explained_share')}, "
                f"n={strongest.get('sample_size')})."
            )
            driver_limits.extend(driver_analysis.get("limitations") or [])
            if strongest.get("stability_status") == "SENSITIVE":
                driver_limits.append("Top-ranked association is sensitive to analysis window selection.")
        elif exclusions:
            driver_status = "INSUFFICIENT_EVIDENCE"
            driver_reasons.append("No candidate driver passed its configured checks; exclusions are retained below.")
            driver_limits.extend(driver_analysis.get("limitations") or [])
        else:
            driver_status = "NOT_ASSESSED" if not movement else "INSUFFICIENT_EVIDENCE"
            driver_reasons.append("No ranked driver evidence was produced for this run.")
        driver_dimension = dimension(
            driver_status, "JOINT_ROBUST_REGRESSION_EXPLAINED_MOVEMENT",
            {
                "candidates": candidates,
                "exclusions": exclusions,
                "driver_analysis": driver_analysis,
                "source_coverage": result.get("source_coverage"),
                "missingness_denominator": None,
                "driver_source_inventory": [
                    {key: source.get(key) for key in ("source_id", "coverage_status", "quality_status", "latest_available_time")}
                    for source in source_evidence.get("sources", [])
                ],
            },
            driver_reasons, driver_limits,
            applicable=bool(driver_analysis) or source_blocking,
            blocking=source_blocking,
            evidence_refs=["driver_analysis.ranked_drivers", "driver_analysis.excluded_drivers"] if driver_analysis else [],
        )

        verification = result.get("causal_verification") or {}
        legacy_confidence = result.get("confidence") or {}
        reason_code = verification.get("reason_code") or (legacy_confidence.get("reasons") or ["NO_DESIGN"])[0]
        if reason_code in {"CONTROL_NOT_AUTHORIZED", "TREATMENT_SLICE_MISMATCH", "UNDECLARED_DRIVER", "FUTURE_POST_PERIOD"}:
            causal_design_approved = False
        causal_reasons = [verification.get("reason") or "No approved causal design was evaluated."]
        causal_limits: list[str] = []
        if source_blocking:
            causal_status = "CONFLICTING_EVIDENCE"
            causal_reasons = ["Causal claims are blocked by contradictory source evidence."]
        elif not causal_design_approved:
            causal_status = "NOT_ASSESSED"
            causal_reasons = ["No approved, authorized server-side causal design exists for this run."]
            causal_limits.append("Correlation and accounting decomposition do not establish operational causality.")
        else:
            causal_status = {
                "CONDITIONAL_SUPPORT": "MODERATE",
                "CONFLICTING": "CONFLICTING_EVIDENCE",
                "INSUFFICIENT": "INSUFFICIENT_EVIDENCE",
                "INCONCLUSIVE": "LOW",
                "NOT_ASSESSED": "NOT_ASSESSED",
            }.get(legacy_confidence.get("status"), "INSUFFICIENT_EVIDENCE")
            if causal_status == "MODERATE":
                causal_limits.append("Observational design support is conditional and is not proof of causality.")
        if not source_blocking and reason_code in {"CONTROL_NOT_AUTHORIZED", "TREATMENT_SLICE_MISMATCH", "UNDECLARED_DRIVER", "FUTURE_POST_PERIOD"}:
            causal_status = "NOT_ASSESSED"
            causal_limits.append("Design authorization or scope validation did not pass.")
        causal_inputs = {
            "approved_design": causal_design_approved,
            "treatment_authorized": result.get("verdict") != "ACCESS_DENIED",
            "control_authorized": causal_design_approved and reason_code != "CONTROL_NOT_AUTHORIZED",
            "source_conflict_check_passed": not source_blocking,
            "reason_code": reason_code,
            "method": verification.get("method"),
            "pre_days": verification.get("pre_days"),
            "post_days": verification.get("post_days"),
            "outcome_window_coverage": (legacy_confidence.get("sub_scores") or {}).get("outcome_window_coverage"),
            "temporal_precedence_passed": verification.get("temporal_precedence_passed"),
            "pretrend_slope": verification.get("pretrend_slope"),
            "pretrend_p_value": verification.get("pretrend_p_value"),
            "pre_event_shift": verification.get("pre_event_shift"),
            "placebo_effects": verification.get("placebo_effects"),
            "driver_exposure_effect": verification.get("driver_exposure_effect"),
            "driver_exposure_periods": verification.get("driver_exposure_periods"),
            "effect": verification.get("did_effect"),
            "interval": verification.get("confidence_interval"),
            "interval_precision_diagnostic": (legacy_confidence.get("sub_scores") or {}).get("did_interval_precision"),
            "diagnostic_status": legacy_confidence.get("status"),
        }
        causal_dimension = dimension(
            causal_status, verification.get("method", "APPROVED_DESIGN_DIAGNOSTICS"),
            causal_inputs, causal_reasons, causal_limits,
            applicable=causal_design_approved or source_blocking,
            blocking=source_blocking,
            evidence_refs=["causal_verification", "confidence"] if verification or legacy_confidence else [],
        )

        dimensions = {
            "movement": movement_dimension,
            "source": source_dimension,
            "driver": driver_dimension,
            "causal": causal_dimension,
        }
        blocking_dimensions = [name for name, item in dimensions.items() if item["blocking"]]
        if source_blocking:
            overall_status = "CONFLICTING_EVIDENCE"
            overall_reasons = ["A blocking source contradiction takes precedence over other dimension statuses."]
        elif movement_status == "INSUFFICIENT_EVIDENCE" or source_status == "INSUFFICIENT_EVIDENCE":
            overall_status = "INSUFFICIENT_EVIDENCE"
            overall_reasons = ["A required movement-history or source-evidence gate is insufficient; abstain from a stronger conclusion."]
        elif movement_status == "LOW" or source_status == "LOW":
            overall_status = "LOW"
            overall_reasons = ["At least one required evidence dimension has a failed or limited gate."]
        elif causal_status == "NOT_ASSESSED":
            overall_status = "MODERATE"
            overall_reasons = ["Movement/source evidence is assessed, but no approved causal design supports a causal conclusion."]
        elif causal_status == "MODERATE" and movement_status == "HIGH" and source_status in ("HIGH", "MODERATE"):
            overall_status = "MODERATE"
            overall_reasons = ["Approved observational diagnostics are conditionally supportive; no probability of causation is claimed."]
        else:
            overall_status = "HIGH" if movement_status == "HIGH" and source_status == "HIGH" and causal_status == "MODERATE" else "MODERATE"
            overall_reasons = ["Conclusion follows the dimension gates; it is not an averaged score or probability."]

        return {
            "version": "1.0",
            "evaluated_at": evaluated_at,
            "overall": {
                "status": overall_status,
                "method": "BLOCKING_GATES_V1",
                "reasons": overall_reasons,
                "blocking_dimensions": blocking_dimensions,
            },
            **dimensions,
        }
