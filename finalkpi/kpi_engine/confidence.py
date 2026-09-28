# IMPLEMENTATION HANDOFF — calibrated confidence and uncertainty
# Current: movement/source dimensions use deterministic engine outputs and
# stay uncalibrated (score stays null). Stage 7 (F-C1, F-C2): the driver
# dimension is replaced by `attribution` -- the top-ranked driver's per-driver
# Attribution Confidence (AC) band from AttributionConfidenceEngine, with
# `driver` kept only as a compatibility alias of the same dict. The overall
# status is now the weakest-required-dimension rule over movement, source,
# attribution and causal (when assessed), with two headline conclusions:
# movement_conclusion ("is it real?") and explanation_conclusion ("do we
# know why?").
# Next: validate probability calibration on reviewed labelled outcomes before
# treating AC as a validated probability; keep analysis thresholds in their
# owning policies.
# Check: sparse/conflicting evidence abstains, NOT_APPLICABLE stays neutral,
# a REJECTED top-driver causal test with no AC>=0.6 alternative forces
# CONFLICTING_EVIDENCE, and no association or accounting identity is upgraded
# to a causal claim.

"""Transparent evidence diagnostics; AC is a transparent evidence-weighted
estimate, not yet a calibrated causal probability (see attribution_confidence.py)."""

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any

from kpi_engine.attribution_confidence import AttributionConfidenceEngine, default_model
from kpi_engine.verification.models import CausalVerificationResult, VerificationPolicy

_DIMENSION_SCALE = {
    "CONFLICTING_EVIDENCE": 0,
    "INSUFFICIENT_EVIDENCE": 1,
    "LOW": 2,
    "MODERATE": 3,
    "HIGH": 4,
}


