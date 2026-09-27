# IMPLEMENTATION HANDOFF — driver analysis evidence
# Current: native-grain first differences, governed lags, available-pair and
# coverage checks, nested-window stability, explicit composite ranking score.
# Lag search remains exploratory; no multiple-testing correction is applied.
# Next: validate dependence-aware p-value correction on reviewed labelled runs,
# and add conditional/multivariate interaction analysis only with diagnostics.
# Check: candidate completeness, future-row invariance, weekly deduplication,
# missingness denominators, lag order and window-sensitive rank behavior.

"""Lagged associations only; never promote a candidate driver to a cause."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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
    rank: int = 1
    abs_correlation: float = 0.0
    source_id: str = "sales_daily"
    expected_direction: Optional[str] = None
    direction_consistent: Optional[bool] = None
    ranking_window_days: int = 120
    threshold_used: float = 0.3
    target_period_available: bool = True
    evidence_descriptor: str = "EXPLORATORY"  # EXPLORATORY | STABLE_ASSOCIATION | DIRECTION_CONFLICT
    claim_type: str = "CORRELATIONAL"
    limitations: tuple[str, ...] = field(default_factory=tuple)
    display_name: str = ""
    driver_unit: str | None = None
    controllability: str = "contextual"
    aggregation: str = "mean"
    alignment_method: str = "daily_date_grouping"
    direction: str = "POSITIVE"
    score: float = 0.0
    score_name: str = "coverage_sample_stability_adjusted_association"
    raw_correlation: float = 0.0
    missing_observations: int = 0
    coverage_ratio: float = 0.0
    lag_candidates_tested: int = 0
    temporal_order: str = "COINCIDENT"
    temporal_order_supported: bool = False
    stability_status: str = "NOT_ASSESSED"
    stability_details: Dict[str, Any] = field(default_factory=dict)
    seasonality_control: str = "NONE"
    trend_control: str = "FIRST_DIFFERENCE"
    eligibility_checks: Dict[str, Any] = field(default_factory=dict)
    evidence_references: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class DriverExclusion:
    driver_id: str
    reason_code: str
    reason: str
    sample_size: int = 0
    source_id: str = "sales_daily"
    failed_checks: List[str] = field(default_factory=list)
    evidence_references: List[Dict[str, Any]] = field(default_factory=list)
    missing_observations: int | None = None
    coverage_ratio: float | None = None
    lag_candidates_tested: int = 0
    tested_lags: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class RankingResult:
    candidates: List[CandidateDriver]
    exclusions: List[DriverExclusion]
    driver_analysis: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RankingPolicy:
    max_lag: int = 7
    window_days: int = 120
    min_pairs: int = 14
    weekly_min_pairs: int = 8
    threshold: float = 0.3
    source_grain: str = "daily"
    allowed_lags: Optional[List[int]] = None
    minimum_coverage: float = 0.6
    stability_window_fraction: float = 0.8

    @classmethod
    def from_contract(cls, contract: KPIContract | None, driver_spec: Optional[Dict[str, Any]] = None) -> "RankingPolicy":
        config: Dict[str, Any] = {}
        if contract is not None and getattr(contract, "comparison_policy", None) is not None:
            cfg = getattr(contract.comparison_policy, "config", {}) or {}
            if isinstance(cfg, dict):
                config.update(cfg)
        if contract is not None and hasattr(contract, "ranking_policy") and contract.ranking_policy:
            cfg = getattr(contract, "ranking_policy")
            if isinstance(cfg, dict):
                config.update(cfg)
        if isinstance(driver_spec, dict):
            config.update({
                k: v for k, v in driver_spec.items() if k in {
                    "max_lag", "window_days", "min_pairs", "weekly_min_pairs", "threshold", "source_grain", "allowed_lags", "minimum_coverage", "stability_window_fraction"
                }
            })
        if isinstance(driver_spec, dict):
            nested = driver_spec.get("ranking") or driver_spec.get("policy") or driver_spec.get("lag_policy")
            if isinstance(nested, dict):
                config.update({
                    k: v for k, v in nested.items() if k in {
                        "max_lag", "window_days", "min_pairs", "weekly_min_pairs", "threshold", "source_grain", "allowed_lags", "minimum_coverage", "stability_window_fraction"
                    }
                })
        allowed_lags = config.get("allowed_lags")
        if isinstance(allowed_lags, str):
            allowed_lags = [int(part.strip()) for part in allowed_lags.split(",") if part.strip()]
        return cls(
            max_lag=int(config.get("max_lag", 7)),
            window_days=int(config.get("window_days", 120)),
            min_pairs=int(config.get("min_pairs", 14)),
            weekly_min_pairs=int(config.get("weekly_min_pairs", 8)),
            threshold=float(config.get("threshold", 0.3)),
            source_grain=str(config.get("source_grain", "daily")),
            allowed_lags=list(allowed_lags) if allowed_lags is not None else None,
            minimum_coverage=float(config.get("minimum_coverage", 0.6)),
            stability_window_fraction=float(config.get("stability_window_fraction", 0.8)),
        )


class CorrelationalRanker:
    """Rank changes in declared drivers against KPI changes at their native grain."""

    @staticmethod
    def calculate_lagged_correlation(
        kpi_series: pd.Series, driver_series: pd.Series, max_lag: int = 7,
        min_pairs: int = 14,
    ) -> tuple[float, int, int]:
        # Lag selection maximizes correlation on this same sample; it does not
        # establish causal direction or provide a multiple-testing correction.
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

    @staticmethod
    def _resolve_driver_column(
        frame: pd.DataFrame,
        driver_id: str,
        spec: Dict[str, Any],
        driver_columns: Optional[Dict[str, str]] = None,
    ) -> str | None:
        raw_column = spec.get("column") or (driver_columns or {}).get(driver_id, driver_id)
        if raw_column in frame:
            return str(raw_column)
        source = str(spec.get("source") or "").strip()
        column_name = str(raw_column).strip()
        candidates: List[str] = []
        if source:
            for prefix in (source, source.replace("_weekly", "").replace("_daily", ""), source.replace("-", "_")):
                if prefix:
                    candidates.extend([
                        f"{prefix}_{column_name}",
                        f"{prefix}.{column_name}",
                        f"{prefix}__{column_name}",
                    ])
        candidates.extend([
            f"{column_name}_{source}" if source else column_name,
            f"{column_name}.{source}" if source else column_name,
        ])
        for candidate in candidates:
            if candidate in frame:
                return candidate
        return str(raw_column) if raw_column is not None else None

    @staticmethod
    def _resolve_policy(contract: KPIContract | None, driver_spec: Optional[Dict[str, Any]] = None) -> RankingPolicy:
        return RankingPolicy.from_contract(contract, driver_spec)

    @staticmethod
    def _lag_candidates(allowed_lags: Optional[List[int]], max_lag: int) -> List[int]:
        if not allowed_lags:
            return list(range(max_lag + 1))
        result = []
        for lag in sorted(set(int(value) for value in allowed_lags)):
            if 0 <= lag <= max_lag:
                result.append(lag)
        return result or list(range(max_lag + 1))

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
        scope: Dict[str, str] | None = None,
        as_of: str | None = None,
    ) -> RankingResult:
        if "date" not in df or (contract is None and kpi_col not in df):
            raise ValueError(f"Missing date or KPI column {kpi_col}")
        frame = df.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        if target_date is not None:
            target = pd.Timestamp(target_date)
            frame = frame[(frame["date"] <= target) &
                          (frame["date"] >= target - pd.Timedelta(days=window_days))]
        else:
            target = frame["date"].max() if not frame.empty else pd.NaT
        if as_of is not None and "available_at" in frame:
            frame["available_at"] = pd.to_datetime(frame["available_at"], errors="coerce")
            frame = frame[frame["available_at"] <= pd.Timestamp(as_of)]

        specs = {spec["id"]: spec for spec in contract.candidate_drivers} if contract else {}
        candidate_ids = list(dict.fromkeys(candidate_cols))
        if not candidate_ids and specs:
            candidate_ids = list(specs)
        requested_scope = dict(scope or {})
        start_date = None if pd.isna(target) else (target - pd.Timedelta(days=window_days)).date().isoformat()
        target_period = {
            "start": start_date,
            "end": None if pd.isna(target) else target.date().isoformat(),
            "as_of": as_of,
            "window_days": window_days,
        }
        method = "NATIVE_GRAIN_FIRST_DIFFERENCE_LAGGED_PEARSON_ASSOCIATION"
        general_limitations = [
            "Association only: this marginal diagnostic does not estimate contribution or causation.",
            "First differencing reduces level-trend association; it is not seasonal adjustment or full detrending.",
            "No seasonal control is applied; recurring seasonal patterns may remain.",
            "Drivers are ranked marginally; correlated or interacting drivers are not conditionally separated.",
            "No multiple-testing correction is applied; maximizing across lags/windows is exploratory and may inflate apparent association.",
            "Coincident associations do not establish that a driver preceded the KPI movement.",
        ]
        if frame.empty:
            excluded = [DriverExclusion(
                driver_id, "INSUFFICIENT_HISTORY", "No KPI observations in the governed ranking window",
                source_id=specs.get(driver_id, {}).get("source", "sales_daily"),
                failed_checks=["ranking_window_has_observations"],
            ) for driver_id in candidate_ids]
            status = "NOT_APPLICABLE" if not candidate_ids else "INSUFFICIENT_EVIDENCE"
            analysis = self._analysis_contract(
                status, method, kpi_col, target_period, requested_scope, candidate_ids,
                [], excluded, general_limitations, 0, 0,
            )
            return RankingResult([], excluded, analysis)

        kpi_daily = daily_values(frame, contract) if contract else frame.groupby("date")[kpi_col].sum(min_count=1)
        calendar = pd.date_range(frame["date"].min(), frame["date"].max(), freq="D")
        kpi_daily = kpi_daily.reindex(calendar)
        results: List[CandidateDriver] = []
        exclusions: List[DriverExclusion] = []
        hypotheses_tested = 0
        max_window_count = 0

        for driver_id in candidate_ids:
            spec = specs.get(driver_id, {})
            policy = self._resolve_policy(contract, spec)
            active_max_lag = int(spec.get("max_lag", policy.max_lag)) if isinstance(spec, dict) else policy.max_lag
            active_window_days = int(spec.get("window_days", policy.window_days)) if isinstance(spec, dict) else policy.window_days
            active_min_pairs = int(spec.get("min_pairs", policy.min_pairs)) if isinstance(spec, dict) else policy.min_pairs
            active_threshold = float(spec.get("threshold", policy.threshold)) if isinstance(spec, dict) else policy.threshold
            effective_max_lag = max(0, min(active_max_lag, max_lag if max_lag is not None else active_max_lag))
            if target_date is not None:
                effective_window_days = max(active_window_days, int(window_days))
            else:
                effective_window_days = active_window_days
            column = self._resolve_driver_column(frame, driver_id, spec, driver_columns)
            if column not in frame:
                exclusions.append(DriverExclusion(
                    driver_id, "SOURCE_UNAVAILABLE", f"Declared driver column {column} is unavailable",
                    source_id=spec.get("source", "sales_daily"),
                    failed_checks=["source_column_available"],
                ))
                continue
            if column in {kpi_col, getattr(contract, "value_column", None)}:
                exclusions.append(DriverExclusion(
                    driver_id, "TARGET_LEAKAGE", "The driver is the KPI value itself",
                    source_id=spec.get("source", "sales_daily"),
                    failed_checks=["not_target_leakage"],
                ))
                continue
            aggregation = spec.get("aggregation", "mean")
            grain = spec.get("grain", policy.source_grain)
            if aggregation not in {"sum", "mean"} or grain not in {"daily", "weekly", "monthly"}:
                raise ValueError(f"Unsupported driver aggregation or grain: {driver_id}")

            availability = spec.get("availability") or spec.get("lag_availability") or {}
            allowed_lags = self._lag_candidates(spec.get("allowed_lags") or policy.allowed_lags, effective_max_lag)
            if isinstance(availability, dict):
                unavailable = set(availability.get("unavailable_lags", []) or [])
                if unavailable:
                    allowed_lags = [lag for lag in allowed_lags if lag not in set(int(v) for v in unavailable)]
            if not allowed_lags:
                exclusions.append(DriverExclusion(
                    driver_id, "LAG_UNAVAILABLE",
                    "No governed lag candidates are available for this driver at the current comparison window",
                    source_id=spec.get("source", "sales_daily"),
                    failed_checks=["governed_lag_available"],
                ))
                continue

            if grain == "daily":
                alignment_method = "daily date aggregation on the scoped as-of frame"
                grouped = frame.groupby("date")[column]
                driver = (grouped.sum(min_count=1) if aggregation == "sum" else grouped.mean()).reindex(calendar)
                kpi_changes = kpi_daily.diff()
                driver_changes = driver.diff()
                minimum_pairs = active_min_pairs
                interval_days = 1
            elif grain == "weekly":
                alignment_method = "deduplicate by ISO week and scope dimensions; compare complete weeks"
                if "week_start" not in frame:
                    exclusions.append(DriverExclusion(
                        driver_id, "SOURCE_UNAVAILABLE", "Weekly source has no week_start column",
                        source_id=spec.get("source", "marketing_weekly"),
                        failed_checks=["native_grain_key_available"],
                    ))
                    continue
                weekly_rows = frame[frame["week_start"].notna() & frame[column].notna()].copy()
                if weekly_rows.empty:
                    exclusions.append(DriverExclusion(
                        driver_id, "SOURCE_UNAVAILABLE", "No available weekly driver observations",
                        source_id=spec.get("source", "marketing_weekly"),
                        failed_checks=["driver_observations_available"],
                    ))
                    continue
                weekly_rows["week_start"] = pd.to_datetime(weekly_rows["week_start"])
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
                        source_id=spec.get("source", "marketing_weekly"),
                        failed_checks=["complete_segment_week_coverage"],
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
                allowed_lags = sorted(set(value // 7 for value in allowed_lags))
                minimum_pairs = policy.weekly_min_pairs
                interval_days = 7
            else:
                alignment_method = "deduplicate by calendar month and scope dimensions; aggregate at monthly grain"
                month_column = "month_start" if "month_start" in frame else "month" if "month" in frame else "date"
                monthly_rows = frame[frame[column].notna()].copy()
                if monthly_rows.empty:
                    exclusions.append(DriverExclusion(
                        driver_id, "SOURCE_UNAVAILABLE", "No monthly driver observations are available",
                        source_id=spec.get("source", "sales_monthly"),
                        failed_checks=["monthly_driver_observations_available"],
                    ))
                    continue
                monthly_rows["_month"] = pd.to_datetime(monthly_rows[month_column], errors="coerce").dt.to_period("M").dt.to_timestamp()
                monthly_rows = monthly_rows[monthly_rows["_month"].notna()]
                keys = [name for name in ("region", "category") if name in monthly_rows]
                if monthly_rows.groupby(["_month", *keys])[column].nunique(dropna=False).gt(1).any():
                    raise ValueError(f"Conflicting repeated monthly values for {driver_id}")
                monthly_rows = monthly_rows.drop_duplicates(["_month", *keys])
                monthly_group = monthly_rows.groupby("_month")[column]
                driver = monthly_group.sum(min_count=1) if aggregation == "sum" else monthly_group.mean()
                daily_months = kpi_daily.index.to_period("M")
                if contract is not None and contract.aggregation == "ratio_of_sums":
                    monthly_parts = frame.assign(_month=frame["date"].dt.to_period("M")).groupby("_month")[[contract.numerator_column, contract.denominator_column]].sum(min_count=1)
                    monthly_kpi = monthly_parts[contract.numerator_column] / monthly_parts[contract.denominator_column].where(monthly_parts[contract.denominator_column] > 0)
                    monthly_kpi.index = monthly_kpi.index.to_timestamp()
                elif contract is not None and contract.aggregation == "weighted_mean":
                    valid = frame[contract.value_column].notna() & frame[contract.weight_column].notna()
                    weighted = frame.assign(
                        _month=frame["date"].dt.to_period("M"),
                        _num=frame[contract.value_column].where(valid) * frame[contract.weight_column].where(valid),
                        _den=frame[contract.weight_column].where(valid),
                    ).groupby("_month")[ ["_num", "_den"] ].sum(min_count=1)
                    monthly_kpi = weighted["_num"] / weighted["_den"].where(weighted["_den"] > 0)
                    monthly_kpi.index = monthly_kpi.index.to_timestamp()
                else:
                    daily_kpi = pd.DataFrame({"month": daily_months, "value": kpi_daily.values})
                    month_group = daily_kpi.groupby("month")["value"]
                    monthly_kpi = month_group.sum(min_count=1) if contract is None or contract.aggregation == "sum" else month_group.mean()
                    monthly_kpi.index = monthly_kpi.index.to_timestamp()
                common = monthly_kpi.index.union(driver.index)
                monthly_kpi = monthly_kpi.reindex(common).sort_index()
                driver = driver.reindex(common).sort_index()
                kpi_changes = monthly_kpi.diff()
                driver_changes = driver.diff()
                allowed_lags = sorted(set(value // 30 for value in allowed_lags))
                minimum_pairs = int(spec.get("monthly_min_pairs", max(4, policy.weekly_min_pairs // 2)))
                interval_days = 30

            if grain == "daily":
                kpi_changes = kpi_daily.diff()
                driver_changes = driver.diff()
            elif grain == "weekly":
                kpi_changes = weekly_kpi.diff()
                driver_changes = driver.diff()
            lag_trials = []
            hypotheses_tested += len(allowed_lags)
            for lag in allowed_lags:
                aligned = pd.concat([kpi_changes, driver_changes.shift(lag)], axis=1)
                paired = aligned.dropna()
                value = None
                if len(paired) >= minimum_pairs and paired.iloc[:, 0].std() >= 1e-9 and paired.iloc[:, 1].std() >= 1e-9:
                    measured = paired.iloc[:, 0].corr(paired.iloc[:, 1])
                    value = float(measured) if pd.notna(measured) else None
                lag_trials.append({
                    "lag_periods": lag,
                    "lag_days": lag * interval_days,
                    "sample_size": int(len(paired)),
                    "correlation": None if value is None else round(value, 6),
                    "eligible": value is not None,
                })
            eligible_trials = [trial for trial in lag_trials if trial["eligible"]]
            if not eligible_trials:
                observed_pair_count = max((trial["sample_size"] for trial in lag_trials), default=0)
                selected_trial = max(lag_trials, key=lambda trial: trial["sample_size"], default={})
                possible_pairs = max(1, int(kpi_changes.notna().sum()) - selected_trial.get("lag_periods", 0))
                missing_pairs = max(0, possible_pairs - observed_pair_count)
                reason_code = "INSUFFICIENT_HISTORY" if observed_pair_count < minimum_pairs else "CONSTANT_SERIES"
                exclusions.append(DriverExclusion(
                    driver_id, reason_code,
                    f"No governed lag produced {minimum_pairs} variable paired changes; maximum available pairs={observed_pair_count}",
                    observed_pair_count,
                    source_id=spec.get("source", "sales_daily"),
                    failed_checks=["minimum_paired_changes", "nonconstant_series"],
                    missing_observations=missing_pairs,
                    coverage_ratio=round(observed_pair_count / possible_pairs, 6),
                    lag_candidates_tested=len(allowed_lags),
                    tested_lags=lag_trials,
                ))
                continue
            best_trial = max(eligible_trials, key=lambda trial: (abs(trial["correlation"]), -trial["lag_periods"]))
            correlation = float(best_trial["correlation"])
            lag = int(best_trial["lag_periods"])
            lag_days = int(best_trial["lag_days"])
            support = int(best_trial["sample_size"])
            possible_pairs = max(1, int(kpi_changes.notna().sum()) - lag)
            coverage_ratio = min(1.0, support / possible_pairs)
            missing_observations = max(0, possible_pairs - support)
            if coverage_ratio < policy.minimum_coverage:
                exclusions.append(DriverExclusion(
                    driver_id, "LOW_COVERAGE",
                    f"Usable paired coverage {coverage_ratio:.3f} is below the configured {policy.minimum_coverage:.3f}",
                    support,
                    source_id=spec.get("source", "sales_daily"),
                    failed_checks=["minimum_coverage"],
                    missing_observations=missing_observations,
                    coverage_ratio=round(coverage_ratio, 6),
                    lag_candidates_tested=len(allowed_lags),
                    tested_lags=lag_trials,
                ))
                continue
            if abs(correlation) < active_threshold:
                exclusions.append(DriverExclusion(
                    driver_id, "BELOW_THRESHOLD",
                    f"Absolute lagged correlation {abs(correlation):.4f} is below configured threshold {active_threshold:.4f}",
                    support,
                    source_id=spec.get("source", "sales_daily"),
                    failed_checks=["association_threshold"],
                    missing_observations=missing_observations,
                    coverage_ratio=round(coverage_ratio, 6),
                    lag_candidates_tested=len(allowed_lags),
                    tested_lags=lag_trials,
                ))
                continue

            # Compare the selected lag on the full window and the recent nested
            # window. This is a sensitivity diagnostic, not independent validation.
            fraction = policy.stability_window_fraction
            recent_start = int(max(0, len(kpi_changes) * (1 - fraction)))
            recent_kpi = kpi_changes.iloc[recent_start:]
            recent_driver = driver_changes.iloc[recent_start:]
            recent_pairs = pd.concat([recent_kpi, recent_driver.shift(lag)], axis=1).dropna()
            recent_correlation = None
            if len(recent_pairs) >= minimum_pairs and recent_pairs.iloc[:, 0].std() >= 1e-9 and recent_pairs.iloc[:, 1].std() >= 1e-9:
                recent_value = recent_pairs.iloc[:, 0].corr(recent_pairs.iloc[:, 1])
                recent_correlation = float(recent_value) if pd.notna(recent_value) else None
            if recent_correlation is None:
                stability_status = "NOT_ASSESSED"
            elif correlation * recent_correlation < 0 or abs(correlation - recent_correlation) > 0.25:
                stability_status = "SENSITIVE"
            else:
                stability_status = "STABLE"
            stability_details = {
                "windows_tested": 2,
                "full_window_correlation": round(correlation, 6),
                "recent_window_fraction": fraction,
                "recent_window_correlation": None if recent_correlation is None else round(recent_correlation, 6),
                "recent_window_sample_size": int(len(recent_pairs)),
                "stability_rule": "SENSITIVE if sign reverses or absolute correlation changes by more than 0.25; otherwise STABLE when recent support meets minimum",
                "lag_trials": lag_trials,
            }
            stability_factor = 1.0 if stability_status == "STABLE" else 0.5
            sample_factor = min(1.0, (support / max(1, minimum_pairs * 2)) ** 0.5)
            score = abs(correlation) * coverage_ratio * sample_factor * stability_factor
            source_id = spec.get("source", "sales_daily")
            # Direction is governance metadata, never inferred from a driver ID.
            expected_dir = spec.get("expected_direction")
            dir_consistent = None if expected_dir is None else (
                (correlation < 0 and expected_dir == "negative") or
                (correlation > 0 and expected_dir == "positive")
            )
            descriptor = "DIRECTION_CONFLICT" if dir_consistent is False else "EXPLORATORY"
            target_period_available = True
            if target_date is not None and not driver.dropna().empty:
                relevant_date = pd.Timestamp(target_date) - pd.Timedelta(days=lag_days)
                if grain == "weekly":
                    relevant_date -= pd.Timedelta(days=relevant_date.dayofweek)
                elif grain == "monthly":
                    relevant_date = relevant_date.to_period("M").to_timestamp()
                target_period_available = pd.Timestamp(driver.dropna().index.max()).normalize() >= relevant_date.normalize()
            if not target_period_available:
                exclusions.append(DriverExclusion(
                    driver_id, "SOURCE_UNAVAILABLE",
                    "Driver observation is unavailable for the target period at the selected lag",
                    support,
                    source_id=source_id,
                    failed_checks=["target_period_driver_available"],
                ))
                continue
            candidate_limitations = [
                "Lag selected by maximizing absolute first-difference correlation over the governed lag candidates",
                "Association is not a contribution or causal estimate",
                "Multiple-testing correction is not applied; ranking is exploratory",
                "First differencing is not seasonal adjustment; seasonal confounding may remain",
                "Drivers are ranked marginally; interacting drivers are not separated",
            ]
            if stability_status == "SENSITIVE":
                candidate_limitations.append("Association changes materially across the recent nested window")
            if lag_days == 0:
                candidate_limitations.append("Coincident changes do not establish temporal precedence")
            if dir_consistent is False:
                candidate_limitations.append("Association sign conflicts with declared driver hypothesis")
            if expected_dir is None:
                candidate_limitations.append("No expected hypothesis direction is declared in the KPI contract")
            if not target_period_available:
                candidate_limitations.append("Driver observation is unavailable for the relevant target lag")

            results.append(CandidateDriver(
                driver_id=driver_id,
                max_correlation=round(correlation, 4),
                abs_correlation=round(abs(correlation), 4),
                optimal_lag_days=lag_days,
                sample_size=support,
                source_grain=grain,
                source_id=source_id,
                driver_change_pct=self._driver_movement(driver),
                expected_direction=expected_dir,
                direction_consistent=dir_consistent,
                ranking_window_days=effective_window_days,
                threshold_used=active_threshold,
                target_period_available=target_period_available,
                evidence_descriptor=descriptor,
                claim_type="CORRELATIONAL",
                limitations=tuple(candidate_limitations),
                display_name=spec.get("display_name", driver_id.replace("_", " ").title()),
                driver_unit=spec.get("unit"),
                controllability=spec.get("controllability", "contextual"),
                aggregation=aggregation,
                alignment_method=alignment_method,
                direction="POSITIVE" if correlation >= 0 else "NEGATIVE",
                score=round(score, 6),
                raw_correlation=round(correlation, 6),
                missing_observations=missing_observations,
                coverage_ratio=round(coverage_ratio, 6),
                lag_candidates_tested=len(allowed_lags),
                temporal_order="BEFORE" if lag_days > 0 else "COINCIDENT",
                temporal_order_supported=lag_days > 0,
                stability_status=stability_status,
                stability_details=stability_details,
                seasonality_control="NONE",
                trend_control="FIRST_DIFFERENCE",
                eligibility_checks={
                    "source_column_available": True,
                    "target_period_available": target_period_available,
                    "minimum_pairs": minimum_pairs,
                    "sample_size": support,
                    "minimum_coverage": policy.minimum_coverage,
                    "coverage_ratio": round(coverage_ratio, 6),
                    "association_threshold": active_threshold,
                    "threshold_passed": abs(correlation) >= active_threshold,
                    "expected_direction": expected_dir,
                    "direction_consistent": dir_consistent,
                    "stability_status": stability_status,
                },
                evidence_references=[{
                    "source_id": source_id,
                    "date_start": start_date,
                    "date_end": None if pd.isna(target) else target.date().isoformat(),
                    "driver_column": column,
                    "kpi": kpi_col,
                }],
            ))

        results.sort(key=lambda item: (-item.score, -item.abs_correlation, item.driver_id))
        for index, item in enumerate(results):
            item.rank = index + 1
        hypotheses_tested = max(hypotheses_tested, sum(item.lag_candidates_tested for item in results))
        max_window_count = sum(item.stability_details.get("windows_tested", 0) for item in results)
        if not candidate_ids:
            status = "NOT_APPLICABLE"
        elif not results and any(item.reason_code == "INSUFFICIENT_HISTORY" for item in exclusions):
            status = "INSUFFICIENT_EVIDENCE"
        elif not results:
            status = "INSUFFICIENT_EVIDENCE"
        else:
            status = "ASSESSED"
        analysis = self._analysis_contract(
            status, method, kpi_col, target_period, requested_scope, candidate_ids,
            results, exclusions, general_limitations, hypotheses_tested, max_window_count,
        )
        return RankingResult(results, exclusions, analysis)

    @staticmethod
    def _analysis_contract(
        status: str,
        method: str,
        target_kpi: str,
        target_period: Dict[str, Any],
        scope: Dict[str, str],
        candidate_ids: List[str],
        candidates: List[CandidateDriver],
        exclusions: List[DriverExclusion],
        limitations: List[str],
        hypotheses_tested: int,
        windows_tested: int,
    ) -> Dict[str, Any]:
        ranked = []
        for candidate in candidates:
            ranked.append({
                "rank": candidate.rank,
                "driver_id": candidate.driver_id,
                "display_name": candidate.display_name,
                "source_id": candidate.source_id,
                "source_grain": candidate.source_grain,
                "aggregation": candidate.aggregation,
                "alignment_method": candidate.alignment_method,
                "driver_unit": candidate.driver_unit,
                "controllability": candidate.controllability,
                "relationship_type": "ASSOCIATION",
                "direction": candidate.direction,
                "score": candidate.score,
                "score_name": candidate.score_name,
                "score_scale": "0..1 ranking index; not calibrated, not probability, and not a contribution",
                "score_components": {
                    "absolute_raw_correlation": candidate.abs_correlation,
                    "paired_coverage_ratio": candidate.coverage_ratio,
                    "sample_support_factor": round(min(1.0, (candidate.sample_size / max(1, candidate.eligibility_checks["minimum_pairs"] * 2)) ** 0.5), 6),
                    "stability_factor": 1.0 if candidate.stability_status == "STABLE" else 0.5,
                    "weights": {"correlation": 1.0, "coverage": 1.0, "sample_support": 1.0, "stability": 1.0},
                },
                "raw_correlation": candidate.raw_correlation,
                "adjusted_significance": None,
                "sample_size": candidate.sample_size,
                "missing_observations": candidate.missing_observations,
                "coverage_ratio": candidate.coverage_ratio,
                "selected_lag_days": candidate.optimal_lag_days,
                "lag_candidates_tested": candidate.lag_candidates_tested,
                "tested_lags": candidate.stability_details.get("lag_trials", []),
                "temporal_order": candidate.temporal_order,
                "temporal_order_supported": candidate.temporal_order_supported,
                "stability_status": candidate.stability_status,
                "stability_details": candidate.stability_details,
                "seasonality_control": candidate.seasonality_control,
                "trend_control": candidate.trend_control,
                "eligibility_checks": candidate.eligibility_checks,
                "evidence_references": candidate.evidence_references,
                "limitations": list(candidate.limitations),
                "claim_boundary": "Association only - not an accounting contribution or causal estimate.",
            })
        excluded = [{
            "driver_id": item.driver_id,
            "source_id": item.source_id,
            "reason_code": item.reason_code,
            "reason": item.reason,
            "sample_size": item.sample_size,
            "failed_checks": item.failed_checks,
            "evidence_references": item.evidence_references or [{
                "source_id": item.source_id,
                "target_kpi": target_kpi,
                "period_start": target_period.get("start"),
                "period_end": target_period.get("end"),
                "scope": scope,
            }],
            "missing_observations": item.missing_observations,
            "coverage_ratio": item.coverage_ratio,
            "lag_candidates_tested": item.lag_candidates_tested,
            "tested_lags": item.tested_lags,
        } for item in exclusions]
        represented = [item["driver_id"] for item in ranked] + [item["driver_id"] for item in excluded]
        if sorted(represented) != sorted(candidate_ids) or len(represented) != len(set(represented)):
            raise ValueError("Every governed driver must be represented exactly once as ranked or excluded")
        return {
            "status": status,
            "method": method,
            "target_kpi": target_kpi,
            "target_period": target_period,
            "scope": scope,
            "candidate_count": len(candidate_ids),
            "eligible_count": len(ranked),
            "ranked_count": len(ranked),
            "excluded_count": len(excluded),
            "hypotheses_tested": hypotheses_tested,
            "windows_tested": windows_tested,
            "correction_method": None,
            "limitations": limitations,
            "ranked_drivers": ranked,
            "excluded_drivers": excluded,
        }

    def excluded_analysis(
        self,
        contract: KPIContract,
        *,
        target_kpi: str,
        target_date: str,
        scope: Dict[str, str] | None,
        reason_code: str,
        reason: str,
        status: str,
    ) -> Dict[str, Any]:
        governed = list(contract.candidate_drivers)
        ids = [item["id"] for item in governed]
        excluded = [DriverExclusion(
            driver_id=item["id"],
            source_id=item.get("source", "sales_daily"),
            reason_code=reason_code,
            reason=reason,
            failed_checks=[reason_code.lower()],
        ) for item in governed]
        return self._analysis_contract(
            status,
            "NATIVE_GRAIN_FIRST_DIFFERENCE_LAGGED_PEARSON_ASSOCIATION",
            target_kpi,
            {"start": None, "end": target_date, "window_days": None},
            dict(scope or {}),
            ids,
            [],
            excluded,
            [reason],
            0,
            0,
        )

    def rank_candidates(self, *args, **kwargs) -> List[CandidateDriver]:
        """Backward-compatible ranked-list API; use evaluate_candidates for reasons."""
        return self.evaluate_candidates(*args, **kwargs).candidates
