"""Lagged associations only; never promote a candidate driver to a cause."""

from dataclasses import dataclass
from typing import Dict, List

import pandas as pd

from kpi_engine.contracts.metrics import daily_values
from kpi_engine.contracts.models import KPIContract


@dataclass
class CandidateDriver:
    driver_id: str
    max_correlation: float
    optimal_lag_days: int
    sample_size: int
    source_grain: str
    driver_change_pct: float | None
    claim_type: str = "CORRELATIONAL"


@dataclass
class DriverExclusion:
    driver_id: str
    reason_code: str
    reason: str
    sample_size: int = 0


@dataclass
class RankingResult:
    candidates: List[CandidateDriver]
    exclusions: List[DriverExclusion]


class CorrelationalRanker:
    """Rank changes in declared drivers against KPI changes at their native grain."""

    @staticmethod
    def calculate_lagged_correlation(
        kpi_series: pd.Series, driver_series: pd.Series, max_lag: int = 7,
        min_pairs: int = 14,
    ) -> tuple[float, int, int]:
        best = (0.0, 0, 0)
        for lag in range(max_lag + 1):
            paired = pd.concat([kpi_series, driver_series.shift(lag)], axis=1).dropna()
            if len(paired) < min_pairs:
                continue
            if paired.iloc[:, 0].std() < 1e-9 or paired.iloc[:, 1].std() < 1e-9:
                continue
            correlation = paired.iloc[:, 0].corr(paired.iloc[:, 1])
            if pd.notna(correlation) and abs(correlation) > abs(best[0]):
                best = (float(correlation), lag, len(paired))
        return best

    @staticmethod
    def _driver_movement(series: pd.Series) -> float | None:
        available = series.dropna()
        if len(available) < 2:
            return None
        baseline = float(available.iloc[:-1].tail(7).mean())
        if abs(baseline) < 1e-9:
            return None
        return round(100.0 * (float(available.iloc[-1]) - baseline) / abs(baseline), 2)

    def evaluate_candidates(
        self,
        df: pd.DataFrame,
        kpi_col: str,
        candidate_cols: List[str],
        max_lag: int = 7,
        target_date: str | None = None,
        window_days: int = 120,
        driver_columns: Dict[str, str] | None = None,
        contract: KPIContract | None = None,
    ) -> RankingResult:
        if "date" not in df or (contract is None and kpi_col not in df):
            raise ValueError(f"Missing date or KPI column {kpi_col}")
        frame = df.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        if target_date is not None:
            target = pd.Timestamp(target_date)
            frame = frame[(frame["date"] <= target) &
                          (frame["date"] >= target - pd.Timedelta(days=window_days))]
        if frame.empty:
            return RankingResult([], [DriverExclusion(
                driver_id, "NO_DATA_IN_WINDOW", "No KPI observations in the ranking window"
            ) for driver_id in candidate_cols])
        specs = {spec["id"]: spec for spec in contract.candidate_drivers} if contract else {}
        kpi_daily = daily_values(frame, contract) if contract else frame.groupby("date")[kpi_col].sum(min_count=1)
        calendar = pd.date_range(frame["date"].min(), frame["date"].max(), freq="D")
        kpi_daily = kpi_daily.reindex(calendar)
        results: List[CandidateDriver] = []
        exclusions: List[DriverExclusion] = []

        for driver_id in candidate_cols:
            spec = specs.get(driver_id, {})
            column = spec.get("column") or (driver_columns or {}).get(driver_id, driver_id)
            if column not in frame:
                exclusions.append(DriverExclusion(
                    driver_id, "MISSING_COLUMN", f"Declared driver column {column} is unavailable"
                ))
                continue
            if column in {kpi_col, getattr(contract, "value_column", None)}:
                exclusions.append(DriverExclusion(
                    driver_id, "TARGET_LEAKAGE", "The driver is the KPI value itself"
                ))
                continue
            aggregation = spec.get("aggregation", "mean")
            grain = spec.get("grain", "daily")
            if aggregation not in {"sum", "mean"} or grain not in {"daily", "weekly"}:
                raise ValueError(f"Unsupported driver aggregation or grain: {driver_id}")

            if grain == "daily":
                grouped = frame.groupby("date")[column]
                driver = (grouped.sum(min_count=1) if aggregation == "sum" else grouped.mean()).reindex(calendar)
                # Changes reduce correlations arising solely from a shared trend.
                kpi_changes = kpi_daily.diff()
                driver_changes = driver.diff()
                correlation, lag, support = self.calculate_lagged_correlation(
                    kpi_changes, driver_changes, max_lag=max_lag, min_pairs=14
                )
                lag0_pairs = pd.concat([kpi_changes, driver_changes], axis=1).dropna()
                available_pairs = len(lag0_pairs)
                minimum_pairs = 14
                lag_days = lag
            else:
                if "week_start" not in frame:
                    exclusions.append(DriverExclusion(
                        driver_id, "MISSING_WEEK_KEY", "Weekly source has no week_start column"
                    ))
                    continue
                weekly_rows = frame[frame["week_start"].notna() & frame[column].notna()].copy()
                if weekly_rows.empty:
                    exclusions.append(DriverExclusion(
                        driver_id, "NO_AVAILABLE_WEEKLY_DATA", "No available weekly driver observations"
                    ))
                    continue
                weekly_rows["week_start"] = pd.to_datetime(weekly_rows["week_start"])
                # One source observation per week and segment, not seven daily copies.
                keys = [name for name in ("region", "category") if name in weekly_rows]
                if (weekly_rows.groupby(["week_start", *keys])[column]
                        .nunique(dropna=False).gt(1).any()):
                    raise ValueError(f"Conflicting repeated weekly values for {driver_id}")
                weekly_rows = weekly_rows.drop_duplicates(["week_start", *keys])
                grouped = weekly_rows.groupby("week_start")[column]
                driver = grouped.sum(min_count=1) if aggregation == "sum" else grouped.mean()
                sales_weeks = frame["date"] - pd.to_timedelta(frame["date"].dt.dayofweek, unit="D")
                expected = frame.assign(_week=sales_weeks)[["_week", *keys]].drop_duplicates()
                expected_count = expected.groupby("_week").size()
                observed_count = weekly_rows.groupby("week_start").size()
                complete_weeks = expected_count.index[
                    observed_count.reindex(expected_count.index, fill_value=0).ge(expected_count)
                ]
                driver = driver[driver.index.isin(complete_weeks)]
                if driver.empty:
                    exclusions.append(DriverExclusion(
                        driver_id, "INCOMPLETE_WEEKLY_COVERAGE",
                        "No week covers every segment in the requested slice",
                    ))
                    continue
                week_start = kpi_daily.index - pd.to_timedelta(kpi_daily.index.dayofweek, unit="D")
                weekly_kpi_frame = pd.DataFrame({"week_start": week_start, "value": kpi_daily.values})
                week_group = weekly_kpi_frame.groupby("week_start")["value"]
                complete = week_group.count() == 7
                if contract is not None and contract.aggregation == "ratio_of_sums":
                    parts = frame.assign(
                        _week=frame["date"] - pd.to_timedelta(frame["date"].dt.dayofweek, unit="D")
                    ).groupby("_week")[[contract.numerator_column, contract.denominator_column]].sum(min_count=1)
                    weekly_kpi = parts[contract.numerator_column] / parts[contract.denominator_column].where(
                        parts[contract.denominator_column] > 0
                    )
                elif contract is not None and contract.aggregation == "weighted_mean":
                    valid = frame[contract.value_column].notna() & frame[contract.weight_column].notna()
                    weighted = frame.assign(
                        _week=frame["date"] - pd.to_timedelta(frame["date"].dt.dayofweek, unit="D"),
                        _num=frame[contract.value_column].where(valid) * frame[contract.weight_column].where(valid),
                        _den=frame[contract.weight_column].where(valid),
                    ).groupby("_week")[["_num", "_den"]].sum(min_count=1)
                    weekly_kpi = weighted["_num"] / weighted["_den"].where(weighted["_den"] > 0)
                else:
                    weekly_kpi = (week_group.sum(min_count=1) if contract is None or contract.aggregation == "sum"
                                  else week_group.mean())
                weekly_kpi = weekly_kpi.reindex(complete.index)[complete]
                common = weekly_kpi.index.union(driver.index)
                weekly_kpi = weekly_kpi.reindex(common).sort_index()
                driver = driver.reindex(common).sort_index()
                correlation, lag, support = self.calculate_lagged_correlation(
                    weekly_kpi.diff(), driver.diff(), max_lag=max_lag // 7,
                    min_pairs=8,
                )
                lag0_pairs = pd.concat([weekly_kpi.diff(), driver.diff()], axis=1).dropna()
                available_pairs = len(lag0_pairs)
                minimum_pairs = 8
                lag_days = lag * 7

            if support == 0:
                if available_pairs < minimum_pairs:
                    exclusions.append(DriverExclusion(
                        driver_id, "INSUFFICIENT_PAIRS",
                        f"Only {available_pairs} paired {grain} changes; need at least {minimum_pairs}",
                        available_pairs,
                    ))
                elif (lag0_pairs.std() < 1e-9).any():
                    exclusions.append(DriverExclusion(
                        driver_id, "NO_VARIATION",
                        "The KPI or driver has too little variation to estimate correlation",
                        available_pairs,
                    ))
                else:
                    exclusions.append(DriverExclusion(
                        driver_id, "WEAK_ASSOCIATION",
                        "Absolute lagged correlation is below 0.3000",
                        available_pairs,
                    ))
                continue
            if abs(correlation) < 0.3:
                exclusions.append(DriverExclusion(
                    driver_id, "WEAK_ASSOCIATION",
                    f"Absolute lagged correlation {abs(correlation):.4f} is below 0.3000",
                    support,
                ))
                continue
            results.append(CandidateDriver(
                driver_id=driver_id,
                max_correlation=round(correlation, 4),
                optimal_lag_days=lag_days,
                sample_size=support,
                source_grain=grain,
                driver_change_pct=self._driver_movement(driver),
            ))

        results.sort(key=lambda item: (-abs(item.max_correlation), item.driver_id))
        return RankingResult(results, exclusions)

    def rank_candidates(self, *args, **kwargs) -> List[CandidateDriver]:
        """Backward-compatible ranked-list API; use evaluate_candidates for reasons."""
        return self.evaluate_candidates(*args, **kwargs).candidates
