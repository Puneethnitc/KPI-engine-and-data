# IMPLEMENTATION HANDOFF — current calculation reference
# Current: aggregate by date using sum, mean, weighted mean or ratio of sums.
# Stage 2 (F-D1) adds same_weekday_expected (the shared expected-value
# calculation for detection and decomposition) and weekday_adjusted_residuals
# (log-ratio residuals for the dispersion scale, with a linear fallback for
# non-positive values). history_days is now max(90, min_history_periods), up
# from 30, so there is enough same-weekday depth.
# Next: keep this as the reference for DuckDB parity, then delegate to one metric
# service shared by detection, ranking and verification. Define temporal rollup
# separately from dimension rollup; a mean of daily means may be inappropriate.
# Missing values currently can produce partial sums. Ratio numerators and
# denominators are summed independently, even with unmatched missing rows.
# Add explicit completeness/paired-input policy before accepting such results.
# Check: unequal denominators/weights, zero denominator, all-null and partially
# null inputs, negative/non-finite inputs, and consistent results across grains.

"""Compute additive and ratio KPI series from source columns."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from kpi_engine.contracts.models import KPIContract


def same_weekday_expected(
    series: pd.Series,
    target_date: pd.Timestamp,
    k_weeks: int = 8,
    min_weekday_points: int = 4,
) -> tuple[Optional[float], str]:
    """Same-weekday median expectation (Stage 2, F-D1).

    The expected value for `target_date` is the median of the same weekday
    over the last `k_weeks` weeks. With fewer than `min_weekday_points`
    same-weekday observations, falls back to a weekday-adjusted median:
    overall median x weekday factor estimated on the available history.
    `series` must already be as-of safe; any row at or after target_date is
    ignored here as a defensive measure, not relied on for as-of safety.
    """
    target = pd.Timestamp(target_date).normalize()
    history = series[series.index < target].dropna()
    if history.empty:
        return None, "UNAVAILABLE"
    target_weekday = target.dayofweek
    same_weekday = history[history.index.dayofweek == target_weekday].sort_index()
    recent_same_weekday = same_weekday.iloc[-k_weeks:]
    if len(recent_same_weekday) >= min_weekday_points:
        return float(recent_same_weekday.median()), "SAME_WEEKDAY_MEDIAN"
    overall_median = float(history.median())
    factor = 1.0
    if np.isfinite(overall_median) and overall_median != 0:
        weekday_medians = history.groupby(history.index.dayofweek).median()
        if target_weekday in weekday_medians.index:
            candidate_factor = float(weekday_medians.loc[target_weekday]) / overall_median
            if np.isfinite(candidate_factor):
                factor = candidate_factor
    return overall_median * factor, "WEEKDAY_ADJUSTED"


def weekday_adjusted_residuals(series: pd.Series) -> pd.Series:
    """De-seasonalise a daily series by each row's own weekday median, in log
    space: log(value / that weekday's median).

    Used for the Stage 2 residual dispersion scale (MAD of these residuals,
    over the whole supplied window) -- never for the point "expected value"
    itself, which uses `same_weekday_expected`'s narrower, more recent
    k-weeks window.

    Log space, not a plain difference (Stage 2 review fix, F-D3): this
    dataset's noise is proportional, not additive -- weekend absolute levels
    are higher but the percentage spread is flat at roughly the same rate
    every day. A pooled absolute-residual MAD therefore reads as tighter on
    quiet weekdays and looser on weekends, which pushed false alarms onto
    Fri/Sat/Sun even on ordinary days. Non-positive values (log undefined,
    e.g. a KPI that can hit exactly 0) are excluded, the same as any other
    missing observation; robust.py falls back to a linear (additive) residual
    only when there are too few positive values left to score at all.
    """
    clean = series.dropna()
    clean = clean[clean > 0]
    if clean.empty:
        return clean
    weekday_medians = clean.groupby(clean.index.dayofweek).median()
    weekday_medians = weekday_medians[weekday_medians > 0]
    clean = clean[clean.index.dayofweek.isin(weekday_medians.index)]
    if clean.empty:
        return clean
    mapped_medians = clean.index.dayofweek.map(weekday_medians).astype(float)
    return np.log(clean.astype(float)) - np.log(mapped_medians)


def linear_weekday_adjusted_residuals(series: pd.Series) -> pd.Series:
    """Additive fallback for `weekday_adjusted_residuals`: value minus that
    weekday's median, with no log transform. Only used when a series has
    non-positive values and a log-ratio residual is undefined for it."""
    clean = series.dropna()
    if clean.empty:
        return clean
    weekday_medians = clean.groupby(clean.index.dayofweek).median()
    return clean - clean.index.dayofweek.map(weekday_medians)


@dataclass(frozen=True)
class ComparisonPlan:
    target_date: pd.Timestamp
    history_days: int
    baseline_start: pd.Timestamp
    baseline_end: pd.Timestamp
    baseline_frame: pd.DataFrame
    current_frame: pd.DataFrame
    baseline_series: Optional[pd.Series] = None
    expected_value: Optional[float] = None
    expected_method: str = "UNAVAILABLE"

    def __post_init__(self) -> None:
        if not isinstance(self.target_date, pd.Timestamp):
            object.__setattr__(self, "target_date", pd.Timestamp(self.target_date).normalize())
        if not isinstance(self.baseline_start, pd.Timestamp):
            object.__setattr__(self, "baseline_start", pd.Timestamp(self.baseline_start))
        if not isinstance(self.baseline_end, pd.Timestamp):
            object.__setattr__(self, "baseline_end", pd.Timestamp(self.baseline_end))


@dataclass(frozen=True)
class PreparedMetricRequest:
    kpi_id: str
    contract: KPIContract
    frame: pd.DataFrame
    series: pd.Series
    comparison: ComparisonPlan
    scope: Dict[str, str]
    as_of: Optional[pd.Timestamp] = None


def prepare_metric_request(
    frame: pd.DataFrame,
    contract: KPIContract,
    target_date: str | pd.Timestamp,
    dimension_slice: Optional[Dict[str, str]] = None,
    as_of: Optional[str | pd.Timestamp] = None,
) -> PreparedMetricRequest:
    filtered = frame.copy()
    if dimension_slice:
        for key, value in dimension_slice.items():
            if key not in filtered.columns:
                raise ValueError(f"Unknown dimension: {key}")
            filtered = filtered[filtered[key] == value]

    if "date" not in filtered.columns:
        raise ValueError("Missing date column")

    filtered = filtered.copy()
    filtered["date"] = pd.to_datetime(filtered["date"], errors="coerce")
    target = pd.Timestamp(target_date).normalize()
    # Stage 2 (F-D1): widened from 30 to 90 days so there is enough history for
    # an 8-same-weekday-week expectation and a 60-90 day residual scale; a
    # contract with a longer min_history_periods still gets at least that.
    history_days = max(90, int(contract.min_history_periods))
    baseline_frame = filtered[
        (filtered["date"] < target) &
        (filtered["date"] >= target - pd.Timedelta(days=history_days))
    ].copy()
    current_frame = filtered[filtered["date"] == target].copy()
    series = daily_values(filtered, contract).sort_index()
    baseline_series = series[
        (series.index < target) &
        (series.index >= target - pd.Timedelta(days=history_days))
    ].dropna()
    expected_value, expected_method = same_weekday_expected(baseline_series, target)
    comparison = ComparisonPlan(
        target_date=target,
        history_days=history_days,
        baseline_start=target - pd.Timedelta(days=history_days),
        baseline_end=target - pd.Timedelta(days=1),
        baseline_frame=baseline_frame,
        current_frame=current_frame,
        baseline_series=baseline_series,
        expected_value=expected_value,
        expected_method=expected_method,
    )
    return PreparedMetricRequest(
        kpi_id=contract.kpi_id,
        contract=contract,
        frame=filtered,
        series=series,
        comparison=comparison,
        scope=dict(dimension_slice or {}),
        as_of=pd.Timestamp(as_of) if as_of is not None else None,
    )


def daily_values(frame: pd.DataFrame, contract: KPIContract) -> pd.Series:
    if "date" not in frame.columns:
        raise ValueError("Missing date column")
    if contract.aggregation == "sum":
        if contract.value_column not in frame.columns:
            raise ValueError(f"Missing KPI source column: {contract.value_column}")
        values = frame.groupby("date")[contract.value_column].sum(min_count=1)
    elif contract.aggregation == "mean":
        if contract.value_column not in frame.columns:
            raise ValueError(f"Missing KPI source column: {contract.value_column}")
        values = frame.groupby("date")[contract.value_column].mean()
    elif contract.aggregation == "weighted_mean":
        value, weight = contract.value_column, contract.weight_column
        for column in (value, weight):
            if column not in frame.columns:
                raise ValueError(f"Missing weighted-mean source column: {column}")
        if (frame[weight].dropna() < 0).any():
            raise ValueError("Weighted-mean weights cannot be negative")
        valid = frame[value].notna() & frame[weight].notna()
        weights = frame[weight].where(valid)
        numerator = frame[value].where(valid) * weights
        sums = pd.DataFrame({"date": frame["date"], "num": numerator, "den": weights}).groupby("date").sum(min_count=1)
        values = sums["num"] / sums["den"].where(sums["den"] > 0)
    elif contract.aggregation == "ratio_of_sums":
        numerator, denominator = contract.numerator_column, contract.denominator_column
        for column in (numerator, denominator):
            if column not in frame.columns:
                raise ValueError(f"Missing ratio source column: {column}")
        parts = frame.groupby("date")[[numerator, denominator]].sum(min_count=1)
        values = parts[numerator] / parts[denominator].where(parts[denominator] > 0)
        values = values.replace([np.inf, -np.inf], np.nan)
    else:
        raise ValueError(f"Unsupported aggregation: {contract.aggregation}")
    return values.sort_index()
