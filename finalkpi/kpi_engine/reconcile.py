# IMPLEMENTATION HANDOFF — source agreement
# Current (Stage 4, F-C3): mode "auto" tries a closed-period comparison first
# (finance row status=closed, month_end is the calendar month end, and the
# target date is the last day of the month), then falls back to an MTD
# snapshot compared through the finance row's own coverage_end -- never
# through target_date, which was the original bug (comparing a partial
# finance figure against a full-or-wrong-window sales total). PENDING_CLOSE
# is a new, neutral status: a finance row is known to exist for this period
# but was not yet available as of the cutoff (distinct from
# NOT_AVAILABLE_FOR_PERIOD, which means overdue or genuinely missing).
# provisional_tolerance_pct (contract-declared, defaults to
# historical_tolerance_pct) widens the AGREED bar for a provisional snapshot,
# since it is expected to be a rougher number than a closed one.
# Next: contract declares both sources/measures, common grain, keys, unit/currency.
# Select a revision at the cutoff before summing. Do not prorate monthly finance.
# The 3.5% and 2.5x defaults are policy; the near-zero reference rule also needs
# an explicit absolute-gap policy so a tiny difference is not always 100%.
# Check: unavailable finance, partial sales, revised snapshots, mismatched units,
# equal aggregate totals hiding offsetting segment discrepancies, and zero totals.

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Dict, Any, Optional

# ---------------------------------------------------------------------------
# Canonical cross-source comparison statuses
# ---------------------------------------------------------------------------
# NOT_APPLICABLE          – no comparable second-source measure is declared for
#                           this KPI; comparison is not expected or meaningful.
# PENDING_CLOSE           – a comparator is declared and known to exist for this
#                           period, but is not yet due/available as of the
#                           cutoff. Neutral for confidence, like NOT_APPLICABLE.
# NOT_AVAILABLE_FOR_PERIOD – a comparator is declared but no valid matching
#                           period/as-of snapshot is available right now, and
#                           it is not a case of "not yet due" (overdue or
#                           genuinely missing). Lowers confidence.
# AGREED                  – comparison is possible; values agree within tolerance.
# DRIFT                   – comparison is possible; values differ beyond tolerance
#                           but below the contradiction boundary.
# CONTRADICTED            – values differ beyond the contradiction boundary; hard
#                           gate preventing unsupported driver attribution.
#
# The legacy NOT_RECONCILED status is never emitted from this module.  It is
# handled in pipeline.py as a backward-compatibility alias if seen from older
# cached results; new results always carry one of the six statuses above.

@dataclass
class ReconciliationVerdict:
    status: str  # One of: NOT_APPLICABLE, PENDING_CLOSE, NOT_AVAILABLE_FOR_PERIOD, AGREED, DRIFT, CONTRADICTED
    gap_pct: Optional[float]
    tolerance_used: float
    details: Dict[str, Any]


