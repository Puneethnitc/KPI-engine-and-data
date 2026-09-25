# IMPLEMENTATION HANDOFF — current calculation reference
# Current: aggregate by date using sum, mean, weighted mean or ratio of sums.
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


@dataclass(frozen=True)
class ComparisonPlan:
    target_date: pd.Timestamp
    history_days: int
    baseline_start: pd.Timestamp
    baseline_end: pd.Timestamp
    baseline_frame: pd.DataFrame
    current_frame: pd.DataFrame
    baseline_series: Optional[pd.Series] = None

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
    history_days = max(30, int(contract.min_history_periods))
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
    comparison = ComparisonPlan(
        target_date=target,
        history_days=history_days,
        baseline_start=target - pd.Timedelta(days=history_days),
        baseline_end=target - pd.Timedelta(days=1),
        baseline_frame=baseline_frame,
        current_frame=current_frame,
        baseline_series=baseline_series,
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
