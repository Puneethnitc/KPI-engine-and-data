"""
fix_dataset.py
Takes the original single-table kpi_dataset.csv and reshapes it into what the
hackathon brief actually asks for:

  1. sales_daily.csv        -- daily grain, "operational" system, refreshes same day
  2. marketing_weekly.csv   -- weekly grain, refreshes T+2 days after week end
  3. finance_monthly.csv    -- monthly grain, refreshes T+5 days after month close,
                                and the CURRENT (most recent) month is deliberately
                                a partial/lagged snapshot -> creates a real,
                                demoable "sources disagree" reconciliation moment
  4. unstructured_evidence.csv -- synthetic tickets / promo-calendar / news snippets
                                   timed to the 6 ground-truth event windows
  5. sparse_launch appended to sales_daily -- a brand-new "Beauty" category with
     only 30 days of history (all regions), for the sparse-history scenario
  6. access_control.csv -- row-level ownership tags per region, for the
     role-based-security scenario

Everything here is derived from / appended to the original kpi_dataset.csv --
the underlying causal structure and the 6 ground-truth events are untouched.
"""
import pandas as pd
import numpy as np

rng = np.random.default_rng(42)

df = pd.read_csv("kpi_dataset.csv", parse_dates=["date"])
events = pd.read_csv("ground_truth_events.csv", parse_dates=["start_date", "end_date"])

# ---------------------------------------------------------------------------
# 1. SPARSE-HISTORY SEGMENT: a brand-new "Beauty" category, all 4 regions,
#    only the last 30 days of the dataset's timeline. No ad-stock/seasonality
#    machinery -- it's meant to look like a product that hasn't accumulated
#    enough history to build a reliable seasonal baseline yet.
# ---------------------------------------------------------------------------
last_date = df["date"].max()
launch_dates = pd.date_range(last_date - pd.Timedelta(days=29), last_date, freq="D")
regions = df["region"].unique()

beauty_rows = []
for region in regions:
    base_traffic = rng.uniform(600, 900)
    for d in launch_dates:
        traffic_organic = base_traffic * rng.normal(1.0, 0.12)
        traffic_paid = base_traffic * 0.25 * rng.normal(1.0, 0.15)
        traffic_direct = base_traffic * 0.05 * rng.normal(1.0, 0.2)
        traffic_total = traffic_organic + traffic_paid + traffic_direct
        conv = max(0.005, rng.normal(0.025, 0.004))
        orders = traffic_total * conv
        units = orders * rng.normal(1.9, 0.1)
        aov = max(15, rng.normal(38, 4))
        stock = 1.0
        beauty_rows.append(dict(
            date=d, region=region, category="Beauty",
            day_of_week=d.dayofweek, month=d.month,
            marketing_spend=round(base_traffic * 0.4, 2),
            adstock_marketing=round(base_traffic * 0.4, 2),
            email_sends=int(rng.integers(500, 1500)),
            traffic_organic=round(traffic_organic, 1),
            traffic_paid=round(traffic_paid, 1),
            traffic_direct=round(traffic_direct, 1),
            traffic_total=round(traffic_total, 1),
            traffic_online=round(traffic_total * 0.68, 1),
            traffic_instore=round(traffic_total * 0.22, 1),
            traffic_wholesale=round(traffic_total * 0.10, 1),
            price_discount_depth=0.0, promo_flag=0,
            stock_availability=stock,
            checkout_latency_ms=round(rng.normal(300, 20), 1),
            conversion_rate=round(conv, 5),
            orders=round(orders, 1),
            units_sold=round(units, 1),
            lost_units_stockout=0.0,
            aov=round(aov, 2),
            net_sales_revenue=round(units * aov, 2),
            weather_temp_c=round(rng.normal(15, 5), 1),
            competitor_price_index=round(rng.normal(100, 2), 2),
        ))
beauty_df = pd.DataFrame(beauty_rows)

sales_full = pd.concat([df, beauty_df], ignore_index=True).sort_values(
    ["date", "region", "category"]
).reset_index(drop=True)

# ---------------------------------------------------------------------------
# 2. SALES_DAILY (source A) -- the operational system. Daily grain.
#    Refresh cadence: same-day, available next morning (T+1, 06:00).
# ---------------------------------------------------------------------------
sales_cols = [
    "date", "region", "category", "day_of_week", "month",
    "orders", "units_sold", "lost_units_stockout", "aov", "net_sales_revenue",
    "stock_availability", "checkout_latency_ms", "conversion_rate",
    "traffic_online", "traffic_instore", "traffic_wholesale",
    "price_discount_depth", "promo_flag",
]
sales_daily = sales_full[sales_cols].copy()
sales_daily["source_system"] = "sales_ops_db"
sales_daily["grain"] = "daily"
sales_daily["available_at"] = sales_daily["date"] + pd.Timedelta(days=1, hours=6)
sales_daily.to_csv("sales_daily.csv", index=False)

