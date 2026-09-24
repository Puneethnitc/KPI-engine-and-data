"""Compute additive and ratio KPI series from source columns."""

import numpy as np
import pandas as pd

from kpi_engine.contracts.models import KPIContract


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
