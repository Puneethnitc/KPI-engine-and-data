# IMPLEMENTATION HANDOFF — event design and results
# Current: caller provides treated/control slices, dates, quiet windows and signed
# hypotheses; results preserve effect, uncertainty and explicit reason codes.
# Next: attach design ID/version, resolved method policy, source/contract lineage,
# unit and period semantics. Persist a design before analysis if claiming it was
# predeclared; the current dataclass cannot prove when the design was chosen.
# Check: direction, scope and periods validate together, sensitivity designs
# test the same hypothesis, and SUPPORTED_CONDITIONAL never becomes causal proof.

"""Explicit event design and structured causal-check result."""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class VerificationPolicy:
    min_pre_days: int = 14
    min_post_days: int = 7
    min_placebo_days: int = 14
    placebo_effect_threshold: float = 0.5
    pre_event_shift_ratio: float = 0.75
    alpha: float = 0.05
    max_hac_lags: int = 7
    quiet_window_count: tuple[int, ...] = (2, 3)

    def validate(self) -> None:
        if self.min_pre_days <= 0:
            raise ValueError("Verification policy min_pre_days must be positive")
        if self.min_post_days <= 0:
            raise ValueError("Verification policy min_post_days must be positive")
        if self.min_placebo_days <= 0:
            raise ValueError("Verification policy min_placebo_days must be positive")
        if not 0 < self.placebo_effect_threshold < 1:
            raise ValueError("Verification policy placebo_effect_threshold must be between 0 and 1")
        if not 0 < self.pre_event_shift_ratio < 1:
            raise ValueError("Verification policy pre_event_shift_ratio must be between 0 and 1")
        if not 0 < self.alpha < 1:
            raise ValueError("Verification policy alpha must be between 0 and 1")
        if self.max_hac_lags <= 0:
            raise ValueError("Verification policy max_hac_lags must be positive")

    @classmethod
    def from_mapping(cls, data: Optional[Any]) -> "VerificationPolicy":
        if data is None:
            return cls()
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValueError("Verification policy must be a mapping or VerificationPolicy instance")
        policy = cls(
            min_pre_days=int(data.get("min_pre_days", cls.min_pre_days)),
            min_post_days=int(data.get("min_post_days", cls.min_post_days)),
            min_placebo_days=int(data.get("min_placebo_days", cls.min_placebo_days)),
            placebo_effect_threshold=float(data.get("placebo_effect_threshold", cls.placebo_effect_threshold)),
            pre_event_shift_ratio=float(data.get("pre_event_shift_ratio", cls.pre_event_shift_ratio)),
            alpha=float(data.get("alpha", cls.alpha)),
            max_hac_lags=int(data.get("max_hac_lags", cls.max_hac_lags)),
            quiet_window_count=tuple(data.get("quiet_window_count", cls.quiet_window_count)),
        )
        policy.validate()
        return policy


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
    policy: Optional[VerificationPolicy] = None


@dataclass(frozen=True)
class VerificationSensitivityResult:
    """Predeclared-design robustness, never a causal probability."""

    status: str  # CONSISTENT_CONDITIONAL | SENSITIVE | UNTESTABLE
    results: tuple[CausalVerificationResult, ...]
    design_count: int