# ---------------------------------------------------------------------------
# 3. MARKETING_WEEKLY (source B) -- weekly grain, aggregated from daily.
#    Refresh cadence: the ad platform's weekly report lands T+2 days after
#    the week (Mon-Sun) ends.
# ---------------------------------------------------------------------------
mk = sales_full[[
    "date", "region", "category", "marketing_spend", "adstock_marketing",
    "email_sends", "traffic_organic", "traffic_paid", "traffic_direct",
    "traffic_total",
]].copy()
mk["week_start"] = mk["date"] - pd.to_timedelta(mk["date"].dt.dayofweek, unit="D")
marketing_weekly = (
    mk.groupby(["region", "category", "week_start"], as_index=False)
    .agg(
        marketing_spend=("marketing_spend", "sum"),
        adstock_marketing=("adstock_marketing", "mean"),
        email_sends=("email_sends", "sum"),
        traffic_organic=("traffic_organic", "sum"),
        traffic_paid=("traffic_paid", "sum"),
        traffic_direct=("traffic_direct", "sum"),
        traffic_total=("traffic_total", "sum"),
    )
)
marketing_weekly["week_end"] = marketing_weekly["week_start"] + pd.Timedelta(days=6)
marketing_weekly["source_system"] = "ad_platform_export"
marketing_weekly["grain"] = "weekly"
marketing_weekly["available_at"] = marketing_weekly["week_end"] + pd.Timedelta(days=2, hours=9)
marketing_weekly = marketing_weekly[[
    "week_start", "week_end", "region", "category", "marketing_spend",
    "adstock_marketing", "email_sends", "traffic_organic", "traffic_paid",
    "traffic_direct", "traffic_total", "source_system", "grain", "available_at",
]]
marketing_weekly.to_csv("marketing_weekly.csv", index=False)

# ---------------------------------------------------------------------------
# 4. FINANCE_MONTHLY (source C) -- monthly grain, the "ledger of record".
#    Refresh cadence: closes T+5 days after month end. Historically-closed
#    months are final and match sales_daily's rollup exactly. But the
#    CURRENT (most recent, still-open) month is a genuinely different,
#    partial number -- finance has only ingested data through a cutoff a
#    few days before the snapshot date. This is a deliberate, demoable
#    "why don't the two systems agree" reconciliation case.
# ---------------------------------------------------------------------------
sales_full["month_start"] = sales_full["date"].values.astype("datetime64[M]")
monthly_true = (
    sales_full.groupby(["region", "category", "month_start"], as_index=False)
    .agg(net_sales_revenue=("net_sales_revenue", "sum"), units_sold=("units_sold", "sum"))
)
monthly_true["month_end"] = monthly_true["month_start"] + pd.offsets.MonthEnd(0)
monthly_true["closes_at"] = monthly_true["month_end"] + pd.Timedelta(days=5, hours=18)

# the most recent month in the dataset is treated as still "open": finance's
# figure only reflects data through 6 days before the true month end
last_month_start = monthly_true["month_start"].max()
open_month_cutoff = sales_full[
    (sales_full["month_start"] == last_month_start)
    & (sales_full["date"] <= (sales_full["date"].max() - pd.Timedelta(days=6)))
]
open_month_partial = (
    open_month_cutoff.groupby(["region", "category"], as_index=False)
    .agg(net_sales_revenue=("net_sales_revenue", "sum"), units_sold=("units_sold", "sum"))
)
open_month_partial["month_start"] = last_month_start
open_month_partial["month_end"] = last_month_start + pd.offsets.MonthEnd(0)
open_month_partial["closes_at"] = pd.NaT  # not yet closed -> as-of snapshot only

finance_monthly = pd.concat(
    [monthly_true[monthly_true["month_start"] != last_month_start], open_month_partial],
    ignore_index=True,
)
finance_monthly["status"] = np.where(
    finance_monthly["closes_at"].isna(), "provisional_open_month", "closed"
)
finance_monthly["source_system"] = "finance_ledger"
finance_monthly["grain"] = "monthly"
finance_monthly = finance_monthly.sort_values(["month_start", "region", "category"])
finance_monthly.to_csv("finance_monthly.csv", index=False)

# ---------------------------------------------------------------------------
# 5. UNSTRUCTURED EVIDENCE -- short synthetic tickets / promo-calendar /
#    news snippets, timed inside the 6 ground-truth event windows, so the
#    retrieval layer has something real to find and cite.
# ---------------------------------------------------------------------------
def d(date_str):
    return pd.Timestamp(date_str)

