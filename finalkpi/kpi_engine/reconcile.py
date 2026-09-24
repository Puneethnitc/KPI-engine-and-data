import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Dict, Any, Optional

@dataclass
class ReconciliationVerdict:
    status: str  # "AGREED", "DRIFT", "CONTRADICTED"
    gap_pct: Optional[float]
    tolerance_used: float
    details: Dict[str, Any]

class SourceReconciler:
    """Stage 1.5: Cross-Source Reconciliation.
    Compares sales_daily running MTD totals against finance_monthly provisional figures
    BEFORE any driver explanation pipeline is allowed to run[cite: 3].
    """
    
    @staticmethod
    def calculate_gap_percentage(sales_val: float, finance_val: float) -> float:
        """Formula: gap_% = (|V_sales - V_finance| / V_sales) * 100[cite: 3]."""
        if abs(sales_val) < 1e-6:
            return 0.0 if abs(finance_val) < 1e-6 else 100.0
        return (abs(sales_val - finance_val) / abs(sales_val)) * 100.0

    @staticmethod
    def not_reconciled(reason: str, tolerance: float = 3.5) -> ReconciliationVerdict:
        return ReconciliationVerdict(
            status="NOT_RECONCILED", gap_pct=None, tolerance_used=tolerance,
            details={"reason": reason},
        )

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
    ) -> ReconciliationVerdict:
        """Compare the same KPI, period and segment when both postings exist.

        The caller must pass frames already filtered by source availability.
        A missing or non-comparable finance posting is never agreement.
        """
        metric_finance = metric_finance or metric_sales
        if metric_sales not in daily_df.columns or metric_finance not in finance_df.columns:
            return self.not_reconciled(f"No comparable finance column for {metric_sales}", historical_tolerance_pct)

        dimensions = ['region', 'category']
        if any(col not in daily_df.columns or col not in finance_df.columns for col in dimensions):
            return self.not_reconciled("Comparable region and category keys are required", historical_tolerance_pct)

        sales = daily_df.copy()
        finance = finance_df.copy()
        for key, value in (dimension_slice or {}).items():
            if key not in sales.columns or key not in finance.columns:
                return self.not_reconciled(f"Cannot reconcile missing dimension {key}", historical_tolerance_pct)
            sales = sales[sales[key] == value]
            finance = finance[finance[key] == value]

        month_sales = sales[sales['date'].dt.to_period('M').astype(str) == target_year_month]
        if target_date is not None:
            month_sales = month_sales[month_sales['date'] <= pd.Timestamp(target_date)]
        
        if month_sales.empty:
            return self.not_reconciled(f"No sales data found for month {target_year_month}", historical_tolerance_pct)

        month_finance = finance[finance['date'].dt.to_period('M').astype(str) == target_year_month]

        if month_finance.empty:
            return self.not_reconciled(
                f"No finance snapshot available as of the evaluation time for {target_year_month}",
                historical_tolerance_pct,
            )

        if month_finance.duplicated(subset=dimensions).any():
            return self.not_reconciled("Multiple finance postings exist for this slice and month; select a snapshot first", historical_tolerance_pct)
        if month_sales.duplicated(subset=['date', *dimensions]).any():
            return self.not_reconciled("Duplicate sales rows exist at daily slice grain", historical_tolerance_pct)
        if 'month_end' not in month_finance.columns:
            return self.not_reconciled("Finance period end is missing", historical_tolerance_pct)
        finance_end = pd.to_datetime(month_finance['month_end'], errors='coerce')
        comparison_end = pd.Timestamp(target_date).normalize() if target_date else finance_end.max()
        if finance_end.isna().any() or not (finance_end.dt.normalize() == comparison_end).all():
            return self.not_reconciled("Finance period does not end on the requested target date", historical_tolerance_pct)

        sales_keys = set(map(tuple, month_sales[dimensions].drop_duplicates().to_numpy()))
        finance_keys = set(map(tuple, month_finance[dimensions].drop_duplicates().to_numpy()))
        if sales_keys != finance_keys:
            return self.not_reconciled("Sales and finance cover different region/category slices", historical_tolerance_pct)

        first_day = pd.Period(target_year_month).start_time.normalize()
        expected_days = len(pd.date_range(first_day, comparison_end, freq='D'))
        coverage = month_sales.groupby(dimensions)['date'].agg(['min', 'max', 'nunique'])
        if ((coverage['min'] != first_day) | (coverage['max'] != comparison_end) |
                (coverage['nunique'] != expected_days)).any():
            return self.not_reconciled("Sales daily coverage is incomplete for the finance period", historical_tolerance_pct)

        sales_values = pd.to_numeric(month_sales[metric_sales], errors='coerce')
        finance_values = pd.to_numeric(month_finance[metric_finance], errors='coerce')
        if not np.isfinite(sales_values.to_numpy(dtype=float)).all() or not np.isfinite(finance_values.to_numpy(dtype=float)).all():
            return self.not_reconciled("Missing or non-finite KPI values prevent reconciliation", historical_tolerance_pct)
        sales_mtd_total = float(sales_values.sum())
        finance_total = float(finance_values.sum())
        
        gap_pct = self.calculate_gap_percentage(sales_mtd_total, finance_total)

        if gap_pct <= historical_tolerance_pct:
            status = "AGREED"
        elif gap_pct <= (historical_tolerance_pct * contradiction_multiple):
            status = "DRIFT"
        else:
            status = "CONTRADICTED"

        return ReconciliationVerdict(
            status=status,
            gap_pct=round(gap_pct, 2),
            tolerance_used=historical_tolerance_pct,
            details={
                "sales_mtd_total": round(sales_mtd_total, 2),
                "finance_total": round(finance_total, 2),
                "year_month": target_year_month,
                "sales_column_used": metric_sales,
                "finance_column_used": metric_finance,
                "segment": dimension_slice or {},
            }
        )
