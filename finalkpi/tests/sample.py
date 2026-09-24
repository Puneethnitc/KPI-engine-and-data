from kpi_engine.normalize import DataNormalizer

normalizer = DataNormalizer()
daily_df, finance_df = normalizer.align_sources(
    sales_path="data/sales_daily.csv",
    marketing_path="data/marketing_weekly.csv",
    finance_path="data/finance_monthly.csv"
)

print(f"Unified Daily Rows: {len(daily_df)}")
print(f"Columns: {list(daily_df.columns)}")
print(f"Lineage Columns Preserved: {'source_system' in daily_df.columns and 'available_at' in daily_df.columns}")