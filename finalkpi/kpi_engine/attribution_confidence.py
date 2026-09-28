# IMPLEMENTATION HANDOFF — per-driver Attribution Confidence (Stage 7, F-C1/F-C2)
# Current: an evidence-weighted log-odds model (naive-Bayes style) turns each
# ranked driver's explained share, movement strength, direction, precedence,
# stability, statistical support, causal verdict, corroboration and data
# quality into a single AC in [0, 1], with hard caps applied after the
# sigmoid and recorded in caps_applied. Weights live in
# kpi_engine/models/attribution_confidence_v1.yaml (Plan §7.1 table);
# --calibrate on tests/run_ground_truth_eval.py refits them on dev only.
# Next: a real v2 calibration file from logistic regression on labelled runs
# (dev-fit only; report holdout Brier honestly).
# Check: no causal test caps AC at 0.75; a REJECTED causal test caps at 0.20;
# corroboration must never lower AC when it is CORROBORATED or absent; caps
# are applied to the sigmoid output, never folded into the logit sum.

"""Attribution Confidence (AC): the probability a driver caused a material
share (>= 20% of ΔKPI) of a diagnosed movement, from a transparent
evidence-weighted log-odds model. Not a calibrated causal probability until
validated against labelled outcomes; see calibration_status in the model."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

MODEL_DIR = Path(__file__).resolve().parent / "models"
BAND_ORDER = ("HIGH", "MODERATE", "LOW", "VERY_LOW", "EXPLORATORY")


def _logit(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


@dataclass(frozen=True)
class AttributionConfidenceModel:
    version: str
    calibration_status: str
    weights: dict[str, float]
    caps: dict[str, float]
    bands: dict[str, dict[str, Any]]
    thresholds: dict[str, float]
    path: Optional[Path] = None

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AttributionConfidenceModel":
        resolved = path or (MODEL_DIR / "attribution_confidence_v1.yaml")
        with open(resolved) as handle:
            data = yaml.safe_load(handle)
        return cls(
            version=data["version"],
            calibration_status=data.get("calibration_status", "HAND_SET_PRIOR"),
            weights=dict(data["weights"]),
            caps=dict(data["caps"]),
            bands=dict(data["bands"]),
            thresholds=dict(data["thresholds"]),
            path=resolved,
        )

    def band_for(self, ac: float) -> tuple[str, str]:
        for name in BAND_ORDER:
            spec = self.bands[name]
            if ac >= spec["min"]:
                return name, spec["label"]
        very_low = self.bands["VERY_LOW"]
        return "VERY_LOW", very_low["label"]


_DEFAULT_MODEL: Optional[AttributionConfidenceModel] = None


def default_model() -> AttributionConfidenceModel:
    global _DEFAULT_MODEL
    if _DEFAULT_MODEL is None:
        _DEFAULT_MODEL = AttributionConfidenceModel.load()
    return _DEFAULT_MODEL


class AttributionConfidenceEngine:
    """Evidence-weighted log-odds model producing per-driver AC (Plan §7.1)."""

    @staticmethod
    def prior(eligible_moved_driver_count: int, override: Optional[float] = None) -> float:
        if override is not None:
            return float(override)
        return 1.0 / (max(0, int(eligible_moved_driver_count)) + 1)

    #: Every named weight key in the model file, in a stable order -- the
    #: feature columns `--calibrate` (tests/run_ground_truth_eval.py) fits.
    WEIGHT_KEYS = (
        "E1_explained_share", "E1_explained_share_low_penalty",
        "E2_moved_strong", "E2_moved_moderate", "E2_moved_weak_penalty",
        "E3_direction_consistent", "E3_direction_conflict",
        "E4_precedence_before", "E4_precedence_after_penalty",
        "E5_stability_stable", "E5_stability_sensitive",
        "E6_pvalue_strong", "E6_pvalue_moderate", "E6_pvalue_weak_penalty",
        "E7_causal_supported_consistent", "E7_causal_supported_sensitive",
        "E7_causal_inconclusive", "E7_causal_rejected",
        "E8_corroborated", "E8_contradicted",
        "E9_coverage_penalty", "E9_source_low_penalty",
    )

    @staticmethod
    def feature_activations(
        driver: dict[str, Any],
        *,
        causal_result: Optional[dict[str, Any]] = None,
        corroboration: Optional[dict[str, Any]] = None,
        source_status: Optional[str] = None,
        model: Optional[AttributionConfidenceModel] = None,
    ) -> dict[str, float]:
        """The raw per-weight-key activation for one driver: 0/1 for the
        binary evidence branches, and the continuous multiplier for E1's
        explained-share term. `logit(AC) - logit(prior) == sum(activation *
        weight)` for every weight key -- this is exactly the feature matrix
        `--calibrate` fits new weights against (Plan §7.1's "starting from
        the hand weights above as priors")."""
        model = model or default_model()
        w = model.weights
        features = {key: 0.0 for key in AttributionConfidenceEngine.WEIGHT_KEYS}

        explained_share = driver.get("explained_share")
        if explained_share is not None:
            s_d = max(0.0, min(1.5, float(explained_share)))
            features["E1_explained_share"] = min(s_d, 1.0)
            if s_d < w["E1_explained_share_low_threshold"]:
                features["E1_explained_share_low_penalty"] = 1.0

        driver_z = driver.get("driver_change_z")
        if driver_z is not None:
            abs_z = abs(float(driver_z))
            if abs_z >= w["E2_moved_strong_threshold"]:
                features["E2_moved_strong"] = 1.0
            elif abs_z >= w["E2_moved_moderate_threshold"]:
                features["E2_moved_moderate"] = 1.0
            elif abs_z < w["E2_moved_weak_threshold"]:
                features["E2_moved_weak_penalty"] = 1.0

        direction_consistent = driver.get("direction_consistent")
        expected_direction = driver.get("expected_direction")
        if expected_direction is not None:
            if direction_consistent:
                features["E3_direction_consistent"] = 1.0
            else:
                features["E3_direction_conflict"] = 1.0

        lag_days = driver.get("lag_days")
        if lag_days is not None:
            if lag_days > 0:
                features["E4_precedence_before"] = 1.0
            elif lag_days < 0:
                features["E4_precedence_after_penalty"] = 1.0

        stability_status = driver.get("stability_status")
        if stability_status == "STABLE":
            features["E5_stability_stable"] = 1.0
        elif stability_status == "SENSITIVE":
            features["E5_stability_sensitive"] = 1.0

        p_value_adj = driver.get("p_value_adj")
        if p_value_adj is not None:
            if p_value_adj < w["E6_pvalue_strong_threshold"]:
                features["E6_pvalue_strong"] = 1.0
            elif p_value_adj < w["E6_pvalue_moderate_threshold"]:
                features["E6_pvalue_moderate"] = 1.0
            elif p_value_adj >= w["E6_pvalue_weak_threshold"]:
                features["E6_pvalue_weak_penalty"] = 1.0

        causal_verdict = (causal_result or {}).get("verdict") if causal_result else None
        causal_sensitivity = (causal_result or {}).get("sensitivity_status") if causal_result else None
        if causal_verdict == "SUPPORTED_CONDITIONAL":
            if causal_sensitivity == "SENSITIVE":
                features["E7_causal_supported_sensitive"] = 1.0
            else:
                features["E7_causal_supported_consistent"] = 1.0
        elif causal_verdict == "INCONCLUSIVE":
            features["E7_causal_inconclusive"] = 1.0
        elif causal_verdict == "REJECTED":
            features["E7_causal_rejected"] = 1.0

        corroboration_status = (corroboration or {}).get("status") if corroboration else None
        if corroboration_status == "CORROBORATED":
            features["E8_corroborated"] = 1.0
        elif corroboration_status == "CONTRADICTED":
            features["E8_contradicted"] = 1.0

        coverage_ratio = driver.get("coverage_ratio")
        if coverage_ratio is not None and coverage_ratio < w["E9_coverage_threshold"]:
            features["E9_coverage_penalty"] = 1.0
        if source_status == "LOW":
            features["E9_source_low_penalty"] = 1.0

        return features

    @staticmethod
    def compute_driver(
        driver: dict[str, Any],
        *,
        prior: float,
        is_material: bool,
        source_status: str,
        causal_result: Optional[dict[str, Any]] = None,
        corroboration: Optional[dict[str, Any]] = None,
        model: Optional[AttributionConfidenceModel] = None,
    ) -> dict[str, Any]:
        """Compute AC for one ranked driver dict (attribution.py's
        _candidate_to_dict shape). Returns the full per-driver AC record;
        callers gate SOURCE_CONTRADICTED / INSUFFICIENT_HISTORY before
        calling this (AC is then not computed at all, per Plan §7.1)."""
        model = model or default_model()
        w = model.weights
        evidence: list[dict[str, Any]] = []
        logit_ac = _logit(prior)

        def add(item_id: str, name: str, value: Any, weight: float, note: Optional[str] = None, **extra: Any) -> None:
            nonlocal logit_ac
            logit_ac += weight
            entry: dict[str, Any] = {
                "id": item_id, "name": name, "value": value,
                "weight_contribution": round(weight, 4),
            }
            if note:
                entry["note"] = note
            entry.update(extra)
            evidence.append(entry)

        # E1 explained share
        explained_share = driver.get("explained_share")
        if explained_share is not None:
            s_d = max(0.0, min(1.5, float(explained_share)))
            weight = w["E1_explained_share"] * min(s_d, 1.0)
            note = f"Explains {s_d * 100:.0f}% of the movement"
            if s_d < w["E1_explained_share_low_threshold"]:
                weight += w["E1_explained_share_low_penalty"]
                note += " (below the material-share threshold)"
            add("E1", "explained_share", round(s_d, 4), weight, note)
        else:
            add("E1", "explained_share", None, 0.0, "Explained share unavailable")

        # E2 driver actually moved
        driver_z = driver.get("driver_change_z")
        if driver_z is not None:
            abs_z = abs(float(driver_z))
            if abs_z >= w["E2_moved_strong_threshold"]:
                weight, note = w["E2_moved_strong"], f"Driver moved strongly (|z|={abs_z:.2f})"
            elif abs_z >= w["E2_moved_moderate_threshold"]:
                weight, note = w["E2_moved_moderate"], f"Driver moved moderately (|z|={abs_z:.2f})"
            elif abs_z < w["E2_moved_weak_threshold"]:
                weight, note = w["E2_moved_weak_penalty"], f"Driver barely moved (|z|={abs_z:.2f})"
            else:
                weight, note = 0.0, f"Driver moved (|z|={abs_z:.2f})"
            add("E2", "driver_moved", round(abs_z, 4), weight, note)
        else:
            add("E2", "driver_moved", None, 0.0, "Driver movement magnitude unavailable")

        # E3 direction consistent with contract
        direction_consistent = driver.get("direction_consistent")
        expected_direction = driver.get("expected_direction")
        if expected_direction is None:
            add("E3", "direction_consistency", None, 0.0, "No expected hypothesis direction is declared")
        elif direction_consistent:
            add("E3", "direction_consistency", True, w["E3_direction_consistent"], "Beta sign matches the declared hypothesis")
        else:
            add("E3", "direction_consistency", False, w["E3_direction_conflict"], "Beta sign conflicts with the declared hypothesis")

        # E4 temporal precedence
        lag_days = driver.get("lag_days")
        if lag_days is None:
            add("E4", "temporal_precedence", None, 0.0, "Lag is unavailable")
        elif lag_days > 0:
            add("E4", "temporal_precedence", "BEFORE", w["E4_precedence_before"], f"Driver moved {lag_days} day(s) before the KPI")
        elif lag_days == 0:
            add("E4", "temporal_precedence", "COINCIDENT", 0.0, "Driver and KPI moved on the same day")
        else:
            add("E4", "temporal_precedence", "AFTER", w["E4_precedence_after_penalty"], "Driver moved after the KPI")

        # E5 stability (disjoint halves)
        stability_status = driver.get("stability_status")
        if stability_status == "STABLE":
            add("E5", "stability", "STABLE", w["E5_stability_stable"], "Beta is stable across disjoint history halves")
        elif stability_status == "SENSITIVE":
            add("E5", "stability", "SENSITIVE", w["E5_stability_sensitive"], "Beta changes materially across disjoint history halves")
        else:
            add("E5", "stability", stability_status, 0.0, "Stability not assessed")

        # E6 statistical support
        p_value_adj = driver.get("p_value_adj")
        if p_value_adj is not None:
            if p_value_adj < w["E6_pvalue_strong_threshold"]:
                weight, note = w["E6_pvalue_strong"], f"Adjusted p-value {p_value_adj:.4f} is strong"
            elif p_value_adj < w["E6_pvalue_moderate_threshold"]:
                weight, note = w["E6_pvalue_moderate"], f"Adjusted p-value {p_value_adj:.4f} is moderate"
            elif p_value_adj >= w["E6_pvalue_weak_threshold"]:
                weight, note = w["E6_pvalue_weak_penalty"], f"Adjusted p-value {p_value_adj:.4f} is weak"
            else:
                weight, note = 0.0, f"Adjusted p-value {p_value_adj:.4f}"
            add("E6", "statistical_support", p_value_adj, weight, note)
        else:
            add("E6", "statistical_support", None, 0.0, "No p-value available (ridge-penalised fit)")

        # E7 causal test (Stage 5)
        causal_verdict = (causal_result or {}).get("verdict") if causal_result else None
        causal_sensitivity = (causal_result or {}).get("sensitivity_status") if causal_result else None
        if causal_verdict == "SUPPORTED_CONDITIONAL":
            if causal_sensitivity == "SENSITIVE":
                weight, note = w["E7_causal_supported_sensitive"], "Causal design supports the driver; sensitive to design choice"
            else:
                weight, note = w["E7_causal_supported_consistent"], "Causal design supports the driver and is consistent"
            add("E7", "causal_test", f"SUPPORTED_CONDITIONAL/{causal_sensitivity or 'CONSISTENT'}", weight, note)
        elif causal_verdict == "INCONCLUSIVE":
            add("E7", "causal_test", "INCONCLUSIVE", w["E7_causal_inconclusive"], "Causal design was inconclusive")
        elif causal_verdict == "REJECTED":
            add("E7", "causal_test", "REJECTED", w["E7_causal_rejected"], "Causal design rejected this driver as a cause")
        else:
            add("E7", "causal_test", causal_verdict or "NOT_RUN", 0.0, "No causal test was run for this driver")

        # E8 unstructured corroboration (Stage 6)
        corroboration_status = (corroboration or {}).get("status") if corroboration else None
        doc_ids = [doc.get("doc_id") for doc in (corroboration or {}).get("documents", [])] if corroboration else []
        if corroboration_status == "CORROBORATED":
            add("E8", "corroboration", "CORROBORATED", w["E8_corroborated"], "Corroborated by unstructured evidence", doc_ids=doc_ids)
        elif corroboration_status == "CONTRADICTED":
            add("E8", "corroboration", "CONTRADICTED", w["E8_contradicted"], "Contradicted by unstructured evidence", doc_ids=doc_ids)
        else:
            add("E8", "corroboration", corroboration_status or "NONE", 0.0, "No corroborating or contradicting evidence found")

        # E9 data quality
        coverage_ratio = driver.get("coverage_ratio")
        e9_weight = 0.0
        e9_notes: list[str] = []
        if coverage_ratio is not None and coverage_ratio < w["E9_coverage_threshold"]:
            e9_weight += w["E9_coverage_penalty"]
            e9_notes.append(f"Coverage ratio {coverage_ratio:.2f} is below {w['E9_coverage_threshold']}")
        if source_status == "LOW":
            e9_weight += w["E9_source_low_penalty"]
            e9_notes.append("Source evidence dimension is LOW")
        add("E9", "data_quality", coverage_ratio, e9_weight, "; ".join(e9_notes) or "No data-quality penalty applied")

        ac_raw = _sigmoid(logit_ac)

        caps_applied: list[dict[str, Any]] = []
        cap_values: list[float] = []
        if not is_material:
            cap_values.append(model.caps["non_material_max"])
            caps_applied.append({"name": "non_material", "max": model.caps["non_material_max"], "reason": "Movement is not material"})
        if causal_verdict == "REJECTED":
            cap_values.append(model.caps["causal_rejected_max"])
            caps_applied.append({"name": "causal_rejected", "max": model.caps["causal_rejected_max"], "reason": "Causal test rejected this driver"})
        elif causal_verdict is None or causal_verdict == "UNTESTABLE":
            cap_values.append(model.caps["no_causal_test_max"])
            caps_applied.append({"name": "no_causal_test", "max": model.caps["no_causal_test_max"], "reason": "No causal test result for this driver"})
        if expected_direction is None:
            cap_values.append(model.caps["direction_undeclared_max"])
            caps_applied.append({"name": "direction_undeclared", "max": model.caps["direction_undeclared_max"], "reason": "No expected hypothesis direction is declared"})

        ac_final = min([ac_raw, *cap_values]) if cap_values else ac_raw
        ac_final = max(0.0, min(1.0, ac_final))

        band, label = model.band_for(ac_final)
        if not is_material and ac_final <= model.caps["non_material_max"]:
            # The 0.5 cap is why this is not just "MODERATE": a driver can
            # clear every material band's evidence and still be capped out,
            # because the movement itself never cleared materiality.
            exploratory = model.bands["EXPLORATORY"]
            band, label = "EXPLORATORY", exploratory["label"]

        return {
            "driver_id": driver.get("driver_id"),
            "display_name": driver.get("display_name", driver.get("driver_id")),
            "attribution_confidence": round(ac_final, 4),
            "band": band,
            "label": label,
            "prior": round(prior, 4),
            "evidence": evidence,
            "caps_applied": caps_applied,
            "model_version": model.version,
            "calibration": {"status": model.calibration_status, "split": None},
        }

    @staticmethod
    def unexplained_row(driver_acs: list[dict[str, Any]], model: Optional[AttributionConfidenceModel] = None) -> dict[str, Any]:
        model = model or default_model()
        max_ac = max((item["attribution_confidence"] for item in driver_acs), default=0.0)
        unexplained_ac = round(max(0.0, min(1.0, 1.0 - max_ac)), 4)
        band, label = model.band_for(unexplained_ac)
        return {
            "driver_id": "unexplained",
            "display_name": "Unexplained residual",
            "attribution_confidence": unexplained_ac,
            "band": band,
            "label": label,
            "prior": None,
            "evidence": [],
            "caps_applied": [],
            "model_version": model.version,
            "calibration": {"status": model.calibration_status, "split": None},
        }

    @classmethod
    def compute_profile(
        cls,
        *,
        ranked_drivers: list[dict[str, Any]],
        is_material: bool,
        source_status: str,
        source_blocking: bool = False,
        causal_verification: Optional[dict[str, Any]] = None,
        causal_verifications: Optional[list[dict[str, Any]]] = None,
        corroboration_by_driver: Optional[dict[str, dict[str, Any]]] = None,
        driver_priors: Optional[dict[str, float]] = None,
        model: Optional[AttributionConfidenceModel] = None,
    ) -> dict[str, Any]:
        """Top-level per-run AC profile: one record per ranked driver, an
        unexplained row, and the ambiguity/no-confident-driver status (Plan
        §7.1, "Ambiguity rule")."""
        model = model or default_model()

        if source_blocking:
            return {
                "model_version": model.version,
                "attribution_status": "BLOCKED",
                "drivers": [],
                "unexplained": None,
                "top_driver_id": None,
            }

        # Every driver that moved is scored, including offsetting ones. An
        # offsetting driver moved against the KPI's direction, which is a
        # statement about it (its E2 movement is large and its E3 direction
        # conflicts), not a reason to leave it unscored: a ranked driver shown
        # with no AC would read as "not assessed" rather than "scored and low".
        movers = [d for d in ranked_drivers if d.get("moved")]
        min_history = model.thresholds["min_history_periods"]
        eligible = [d for d in movers if (d.get("sample_size") or 0) >= min_history]
        sparse = [d for d in movers if d not in eligible]

        corroboration_by_driver = corroboration_by_driver or {}
        driver_priors = driver_priors or {}
        records: list[dict[str, Any]] = []
        causal_by_driver = {
            item.get("driver_id"): item for item in (causal_verifications or [])
            if item.get("driver_id")
        }
        for driver in eligible:
            driver_id = driver.get("driver_id")
            causal_for_driver = causal_by_driver.get(driver_id)
            if causal_for_driver is None and causal_verification and causal_verification.get("driver_id") == driver_id:
                causal_for_driver = causal_verification
            prior = cls.prior(len(eligible), driver_priors.get(driver_id))
            record = cls.compute_driver(
                driver,
                prior=prior,
                is_material=is_material,
                source_status=source_status,
                causal_result=causal_for_driver,
                corroboration=corroboration_by_driver.get(driver_id),
                model=model,
            )
            records.append(record)

        for driver in sparse:
            records.append({
                "driver_id": driver.get("driver_id"),
                "display_name": driver.get("display_name", driver.get("driver_id")),
                "attribution_confidence": None,
                "band": None,
                "label": None,
                "status": "INSUFFICIENT_HISTORY",
                "prior": None,
                "evidence": [],
                "caps_applied": [],
                "model_version": model.version,
                "calibration": {"status": model.calibration_status, "split": None},
            })

        records.sort(key=lambda item: (item["attribution_confidence"] is None, -(item["attribution_confidence"] or 0.0)))
        scored = [item for item in records if item["attribution_confidence"] is not None]
        unexplained = cls.unexplained_row(scored, model=model)

        if not scored:
            attribution_status = "NO_CONFIDENT_DRIVER" if records else "NO_DRIVERS"
            top_driver_id = None
        else:
            top, second = scored[0], (scored[1] if len(scored) > 1 else None)
            top_ac = top["attribution_confidence"]
            top_driver_id = top["driver_id"]
            if top_ac < model.thresholds["no_confident_driver_max_ac"]:
                attribution_status = "NO_CONFIDENT_DRIVER"
            elif (
                second is not None
                and abs(top_ac - second["attribution_confidence"]) <= model.thresholds["ambiguous_gap"]
                and top_ac >= model.thresholds["ambiguous_min_ac"]
                and second["attribution_confidence"] >= model.thresholds["ambiguous_min_ac"]
            ):
                attribution_status = "AMBIGUOUS"
            else:
                attribution_status = "CONFIDENT"

        return {
            "model_version": model.version,
            "attribution_status": attribution_status,
            "drivers": records,
            "unexplained": unexplained,
            "top_driver_id": top_driver_id,
        }
