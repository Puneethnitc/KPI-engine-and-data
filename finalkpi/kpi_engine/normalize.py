import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple

class DataNormalizer:
    """Load source grains and align weekly observations to dated sales rows.
    """

    def __init__(self, source_schemas: Optional[Dict[str, Dict[str, str]]] = None):
        self.source_schemas = source_schemas or {}

    def _read_source(self, filepath: str, source: str) -> pd.DataFrame:
        frame = pd.read_csv(filepath)
        mapping = self.source_schemas.get(source, {})
        if (not isinstance(mapping, dict)
                or any(not isinstance(key, str) or not key or
                       not isinstance(value, str) or not value
                       for key, value in mapping.items())
                or len(set(mapping.values())) != len(mapping)):
            raise ValueError(f"Invalid column mapping for {source}")
        missing = set(mapping.values()) - set(frame.columns)
        if missing:
            raise ValueError(f"{source}: mapped source columns missing: {sorted(missing)}")
        conflicts = (set(mapping) & set(frame.columns)) - set(mapping.values())
        if conflicts:
            raise ValueError(f"{source}: mapped target columns already exist: {sorted(conflicts)}")
        return frame.rename(columns={raw: canonical for canonical, raw in mapping.items()})

    @staticmethod
    def _require_columns(frame: pd.DataFrame, source: str, columns: tuple[str, ...]) -> None:
        missing = set(columns) - set(frame.columns)
        if missing:
            raise ValueError(f"{source}: required columns missing: {sorted(missing)}")

    @staticmethod
    def _require_unique(frame: pd.DataFrame, source: str, columns: list[str]) -> None:
        if frame.duplicated(subset=columns).any():
            raise ValueError(f"{source}: duplicate rows at grain {columns}")
    
    @staticmethod
    def ratio_safe_division(numerator: pd.Series, denominator: pd.Series, epsilon: float = 1e-6) -> pd.Series:
        """Ratio-safe division formula to prevent ZeroDenominator panics[cite: 3]."""
        mask = denominator.abs() <= epsilon
        result = numerator / denominator
        result[mask] = np.nan
        return result

    def load_and_normalize_sales(self, filepath: str, as_of: Optional[pd.Timestamp] = None) -> pd.DataFrame:
        """Load daily sales and preserve its declared source and availability."""
        df = self._read_source(filepath, "sales_daily")
        self._require_columns(df, "sales_daily", ("date", "region", "category", "available_at"))
        df['date'] = pd.to_datetime(df['date'], errors='raise')
        df['available_at'] = pd.to_datetime(df['available_at'], errors='raise')
        if df[['date', 'region', 'category', 'available_at']].isna().any().any():
            raise ValueError("sales_daily: date, dimension, and availability cannot be null")
        if 'grain' in df.columns and not df['grain'].eq('daily').all():
            raise ValueError("sales_daily: declared row grain must be daily")
        if as_of is not None:
            df = df[df['available_at'] <= pd.Timestamp(as_of)].copy()
        self._require_unique(df, "sales_daily", ['date', 'region', 'category'])
        
        if 'aov' not in df.columns and 'units_sold' in df.columns and 'net_sales_revenue' in df.columns:
            df['aov'] = self.ratio_safe_division(df['net_sales_revenue'], df['units_sold'])

        if 'source_system' not in df.columns:
            df['source_system'] = 'sales_daily'
        df['source_grain'] = df['grain'] if 'grain' in df.columns else 'daily'
        return df

    def load_and_normalize_marketing(
        self, filepath: str, daily_date_range: pd.DatetimeIndex,
        as_of: Optional[pd.Timestamp] = None,
    ) -> pd.DataFrame:
        """Repeat weekly observations on their calendar days without dividing values."""
        df = self._read_source(filepath, "marketing_weekly")
        
        self._require_columns(df, "marketing_weekly", ("week_start", "region", "category", "available_at"))
        df['week_start'] = pd.to_datetime(df['week_start'], errors='raise')
        df['available_at'] = pd.to_datetime(df['available_at'], errors='raise')
        if df[['week_start', 'region', 'category', 'available_at']].isna().any().any():
            raise ValueError("marketing_weekly: week, dimension, and availability cannot be null")
        if 'grain' in df.columns and not df['grain'].eq('weekly').all():
            raise ValueError("marketing_weekly: declared row grain must be weekly")
        if 'week_end' in df.columns:
            week_end = pd.to_datetime(df['week_end'], errors='raise')
            if week_end.isna().any() or not week_end.eq(df['week_start'] + pd.Timedelta(days=6)).all():
                raise ValueError("marketing_weekly: week_end must be six days after week_start")
        if as_of is not None:
            df = df[df['available_at'] <= pd.Timestamp(as_of)].copy()
        self._require_unique(df, "marketing_weekly", ['week_start', 'region', 'category'])

        # Carry a weekly observation onto its seven dates for alignment only;
        # its source_grain remains weekly, so it must never be summed as daily spend.
        resampled_df = pd.concat(
            [df.assign(date=df['week_start'] + pd.Timedelta(days=offset)) for offset in range(7)],
            ignore_index=True,
        )
        if 'source_system' not in resampled_df.columns:
            resampled_df['source_system'] = 'marketing_weekly'
        resampled_df['source_grain'] = 'weekly'
        return resampled_df

    def load_and_normalize_finance(self, filepath: str, as_of: Optional[pd.Timestamp] = None) -> pd.DataFrame:
        """Load monthly finance postings with their known availability."""
        df = self._read_source(filepath, "finance_monthly")
        
        self._require_columns(df, "finance_monthly", ("region", "category", "month_end"))
        # Use a declared month field, never an arbitrary first column.
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
        elif 'month' in df.columns:
            df['date'] = pd.to_datetime(df['month'].astype(str) + '-01')
        elif 'month_start' in df.columns:
            df['date'] = pd.to_datetime(df['month_start'])
        elif 'period' in df.columns:
            df['date'] = pd.to_datetime(df['period'].astype(str) + '-01')
        else:
            raise ValueError("finance_monthly: a date, month, month_start, or period column is required")
        df['month_end'] = pd.to_datetime(df['month_end'], errors='raise')
        if df[['date', 'month_end', 'region', 'category']].isna().any().any():
            raise ValueError("finance_monthly: period and dimensions cannot be null")
        if 'grain' in df.columns and not df['grain'].eq('monthly').all():
            raise ValueError("finance_monthly: declared row grain must be monthly")
            
        if 'source_system' not in df.columns:
            df['source_system'] = 'finance_monthly'
        df['source_grain'] = 'monthly'
        # Closed records have a declared posting time. The provisional row in
        # this dataset has no snapshot timestamp, so it cannot be used for a
        # historical as-of claim.
        if 'available_at' in df.columns:
            df['available_at'] = pd.to_datetime(df['available_at'], errors='raise')
        elif 'closes_at' in df.columns:
            df['available_at'] = pd.to_datetime(df['closes_at'], errors='raise')
            if 'status' in df.columns:
                df.loc[df['status'] != 'closed', 'available_at'] = pd.NaT
        else:
            raise ValueError("finance_monthly: available_at or closes_at is required")
        if as_of is not None:
            df = df[df['available_at'] <= pd.Timestamp(as_of)].copy()
        return df

    def align_sources(
        self, 
        sales_path: str, 
        marketing_path: Optional[str],
        finance_path: Optional[str],
        as_of: Optional[pd.Timestamp] = None,
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Align daily sales with available weekly data, keeping finance separate."""
        if as_of is not None:
            as_of = pd.Timestamp(as_of)
        sales_df = self.load_and_normalize_sales(sales_path, as_of=as_of)
        
        finance_df = self.load_and_normalize_finance(finance_path, as_of=as_of) if finance_path else pd.DataFrame()
        if sales_df.empty:
            return sales_df, finance_df

        if marketing_path is None:
            sales_df['marketing_coverage'] = 'NOT_DECLARED'
            return sales_df, finance_df

        min_date = sales_df['date'].min()
        max_date = sales_df['date'].max()
        date_range = pd.date_range(min_date, max_date, freq='D')

        marketing_df = self.load_and_normalize_marketing(marketing_path, date_range, as_of=as_of)

        merge_keys = ['date', 'region', 'category']
        # BUGFIX: both frames also carry 'category'. Without joining on it too,
        # every sales row fans out against every marketing category sharing
        # the same date+region (verified: 3x inflation for 3-category regions,
        # 4x once Beauty exists in Dec 2024 -- a time-varying corruption of
        # every revenue/units number computed downstream of this merge).
        unified_daily = pd.merge(
            sales_df, 
            marketing_df, 
            on=merge_keys, 
            how='left', 
            suffixes=('', '_mkt'),
            validate='one_to_one',
            indicator=True,
        )

        # Guard so this class of bug can't silently reappear: row count in
        # must equal row count out for a left-join keyed on a unique grain.
        if len(unified_daily) != len(sales_df):
            raise ValueError(
                f"align_sources: merge fan-out detected. sales_df had "
                f"{len(sales_df)} rows, unified_daily has {len(unified_daily)}. "
                f"merge_keys={merge_keys} do not uniquely key marketing_df."
            )

        unified_daily['marketing_coverage'] = unified_daily['_merge'].map({
            'both': 'AVAILABLE', 'left_only': 'UNAVAILABLE_OR_MISSING',
        }).astype(str)
        unified_daily = unified_daily.drop(columns=['_merge'])

        return unified_daily, finance_df
