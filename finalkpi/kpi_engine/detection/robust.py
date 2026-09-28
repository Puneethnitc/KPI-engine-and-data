# IMPLEMENTATION HANDOFF — primary movement detector
# Current (Stage 2, F-D1/F-D3): expected value is a same-weekday median (last
# 8 weeks, weekday-adjusted-median fallback); point/sustained scores are
# log(actual/expected) over a log-residual MAD scale (log(value / that
# weekday's median)), not a plain difference -- this dataset's noise is
# proportional, not additive, and a pooled absolute-residual MAD read weekend
# false positives as noisier than they really are in relative terms.
# Materiality requires abs_threshold AND rel_threshold (F-D3). Falls back to a
# linear residual only when a value is non-positive (log undefined).
# Next: resolve comparison window, coverage/calendar, sustained window and static
# baseline policy separately. Consume a prepared series and shared baseline plan.
# Keep MAD/IQR scaling constants as method math; define unit-aware scale floors.
# Check: tiny-scale ratios, constant-to-step changes, missing segment-days,
# irregular calendars, and seasonal changes. Alert thresholds are heuristic
# robust-score cutoffs, not calibrated p-values or false-positive guarantees.

"""One rolling robust-baseline detector for point and sustained KPI movement."""

import numpy as np
import pandas as pd
from typing import Any, Dict, Optional

from kpi_engine.contracts.metrics import (
    ComparisonPlan,
    daily_values,
    linear_weekday_adjusted_residuals,
    same_weekday_expected,
    weekday_adjusted_residuals,
)
from kpi_engine.detection.models import DetectionPolicy, MovementAssessment