class SourceReconciler:
    """Optional cross-source comparison for KPIs that declare a finance comparator.

    Stage 1.5 of the pipeline.  Only KPIs whose contract sets
    ``reconciliation: …`` ever reach this reconciler; all others receive a
    NOT_APPLICABLE verdict without loading finance data.
    """

    @staticmethod
    def calculate_gap_percentage(sales_val: float, finance_val: float) -> float:
        """Formula: gap_% = (|V_sales - V_finance| / V_sales) * 100."""
        if abs(sales_val) < 1e-6:
            return 0.0 if abs(finance_val) < 1e-6 else 100.0
        return (abs(sales_val - finance_val) / abs(sales_val)) * 100.0

    # ------------------------------------------------------------------
    # Canonical verdict constructors
    # ------------------------------------------------------------------

    @staticmethod
    def not_applicable(reason: str, tolerance: float = 3.5) -> ReconciliationVerdict:
        """No comparable second-source measure is declared for this KPI."""
        return ReconciliationVerdict(
            status="NOT_APPLICABLE", gap_pct=None, tolerance_used=tolerance,
            details={"reason": reason},
        )

    @staticmethod
    def not_available_for_period(reason: str, tolerance: float = 3.5) -> ReconciliationVerdict:
        """A comparator is declared but no valid snapshot/period is available."""
        return ReconciliationVerdict(
            status="NOT_AVAILABLE_FOR_PERIOD", gap_pct=None, tolerance_used=tolerance,
            details={"reason": reason},
        )

    @staticmethod
    def pending_close(reason: str, tolerance: float = 3.5) -> ReconciliationVerdict:
        """A comparator exists for this period but is not yet due as of the
        cutoff (Stage 4, F-C3). Neutral for confidence, like NOT_APPLICABLE --
        this is the expected state for most of a month, not a data problem."""
        return ReconciliationVerdict(
            status="PENDING_CLOSE", gap_pct=None, tolerance_used=tolerance,
            details={"reason": reason},
        )

    # Kept for backward compatibility with callers that still use the old name.
    # All internal calls have been updated to the two constructors above.
    @staticmethod
    def not_reconciled(reason: str, tolerance: float = 3.5) -> ReconciliationVerdict:
        """Backward-compatible alias — maps to NOT_AVAILABLE_FOR_PERIOD."""
        return ReconciliationVerdict(
            status="NOT_AVAILABLE_FOR_PERIOD", gap_pct=None, tolerance_used=tolerance,
            details={"reason": reason, "_compat": "mapped_from_not_reconciled"},
        )

    @staticmethod
    def _normalize_mode(mode: Optional[str]) -> str:
        if mode is None:
            return "closed_period"
        normalized = str(mode).strip().lower().replace("-", "_")
        aliases = {
            "closed_month": "closed_period",
            "closed_period": "closed_period",
            "snapshot": "snapshot",
            "mtd_snapshot": "snapshot",
            "as_of_snapshot": "snapshot",
            "asof_snapshot": "snapshot",
            "mtd": "snapshot",
            "auto": "auto",
        }
        return aliases.get(normalized, normalized)

    @staticmethod
    def _normalized_units(frame: pd.DataFrame, unit_column: str = "unit") -> set[str]:
        if unit_column not in frame.columns:
            return set()
        units = frame[unit_column].dropna().astype(str).str.strip()
        return set(units[units != ""])

    @staticmethod
    def _select_latest_revision(frame: pd.DataFrame, dimensions: list[str], revision_field: str = "revision") -> pd.DataFrame:
        if revision_field not in frame.columns:
            return frame
        if frame.empty:
            return frame
        sort_columns = [*dimensions, revision_field]
        if not all(col in frame.columns for col in sort_columns):
            return frame
        frame = frame.sort_values(sort_columns, ascending=[True] * len(dimensions) + [False])
        return frame.drop_duplicates(subset=dimensions, keep="first")

    @staticmethod
    def _pending_close_due_date(
        unfiltered_finance_df: Optional[pd.DataFrame],
        target_year_month: str,
        dimension_slice: Optional[Dict[str, str]],
        as_of: Optional[str],
    ) -> Optional[pd.Timestamp]:
        """The earliest `available_at` still in the future as of the cutoff,
        for a finance row that is known to exist for this period/slice (in
        the full, unfiltered history) -- i.e. genuinely "not due yet", not
        "missing". None if nothing pending is found. Requires the caller to
        supply the unfiltered frame explicitly: `finance_df` passed to
        `reconcile_mtd` is normally already as-of filtered upstream
        (kpi_engine/normalize.py), so a future row is invisible to every
        other code path here by design; this is the one place that
        deliberately looks past that filter, only to answer "is this merely
        not-yet-due" versus "overdue or missing" for the PENDING_CLOSE split.
        """
        if unfiltered_finance_df is None or unfiltered_finance_df.empty or as_of is None:
            return None
        if "date" not in unfiltered_finance_df.columns or "available_at" not in unfiltered_finance_df.columns:
            return None
        frame = unfiltered_finance_df.copy()
        for key, value in (dimension_slice or {}).items():
            if key not in frame.columns:
                return None
            frame = frame[frame[key] == value]
        frame = frame[frame["date"].dt.to_period("M").astype(str) == target_year_month]
        if frame.empty:
            return None
        available_at = pd.to_datetime(frame["available_at"], errors="coerce")
        cutoff = pd.Timestamp(as_of)
        future = available_at[available_at.notna() & (available_at > cutoff)]
        return future.min() if not future.empty else None

    def reconcile_mtd(
        self,
        daily_df: pd.DataFrame,
        finance_df: pd.DataFrame,
        target_year_month: str,
        metric_sales: str = 'net_sales_revenue',
        metric_finance: Optional[str] = None,
        historical_tolerance_pct: float = 3.5,
        contradiction_multiple: float = 2.5,
        target_date: Optional[str] = None,
        dimension_slice: Optional[Dict[str, str]] = None,
        mode: Optional[str] = "closed_period",
        as_of: Optional[str] = None,
        unit_column: str = "unit",
        revision_field: str = "revision",
        require_matching_coverage: bool = True,
        provisional_tolerance_pct: Optional[float] = None,
        unfiltered_finance_df: Optional[pd.DataFrame] = None,
    ) -> ReconciliationVerdict:
        """Compare the same KPI, period and segment when both postings exist.

        mode "closed_period" requires a fully closed month at the requested
        `target_date`. mode "snapshot" compares sales through the finance
        row's own `coverage_end` (never through `target_date`), gated on a
        matching `available_at` cutoff. mode "auto" tries closed_period
        first, then falls back to snapshot.

        Returns one of the six canonical statuses. NOT_APPLICABLE is never
        returned from here (the pipeline sets it before calling this method).
        PENDING_CLOSE and NOT_AVAILABLE_FOR_PERIOD both mean "no comparison
        was made", but PENDING_CLOSE means the comparator is simply not due
        yet (neutral), and requires `unfiltered_finance_df` (the full,
        not-as-of-filtered finance history) to detect -- otherwise this
        degrades to NOT_AVAILABLE_FOR_PERIOD for every not-yet-due case,
        which is still correct, just less informative.
        Data-quality failures map to DRIFT or CONTRADICTED rather than being
        silently treated as unavailability.
        """
        mode_name = self._normalize_mode(mode)
        metric_finance = metric_finance or metric_sales
        provisional_tolerance_pct = (
            historical_tolerance_pct if provisional_tolerance_pct is None else provisional_tolerance_pct
        )
        if mode_name not in ("closed_period", "snapshot", "auto"):
            raise ValueError(f"Unsupported reconciliation mode: {mode_name!r}")

        # ── Missing column in source data → NOT_AVAILABLE_FOR_PERIOD ─────────
        if metric_sales not in daily_df.columns or metric_finance not in finance_df.columns:
            return self.not_available_for_period(
                f"No comparable finance column for {metric_sales}", historical_tolerance_pct
            )

        dimensions = ['region', 'category']
        if any(col not in daily_df.columns or col not in finance_df.columns for col in dimensions):
            return self.not_available_for_period(
                "Comparable region and category keys are required", historical_tolerance_pct
            )

        sales = daily_df.copy()
        finance = finance_df.copy()
        for key, value in (dimension_slice or {}).items():
            if key not in sales.columns or key not in finance.columns:
                return self.not_available_for_period(
                    f"Cannot compare: missing dimension {key}", historical_tolerance_pct
                )
            sales = sales[sales[key] == value]
            finance = finance[finance[key] == value]

        # ── Unit mismatch is a genuine data-quality problem → DRIFT ──────────
        if unit_column in sales.columns or unit_column in finance.columns:
            sales_units = self._normalized_units(sales, unit_column)
            finance_units = self._normalized_units(finance, unit_column)
            if sales_units and finance_units and sales_units != finance_units:
                return ReconciliationVerdict(
                    status="DRIFT",
                    gap_pct=None,
                    tolerance_used=historical_tolerance_pct,
                    details={
                        "reason": f"Sales and finance units differ: {sorted(sales_units)} vs {sorted(finance_units)}",
                        "quality_flag": "UNIT_MISMATCH",
                    },
                )

        cutoff = pd.Timestamp(as_of) if as_of is not None else None
        if mode_name in ("snapshot", "auto"):
            if 'available_at' not in sales.columns or 'available_at' not in finance.columns:
                return self.not_available_for_period(
                    "MTD snapshot requires available_at timestamps on both sources", historical_tolerance_pct
                )
            sales['available_at'] = pd.to_datetime(sales['available_at'], errors='coerce')
            finance['available_at'] = pd.to_datetime(finance['available_at'], errors='coerce')
            if sales['available_at'].isna().any():
                return self.not_available_for_period(
                    "available_at timestamps are required to reconcile an MTD snapshot", historical_tolerance_pct
                )
            if cutoff is not None:
                sales = sales[sales['available_at'] <= cutoff].copy()
                finance = finance[finance['available_at'].notna() & (finance['available_at'] <= cutoff)].copy()

        # Sales must always cover through target_date at the latest; this is
        # a safety cap, not the comparison window itself (that is decided
        # per-mode below, from the finance row's own coverage).
        month_sales_all = sales[sales['date'].dt.to_period('M').astype(str) == target_year_month]
        if target_date is not None:
            month_sales_all = month_sales_all[month_sales_all['date'] <= pd.Timestamp(target_date)]
        if month_sales_all.empty:
            return self.not_available_for_period(
                f"No sales data found for month {target_year_month}", historical_tolerance_pct
            )

        month_finance = finance[finance['date'].dt.to_period('M').astype(str) == target_year_month]
        if month_finance.empty:
            due_date = self._pending_close_due_date(
                unfiltered_finance_df, target_year_month, dimension_slice, as_of,
            ) if mode_name in ("snapshot", "auto") else None
            if due_date is not None:
                return self.pending_close(
                    f"Finance close not due until {due_date.date().isoformat()}",
                    historical_tolerance_pct,
                )
            return self.not_available_for_period(
                f"No finance snapshot available as of the evaluation time for {target_year_month}",
                historical_tolerance_pct,
            )

        if revision_field in month_finance.columns:
            month_finance = self._select_latest_revision(month_finance, dimensions, revision_field)

        # ── Duplicate postings are a genuine quality problem → DRIFT ─────────
        if month_finance.duplicated(subset=dimensions).any():
            return ReconciliationVerdict(
                status="DRIFT",
                gap_pct=None,
                tolerance_used=historical_tolerance_pct,
                details={
                    "reason": "Multiple finance postings exist for this slice and month; select a snapshot first",
                    "quality_flag": "DUPLICATE_FINANCE_POSTINGS",
                },
            )

        if 'month_end' not in month_finance.columns:
            return self.not_available_for_period(
                "Finance period end is missing", historical_tolerance_pct
            )
        finance_end = pd.to_datetime(month_finance['month_end'], errors='coerce')
        if finance_end.isna().any():
            return self.not_available_for_period(
                "Finance period end is missing", historical_tolerance_pct
            )

        full_month_end = pd.Period(target_year_month).end_time.normalize()
        target_is_full_month = (
            target_date is None or pd.Timestamp(target_date).normalize() == full_month_end
        )
        is_closed_status = 'status' not in month_finance.columns or (month_finance['status'] == 'closed').all()
        # A closed row is "available" once the month itself has closed as of
        # the cutoff (finance_end == the calendar month end, status closed),
        # independent of which day within that month target_date happens to
        # ask about -- the reconciled grain is the month, not the day. Strict
        # "closed_period" mode additionally requires target_date to BE the
        # month end (its original, narrower contract); "auto" does not.
        closed_row_available = is_closed_status and (finance_end.dt.normalize() == full_month_end).all()
        closed_available = target_is_full_month and closed_row_available

        comparison_end: Optional[pd.Timestamp] = None
        tolerance = historical_tolerance_pct
        used_mode = mode_name
        if mode_name == "closed_period":
            if not closed_available:
                return self.not_available_for_period(
                    "Finance period does not end on the requested target date — "
                    "independent comparison unavailable for this mid-period date",
                    historical_tolerance_pct,
                )
            comparison_end = full_month_end
        elif mode_name in ("snapshot", "auto"):
            if mode_name == "auto" and closed_row_available:
                comparison_end = full_month_end
                used_mode = "closed_period"
            else:
                if 'coverage_end' not in month_finance.columns:
                    if mode_name == "snapshot":
                        return self.not_available_for_period(
                            "MTD snapshot requires a declared coverage_end on the finance row", historical_tolerance_pct,
                        )
                    return self.not_available_for_period(
                        "No closed or snapshot comparison is available for this period", historical_tolerance_pct,
                    )
                coverage_end_values = pd.to_datetime(month_finance['coverage_end'], errors='coerce')
                if coverage_end_values.isna().any() or coverage_end_values.dt.normalize().nunique() != 1:
                    return self.not_available_for_period(
                        "MTD snapshot coverage_end is missing or inconsistent across the requested slice",
                        historical_tolerance_pct,
                    )
                comparison_end = coverage_end_values.iloc[0].normalize()
                used_mode = "snapshot"
                tolerance = historical_tolerance_pct if is_closed_status else provisional_tolerance_pct

        month_sales = month_sales_all[month_sales_all['date'] <= comparison_end]
        if month_sales.empty:
            return self.not_available_for_period(
                f"No sales data found through {comparison_end.date()} for {target_year_month}", historical_tolerance_pct
            )

        sales_keys = set(map(tuple, month_sales[dimensions].drop_duplicates().to_numpy()))
        finance_keys = set(map(tuple, month_finance[dimensions].drop_duplicates().to_numpy()))
        if sales_keys != finance_keys:
            return self.not_available_for_period(
                "Sales and finance cover different region/category slices", historical_tolerance_pct
            )
        if month_sales.duplicated(subset=['date', *dimensions]).any():
            return ReconciliationVerdict(
                status="DRIFT",
                gap_pct=None,
                tolerance_used=tolerance,
                details={
                    "reason": "Duplicate sales rows exist at daily slice grain",
                    "quality_flag": "DUPLICATE_SALES_ROWS",
                },
            )

        first_day = pd.Period(target_year_month).start_time.normalize()
        expected_days = len(pd.date_range(first_day, comparison_end, freq='D'))
        coverage = month_sales.groupby(dimensions)['date'].agg(['min', 'max', 'nunique'])
        if require_matching_coverage and ((coverage['min'] != first_day) | (coverage['max'] != comparison_end) |
                (coverage['nunique'] != expected_days)).any():
            return self.not_available_for_period(
                "Sales daily coverage is incomplete for the finance period", historical_tolerance_pct
            )

        sales_values = pd.to_numeric(month_sales[metric_sales], errors='coerce')
        finance_values = pd.to_numeric(month_finance[metric_finance], errors='coerce')

        # ── Non-finite values are a genuine quality problem → DRIFT ──────────
        if not np.isfinite(sales_values.to_numpy(dtype=float)).all() or not np.isfinite(finance_values.to_numpy(dtype=float)).all():
            return ReconciliationVerdict(
                status="DRIFT",
                gap_pct=None,
                tolerance_used=tolerance,
                details={
                    "reason": "Missing or non-finite KPI values prevent a clean comparison",
                    "quality_flag": "NON_FINITE_VALUES",
                },
            )

        sales_mtd_total = float(sales_values.sum())
        finance_total = float(finance_values.sum())

        gap_pct = self.calculate_gap_percentage(sales_mtd_total, finance_total)

        if gap_pct <= tolerance:
            status = "AGREED"
        elif gap_pct <= (tolerance * contradiction_multiple):
            status = "DRIFT"
        else:
            status = "CONTRADICTED"

        revision_used = None
        if revision_field in month_finance.columns and not month_finance.empty:
            revision_used = int(month_finance[revision_field].iloc[0])

        return ReconciliationVerdict(
            status=status,
            gap_pct=round(gap_pct, 2),
            tolerance_used=tolerance,
            details={
                "sales_mtd_total": round(sales_mtd_total, 2),
                "finance_total": round(finance_total, 2),
                "year_month": target_year_month,
                "sales_column_used": metric_sales,
                "finance_column_used": metric_finance,
                "segment": dimension_slice or {},
                "mode": used_mode,
                "comparison_window": {
                    "start": first_day.date().isoformat(),
                    "end": comparison_end.date().isoformat(),
                },
                "finance_revision": revision_used,
                "finance_status": (
                    month_finance['status'].iloc[0] if 'status' in month_finance.columns and not month_finance.empty else None
                ),
            }
        )
