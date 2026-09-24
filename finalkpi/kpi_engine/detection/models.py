"""Structured, auditable detection result."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class MovementAssessment:
    target_date: str
    actual_value: Optional[float]
    expected_value: Optional[float]
    delta: Optional[float]
    z_score: Optional[float]
    mad_score: Optional[float]  # Backward-compatible name for robust_score.
    is_statistically_significant: bool
    is_business_material: bool
    is_material: bool  # Provisional alert decision: robust branch only.
    status: str = "OK"
    dispersion_method: Optional[str] = None
    method: str = "rolling_robust_baseline"
    pattern: Optional[str] = None  # POINT | SUSTAINED | NONE
    baseline_count: int = 0
    baseline_center: Optional[float] = None
    baseline_scale: Optional[float] = None
    robust_score: Optional[float] = None
    sustained_score: Optional[float] = None
    robust_is_material: bool = False
    seasonal_status: str = "NOT_EVALUATED"
    seasonal_score: Optional[float] = None
    seasonal_expected: Optional[float] = None
    seasonal_is_material: bool = False
    seasonal_calibration_count: int = 0
    detector_agreement: str = "NEITHER"  # BOTH | ROBUST_ONLY | SEASONAL_ONLY | NEITHER
    alert_policy: str = "ROBUST_PRIMARY_SEASONAL_REVIEW"
