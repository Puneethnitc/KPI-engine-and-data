# IMPLEMENTATION HANDOFF — seasonal review evidence
# Current: MSTL forecast with prior-only walk-forward errors; fixed calibration
# 21 days, minimum fit 60, default window 90 and trend span 4*period+1.
# Next: resolve supported seasonality/calendars and fit/calibration policy;
# reuse the prepared series, retain chronological calibration and explicit gaps.
# Do not make this branch the primary alert by accident during SQL migration.
# Check: fit never includes target/future values, declared periods are supported,
# missing/non-finite history abstains, and policy changes have held-out evidence.

"""As-of seasonal forecasts calibrated with prior one-step forecast errors."""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import MSTL

from kpi_engine.contracts.metrics import daily_values
from kpi_engine.detection.robust import RobustBaselineDetector


@dataclass(frozen=True)
class SeasonalEvidence:
    status: str
    score: float | None = None
    expected: float | None = None
    is_material: bool = False
    calibration_count: int = 0


class SeasonalForecastDetector:
    """Weekly MSTL forecast, scored against walk-forward errors, never fit on target."""

    calibration_days = 21
    min_fit_days = 60

    @staticmethod
    def _forecast(history: pd.Series, period: int) -> float:
        fit = MSTL(
            history.to_numpy(dtype=float), periods=(period,),
            stl_kwargs={"robust": True, "trend": 4 * period + 1},
        ).fit()
        seasonal = np.asarray(fit.seasonal)
        if seasonal.ndim > 1:
            seasonal = seasonal.sum(axis=1)
        return float(fit.trend[-1] + seasonal[-period])

    def evaluate(self, df, contract, target_date, dimension_slice=None, window_days=90):
        frame = df.copy()
        for column, value in (dimension_slice or {}).items():
            if column not in frame.columns:
                raise ValueError(f"Unknown dimension: {column}")
            frame = frame[frame[column] == value]
        frame["date"] = pd.to_datetime(frame["date"])
        series = daily_values(frame, contract).sort_index()
        target = pd.Timestamp(target_date)
        if target not in series.index or not np.isfinite(series.loc[target]):
            return SeasonalEvidence("NO_DATA_FOR_DATE")
        period = contract.seasonal_period
        if period < 2:
            return SeasonalEvidence("UNSUPPORTED_PERIOD")
        fit_days = max(window_days, contract.min_history_periods, 4 * period)
        min_fit = max(self.min_fit_days, contract.min_history_periods, 4 * period)
        # Each calibration day is forecast using only the days before it.
        errors = []
        for day in pd.date_range(target - pd.Timedelta(days=self.calibration_days),
                                 target - pd.Timedelta(days=1)):
            prior = series[series.index < day].tail(fit_days)
            if (len(prior) < min_fit or prior.index[-1] != day - pd.Timedelta(days=1)
                    or not prior.index.equals(pd.date_range(prior.index[0], day - pd.Timedelta(days=1)))):
                return SeasonalEvidence("INSUFFICIENT_HISTORY")
            observed = series.get(day)
            if observed is None or not np.isfinite(observed):
                return SeasonalEvidence("INSUFFICIENT_HISTORY")
            errors.append(float(observed) - self._forecast(prior, period))
        history = series[series.index < target].tail(fit_days)
        if (len(history) < min_fit or history.index[-1] != target - pd.Timedelta(days=1)
                or not history.index.equals(pd.date_range(history.index[0], target - pd.Timedelta(days=1)))):
            return SeasonalEvidence("INSUFFICIENT_HISTORY")
        forecast = self._forecast(history, period)
        error_center, scale, _ = RobustBaselineDetector.calculate_robust_dispersion(
            pd.Series(errors)
        )
        expected = forecast + error_center
        if not np.isfinite(scale) or scale <= 0:
            return SeasonalEvidence("UNSCORABLE_BASELINE", expected=round(expected, 6),
                                    calibration_count=len(errors))
        actual = float(series.loc[target])
        score = (actual - expected) / scale
        significant = abs(score) >= contract.materiality.z_threshold
        material = abs(actual - expected) >= contract.materiality.abs_threshold
        return SeasonalEvidence("OK", round(score, 4), round(expected, 6),
                                significant and material, len(errors))


# Older public name remains import-compatible.
STLResidualDetector = SeasonalForecastDetector