class RobustBaselineDetector:
    """Rolling robust baseline for isolated and sustained movements.

    The runtime method remains one robust score with MAD, IQR, then standard
    deviation as scale fallbacks. It evaluates the target observation and a
    recent-window median against earlier history. No STL fit or future data is
    used. Thresholds must be calibrated before decision use.
    """

    default_policy = DetectionPolicy()

    @staticmethod
    def resolve_policy(policy: Optional[DetectionPolicy] = None, contract: Optional[Any] = None) -> DetectionPolicy:
        if policy is not None:
            if hasattr(policy, "validate"):
                policy.validate()
            return policy
        fallback = DetectionPolicy(
            min_history_periods=int(getattr(contract, "min_history_periods", DetectionPolicy.min_history_periods)) if contract is not None else DetectionPolicy.min_history_periods,
            min_compared_days=DetectionPolicy.min_compared_days,
            sustained_window_days=int(getattr(contract, "seasonal_period", DetectionPolicy.sustained_window_days)) if contract is not None else DetectionPolicy.sustained_window_days,
        )
        if hasattr(fallback, "validate"):
            fallback.validate()
        return fallback

    @staticmethod
    def calculate_robust_dispersion(series: pd.Series) -> tuple[float, float, str]:
        """Calculates expected baseline and dispersion using resilient fallbacks."""
        median = float(series.median())
        mad = float(np.median(np.abs(series - median)))
        
        # Tier 1: MAD
        if mad >= 1e-4:
            return median, 1.4826 * mad, "MAD"

        # Tier 2 Fallback: Interquartile Range (IQR)
        q75, q25 = np.percentile(series, [75, 25])
        iqr = (q75 - q25) / 1.349
        if iqr >= 1e-4:
            return median, float(iqr), "IQR"

        # Tier 3 Fallback: Standard Deviation
        std = float(series.std())
        if std >= 1e-4:
            return float(series.mean()), std, "STD"

        # Tier 4 Fallback: Zero Variance Baseline
        return median, float("nan"), "STATIC_ZERO_VAR"

    def evaluate_movement(
        self,
        df: pd.DataFrame,
        kpi_contract: Any,
        target_date: str,
        dimension_slice: Optional[Dict[str, str]] = None,
        metric_col: str = 'net_sales_revenue',
        window_days: int = 90,
        comparison_plan: Optional[ComparisonPlan] = None,
        policy: Optional[DetectionPolicy] = None,
    ) -> MovementAssessment:
        resolved_policy = self.resolve_policy(policy, kpi_contract)
        filtered_df = df.copy()

        if dimension_slice:
            for col, val in dimension_slice.items():
                if col not in filtered_df.columns:
                    raise ValueError(f"Unknown dimension: {col}")
                filtered_df = filtered_df[filtered_df[col] == val]

        if kpi_contract is None or metric_col != kpi_contract.kpi_id:
            raise ValueError("Detection requires a matching KPI contract")

        filtered_df['date'] = pd.to_datetime(filtered_df['date'])
        daily_series = daily_values(filtered_df, kpi_contract)
        precision = 6 if kpi_contract.aggregation != "sum" else 2

        min_history_periods = kpi_contract.min_history_periods
        effective_window_days = max(window_days, min_history_periods)
        target_dt = pd.to_datetime(target_date)

        if comparison_plan is not None:
            target_dt = comparison_plan.target_date
            baseline = comparison_plan.baseline_series if comparison_plan.baseline_series is not None else daily_values(comparison_plan.baseline_frame, kpi_contract)
            if target_dt not in daily_series.index:
                daily_series = daily_series.reindex(pd.Index([target_dt], name='date'))
        else:
            baseline = daily_series[
                (daily_series.index < target_dt) &
                (daily_series.index >= target_dt - pd.Timedelta(days=effective_window_days))
            ].dropna()

        if target_dt not in daily_series.index:
            return MovementAssessment(
                target_date=target_date, actual_value=None, expected_value=None,
                delta=None, z_score=None, mad_score=None,
                is_statistically_significant=False, is_business_material=False, is_material=False,
                status="NO_DATA_FOR_DATE",
                policy=resolved_policy,
            )

        actual_val = float(daily_series.loc[target_dt])
        if not np.isfinite(actual_val):
            return MovementAssessment(
                target_date=target_date, actual_value=None, expected_value=None,
                delta=None, z_score=None, mad_score=None,
                is_statistically_significant=False, is_business_material=False,
                is_material=False, status="NO_DATA_FOR_DATE",
                policy=resolved_policy,
            )

        # Sparse-history / cold-start gate (was previously unimplemented --
        # a 30-day-old product like Beauty would silently get a "normal"
        # assessment off ~20 days of data instead of an honest abstention).
        if len(baseline) < min_history_periods:
            return MovementAssessment(
                target_date=target_date,
                actual_value=round(actual_val, precision),
                expected_value=None,
                delta=None, z_score=None, mad_score=None,
                is_statistically_significant=False, is_business_material=False, is_material=False,
                status="INSUFFICIENT_HISTORY", baseline_count=int(len(baseline)),
                policy=resolved_policy,
            )

        # Stage 2 (F-D1): the expected value is the median of the same weekday
        # over the last k=8 weeks (falling back to a weekday-adjusted median
        # with too few same-weekday points), not the arithmetic mean of every
        # baseline day regardless of weekday. A comparison_plan's expected
        # value is reused as-is so detection and decomposition (pipeline.py)
        # never disagree about what "expected" means for this run.
        if comparison_plan is not None and comparison_plan.expected_value is not None:
            expected_val = comparison_plan.expected_value
            expected_method = comparison_plan.expected_method
        else:
            expected_val, expected_method = same_weekday_expected(baseline, target_dt)
        if expected_val is None or not np.isfinite(expected_val):
            score_center, _, method_used = self.calculate_robust_dispersion(baseline)
            return MovementAssessment(
                target_date=target_date, actual_value=round(actual_val, precision),
                expected_value=None, delta=None, z_score=None, mad_score=None,
                is_statistically_significant=False, is_business_material=False,
                is_material=False, status="UNSCORABLE_BASELINE",
                dispersion_method=method_used, baseline_count=int(len(baseline)),
                baseline_center=round(score_center, precision),
                policy=resolved_policy,
            )
        delta = actual_val - expected_val

        # Stage 2 (F-D1, review fix): scale is the robust MAD of log-ratio
        # weekday-adjusted residuals (log(value / that weekday's median)),
        # not a plain difference. This dataset's noise is proportional --
        # roughly a flat ~10% regardless of a weekday's absolute level, not
        # a flat absolute amount -- so a pooled absolute-residual MAD reads
        # weekends (a higher baseline) as noisier than they really are in
        # relative terms, which pushed false alarms onto Fri/Sat/Sun. Scoring
        # in log space fixes that. Falls back to a linear (additive) residual
        # only when the target or expected value is not strictly positive
        # (log undefined), e.g. a KPI that can be exactly 0.
        log_scoring = actual_val > 0 and expected_val > 0
        if log_scoring:
            residuals = weekday_adjusted_residuals(baseline)
            score_numerator = float(np.log(actual_val) - np.log(expected_val))
        else:
            residuals = linear_weekday_adjusted_residuals(baseline)
            score_numerator = delta
        score_center, dispersion_val, method_used = self.calculate_robust_dispersion(residuals)

        if not np.isfinite(dispersion_val) or dispersion_val <= 0:
            return MovementAssessment(
                target_date=target_date, actual_value=round(actual_val, precision),
                expected_value=round(expected_val, precision), delta=round(delta, precision),
                z_score=None, mad_score=None,
                is_statistically_significant=False, is_business_material=False,
                is_material=False, status="UNSCORABLE_BASELINE",
                dispersion_method=method_used, baseline_count=int(len(baseline)),
                baseline_center=round(score_center, precision),
                policy=resolved_policy,
            )

        # Decisions use full-precision scores; rounding is only for the payload.
        point_score = score_numerator / dispersion_val
        sustained_score = None
        recent_days = kpi_contract.seasonal_period
        if recent_days >= 4 and len(residuals) - (recent_days - 1) >= 14:
            recent_residuals = pd.concat([
                residuals.iloc[-(recent_days - 1):],
                pd.Series([score_numerator], index=[target_dt]),
            ])
            sustained_score = float(recent_residuals.median()) / dispersion_val

        std_val = float(baseline.std())
        z_score = round(delta / std_val, 4) if std_val > 1e-6 else None

        # BUGFIX: KPIContract stores thresholds nested under `.materiality`,
        # not as flat attributes. The old getattr(kpi_contract, 'z_threshold', ...)
        # always missed and silently used the hardcoded default -- the governed
        # YAML thresholds were never actually applied.
        materiality = kpi_contract.materiality
        stat_threshold = materiality.z_threshold
        business_threshold = materiality.abs_threshold
        rel_threshold = materiality.rel_threshold
        rel_delta = delta / abs(expected_val) if expected_val not in (None, 0) else None

        sustained_hit = (
            sustained_score is not None
            and abs(sustained_score) >= stat_threshold
            and np.sign(sustained_score) == np.sign(delta)
        )
        point_hit = abs(point_score) >= stat_threshold
        is_stat_sig = bool(point_hit or sustained_hit)
        # Stage 2 (F-D3): materiality now requires the absolute floor AND a
        # slice-relative gate (when the contract declares one), so a small
        # segment's tiny absolute change and a large segment's proportionally
        # tiny change are both filtered out.
        rel_hit = rel_threshold <= 0 or (rel_delta is not None and abs(rel_delta) >= rel_threshold)
        is_biz_mat = bool(abs(delta) >= business_threshold and rel_hit)
        is_material_dual = bool(is_stat_sig and is_biz_mat)
        pattern = "SUSTAINED" if sustained_hit else "POINT" if point_hit else "NONE"

        return MovementAssessment(
            target_date=target_date,
            actual_value=round(actual_val, precision),
            expected_value=round(expected_val, precision),
            delta=round(delta, precision),
            z_score=z_score,
            mad_score=round(point_score, 4),
            is_statistically_significant=is_stat_sig,
            is_business_material=is_biz_mat,
            is_material=is_material_dual,
            status="OK",
            dispersion_method=method_used,
            pattern=pattern,
            baseline_count=int(len(baseline)),
            baseline_center=round(score_center, precision),
            baseline_scale=round(dispersion_val, 6),
            robust_score=round(point_score, 4),
            sustained_score=round(sustained_score, 4) if sustained_score is not None else None,
            expected_method=expected_method,
            rel_delta=round(rel_delta, 6) if rel_delta is not None else None,
            rel_threshold=rel_threshold if rel_threshold > 0 else None,
            policy=resolved_policy,
        )
