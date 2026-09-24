"""One rolling robust-baseline detector for point and sustained KPI movement."""

import numpy as np
import pandas as pd
from typing import Any, Dict, Optional

from kpi_engine.contracts.metrics import daily_values
from kpi_engine.detection.models import MovementAssessment

class RobustBaselineDetector:
    """Rolling robust baseline for isolated and sustained movements.

    The runtime method remains one robust score with MAD, IQR, then standard
    deviation as scale fallbacks. It evaluates the target observation and a
    recent-window median against earlier history. No STL fit or future data is
    used. Thresholds must be calibrated before decision use.
    """

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
        window_days: int = 30
    ) -> MovementAssessment:
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

        target_dt = pd.to_datetime(target_date)
        if target_dt not in daily_series.index:
            return MovementAssessment(
                target_date=target_date, actual_value=None, expected_value=None,
                delta=None, z_score=None, mad_score=None,
                is_statistically_significant=False, is_business_material=False, is_material=False,
                status="NO_DATA_FOR_DATE"
            )

        # BUGFIX: window_days must be at least the contract's min_history_periods,
        # or the sparse-history gate below can never be satisfied even for KPIs
        # with plenty of real history (e.g. min_history_periods=60 > window_days=30
        # would falsely mark every net_sales_revenue call as insufficient).
        min_history_periods = kpi_contract.min_history_periods
        effective_window_days = max(window_days, min_history_periods)

        actual_val = float(daily_series.loc[target_dt])
        if not np.isfinite(actual_val):
            return MovementAssessment(
                target_date=target_date, actual_value=None, expected_value=None,
                delta=None, z_score=None, mad_score=None,
                is_statistically_significant=False, is_business_material=False,
                is_material=False, status="NO_DATA_FOR_DATE",
            )

        baseline = daily_series[
            (daily_series.index < target_dt) &
            (daily_series.index >= target_dt - pd.Timedelta(days=effective_window_days))
        ].dropna()

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
            )

        score_center, dispersion_val, method_used = self.calculate_robust_dispersion(baseline)
        # An arithmetic mean is decomposable exactly from mean quantity and
        # weighted mean rate over these same baseline observations.
        expected_val = float(baseline.mean())
        delta = actual_val - expected_val

        if not np.isfinite(dispersion_val) or dispersion_val <= 0:
            return MovementAssessment(
                target_date=target_date, actual_value=round(actual_val, precision),
                expected_value=round(expected_val, precision), delta=round(delta, precision),
                z_score=None, mad_score=None,
                is_statistically_significant=False, is_business_material=False,
                is_material=False, status="UNSCORABLE_BASELINE",
                dispersion_method=method_used, baseline_count=int(len(baseline)),
                baseline_center=round(score_center, precision),
            )

        # Decisions use full-precision scores; rounding is only for the payload.
        point_score = (actual_val - score_center) / dispersion_val
        sustained_score = None
        recent_days = kpi_contract.seasonal_period
        if recent_days >= 4 and len(baseline) - (recent_days - 1) >= 14:
            reference = baseline.iloc[:-(recent_days - 1)]
            recent = pd.concat([baseline.iloc[-(recent_days - 1):],
                                pd.Series([actual_val], index=[target_dt])])
            reference_center, reference_scale, _ = self.calculate_robust_dispersion(reference)
            if np.isfinite(reference_scale) and reference_scale > 0:
                sustained_score = (float(recent.median()) - reference_center) / reference_scale

        std_val = float(baseline.std())
        z_score = round(delta / std_val, 4) if std_val > 1e-6 else None

        # BUGFIX: KPIContract stores thresholds nested under `.materiality`,
        # not as flat attributes. The old getattr(kpi_contract, 'z_threshold', ...)
        # always missed and silently used the hardcoded default -- the governed
        # YAML thresholds were never actually applied.
        materiality = kpi_contract.materiality
        stat_threshold = materiality.z_threshold
        business_threshold = materiality.abs_threshold

        sustained_hit = (
            sustained_score is not None
            and abs(sustained_score) >= stat_threshold
            and np.sign(sustained_score) == np.sign(delta)
        )
        point_hit = abs(point_score) >= stat_threshold
        is_stat_sig = bool(point_hit or sustained_hit)
        is_biz_mat = bool(abs(delta) >= business_threshold)
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
        )
