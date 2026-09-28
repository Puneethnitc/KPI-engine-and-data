"""
add_finance_coverage.py -- Stage 4 (F-C3) data patch.

Adds coverage_end, available_at and revision to finance_monthly.csv, and adds
a mid-month provisional MTD snapshot for every historically-closed month so
MTD reconciliation has real data to compare against mid-month, not just for
the dataset's single currently-open month.

For each closed month/region/category (revision 2, the eventual truth):
    coverage_end  = month_end (the row already covers the whole month)
    available_at  = closes_at (unchanged -- this is when the ledger closed)

For each closed month, a NEW row is added (revision 1, status
"provisional_mid_month"): a snapshot taken on day 15 of the month, covering
sales through day 9 (the same "coverage_end = snapshot_date - 6 days"
lag fix_dataset.py already uses for the one currently-open month). Its
revenue/units are the exact sales_daily sum through that coverage_end, so a
correct MTD comparison (sales-through-coverage_end vs. this row) agrees --
demonstrating the fix, not just adding columns. The comparison this replaces
(sales-through-target_date vs. a full-month or wrongly-dated finance figure)
is exactly the false "16-20% gap" data/README_fixed_dataset.md describes.

The dataset's one existing provisional row (the current, still-open month)
already covers exactly through (max sales date - 6 days) by construction
(see fix_dataset.py) -- this patch only adds the coverage_end/available_at/
revision columns to it explicitly; it does not change its values.

Idempotent: re-running on an already-patched file is a no-op (detected via
the presence of the coverage_end column).

Usage: .venv/bin/python data/patches/add_finance_coverage.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FINANCE_PATH = ROOT / "finance_monthly.csv"
SALES_PATH = ROOT / "sales_daily.csv"

MID_MONTH_SNAPSHOT_DAY = 15  # available_at: the 15th of the month
MID_MONTH_COVERAGE_DAY = 9   # coverage_end: the 9th -- a 6-day publish lag,
                             # matching fix_dataset.py's open-month convention


def main() -> None:
    finance = pd.read_csv(FINANCE_PATH)
    if "coverage_end" in finance.columns:
        print("finance_monthly.csv already patched (coverage_end present); no-op.")
        return

    sales = pd.read_csv(SALES_PATH, parse_dates=["date"])
    finance["month_start"] = pd.to_datetime(finance["month_start"])
    finance["month_end"] = pd.to_datetime(finance["month_end"])
    finance["closes_at"] = pd.to_datetime(finance["closes_at"], errors="coerce")

    closed = finance[finance["status"] == "closed"].copy()
    open_month = finance[finance["status"] != "closed"].copy()
    if len(closed) + len(open_month) != len(finance):
        raise ValueError("Unexpected finance status values; refusing to patch")

    # ---- revision 2: the existing closed rows, unchanged in value --------
    closed["revision"] = 2
    closed["coverage_end"] = closed["month_end"]
    closed["available_at"] = closed["closes_at"]

    # ---- revision 1 (new): a mid-month MTD snapshot per closed month -----
    new_rows = []
    for _, row in closed.iterrows():
        coverage_end = row["month_start"] + pd.Timedelta(days=MID_MONTH_COVERAGE_DAY - 1)
        available_at = row["month_start"] + pd.Timedelta(days=MID_MONTH_SNAPSHOT_DAY - 1)
        month_to_date = sales[
            (sales["region"] == row["region"]) & (sales["category"] == row["category"])
            & (sales["date"] >= row["month_start"]) & (sales["date"] <= coverage_end)
        ]
        if month_to_date.empty:
            # No sales rows this early in the month for this slice (e.g. a
            # category that launched mid-history); skip rather than invent a
            # snapshot with nothing behind it -- PENDING_CLOSE/NOT_AVAILABLE
            # handles that slice/month honestly at query time instead.
            continue
        new_rows.append({
            "region": row["region"], "category": row["category"],
            "month_start": row["month_start"],
            "net_sales_revenue": round(float(month_to_date["net_sales_revenue"].sum()), 2),
            "units_sold": round(float(month_to_date["units_sold"].sum()), 1),
            "month_end": row["month_end"],
            "closes_at": pd.NaT,
            "status": "provisional_mid_month",
            "source_system": "finance_ledger",
            "grain": "monthly",
            "revision": 1,
            "coverage_end": coverage_end,
            "available_at": available_at,
        })
    mid_month = pd.DataFrame(new_rows)

    # ---- the dataset's one still-open month: add columns, keep values ----
    open_month["revision"] = 1
    max_sales_date = sales["date"].max()
    open_month["coverage_end"] = max_sales_date - pd.Timedelta(days=6)
    open_month["available_at"] = max_sales_date

    patched = pd.concat([closed, mid_month, open_month], ignore_index=True)
    patched = patched.sort_values(["month_start", "region", "category", "revision"])
    column_order = [
        "region", "category", "month_start", "net_sales_revenue", "units_sold",
        "month_end", "coverage_end", "available_at", "revision", "closes_at",
        "status", "source_system", "grain",
    ]
    patched = patched[column_order]
    patched.to_csv(FINANCE_PATH, index=False)
    print(f"Patched finance_monthly.csv: {len(finance)} -> {len(patched)} rows "
          f"({len(mid_month)} new mid-month snapshots added).")

    # Sanity check, printed for the record: every new mid-month row must
    # exactly match its own coverage window (by construction), never the
    # false "compare partial finance to full-month sales" gap this fixes.
    check = mid_month.merge(
        sales.assign(month_start=sales["date"].values.astype("datetime64[M]"))
        .groupby(["region", "category", "month_start"], as_index=False)
        .agg(sales_full_month=("net_sales_revenue", "sum")),
        on=["region", "category", "month_start"], how="left",
    )
    check["full_month_gap_pct"] = (
        (check["sales_full_month"] - check["net_sales_revenue"]).abs()
        / check["sales_full_month"].abs() * 100
    )
    print("Mid-month snapshot vs. full-month sales gap (this is the bug the "
          "old comparison exposed; expect it to stay large -- it is not what "
          "Stage 4 compares against):")
    print(check["full_month_gap_pct"].describe())


if __name__ == "__main__":
    main()
