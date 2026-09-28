"""Generate observational designs from attributed drivers and authorised slices."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

import numpy as np
import pandas as pd

from kpi_engine.contracts.metrics import daily_values
from kpi_engine.verification.models import VerificationDesign


@dataclass(frozen=True)
class DesignAttempt:
    driver_id: str
    design: VerificationDesign | None
    reason_code: str | None = None
    controls_rejected: tuple[dict, ...] = ()


class CausalDesigner:
    """Select windows and controls without consulting outcome post-period effects."""

    @staticmethod
    def _slice(frame: pd.DataFrame, scope: dict[str, str]) -> pd.DataFrame:
        for key, value in scope.items():
            frame = frame[frame[key] == value]
        return frame

    @classmethod
    def _driver_series(cls, frame, scope, spec):
        data = cls._slice(frame, scope)
        column = spec["column"]
        if column not in data:
            return pd.Series(dtype=float)
        if spec["grain"] == "weekly":
            data = data.dropna(subset=["week_start", column]).copy()
            if data.empty:
                return pd.Series(dtype=float)
            data["week_start"] = pd.to_datetime(data["week_start"])
            return data.groupby("week_start")[column].mean().sort_index()
        grouped = data.groupby("date")[column]
        return (grouped.sum(min_count=1) if spec.get("aggregation") == "sum"
                else grouped.mean()).sort_index()

    @staticmethod
    def _onset(series: pd.Series, target: pd.Timestamp, direction: int, weekly: bool):
        if series.empty:
            return None
        start = target - pd.Timedelta(days=42)
        series = series[series.index <= target].astype(float)
        for date in series.index[series.index >= start]:
            history = series[series.index < date]
            if weekly:
                history = history.tail(8)
            else:
                history = history[history.index.dayofweek == date.dayofweek].tail(6)
            if len(history) < 4 or not np.isfinite(series.loc[date]):
                continue
            center = float(history.median())
            scale = max(float(np.median(np.abs(history - center))) * 1.4826,
                        abs(center) * 0.01, 1e-9)
            if direction * (float(series.loc[date]) - center) > 1.5 * scale:
                return pd.Timestamp(date).normalize()
        return None

    @classmethod
    def build(cls, frame: pd.DataFrame, contract, driver: dict, target_date: str,
              treated_slice: dict[str, str], persona: str, access_controller) -> DesignAttempt:
        driver_id = driver.get("driver_id")
        spec = next((item for item in contract.candidate_drivers if item["id"] == driver_id), None)
        if spec is None:
            return DesignAttempt(driver_id or "", None, "UNDECLARED_DRIVER")
        if set(treated_slice) != set(contract.dimensions):
            return DesignAttempt(driver_id, None, "NO_VALID_CONTROL")
        data = frame.copy()
        data["date"] = pd.to_datetime(data["date"])
        target = pd.Timestamp(target_date).normalize()
        treated_driver = cls._driver_series(data, treated_slice, spec)
        direction = int(np.sign(driver.get("driver_change") or 0))
        if not direction:
            return DesignAttempt(driver_id, None, "NO_DRIVER_CHANGE")
        weekly = spec["grain"] == "weekly"
        onset = cls._onset(treated_driver, target, direction, weekly)
        if onset is None:
            return DesignAttempt(driver_id, None, "NO_ONSET_DETECTED")
        pre_start = onset - pd.Timedelta(days=42)
        pre_end = onset - pd.Timedelta(days=1)
        if pre_start < data["date"].min():
            return DesignAttempt(driver_id, None, "INSUFFICIENT_PRE_PERIOD")
        treated_pre = treated_driver[(treated_driver.index >= pre_start) & (treated_driver.index <= pre_end)]
        treated_post = treated_driver[(treated_driver.index >= onset) & (treated_driver.index <= target)]
        if treated_pre.empty or treated_post.empty:
            return DesignAttempt(driver_id, None, "INCOMPLETE_DRIVER_EXPOSURE")
        treated_change = float(treated_post.mean() - treated_pre.mean())
        if abs(treated_change) < 1e-9:
            return DesignAttempt(driver_id, None, "NO_DRIVER_CHANGE")
        treated_relative_change = treated_change / max(abs(float(treated_pre.mean())), 1e-9)
        treated_outcome = daily_values(cls._slice(data, treated_slice), contract)
        rejected = []
        valid = []
        authorized_candidates = 0
        slices = data[list(contract.dimensions)].drop_duplicates().to_dict("records")
        slices.sort(key=lambda item: (item.get("category") != treated_slice.get("category"),
                                      item.get("region") != treated_slice.get("region"),
                                      tuple(item.values())))
        for scope in slices:
            if scope == treated_slice:
                continue
            reason = None
            if not access_controller.check(persona, scope).allowed:
                continue
            else:
                authorized_candidates += 1
                control_driver = cls._driver_series(data, scope, spec)
                cp = control_driver[(control_driver.index >= pre_start) & (control_driver.index <= pre_end)]
                cq = control_driver[(control_driver.index >= onset) & (control_driver.index <= target)]
                if cp.empty or cq.empty:
                    reason = "INCOMPLETE_DRIVER_EXPOSURE"
                elif abs(float(cq.mean() - cp.mean()) / max(abs(float(cp.mean())), 1e-9)) > 0.25 * abs(treated_relative_change):
                    reason = "DRIVER_CHANGED"
                else:
                    control_outcome = daily_values(cls._slice(data, scope), contract)
                    dates = pd.date_range(pre_start, pre_end)
                    pair = pd.concat([treated_outcome.reindex(dates), control_outcome.reindex(dates)], axis=1)
                    if pair.isna().any().any() or (pair <= 0).any().any():
                        reason = "INCOMPLETE_PRE_OUTCOME"
                    elif pair.apply(np.log).corr().iloc[0, 1] < 0.6:
                        reason = "LOW_PRE_CORRELATION"
            if reason:
                rejected.append({"slice": scope, "reason": reason})
            else:
                valid.append(scope)
        if not valid:
            reason = "NO_AUTHORIZED_CONTROL" if not authorized_candidates else "NO_VALID_CONTROL"
            return DesignAttempt(driver_id, None, reason, tuple(rejected))
        quiet = ((pre_start - pd.Timedelta(days=35), pre_start - pd.Timedelta(days=22)),
                 (pre_start - pd.Timedelta(days=21), pre_start - pd.Timedelta(days=8)))
        if quiet[0][0] < data["date"].min():
            return DesignAttempt(driver_id, None, "INSUFFICIENT_PLACEBO_HISTORY", tuple(rejected))
        payload = {
            "kpi": contract.kpi_id, "driver": driver_id, "treated": treated_slice,
            "controls": valid, "pre_start": str(pre_start.date()),
            "onset": str(onset.date()), "post_end": str(target.date()),
        }
        design_id = "auto-" + sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
        design = VerificationDesign(
            driver_id=driver_id, treated_slice=treated_slice, control_slice=valid[0],
            control_slices=tuple(valid), controls_rejected=tuple(rejected), design_id=design_id,
            pre_start=pre_start.date().isoformat(), treatment_start=onset.date().isoformat(),
            post_end=target.date().isoformat(),
            quiet_windows=tuple((a.date().isoformat(), b.date().isoformat()) for a, b in quiet),
            expected_driver_direction=direction,
            expected_outcome_direction=direction * (-1 if spec.get("expected_direction") == "negative" else 1),
        )
        return DesignAttempt(driver_id, design, controls_rejected=tuple(rejected))