def _weakest(*statuses: str | None) -> str:
    """Weakest-required-dimension rule (Plan §7.2). A status outside the
    ordered scale (NOT_ASSESSED, None) is not required and is skipped."""
    ranked = [status for status in statuses if status in _DIMENSION_SCALE]
    if not ranked:
        return "NOT_ASSESSED"
    return min(ranked, key=lambda status: _DIMENSION_SCALE[status])


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
            dimensions["attribution"] = dict(hidden)
            return {
                "version": "1.0",
                "evaluated_at": evaluated_at,
                "overall": {
                    "status": "NOT_ASSESSED",
                    "method": "BLOCKING_GATES_V1",
                    "reasons": ["No protected evidence was evaluated or returned."],
                    "blocking_dimensions": [],
                    "movement_conclusion": "NOT_ASSESSED",
                    "explanation_conclusion": "NOT_ASSESSED",
                },
                "attribution_status": "NOT_ASSESSED",
                "attribution_confidence": [],
                **dimensions,
            }

        event_mode = "movement_assessment" not in result
        movement = result.get("movement_assessment") or {}
        movement_reasons: list[str] = []
        movement_limits: list[str] = []
        movement_status = "INSUFFICIENT_EVIDENCE"
        movement_refs = ["movement_assessment"] if movement else []
        if event_mode:
            movement_status = "NOT_ASSESSED"
            movement_reasons.append("Movement is not assessed in event-verification mode; the event window is predeclared.")
        elif movement.get("status") == "OK":
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
        # Event mode has no daily materiality gate; treat the predeclared
        # event as material so overall status follows explanation_conclusion,
        # not a movement dimension that was never assessed (Plan §7.2).
        #
        # Otherwise use the detector ensemble's own `is_material`, which is the
        # same gate the pipeline used to decide whether to diagnose at all
        # (detection/ensemble.py: a seasonal-only hit is evidence to review,
        # not an alert). Reading `is_business_material` instead let a
        # SEASONAL_REVIEW day score its driver at 0.75 / MODERATE, because a
        # large enough delta can clear business materiality while still
        # failing significance. Fall back to the business flag only for
        # payloads that predate the ensemble's field.
        if event_mode:
            is_material = True
        elif "is_material" in movement:
            is_material = bool(movement["is_material"])
        else:
            is_material = bool(movement.get("is_business_material"))

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
        driver_source_inventory = [
            {key: source.get(key) for key in ("source_id", "coverage_status", "quality_status", "latest_available_time")}
            for source in source_evidence.get("sources", [])
        ]
        attribution_reasons: list[str] = []
        attribution_limits = [
            "Statistical attribution of observed movement; causal status is shown separately.",
        ]
        ac_model_version = default_model().version
        ac_profile: dict[str, Any] = {
            "model_version": ac_model_version, "attribution_status": "NOT_ASSESSED",
            "drivers": [], "unexplained": None, "top_driver_id": None,
        }
        top_driver_id = None
        causal_verification = result.get("causal_verification") or {}
        legacy_confidence = result.get("confidence") or {}
        reason_code = causal_verification.get("reason_code") or (legacy_confidence.get("reasons") or ["NO_DESIGN"])[0]
        if reason_code in {"CONTROL_NOT_AUTHORIZED", "TREATMENT_SLICE_MISMATCH", "UNDECLARED_DRIVER", "FUTURE_POST_PERIOD"}:
            causal_design_approved = False

        # Stage 6-lite writes `corroboration` onto each ranked driver in
        # pipeline.py, immediately after attribution and before this call.
        # Feeding it in here is what makes AC evidence item E8 fire: a
        # CORROBORATED driver gets E8's positive weight, a CONTRADICTED one its
        # penalty, and an unmatched driver contributes 0 (never a penalty).
        corroboration_by_driver = {
            candidate["driver_id"]: candidate["corroboration"]
            for candidate in candidates
            if candidate.get("driver_id") and isinstance(candidate.get("corroboration"), dict)
        }

        if source_blocking:
            attribution_status = "CONFLICTING_EVIDENCE"
            attribution_reasons.append("Driver interpretation is blocked by contradictory source evidence.")
            ac_profile = AttributionConfidenceEngine.compute_profile(
                ranked_drivers=candidates, is_material=is_material, source_status=source_status,
                source_blocking=True,
            )
        elif candidates:
            ac_profile = AttributionConfidenceEngine.compute_profile(
                ranked_drivers=candidates, is_material=is_material, source_status=source_status,
                source_blocking=False,
                causal_verification=causal_verification if causal_design_approved else None,
                corroboration_by_driver=corroboration_by_driver,
            )
            ac_by_id = {item["driver_id"]: item for item in ac_profile["drivers"]}
            for candidate in candidates:
                record = ac_by_id.get(candidate.get("driver_id"))
                if record is None:
                    continue
                candidate.update({
                    "attribution_confidence": record["attribution_confidence"],
                    "band": record["band"],
                    "label": record["label"],
                    "prior": record["prior"],
                    "evidence": record["evidence"],
                    "caps_applied": record["caps_applied"],
                    "model_version": record["model_version"],
                    "calibration": record["calibration"],
                })
            top_driver_id = ac_profile.get("top_driver_id")
            scored = [item for item in ac_profile["drivers"] if item.get("attribution_confidence") is not None]
            band_to_status = {"HIGH": "HIGH", "MODERATE": "MODERATE", "LOW": "LOW", "VERY_LOW": "INSUFFICIENT_EVIDENCE"}
            if scored:
                top = scored[0]
                attribution_status = band_to_status.get(top["band"], "INSUFFICIENT_EVIDENCE")
                if ac_profile["attribution_status"] == "AMBIGUOUS":
                    attribution_status = "LOW"
                elif ac_profile["attribution_status"] == "NO_CONFIDENT_DRIVER":
                    attribution_status = "INSUFFICIENT_EVIDENCE"
                attribution_reasons.append(
                    f"{top.get('display_name', top.get('driver_id'))} is the top-ranked driver with Attribution "
                    f"Confidence {top['attribution_confidence'] * 100:.0f}% ({top['label']})."
                )
                if ac_profile["attribution_status"] == "AMBIGUOUS":
                    attribution_limits.append(
                        "Two or more drivers have similar Attribution Confidence; attribution is ambiguous."
                    )
                if top.get("caps_applied"):
                    attribution_limits.append(
                        "The top driver's Attribution Confidence is capped: "
                        + "; ".join(cap["reason"] for cap in top["caps_applied"])
                    )
            else:
                attribution_status = "INSUFFICIENT_EVIDENCE"
                attribution_reasons.append("No ranked driver had sufficient history to compute Attribution Confidence.")
            attribution_limits.extend(driver_analysis.get("limitations") or [])
        elif exclusions:
            attribution_status = "INSUFFICIENT_EVIDENCE"
            attribution_reasons.append("No candidate driver passed its configured checks; exclusions are retained below.")
            attribution_limits.extend(driver_analysis.get("limitations") or [])
        else:
            attribution_status = "NOT_ASSESSED" if not movement else "INSUFFICIENT_EVIDENCE"
            attribution_reasons.append("No ranked driver evidence was produced for this run.")

        attribution_dimension = dimension(
            attribution_status, "ATTRIBUTION_CONFIDENCE_V1",
            {
                "candidates": candidates,
                "exclusions": exclusions,
                "driver_analysis": driver_analysis,
                "source_coverage": result.get("source_coverage"),
                "missingness_denominator": None,
                "driver_source_inventory": driver_source_inventory,
                "attribution_confidence_profile": ac_profile,
            },
            attribution_reasons, attribution_limits,
            applicable=bool(driver_analysis) or source_blocking,
            blocking=source_blocking,
            evidence_refs=["driver_analysis.ranked_drivers", "driver_analysis.excluded_drivers", "attribution_confidence"] if driver_analysis else [],
        )

        causal_reasons = [causal_verification.get("reason") or "No approved causal design was evaluated."]
        causal_limits: list[str] = []
        targets_top_driver = bool(
            causal_design_approved and top_driver_id
            and causal_verification.get("driver_id") == top_driver_id
        )
        top_driver_causal_rejected = False
        if source_blocking:
            causal_status = "CONFLICTING_EVIDENCE"
            causal_reasons = ["Causal claims are blocked by contradictory source evidence."]
        elif not causal_design_approved:
            causal_status = "NOT_ASSESSED"
            causal_reasons = ["No approved, authorized server-side causal design exists for this run."]
            causal_limits.append("Correlation and accounting decomposition do not establish operational causality.")
        else:
            verdict = causal_verification.get("verdict")
            sensitivity = causal_verification.get("sensitivity_status")
            if verdict == "UNTESTABLE":
                # A design was authorized and the verifier ran; UNTESTABLE
                # means it could not be evaluated for a substantive reason
                # (e.g. insufficient exposure), which is weaker evidence than
                # "no design was ever supplied" (NO_DESIGN -> NOT_ASSESSED).
                causal_status = "NOT_ASSESSED" if reason_code == "NO_DESIGN" else "INSUFFICIENT_EVIDENCE"
            else:
                causal_status = {
                    "SUPPORTED_CONDITIONAL": "MODERATE" if sensitivity == "SENSITIVE" else "HIGH",
                    "INCONCLUSIVE": "LOW",
                    "REJECTED": "CONFLICTING_EVIDENCE",
                }.get(verdict, "NOT_ASSESSED")
            if causal_status == "HIGH":
                causal_limits.append("Approved observational diagnostics are supportive; this is not proof of causality.")
            elif causal_status == "MODERATE":
                causal_limits.append("Observational design support is conditional and is not proof of causality.")
            elif causal_status == "CONFLICTING_EVIDENCE" and targets_top_driver:
                top_driver_causal_rejected = True
            if not targets_top_driver and candidates:
                # Plan §7.2: the causal dimension counts toward the overall
                # explanation only when it targets the top-ranked driver, so
                # a rejected test on a minor driver never poisons confidence
                # in a different, well-explained top driver.
                causal_reasons.append(
                    "This design does not target the top-ranked driver, so it does not count toward the overall conclusion."
                )
        if not source_blocking and reason_code in {"CONTROL_NOT_AUTHORIZED", "TREATMENT_SLICE_MISMATCH", "UNDECLARED_DRIVER", "FUTURE_POST_PERIOD"}:
            causal_status = "NOT_ASSESSED"
            causal_limits.append("Design authorization or scope validation did not pass.")
        causal_required = causal_status != "NOT_ASSESSED" and (targets_top_driver or not candidates)
        causal_inputs = {
            "approved_design": causal_design_approved,
            "top_driver_id": top_driver_id,
            "targets_top_driver": targets_top_driver,
            "counts_toward_overall": causal_required,
            "treatment_authorized": result.get("verdict") != "ACCESS_DENIED",
            "control_authorized": causal_design_approved and reason_code != "CONTROL_NOT_AUTHORIZED",
            "source_conflict_check_passed": not source_blocking,
            "reason_code": reason_code,
            "method": causal_verification.get("method"),
            "pre_days": causal_verification.get("pre_days"),
            "post_days": causal_verification.get("post_days"),
            "outcome_window_coverage": (legacy_confidence.get("sub_scores") or {}).get("outcome_window_coverage"),
            "temporal_precedence_passed": causal_verification.get("temporal_precedence_passed"),
            "pretrend_slope": causal_verification.get("pretrend_slope"),
            "pretrend_p_value": causal_verification.get("pretrend_p_value"),
            "pre_event_shift": causal_verification.get("pre_event_shift"),
            "placebo_effects": causal_verification.get("placebo_effects"),
            "driver_exposure_effect": causal_verification.get("driver_exposure_effect"),
            "driver_exposure_periods": causal_verification.get("driver_exposure_periods"),
            "effect": causal_verification.get("did_effect"),
            "interval": causal_verification.get("confidence_interval"),
            "interval_precision_diagnostic": (legacy_confidence.get("sub_scores") or {}).get("did_interval_precision"),
            "diagnostic_status": legacy_confidence.get("status"),
        }
        causal_dimension = dimension(
            causal_status, causal_verification.get("method", "APPROVED_DESIGN_DIAGNOSTICS"),
            causal_inputs, causal_reasons, causal_limits,
            applicable=causal_design_approved or source_blocking,
            blocking=source_blocking,
            evidence_refs=["causal_verification", "confidence"] if causal_verification or legacy_confidence else [],
        )

        dimensions = {
            "movement": movement_dimension,
            "source": source_dimension,
            "attribution": attribution_dimension,
            "causal": causal_dimension,
        }
        blocking_dimensions = [name for name, item in dimensions.items() if item["blocking"]]

        other_driver_ge_06 = any(
            item.get("driver_id") != top_driver_id and (item.get("attribution_confidence") or 0) >= 0.6
            for item in ac_profile.get("drivers", [])
        )
        conflicting_override = source_blocking or (top_driver_causal_rejected and not other_driver_ge_06)

        movement_conclusion = _weakest(movement_status, source_status)
        explanation_conclusion = _weakest(
            movement_status, source_status, attribution_status,
            causal_status if causal_required else None,
        )

        if conflicting_override:
            overall_status = "CONFLICTING_EVIDENCE"
            if source_blocking:
                overall_reasons = ["A blocking source contradiction takes precedence over other dimension statuses."]
            else:
                overall_reasons = [
                    "The top-ranked driver's causal test was rejected and no alternative driver reaches "
                    "Attribution Confidence >= 60%."
                ]
        else:
            overall_status = explanation_conclusion if is_material else movement_conclusion
            if overall_status == "INSUFFICIENT_EVIDENCE":
                overall_reasons = ["A required evidence dimension is insufficient; abstain from a stronger conclusion."]
            elif overall_status == "LOW":
                overall_reasons = ["At least one required evidence dimension has a failed or limited gate."]
            elif not causal_required:
                overall_reasons = [
                    "Movement, source and attribution evidence are assessed, but no approved causal design "
                    "supports a causal conclusion for the top driver."
                ]
            elif overall_status == "HIGH":
                overall_reasons = ["Every required evidence dimension, including a supportive causal test, reached HIGH."]
            else:
                overall_reasons = ["Conclusion follows the weakest required evidence dimension; it is not an averaged score."]

        return {
            "version": "1.0",
            "evaluated_at": evaluated_at,
            "overall": {
                "status": overall_status,
                "method": "WEAKEST_REQUIRED_DIMENSION_V1",
                "reasons": overall_reasons,
                "blocking_dimensions": blocking_dimensions,
                "movement_conclusion": movement_conclusion,
                "explanation_conclusion": explanation_conclusion,
            },
            "attribution_status": ac_profile.get("attribution_status", "NOT_ASSESSED"),
            "attribution_confidence": ac_profile.get("drivers", []) + (
                [ac_profile["unexplained"]] if ac_profile.get("unexplained") else []
            ),
            **dimensions,
            "driver": attribution_dimension,
        }
