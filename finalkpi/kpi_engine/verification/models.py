"""Explicit event design and structured causal-check result."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class VerificationDesign:
    driver_id: str
    treated_slice: dict[str, str]
    control_slice: dict[str, str]
    pre_start: str
    treatment_start: str
    post_end: str
    quiet_windows: tuple[tuple[str, str], ...]
    expected_outcome_direction: Optional[int] = None  # -1 or +1, predeclared
    expected_driver_direction: Optional[int] = None  # -1 or +1, predeclared


@dataclass(frozen=True)
class CausalVerificationResult:
    driver_id: str
    verdict: str  # SUPPORTED_CONDITIONAL | REJECTED | INCONCLUSIVE | UNTESTABLE
    reason_code: str
    reason: str
    did_effect: Optional[float] = None
    driver_exposure_effect: Optional[float] = None
    driver_exposure_periods: int = 0
    confidence_interval: Optional[tuple[float, float]] = None
    pretrend_slope: Optional[float] = None
    pretrend_p_value: Optional[float] = None
    pre_event_shift: Optional[float] = None
    placebo_effects: tuple[float, ...] = ()
    pre_days: int = 0
    post_days: int = 0
    temporal_precedence_passed: Optional[bool] = None
    method: str = "daily_gap_did_hac_placebo"


@dataclass(frozen=True)
class VerificationSensitivityResult:
    """Predeclared-design robustness, never a causal probability."""

    status: str  # CONSISTENT_CONDITIONAL | SENSITIVE | UNTESTABLE
    results: tuple[CausalVerificationResult, ...]
    design_count: int
