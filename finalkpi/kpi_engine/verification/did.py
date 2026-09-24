"""As-of difference-in-differences with explicit assumptions and abstention."""

import numpy as np
import pandas as pd
import statsmodels.api as sm

from kpi_engine.contracts.metrics import daily_values
from kpi_engine.verification.models import (
    CausalVerificationResult, VerificationDesign, VerificationSensitivityResult,
)


class CausalVerifier:
    """Check a predeclared treatment against one disjoint control slice.

    A positive result supports the hypothesis conditional on the supplied
    design; observational DiD does not prove an intervention caused the change.
    """

    min_pre_days = 14
    min_post_days = 7
    min_placebo_days = 14

    def verify_sensitivity(self, frame: pd.DataFrame, contract,
                           designs: tuple[VerificationDesign, ...]) -> VerificationSensitivityResult:
        """Evaluate all predeclared controls/window choices without best-case selection."""
        if len(designs) < 2 or any(not isinstance(item, VerificationDesign) for item in designs):
            raise ValueError("Declare at least two verification designs before examining results")
        first = designs[0]
        if any(item.driver_id != first.driver_id or item.treated_slice != first.treated_slice
               or item.treatment_start != first.treatment_start
               or item.expected_driver_direction != first.expected_driver_direction
               or item.expected_outcome_direction != first.expected_outcome_direction
               for item in designs):
            raise ValueError("Sensitivity designs must test the same predeclared hypothesis")
        identities = [(tuple(sorted(item.control_slice.items())), item.pre_start, item.post_end,
                       item.quiet_windows) for item in designs]
        if len(set(identities)) != len(identities):
            raise ValueError("Duplicate sensitivity design")
        results = tuple(self.verify(frame, contract, item) for item in designs)
        if all(result.verdict == "SUPPORTED_CONDITIONAL" for result in results):
            status = "CONSISTENT_CONDITIONAL"
        elif any(result.verdict in {"REJECTED", "INCONCLUSIVE"} for result in results):
            status = "SENSITIVE"
        else:
            status = "UNTESTABLE"
        return VerificationSensitivityResult(status, results, len(results))

    @staticmethod
    def _result(design: VerificationDesign, verdict: str, code: str, reason: str,
                **values) -> CausalVerificationResult:
        return CausalVerificationResult(design.driver_id, verdict, code, reason, **values)

    @staticmethod
    def _slice(frame: pd.DataFrame, dimensions: dict[str, str]) -> pd.DataFrame:
        for column, value in dimensions.items():
            frame = frame[frame[column] == value]
        return frame

    def verify(self, frame: pd.DataFrame, contract, design: VerificationDesign) -> CausalVerificationResult:
        if not isinstance(design, VerificationDesign):
            raise TypeError("Causal verification requires a VerificationDesign")
        if (not design.treated_slice or set(design.treated_slice) != set(design.control_slice)
                or set(design.treated_slice) != set(contract.dimensions)
                or design.treated_slice == design.control_slice
                or set(design.treated_slice) - set(contract.dimensions)):
            return self._result(design, "UNTESTABLE", "INVALID_GROUPS",
                                "Treatment and control must be disjoint, fully specified KPI slices")
        try:
            pre_start = pd.Timestamp(design.pre_start).normalize()
            start = pd.Timestamp(design.treatment_start).normalize()
            end = pd.Timestamp(design.post_end).normalize()
            windows = [(pd.Timestamp(a).normalize(), pd.Timestamp(b).normalize())
                       for a, b in design.quiet_windows]
        except (TypeError, ValueError) as error:
            return self._result(design, "UNTESTABLE", "INVALID_DATES", str(error))
        if (not pre_start < start <= end or len(windows) not in (2, 3)
                or design.expected_outcome_direction not in (-1, 1)
                or design.expected_driver_direction not in (-1, 1)):
            return self._result(design, "UNTESTABLE", "INVALID_DESIGN",
                                "Require ordered dates, 2–3 quiet windows, and predeclared driver/outcome directions")
        if (start - pre_start).days < self.min_pre_days or (end - start).days + 1 < self.min_post_days:
            return self._result(design, "UNTESTABLE", "INSUFFICIENT_WINDOW",
                                "Need at least 14 pre-intervention and 7 post-intervention days")
        windows = sorted(windows)
        for index, (first, last) in enumerate(windows):
            if (last >= pre_start or first > last or
                    (last - first).days + 1 < self.min_placebo_days or
                    (index and first <= windows[index - 1][1])):
                return self._result(design, "UNTESTABLE", "INVALID_PLACEBO_WINDOWS",
                                    "Quiet windows must be disjoint, at least 14 days, and before the pre-period")
        if "date" not in frame:
            return self._result(design, "UNTESTABLE", "MISSING_DATE", "Outcome data has no date")
        data = frame.copy()
        data["date"] = pd.to_datetime(data["date"])
        if set(design.treated_slice) - set(data.columns):
            return self._result(design, "UNTESTABLE", "MISSING_DIMENSION",
                                "Outcome data lacks a declared group dimension")
        treated = daily_values(self._slice(data, design.treated_slice), contract)
        control = daily_values(self._slice(data, design.control_slice), contract)

        def gap(first: pd.Timestamp, last: pd.Timestamp):
            dates = pd.date_range(first, last, freq="D")
            aligned = pd.concat([treated.reindex(dates), control.reindex(dates)], axis=1)
            if aligned.isna().any().any() or not np.isfinite(aligned.to_numpy(dtype=float)).all():
                return None
            return aligned.iloc[:, 0] - aligned.iloc[:, 1]

        pre = gap(pre_start, start - pd.Timedelta(days=1))
        post = gap(start, end)
        placebo_gaps = [gap(first, last) for first, last in windows]
        if pre is None or post is None or any(item is None for item in placebo_gaps):
            return self._result(design, "UNTESTABLE", "INCOMPLETE_OUTCOME",
                                "Every treated and control day must be observed in pre, post, and quiet windows")
        pre_days, post_days = len(pre), len(post)
        driver_specs = {item["id"]: item for item in contract.candidate_drivers}
        spec = driver_specs.get(design.driver_id)
        if spec is None or spec["column"] not in data:
            return self._result(design, "UNTESTABLE", "MISSING_DRIVER",
                                "The declared driver observation is unavailable")

        def exposure_series(dimensions: dict[str, str], dates: pd.DatetimeIndex) -> pd.Series:
            subset = self._slice(data, dimensions)
            if spec["grain"] == "weekly":
                if "week_start" not in subset:
                    return pd.Series(dtype=float).reindex(dates)
                subset = subset[subset["week_start"].notna()].copy()
                subset["week_start"] = pd.to_datetime(subset["week_start"])
                distinct = subset.groupby("week_start")[spec["column"]].nunique(dropna=False)
                if distinct.gt(1).any():
                    raise ValueError("Conflicting weekly driver observations")
                subset = subset.drop_duplicates("week_start")
                return subset.set_index("week_start")[spec["column"]].reindex(dates)
            grouped = subset.groupby("date")[spec["column"]]
            values = (grouped.sum(min_count=1) if spec.get("aggregation", "mean") == "sum"
                      else grouped.mean())
            return values.reindex(dates)

        if spec["grain"] == "weekly":
            if start.dayofweek != 0:
                return self._result(design, "UNTESTABLE", "COARSE_TREATMENT_TIME",
                                    "A weekly driver needs a Monday treatment start; this source cannot resolve a mid-week onset")
            pre_dates = pd.DatetimeIndex([
                day for day in pd.date_range(pre_start, start, freq="W-MON")
                if day + pd.Timedelta(days=6) < start
            ])
            post_dates = pd.DatetimeIndex([
                day for day in pd.date_range(start, end, freq="W-MON")
                if day + pd.Timedelta(days=6) <= end
            ])
            if len(pre_dates) < 3 or len(post_dates) < 2:
                return self._result(design, "UNTESTABLE", "INSUFFICIENT_DRIVER_HISTORY",
                                    "Weekly exposure needs 3 complete pre and 2 complete post weeks")
        else:
            pre_dates = pd.date_range(pre_start, start - pd.Timedelta(days=1))
            post_dates = pd.date_range(start, end)
        try:
            tp = exposure_series(design.treated_slice, pre_dates)
            tq = exposure_series(design.treated_slice, post_dates)
            cp = exposure_series(design.control_slice, pre_dates)
            cq = exposure_series(design.control_slice, post_dates)
        except (KeyError, ValueError) as error:
            return self._result(design, "UNTESTABLE", "INVALID_DRIVER_DATA", str(error))
        if any(item.isna().any() or not np.isfinite(item.to_numpy(dtype=float)).all()
               for item in (tp, tq, cp, cq)):
            return self._result(design, "UNTESTABLE", "INCOMPLETE_DRIVER_EXPOSURE",
                                "Driver observations must cover treated and control pre/post periods")
        driver_effect = float((tq.mean() - tp.mean()) - (cq.mean() - cp.mean()))
        exposure = dict(driver_exposure_effect=round(driver_effect, 6),
                        driver_exposure_periods=len(pre_dates) + len(post_dates))
        if abs(driver_effect) <= 1e-9:
            return self._result(design, "INCONCLUSIVE", "NO_EXPOSURE_CONTRAST",
                                "The proposed driver did not change relative to the control", **exposure)
        if driver_effect * design.expected_driver_direction <= 0:
            return self._result(design, "REJECTED", "DRIVER_DIRECTION_MISMATCH",
                                "The observed driver exposure moved opposite the predeclared hypothesis",
                                **exposure)
        onset_effect = float((tq.iloc[0] - tp.mean()) - (cq.iloc[0] - cp.mean()))
        if onset_effect * design.expected_driver_direction <= 0:
            return self._result(design, "UNTESTABLE", "NO_EXPOSURE_AT_START",
                                "The driver contrast was not present at the declared treatment start",
                                **exposure)
        differences = np.r_[pre.to_numpy(dtype=float), post.to_numpy(dtype=float)]
        post_indicator = np.r_[np.zeros(pre_days), np.ones(post_days)]
        fit = sm.OLS(differences, sm.add_constant(post_indicator)).fit(
            cov_type="HAC", cov_kwds={"maxlags": min(7, pre_days - 1, post_days - 1)}
        )
        effect = float(fit.params[1])
        ci = tuple(float(value) for value in fit.conf_int(alpha=0.05)[1])
        trend = sm.OLS(pre.to_numpy(dtype=float), sm.add_constant(np.arange(pre_days))).fit(
            cov_type="HAC", cov_kwds={"maxlags": min(7, pre_days - 1)}
        )
        slope, trend_p = float(trend.params[1]), float(trend.pvalues[1])
        placebo_effects = []
        for values in placebo_gaps:
            split = len(values) // 2
            placebo_effects.append(float(values.iloc[split:].mean() - values.iloc[:split].mean()))
        evidence = dict(
            **exposure,
            did_effect=round(effect, 6),
            confidence_interval=(round(ci[0], 6), round(ci[1], 6)),
            pretrend_slope=round(slope, 6),
            pretrend_p_value=round(trend_p, 6) if np.isfinite(trend_p) else None,
            pre_event_shift=round(
                float(pre.iloc[-7:].mean() - pre.iloc[:-7].mean()), 6
            ),
            placebo_effects=tuple(round(value, 6) for value in placebo_effects),
            pre_days=pre_days, post_days=post_days,
        )
        if not all(np.isfinite((effect, *ci, slope, *placebo_effects))):
            return self._result(design, "UNTESTABLE", "UNSCORABLE_ESTIMATE",
                                "The effect or its uncertainty could not be estimated", **evidence)
        pre_shift = float(pre.iloc[-7:].mean() - pre.iloc[:-7].mean())
        pre_event_failed = (effect * pre_shift > 0 and abs(pre_shift) >= 0.75 * abs(effect)
                            and abs(pre_shift) > 1e-9)
        trend_failed = abs(slope) > 1e-8 and (not np.isfinite(trend_p) or trend_p < 0.05)
        evidence["temporal_precedence_passed"] = bool(not pre_event_failed and not trend_failed)
        if pre_event_failed:
            return self._result(design, "UNTESTABLE", "PRE_EVENT_MOVEMENT",
                                "A substantial same-direction treated-control shift preceded the declared event",
                                **evidence)
        if trend_failed:
            return self._result(design, "UNTESTABLE", "PRETREND_VIOLATION",
                                "The treated-control gap was already trending before treatment", **evidence)
        if design.expected_outcome_direction is not None and effect * design.expected_outcome_direction <= 0:
            return self._result(design, "REJECTED", "DIRECTION_MISMATCH",
                                "The estimated outcome change is opposite the declared hypothesis", **evidence)
        if ci[0] <= 0 <= ci[1]:
            return self._result(design, "INCONCLUSIVE", "CI_INCLUDES_ZERO",
                                "The HAC 95% interval includes no difference-in-differences effect", **evidence)
        if any(abs(placebo) >= 0.5 * abs(effect) for placebo in placebo_effects):
            return self._result(design, "UNTESTABLE", "PLACEBO_FAILED",
                                "A quiet-window change is too large relative to the event effect", **evidence)
        return self._result(design, "SUPPORTED_CONDITIONAL", "CHECKS_PASSED",
                            "DiD, pretrend, and placebo checks passed for this supplied observational design; causation is not proven",
                            **evidence)
