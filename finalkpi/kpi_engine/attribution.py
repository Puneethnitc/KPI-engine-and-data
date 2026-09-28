# IMPLEMENTATION HANDOFF — explained-movement attribution (Stage 3, F-R2/F-R3/F-R6/F-R7/F-R8)
# Current: a joint model per grain (daily drivers together; the weekly driver
# in its own weekly-aggregated model) regresses the KPI's deseasonalised
# residual on each driver's deseasonalised residual at a lag chosen once per
# driver on the history window (time-series split out-of-sample fit, never
# the target day). OLS with HAC standard errors is used unless there are more
# than 4 active drivers or VIF > 5, in which case a small-penalty ridge fit
# replaces it (block-bootstrap intervals; no p-values in that case).
# Benjamini-Hochberg corrects the per-driver p-values across drivers x lags
# tried. A driver's contribution is its destandardised beta times its own
# residual movement at the chosen lag, rescaled from log-residual space back
# to the KPI's unit by the KPI's expected value (first-order log-linear
# approximation) when the KPI was deseasonalised in log space.
# Next: Huber-robust regression as an alternative to HAC-OLS; monthly-driver
# contextual handling once a monthly candidate driver is actually declared;
# further sensitivity checks for ridge intervals.
# Check: future rows appended after the fit/exclusion cutoff must not change
# any output; a driver that did not move must never rank; collinear near-
# duplicate drivers must not double count; the linear model's Shapley
# allocation must equal each driver's linear contribution exactly.

"""Joint robust regression that explains a detected movement, not marginal correlation."""

import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.outliers_influence import variance_inflation_factor

from kpi_engine.contracts.metrics import (
    linear_weekday_adjusted_residuals,
    same_weekday_expected,
    weekday_adjusted_residuals,
)
from kpi_engine.contracts.models import KPIContract
from kpi_engine.detection.robust import RobustBaselineDetector
from kpi_engine.rank import CorrelationalRanker, DriverExclusion

MOVED_Z_THRESHOLD = 1.5
RIDGE_PENALTY = 1.0
STABILITY_RATIO_LOW = 0.5
STABILITY_RATIO_HIGH = 2.0


def _deseasonalize(series: pd.Series) -> tuple[pd.Series, str]:
    """Log-ratio residual when the series is strictly positive, else additive."""
    clean = series.dropna()
    if not clean.empty and (clean > 0).all():
        return weekday_adjusted_residuals(series), "LOG"
    return linear_weekday_adjusted_residuals(series), "LINEAR"


def _residual_at(value: Optional[float], expected: Optional[float], kind: str) -> Optional[float]:
    if value is None or expected is None or not np.isfinite(value) or not np.isfinite(expected):
        return None
    if kind == "LOG":
        if value <= 0 or expected <= 0:
            return None
        return float(np.log(value) - np.log(expected))
    return float(value - expected)


@dataclass
class DriverAttribution:
    driver_id: str
    display_name: str
    rank: int
    source_id: str
    source_grain: str
    aggregation: str
    alignment_method: str
    driver_unit: Optional[str]
    controllability: str
    relationship_type: str
    direction: str
    beta: float
    beta_ci: Tuple[Optional[float], Optional[float]]
    lag_days: int
    driver_change: float
    driver_change_z: float
    contribution: float
    contribution_interval: Tuple[Optional[float], Optional[float]]
    explained_share: Optional[float]
    p_value: Optional[float]
    p_value_adj: Optional[float]
    sample_size: int
    coverage_ratio: float
    direction_consistent: Optional[bool]
    temporal_precedence: Optional[bool]
    stability_status: str
    stability_details: Dict[str, Any]
    moved: bool
    offsetting: bool
    grain_adjusted: bool = False
    collinearity_warning: bool = False
    expected_direction: Optional[str] = None
    target_period_available: bool = True
    method: str = "JOINT_ROBUST_REGRESSION_EXPLAINED_MOVEMENT"
    claim_type: str = "ATTRIBUTED_DRIVER"
    limitations: Tuple[str, ...] = ()
    claim_boundary: str = "Statistical attribution of observed movement; causal status is shown separately."
    evidence_references: List[Dict[str, Any]] = field(default_factory=list)
    tested_lags: List[Dict[str, Any]] = field(default_factory=list)
    lag_candidates_tested: int = 0


@dataclass
class AttributionResult:
    ranked_drivers: List[DriverAttribution]
    excluded_drivers: List[DriverExclusion]
    driver_analysis: Dict[str, Any]