docs = [
    # EVT01: North/Electronics, marketing cut, 2023-07-20 to 2023-08-13
    dict(doc_id="TCK-1001", date=d("2023-07-24"), source_type="support_ticket",
         region="North", category="Electronics",
         text="Regional marketing lead flagged that the Electronics paid-search budget "
              "for North was cut ~90% starting this week as part of a Q3 budget reallocation."),
    dict(doc_id="TCK-1002", date=d("2023-08-02"), source_type="internal_note",
         region="North", category="Electronics",
         text="Paid traffic for North Electronics down sharply again this week. Confirmed "
              "with growth team: campaign budget was paused, not a tracking issue."),

    # EVT02: ALL/Home, flash discount, 2023-10-28 to 2023-11-06
    dict(doc_id="PROMO-2001", date=d("2023-10-27"), source_type="promo_calendar",
         region="ALL", category="Home",
         text="Flash sale scheduled: 30% off all Home category items, all regions, "
              "Oct 28 - Nov 6. Expected to lift units meaningfully despite lower AOV."),
    dict(doc_id="NEWS-2002", date=d("2023-10-29"), source_type="news",
         region="ALL", category="Home",
         text="Retailer's autumn Home flash sale drew strong early traffic according to "
              "industry trackers, with heavy discounting across furniture and decor lines."),

    # EVT03: South/Apparel, stockout, 2024-02-05 to 2024-02-16
    dict(doc_id="TCK-3001", date=d("2024-02-06"), source_type="support_ticket",
         region="South", category="Apparel",
         text="Multiple customer complaints: Apparel items showing in-stock online but "
              "unavailable at South region fulfillment center. Warehouse confirms supply "
              "disruption from vendor."),
    dict(doc_id="TCK-3002", date=d("2024-02-10"), source_type="support_ticket",
         region="South", category="Apparel",
         text="Ongoing stockout in South Apparel, vendor delay now entering second week. "
              "Fulfillment estimates 15% of normal stock on hand."),

    # EVT04: ALL/ALL, checkout latency spike, 2024-05-15 to 2024-05-18
    dict(doc_id="TCK-4001", date=d("2024-05-15"), source_type="internal_note",
         region="ALL", category="ALL",
         text="Engineering incident opened: checkout API latency spiked ~5x starting today "
              "after a payment-gateway config change. Online conversion impact expected; "
              "in-store/wholesale unaffected."),
    dict(doc_id="TCK-4002", date=d("2024-05-18"), source_type="internal_note",
         region="ALL", category="ALL",
         text="Checkout latency incident resolved as of today, rollback of the payment "
              "gateway config deployed last night."),

    # EVT05: East/Electronics, marketing burst low impact, 2024-07-14 to 2024-07-29
    dict(doc_id="PROMO-5001", date=d("2024-07-13"), source_type="promo_calendar",
         region="East", category="Electronics",
         text="East Electronics paid marketing budget doubled starting this week to "
              "capture summer seasonal demand. Team notes this period historically has "
              "strong organic/seasonal lift already."),

    # EVT06: ALL/Apparel, cold snap, 2023-04-11 to 2023-04-23
    dict(doc_id="NEWS-6001", date=d("2023-04-12"), source_type="news",
         region="ALL", category="Apparel",
         text="Unseasonable cold snap moving across the country this week, temperatures "
              "roughly 8-10C below normal for mid-April in multiple regions."),
    dict(doc_id="TCK-6002", date=d("2023-04-15"), source_type="internal_note",
         region="ALL", category="Apparel",
         text="Merchandising team observing a bump in coat and sweater sell-through, "
              "consistent with the cold snap reported earlier this week."),
]
unstructured = pd.DataFrame(docs)
unstructured.to_csv("unstructured_evidence.csv", index=False)

# ---------------------------------------------------------------------------
# 6. ACCESS CONTROL -- row-level ownership tags, for the role-based
#    security scenario. Minimal: one owner persona per region + one
#    global "finance" role that can see all regions but only revenue-level
#    fields (illustrative; enforced in the Data Adapter layer, not here).
# ---------------------------------------------------------------------------
access_control = pd.DataFrame([
    dict(region="North", owner_role="regional_manager_north", can_view_categories="ALL"),
    dict(region="South", owner_role="regional_manager_south", can_view_categories="ALL"),
    dict(region="East", owner_role="regional_manager_east", can_view_categories="ALL"),
    dict(region="West", owner_role="regional_manager_west", can_view_categories="ALL"),
    dict(region="ALL", owner_role="cfo", can_view_categories="ALL"),
])
access_control.to_csv("access_control.csv", index=False)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print("sales_daily.csv        :", sales_daily.shape)
print("marketing_weekly.csv   :", marketing_weekly.shape)
print("finance_monthly.csv    :", finance_monthly.shape)
print("unstructured_evidence.csv:", unstructured.shape)
print("access_control.csv     :", access_control.shape)
print()
print("Sparse-launch segment (Beauty) date range:",
      beauty_df["date"].min().date(), "to", beauty_df["date"].max().date(),
      f"({beauty_df['date'].nunique()} days x {beauty_df['region'].nunique()} regions)")
print()
print("Finance open-month reconciliation gap (sales_daily full month vs finance provisional):")
recon_check = monthly_true[monthly_true["month_start"] == last_month_start][
    ["region", "category", "net_sales_revenue"]
].merge(
    open_month_partial[["region", "category", "net_sales_revenue"]],
    on=["region", "category"], suffixes=("_sales_full_month", "_finance_provisional"),
)
recon_check["gap_pct"] = (
    (recon_check["net_sales_revenue_sales_full_month"] - recon_check["net_sales_revenue_finance_provisional"])
    / recon_check["net_sales_revenue_sales_full_month"] * 100
).round(1)
print(recon_check.head(6).to_string(index=False))
