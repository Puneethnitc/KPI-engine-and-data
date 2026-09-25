# IMPLEMENTATION HANDOFF — movement payload
# Current: one result holds rounded movement, robust/seasonal evidence and policy.
# Next: version this payload to carry unit, comparison-period definition, resolved
# policy, coverage, raw precision and lineage; preserve existing consumer fields.
# Check: unknown values remain null, display rounding never changes decisions,
# and consumers distinguish scoring center from the reported mean baseline.

"""Structured, auditable detection result."""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class DetectionPolicy:
    min_history_periods: int = 30
    min_compared_days: int = 14
    sustained_window_days: int = 7
    scale_floor: float = 1e-4
    variance_floor: float = 1e-4

    def validate(self) -> None:
        if self.min_history_periods <= 0:
            raise ValueError("Detection policy min_history_periods must be positive")
        if self.min_compared_days <= 0:
            raise ValueError("Detection policy min_compared_days must be positive")
        if self.sustained_window_days <= 0:
            raise ValueError("Detection policy sustained_window_days must be positive")
        if self.scale_floor <= 0:
            raise ValueError("Detection policy scale_floor must be positive")
        if self.variance_floor <= 0:
            raise ValueError("Detection policy variance_floor must be positive")

    @classmethod
    def from_mapping(cls, data: Optional[Any]) -> "DetectionPolicy":
        if data is None:
            return cls()
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValueError("Detection policy must be a mapping or DetectionPolicy instance")
        policy = cls(
            min_history_periods=int(data.get("min_history_periods", cls.min_history_periods)),
            min_compared_days=int(data.get("min_compared_days", cls.min_compared_days)),
            sustained_window_days=int(data.get("sustained_window_days", cls.sustained_window_days)),
            scale_floor=float(data.get("scale_floor", cls.scale_floor)),
            variance_floor=float(data.get("variance_floor", cls.variance_floor)),
        )
        policy.validate()
        return policy


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
    policy: Optional[DetectionPolicy] = None