class AttributionEngine:
    """Explain a detected movement in KPI units, never a marginal correlation."""

    default_window_days = 180
    default_min_pairs = 14
    default_weekly_min_pairs = 8

    # -- shared series prep -------------------------------------------------

    @staticmethod
    def _daily_kpi_series(frame: pd.DataFrame, contract: KPIContract, calendar: pd.DatetimeIndex) -> pd.Series:
        from kpi_engine.contracts.metrics import daily_values
        return daily_values(frame, contract).reindex(calendar)

    @staticmethod
    def _driver_series(
        frame: pd.DataFrame, driver_id: str, spec: Dict[str, Any],
        driver_columns: Optional[Dict[str, str]], calendar: pd.DatetimeIndex,
    ) -> tuple[Optional[pd.Series], Optional[str], str]:
        column = CorrelationalRanker._resolve_driver_column(frame, driver_id, spec, driver_columns)
        if column not in frame:
            return None, column, "SOURCE_UNAVAILABLE"
        grain = spec.get("grain", "daily")
        aggregation = spec.get("aggregation", "mean")
        if grain == "daily":
            grouped = frame.groupby("date")[column]
            series = (grouped.sum(min_count=1) if aggregation == "sum" else grouped.mean()).reindex(calendar)
            return series, column, "OK"
        if grain == "weekly":
            if "week_start" not in frame:
                return None, column, "SOURCE_UNAVAILABLE"
            rows = frame[frame["week_start"].notna() & frame[column].notna()].copy()
            if rows.empty:
                return None, column, "SOURCE_UNAVAILABLE"
            rows["week_start"] = pd.to_datetime(rows["week_start"])
            keys = [name for name in ("region", "category") if name in rows]
            if rows.groupby(["week_start", *keys])[column].nunique(dropna=False).gt(1).any():
                raise ValueError(f"Conflicting repeated weekly values for {driver_id}")
            rows = rows.drop_duplicates(["week_start", *keys])
            grouped = rows.groupby("week_start")[column]
            series = grouped.sum(min_count=1) if aggregation == "sum" else grouped.mean()
            return series.sort_index(), column, "OK"
        # Monthly candidate drivers are contextual only (plan Stage 3, step B.3);
        # none are declared today, so this path stays an explicit exclusion
        # rather than an unexercised, unverifiable modeling branch.
        return None, column, "MONTHLY_CONTEXTUAL_ONLY"

    @staticmethod
    def _lag_candidates(spec: Dict[str, Any], max_lag: int, interval_days: int) -> List[int]:
        allowed = spec.get("allowed_lags")
        if not allowed:
            return list(range(0, max_lag + 1, interval_days)) or [0]
        lags = sorted(set(int(v) for v in allowed if 0 <= int(v) <= max_lag))
        return lags or [0]

    @staticmethod
    def _time_series_split_lag(
        kpi_resid: pd.Series, driver_resid: pd.Series, lags: List[int], min_pairs: int,
        train_fraction: float = 0.7,
    ) -> tuple[Optional[int], List[Dict[str, Any]], str]:
        """Pick a driver's lag from the best out-of-sample fit on a forward
        time-series split; only when every lag fails that (a driver whose
        entire history is constant except for the one sustained event under
        diagnosis, e.g. EVT03's 12-day stock-availability dip, has no earlier
        variance any forward split could ever train on) fall back to the best
        full-window in-sample fit, flagged IN_SAMPLE_FALLBACK so the limits
        of that estimate are reported, not hidden.
        """
        trials = []
        best_lag, best_score = None, -np.inf
        in_sample_best_lag, in_sample_best_score = None, -np.inf
        for lag in lags:
            paired = pd.concat([kpi_resid, driver_resid.shift(lag)], axis=1, sort=True).dropna()
            paired.columns = ["kpi", "driver"]
            sample_size = int(len(paired))
            trial = {"lag_days": lag, "sample_size": sample_size, "out_of_sample_r2": None, "in_sample_r2": None, "eligible": False}
            if sample_size < min_pairs or paired["driver"].std() < 1e-9:
                trials.append(trial)
                continue
            full_fit = sm.OLS(paired["kpi"].to_numpy(), sm.add_constant(paired[["driver"]].to_numpy())).fit()
            trial["in_sample_r2"] = round(float(full_fit.rsquared), 6)
            if full_fit.rsquared > in_sample_best_score:
                in_sample_best_score, in_sample_best_lag = full_fit.rsquared, lag
            split = max(1, int(sample_size * train_fraction))
            train, test = paired.iloc[:split], paired.iloc[split:]
            if len(test) < 3 or train["driver"].std() < 1e-9:
                trials.append(trial)
                continue
            design = sm.add_constant(train[["driver"]].to_numpy())
            fit = sm.OLS(train["kpi"].to_numpy(), design).fit()
            test_design = sm.add_constant(test[["driver"]].to_numpy(), has_constant="add")
            predicted = fit.predict(test_design)
            residual = test["kpi"].to_numpy() - predicted
            ss_res = float(np.sum(residual ** 2))
            ss_tot = float(np.sum((test["kpi"].to_numpy() - test["kpi"].mean()) ** 2))
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else (-np.inf if ss_res > 1e-12 else 0.0)
            trial.update(out_of_sample_r2=round(r2, 6), eligible=True)
            trials.append(trial)
            if r2 > best_score:
                best_score, best_lag = r2, lag
        if best_lag is not None:
            return best_lag, trials, "OUT_OF_SAMPLE"
        return in_sample_best_lag, trials, "IN_SAMPLE_FALLBACK"

    # -- joint fit ------------------------------------------------------

    @staticmethod
    def _fit_joint(y: pd.Series, design: pd.DataFrame) -> Dict[str, Any]:
        """Fit y ~ standardized design columns; ridge if collinear or >4 drivers."""
        columns = list(design.columns)
        means = design.mean()
        stds = design.std(ddof=0).replace(0, 1.0)
        standardized = (design - means) / stds
        collinearity_warning = False
        vifs: Dict[str, float] = {}
        if len(columns) >= 2:
            values = sm.add_constant(standardized.to_numpy())
            # A poorly-conditioned or rank-deficient design here IS the
            # collinearity this VIF check exists to catch (two near-duplicate
            # drivers, e.g. the collinearity test fixture); it is reported
            # via collinearity_warning below, not worth a runtime warning.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                for index, name in enumerate(columns):
                    try:
                        vifs[name] = float(variance_inflation_factor(values, index + 1))
                    except Exception:
                        vifs[name] = float("nan")
            # A non-finite VIF (singular design) is itself evidence of severe
            # collinearity, not an absence of it -- treat it as a warning too.
            collinearity_warning = any((not np.isfinite(v)) or v > 5 for v in vifs.values())
        use_ridge = collinearity_warning or len(columns) > 4
        if use_ridge:
            X = standardized.to_numpy()
            n, k = X.shape
            X_design = np.column_stack([np.ones(n), X])
            penalty = np.eye(k + 1) * RIDGE_PENALTY
            penalty[0, 0] = 0.0
            beta = np.linalg.solve(X_design.T @ X_design + penalty, X_design.T @ y.to_numpy())
            coefficients = {name: float(beta[i + 1]) for i, name in enumerate(columns)}
            # Weekly circular blocks preserve local time dependence while
            # resampling. The seed makes a saved diagnosis reproducible.
            rng = np.random.default_rng(0)
            block = min(7, n)
            draws = np.empty((128, k), dtype=float)
            outcome = y.to_numpy()
            for draw in range(len(draws)):
                starts = rng.integers(0, n, size=(n + block - 1) // block)
                indices = np.concatenate([(start + np.arange(block)) % n for start in starts])[:n]
                sampled = X_design[indices]
                fitted = np.linalg.solve(sampled.T @ sampled + penalty, sampled.T @ outcome[indices])
                draws[draw] = fitted[1:]
            bounds = np.percentile(draws, [2.5, 97.5], axis=0)
            intervals = {name: (float(bounds[0, i]), float(bounds[1, i])) for i, name in enumerate(columns)}
            return {
                "method": "RIDGE", "collinearity_warning": collinearity_warning, "vif": vifs,
                "beta_std": coefficients, "beta_ci_std": intervals,
                "p_value": {name: None for name in columns}, "stds": {name: float(value) for name, value in stds.to_dict().items()},
            }
        X_design = sm.add_constant(standardized.to_numpy())
        maxlags = max(1, min(7, len(y) // 20))
        fit = sm.OLS(y.to_numpy(), X_design).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
        conf = fit.conf_int(alpha=0.05)
        coefficients = {name: float(fit.params[i + 1]) for i, name in enumerate(columns)}
        ci = {name: (float(conf[i + 1][0]), float(conf[i + 1][1])) for i, name in enumerate(columns)}
        pvalues = {name: float(fit.pvalues[i + 1]) for i, name in enumerate(columns)}
        return {
            "method": "OLS_HAC", "collinearity_warning": collinearity_warning, "vif": vifs,
            "beta_std": coefficients, "beta_ci_std": ci, "p_value": pvalues, "stds": {name: float(value) for name, value in stds.to_dict().items()},
        }

    @staticmethod
    def _stability(y: pd.Series, design: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        if len(y) < 2 * 14 or design.empty:
            return {name: {"status": "NOT_ASSESSED"} for name in design.columns}
        midpoint = len(y) // 2
        halves = []
        for part_y, part_x in ((y.iloc[:midpoint], design.iloc[:midpoint]), (y.iloc[midpoint:], design.iloc[midpoint:])):
            if len(part_y) < max(8, len(design.columns) + 3):
                halves.append(None)
                continue
            try:
                halves.append(AttributionEngine._fit_joint(part_y, part_x))
            except Exception:
                halves.append(None)
        result: Dict[str, Dict[str, Any]] = {}
        for name in design.columns:
            if halves[0] is None or halves[1] is None:
                result[name] = {"status": "NOT_ASSESSED"}
                continue
            beta1 = halves[0]["beta_std"].get(name)
            beta2 = halves[1]["beta_std"].get(name)
            if beta1 is None or beta2 is None or abs(beta1) < 1e-9:
                result[name] = {"status": "NOT_ASSESSED", "first_half_beta": beta1, "second_half_beta": beta2}
                continue
            same_sign = (beta1 >= 0) == (beta2 >= 0)
            ratio = abs(beta2 / beta1)
            stable = same_sign and STABILITY_RATIO_LOW <= ratio <= STABILITY_RATIO_HIGH
            result[name] = {
                "status": "STABLE" if stable else "SENSITIVE",
                "first_half_beta": round(beta1, 6), "second_half_beta": round(beta2, 6),
                "ratio": round(ratio, 4),
            }
        return result

    # -- public entry point ----------------------------------------------

    def attribute(
        self,
        df: pd.DataFrame,
        kpi_col: str,
        candidate_cols: List[str],
        assessment: Any,
        target_date: str,
        window_days: Optional[int] = None,
        driver_columns: Optional[Dict[str, str]] = None,
        contract: Optional[KPIContract] = None,
        scope: Optional[Dict[str, str]] = None,
        as_of: Optional[str] = None,
    ) -> AttributionResult:
        if "date" not in df or contract is None:
            raise ValueError("Attribution requires a date column and KPI contract")
        frame = df.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        target = pd.Timestamp(target_date).normalize()
        specs = {spec["id"]: spec for spec in contract.candidate_drivers}
        candidate_ids = list(dict.fromkeys(candidate_cols)) or list(specs)
        window = window_days or self.default_window_days
        max_lag = max(
            (int(max(spec.get("allowed_lags") or [7])) for spec in specs.values()), default=7,
        )
        # Excluding the single target-date row from the fit is necessary and
        # sufficient to stop the event fitting itself: with y restricted to
        # date < target, no lag shift of any driver can ever read the target
        # day's own observation into a training row. An earlier draft also
        # cut the preceding max_lag days from the window; that blanket cut
        # destroyed the only real signal for a driver that is constant except
        # during one sustained multi-day event straddling the target (e.g.
        # EVT03's 12-day stock_availability dip) -- the days of the SAME
        # event before the target are legitimate history, not leakage.
        fit_end = target - pd.Timedelta(days=1)
        fit_start = fit_end - pd.Timedelta(days=window - 1)
        fit_calendar = pd.date_range(fit_start, fit_end)
        fit_frame = frame[(frame["date"] >= fit_start) & (frame["date"] <= fit_end)].copy()

        kpi_daily = self._daily_kpi_series(fit_frame, contract, fit_calendar)
        kpi_resid, kpi_kind = _deseasonalize(kpi_daily)

        requested_scope = dict(scope or {})
        target_period = {
            "start": fit_start.date().isoformat(), "end": target.date().isoformat(),
            "as_of": as_of, "window_days": window, "max_lag_considered_days": max_lag,
        }
        general_limitations = [
            "Statistical attribution of observed movement; causal status is shown separately.",
            "The fit excludes the target date's own row so the event cannot fit itself.",
            "Lag is chosen once per driver on out-of-sample fit within the history window, not on the target day.",
            "A driver's contribution is a first-order log-linear approximation when the KPI is deseasonalised in log space.",
        ]

        exclusions: List[DriverExclusion] = []
        daily_group: Dict[str, Dict[str, Any]] = {}
        weekly_group: Dict[str, Dict[str, Any]] = {}
        hypotheses_tested = 0

        for driver_id in candidate_ids:
            spec = specs.get(driver_id, {})
            grain = spec.get("grain", "daily")
            interval_days = 7 if grain == "weekly" else 1
            active_max_lag = int(spec.get("max_lag", max_lag)) if isinstance(spec, dict) else max_lag
            min_pairs = int(spec.get("min_pairs", self.default_weekly_min_pairs if grain == "weekly" else self.default_min_pairs))

            fetch_calendar = fit_calendar
            series, column, status = self._driver_series(fit_frame, driver_id, spec, driver_columns, fetch_calendar)
            source_id = spec.get("source", "sales_daily")
            if status == "MONTHLY_CONTEXTUAL_ONLY":
                exclusions.append(DriverExclusion(
                    driver_id, "MONTHLY_CONTEXTUAL_ONLY",
                    "Monthly candidate drivers are contextual only and are not attributed a contribution.",
                    source_id=source_id, failed_checks=["daily_or_weekly_grain"],
                ))
                continue
            if status != "OK" or series is None or series.dropna().empty:
                exclusions.append(DriverExclusion(
                    driver_id, "SOURCE_UNAVAILABLE", f"Declared driver column {column} is unavailable",
                    source_id=source_id, failed_checks=["source_column_available"],
                ))
                continue

            resid, resid_kind = _deseasonalize(series)
            lags = self._lag_candidates(spec, min(active_max_lag, max_lag), interval_days)
            if grain == "weekly":
                lags = sorted(set(lag // interval_days for lag in lags))
            best_lag, trials, lag_method = self._time_series_split_lag(kpi_resid, resid, lags, min_pairs)
            hypotheses_tested += len(trials)
            if best_lag is None:
                observed = max((t["sample_size"] for t in trials), default=0)
                exclusions.append(DriverExclusion(
                    driver_id, "INSUFFICIENT_HISTORY" if observed < min_pairs else "CONSTANT_SERIES",
                    f"No governed lag produced {min_pairs} usable paired changes, in- or out-of-sample",
                    observed, source_id=source_id, failed_checks=["minimum_paired_changes"],
                    lag_candidates_tested=len(trials), tested_lags=trials,
                ))
                continue

            group = weekly_group if grain == "weekly" else daily_group
            group[driver_id] = {
                "spec": spec, "column": column, "series": series, "residual": resid,
                "resid_kind": resid_kind, "lag": best_lag, "lag_days": best_lag * interval_days,
                "interval_days": interval_days, "trials": trials, "source_id": source_id,
                "min_pairs": min_pairs, "lag_method": lag_method,
            }

        ranked: List[DriverAttribution] = []
        collinearity_flag = False
        for group, group_y, group_kind, grain_label, grain_adjusted in (
            (daily_group, kpi_resid, kpi_kind, "daily", False),
            (weekly_group, None, None, "weekly", True),
        ):
            if not group:
                continue
            if grain_label == "weekly":
                weekly_kpi_frame = pd.DataFrame({
                    "week": pd.to_datetime(fit_calendar) - pd.to_timedelta(pd.to_datetime(fit_calendar).dayofweek, unit="D"),
                    "value": kpi_daily.reindex(fit_calendar).to_numpy(),
                })
                weekly_kpi = weekly_kpi_frame.groupby("week")["value"].sum(min_count=1)
                group_y, group_kind = _deseasonalize(weekly_kpi)

            aligned = {}
            for driver_id, info in group.items():
                shifted = info["residual"].shift(info["lag"])
                aligned[driver_id] = shifted
            design = pd.concat(aligned, axis=1).reindex(group_y.index).dropna(how="any")
            common_y = group_y.reindex(design.index).dropna()
            design = design.reindex(common_y.index)
            if design.empty or len(design) < max(info["min_pairs"] for info in group.values()):
                for driver_id, info in group.items():
                    exclusions.append(DriverExclusion(
                        driver_id, "INSUFFICIENT_HISTORY",
                        "No overlapping observations across the joint model's active drivers",
                        int(len(design)), source_id=info["source_id"],
                        failed_checks=["joint_model_overlap"], lag_candidates_tested=len(info["trials"]),
                        tested_lags=info["trials"],
                    ))
                continue

            fitted = AttributionEngine._fit_joint(common_y, design)
            stability = AttributionEngine._stability(common_y, design)
            collinearity_flag = collinearity_flag or fitted["collinearity_warning"]
            raw_pvalues = [fitted["p_value"][name] for name in design.columns]
            adjusted = {}
            testable = [(name, value) for name, value in zip(design.columns, raw_pvalues) if value is not None]
            if testable:
                _, corrected, _, _ = multipletests([value for _, value in testable], method="fdr_bh")
                adjusted = {name: float(value) for (name, _), value in zip(testable, corrected)}

            kpi_expected_value = getattr(assessment, "expected_value", None)
            kpi_unit_multiplier = kpi_expected_value if group_kind == "LOG" and kpi_expected_value else 1.0
            kpi_delta = float(getattr(assessment, "delta", 0.0) or 0.0)

            for driver_id, info in group.items():
                spec = info["spec"]
                std_dev = fitted["stds"].get(driver_id, 1.0) or 1.0
                beta_std = fitted["beta_std"].get(driver_id, 0.0)
                beta_raw = beta_std / std_dev if std_dev else 0.0
                ci_std = fitted["beta_ci_std"].get(driver_id, (None, None))
                beta_ci = (
                    (ci_std[0] / std_dev, ci_std[1] / std_dev)
                    if ci_std[0] is not None and ci_std[1] is not None else (None, None)
                )

                lag_days = info["lag_days"]
                relevant_date = target - pd.Timedelta(days=lag_days)
                full_series_source = df.copy()
                full_series_source["date"] = pd.to_datetime(full_series_source["date"])
                full_series, _, full_status = self._driver_series(
                    full_series_source, driver_id, spec, driver_columns,
                    pd.date_range(min(full_series_source["date"].min(), relevant_date), max(target, relevant_date)),
                )
                target_period_available = full_status == "OK" and full_series is not None and relevant_date in full_series.dropna().index
                if not target_period_available:
                    exclusions.append(DriverExclusion(
                        driver_id, "SOURCE_UNAVAILABLE",
                        "Driver observation is unavailable for the target period at the selected lag",
                        int(len(design)), source_id=info["source_id"],
                        failed_checks=["target_period_driver_available"],
                        lag_candidates_tested=len(info["trials"]), tested_lags=info["trials"],
                    ))
                    continue
                driver_actual = float(full_series.loc[relevant_date])
                driver_history_full = full_series[full_series.index < relevant_date].dropna()
                driver_expected, _ = same_weekday_expected(driver_history_full, relevant_date)
                driver_change_residual = _residual_at(driver_actual, driver_expected, info["resid_kind"])
                driver_change_raw = None if driver_expected is None else driver_actual - driver_expected
                dispersion_center, dispersion_scale, _ = RobustBaselineDetector.calculate_robust_dispersion(info["residual"].dropna())
                if driver_change_residual is None or not np.isfinite(dispersion_scale) or dispersion_scale <= 0:
                    exclusions.append(DriverExclusion(
                        driver_id, "INSUFFICIENT_HISTORY",
                        "Driver movement at the selected lag could not be scored",
                        int(len(design)), source_id=info["source_id"],
                        failed_checks=["driver_movement_scorable"],
                        lag_candidates_tested=len(info["trials"]), tested_lags=info["trials"],
                    ))
                    continue
                driver_change_z = driver_change_residual / dispersion_scale
                moved = bool(abs(driver_change_z) >= MOVED_Z_THRESHOLD)

                contribution = beta_raw * driver_change_residual * kpi_unit_multiplier
                contribution_interval = (
                    (beta_ci[0] * driver_change_residual * kpi_unit_multiplier,
                     beta_ci[1] * driver_change_residual * kpi_unit_multiplier)
                    if beta_ci[0] is not None else (None, None)
                )
                if contribution_interval[0] is not None and contribution_interval[0] > contribution_interval[1]:
                    contribution_interval = (contribution_interval[1], contribution_interval[0])
                explained_share = None if abs(kpi_delta) < 1e-9 else contribution / kpi_delta

                if not moved:
                    exclusions.append(DriverExclusion(
                        driver_id, "DID_NOT_MOVE",
                        f"Driver moved |z|={abs(driver_change_z):.3f}, below the {MOVED_Z_THRESHOLD} threshold "
                        "required to explain any part of the movement.",
                        int(len(design)), source_id=info["source_id"],
                        failed_checks=["driver_moved"],
                        lag_candidates_tested=len(info["trials"]), tested_lags=info["trials"],
                    ))
                    continue

                offsetting = bool(np.sign(contribution) != np.sign(kpi_delta)) and abs(contribution) > 1e-9
                expected_dir = CorrelationalRanker._resolve_expected_direction(spec, requested_scope)
                dir_consistent = None if expected_dir is None else (
                    (beta_raw < 0 and expected_dir == "negative") or (beta_raw > 0 and expected_dir == "positive")
                )
                stability_info = stability.get(driver_id, {"status": "NOT_ASSESSED"})
                temporal_precedence = lag_days > 0 if lag_days is not None else None
                p_value = fitted["p_value"].get(driver_id)
                p_value_adj = adjusted.get(driver_id)

                candidate_limitations = list(general_limitations)
                if info.get("lag_method") == "IN_SAMPLE_FALLBACK":
                    candidate_limitations.append(
                        "This driver's history has no variance outside the event under diagnosis, so its lag "
                        "was chosen by in-sample fit rather than a held-out out-of-sample test."
                    )
                if fitted["method"] == "RIDGE":
                    candidate_limitations.append("Ridge-penalised fit: the contribution interval uses a deterministic seven-day block bootstrap; no p-value is reported.")
                if stability_info.get("status") == "SENSITIVE":
                    candidate_limitations.append("Beta estimate changes materially across the two disjoint history halves.")
                if dir_consistent is False:
                    candidate_limitations.append("Beta sign conflicts with the declared driver hypothesis.")
                if expected_dir is None:
                    candidate_limitations.append("No expected hypothesis direction is declared in the KPI contract.")
                if offsetting:
                    candidate_limitations.append("This driver moved opposite the KPI's direction; it offsets, not explains, the movement.")

                ranked.append(DriverAttribution(
                    driver_id=driver_id,
                    display_name=spec.get("display_name", driver_id.replace("_", " ").title()),
                    rank=0,
                    source_id=info["source_id"], source_grain=grain_label,
                    aggregation=spec.get("aggregation", "mean"),
                    alignment_method=(
                        "daily deseasonalised joint regression" if grain_label == "daily"
                        else "weekly-aggregated deseasonalised regression, pro-rated to the target day"
                    ),
                    driver_unit=spec.get("unit"), controllability=spec.get("controllability", "contextual"),
                    relationship_type="ATTRIBUTION", direction="POSITIVE" if beta_raw >= 0 else "NEGATIVE",
                    beta=round(beta_raw, 8), beta_ci=(
                        None if beta_ci[0] is None else round(beta_ci[0], 8),
                        None if beta_ci[1] is None else round(beta_ci[1], 8),
                    ),
                    lag_days=lag_days,
                    driver_change=round(driver_change_raw, 6) if driver_change_raw is not None else None,
                    driver_change_z=round(driver_change_z, 4),
                    contribution=round(contribution, 6 if contract.aggregation != "sum" else 2),
                    contribution_interval=(
                        None if contribution_interval[0] is None else round(contribution_interval[0], 6 if contract.aggregation != "sum" else 2),
                        None if contribution_interval[1] is None else round(contribution_interval[1], 6 if contract.aggregation != "sum" else 2),
                    ),
                    explained_share=None if explained_share is None else round(explained_share, 4),
                    p_value=None if p_value is None else round(p_value, 6),
                    p_value_adj=None if p_value_adj is None else round(p_value_adj, 6),
                    sample_size=int(len(design)), coverage_ratio=round(len(design) / max(1, len(group_y.dropna())), 4),
                    direction_consistent=dir_consistent, temporal_precedence=temporal_precedence,
                    stability_status=stability_info.get("status", "NOT_ASSESSED"), stability_details=stability_info,
                    moved=moved, offsetting=offsetting, grain_adjusted=grain_adjusted,
                    collinearity_warning=fitted["collinearity_warning"], expected_direction=expected_dir,
                    target_period_available=target_period_available,
                    limitations=tuple(candidate_limitations),
                    evidence_references=[{
                        "source_id": info["source_id"], "date_start": target_period["start"],
                        "date_end": target_period["end"], "driver_column": info["column"], "kpi": kpi_col,
                    }],
                    tested_lags=info["trials"], lag_candidates_tested=len(info["trials"]),
                ))

        ranked.sort(key=lambda item: (item.offsetting, -abs(item.contribution), item.driver_id))
        for index, item in enumerate(ranked):
            item.rank = index + 1

        total_contribution = sum(item.contribution for item in ranked)
        residual = float(getattr(assessment, "delta", 0.0) or 0.0) - total_contribution
        residual_share = None
        kpi_delta = float(getattr(assessment, "delta", 0.0) or 0.0)
        if abs(kpi_delta) > 1e-9:
            residual_share = round(residual / kpi_delta, 4)

        if not candidate_ids:
            status = "NOT_APPLICABLE"
        elif not ranked and not assessment.is_material:
            status = "EXPLORATORY_NON_MATERIAL"
        elif not ranked:
            status = "INSUFFICIENT_EVIDENCE"
        else:
            status = "ASSESSED" if assessment.is_material else "EXPLORATORY_NON_MATERIAL"

        represented = {item.driver_id for item in ranked} | {item.driver_id for item in exclusions}
        if represented != set(candidate_ids) or len(represented) != len(ranked) + len(exclusions):
            raise ValueError("Every governed driver must be represented exactly once as ranked or excluded")

        shapley_check = self._verify_shapley_equivalence(kpi_col, contract.unit, ranked, kpi_delta)

        driver_analysis = {
            "status": status,
            "method": "JOINT_ROBUST_REGRESSION_EXPLAINED_MOVEMENT",
            "target_kpi": kpi_col,
            "target_period": target_period,
            "scope": requested_scope,
            "delta_kpi": round(kpi_delta, 6 if contract.aggregation != "sum" else 2),
            "residual": round(residual, 6 if contract.aggregation != "sum" else 2),
            "residual_share": residual_share,
            "candidate_count": len(candidate_ids),
            "ranked_count": len(ranked),
            "moved_count": sum(1 for item in ranked if item.moved),
            "offsetting_count": sum(1 for item in ranked if item.offsetting),
            "excluded_count": len(exclusions),
            "hypotheses_tested": hypotheses_tested,
            "correction_method": "benjamini_hochberg",
            "collinearity_warning": collinearity_flag,
            "limitations": general_limitations,
            "ranked_drivers": [self._candidate_to_dict(item) for item in ranked],
            "excluded_drivers": [self._exclusion_to_dict(item, target_kpi=kpi_col, target_period=target_period, scope=requested_scope) for item in exclusions],
            "shapley_equivalence_check": shapley_check,
        }
        return AttributionResult(ranked, exclusions, driver_analysis)

    @staticmethod
    def _verify_shapley_equivalence(
        kpi_id: str, unit: str, ranked: List[DriverAttribution], kpi_delta: float,
    ) -> Optional[Dict[str, Any]]:
        """Plan Stage 3, step B.10: for the linear model this engine fits, a
        driver's Shapley allocation must equal its linear contribution c_d
        exactly (up to floating precision), since the coalition value here is
        additive by construction (value(subset) = sum of c_d over the
        subset). ShapleyContributor only accepts 2-4 drivers, so this check
        runs whenever that many drivers moved (ranked, including offsetting).
        """
        from kpi_engine.contribute import ContributionScenario, ShapleyContributor

        movers = [item for item in ranked if item.moved]
        if not 2 <= len(movers) <= 4:
            return None
        driver_ids = tuple(item.driver_id for item in movers)
        contribution_by_id = {item.driver_id: item.contribution for item in movers}

        def coalition_value(subset: tuple) -> float:
            return float(sum(contribution_by_id[driver_id] for driver_id in subset))

        coalition_values = {}
        for size in range(len(driver_ids) + 1):
            from itertools import combinations
            for subset in combinations(driver_ids, size):
                coalition_values[subset] = coalition_value(subset)
        modeled_total = coalition_value(driver_ids)
        scenario = ContributionScenario(kpi_id, unit, driver_ids, coalition_values, modeled_total)
        result = ShapleyContributor.quantify(scenario)
        diffs = {
            contribution.driver_id: abs(contribution.modeled_effect - contribution_by_id[contribution.driver_id])
            for contribution in result.contributions
        }
        max_diff = max(diffs.values(), default=0.0)
        return {
            "drivers_checked": list(driver_ids), "max_abs_diff": round(max_diff, 8),
            "passed": max_diff < 1e-6 * max(1.0, abs(modeled_total)),
        }

    @staticmethod
    def _candidate_to_dict(candidate: DriverAttribution) -> Dict[str, Any]:
        return {
            "rank": candidate.rank, "driver_id": candidate.driver_id, "display_name": candidate.display_name,
            "source_id": candidate.source_id, "source_grain": candidate.source_grain,
            "aggregation": candidate.aggregation, "alignment_method": candidate.alignment_method,
            "driver_unit": candidate.driver_unit, "controllability": candidate.controllability,
            "relationship_type": candidate.relationship_type, "direction": candidate.direction,
            "claim_type": candidate.claim_type, "method": candidate.method,
            "beta": candidate.beta, "beta_ci": list(candidate.beta_ci), "lag_days": candidate.lag_days,
            "driver_change": candidate.driver_change, "driver_change_z": candidate.driver_change_z,
            "contribution": candidate.contribution, "contribution_interval": list(candidate.contribution_interval),
            "explained_share": candidate.explained_share, "p_value": candidate.p_value, "p_value_adj": candidate.p_value_adj,
            "sample_size": candidate.sample_size, "coverage_ratio": candidate.coverage_ratio,
            "selected_lag_days": candidate.lag_days, "lag_candidates_tested": candidate.lag_candidates_tested,
            "tested_lags": candidate.tested_lags,
            "temporal_order": "BEFORE" if candidate.lag_days else "COINCIDENT",
            "temporal_order_supported": candidate.temporal_precedence,
            "direction_consistent": candidate.direction_consistent, "expected_direction": candidate.expected_direction,
            "stability_status": candidate.stability_status, "stability_details": candidate.stability_details,
            "moved": candidate.moved, "offsetting": candidate.offsetting, "grain_adjusted": candidate.grain_adjusted,
            "collinearity_warning": candidate.collinearity_warning,
            "target_period_available": candidate.target_period_available,
            "limitations": list(candidate.limitations), "claim_boundary": candidate.claim_boundary,
            "evidence_references": candidate.evidence_references,
        }

    @staticmethod
    def _exclusion_to_dict(item: DriverExclusion, *, target_kpi: str, target_period: Dict[str, Any], scope: Dict[str, str]) -> Dict[str, Any]:
        return {
            "driver_id": item.driver_id, "source_id": item.source_id, "reason_code": item.reason_code,
            "reason": item.reason, "sample_size": item.sample_size, "failed_checks": item.failed_checks,
            "evidence_references": item.evidence_references or [{
                "source_id": item.source_id, "target_kpi": target_kpi,
                "period_start": target_period.get("start"), "period_end": target_period.get("end"), "scope": scope,
            }],
            "missing_observations": item.missing_observations, "coverage_ratio": item.coverage_ratio,
            "lag_candidates_tested": item.lag_candidates_tested, "tested_lags": item.tested_lags,
        }
