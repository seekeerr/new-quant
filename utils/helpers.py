"""
Utility functions: date handling, logging helpers, and misc tools.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────
# NSE TRADING CALENDAR HELPERS
# ─────────────────────────────────────────────────────────────────────

def get_trading_dates(
    start: str,
    end: str,
    reference_dates: Optional[pd.DatetimeIndex] = None,
) -> pd.DatetimeIndex:
    """
    Return business dates between start and end.
    If reference_dates are provided (actual trading dates from data),
    use those instead of a generic business day calendar.
    """
    if reference_dates is not None:
        mask = (reference_dates >= pd.Timestamp(start)) & (
            reference_dates <= pd.Timestamp(end)
        )
        return reference_dates[mask]
    return pd.bdate_range(start=start, end=end)


def get_rebalance_dates(
    trading_dates: pd.DatetimeIndex,
    frequency: str = "monthly",
) -> pd.DatetimeIndex:
    """
    Generate rebalance dates from a list of trading dates.

    Parameters
    ----------
    trading_dates : DatetimeIndex
        All available trading dates.
    frequency : str
        'weekly' — every Friday (or last trading day of week)
        'biweekly' — every other Friday
        'monthly' — first trading day of each month

    Returns
    -------
    DatetimeIndex of rebalance dates.
    """
    if frequency == "weekly":
        # Group by (year, week), pick last date in each group
        groups = trading_dates.to_series().groupby(
            [trading_dates.isocalendar().year, trading_dates.isocalendar().week]
        )
        rebal = groups.last()
        return pd.DatetimeIndex(rebal.values)

    elif frequency == "biweekly":
        weekly = trading_dates.to_series().groupby(
            [trading_dates.isocalendar().year, trading_dates.isocalendar().week]
        ).last()
        # Take every other week
        return pd.DatetimeIndex(weekly.values[::2])

    elif frequency == "monthly":
        # First trading day of each month
        groups = trading_dates.to_series().groupby(
            [trading_dates.year, trading_dates.month]
        )
        rebal = groups.first()
        return pd.DatetimeIndex(rebal.values)

    elif frequency == "quarterly":
        # First trading day of each quarter (Jan, Apr, Jul, Oct)
        quarter_months = {1, 4, 7, 10}
        monthly = trading_dates.to_series().groupby(
            [trading_dates.year, trading_dates.month]
        ).first()
        quarterly = monthly[
            monthly.apply(lambda d: d.month in quarter_months)
        ]
        return pd.DatetimeIndex(quarterly.values)

    else:
        raise ValueError(f"Unknown rebalance frequency: {frequency}")


# ─────────────────────────────────────────────────────────────────────
# DATA HELPERS
# ─────────────────────────────────────────────────────────────────────

def ensure_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure the DataFrame index is a DatetimeIndex."""
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    return df


def align_dataframes(
    *dfs: pd.DataFrame,
    how: str = "inner",
) -> Tuple[pd.DataFrame, ...]:
    """Align multiple DataFrames on their index (dates)."""
    if len(dfs) < 2:
        return dfs

    common_index = dfs[0].index
    for df in dfs[1:]:
        if how == "inner":
            common_index = common_index.intersection(df.index)
        else:
            common_index = common_index.union(df.index)

    common_index = common_index.sort_values()
    return tuple(df.reindex(common_index) for df in dfs)


def rolling_percentile_rank(
    series: pd.Series,
    window: int = 252,
) -> pd.Series:
    """
    Compute the rolling percentile rank of each value within
    its trailing window. Returns values in [0, 100].
    """
    def _pct_rank(arr):
        if len(arr) < 2 or np.isnan(arr[-1]):
            return np.nan
        val = arr[-1]
        return (np.nansum(arr[:-1] < val) / np.nansum(~np.isnan(arr[:-1]))) * 100

    return series.rolling(window, min_periods=max(20, window // 4)).apply(
        _pct_rank, raw=True
    )


def cross_sectional_percentile_rank(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each row (date), rank columns (stocks) from 0 to 100.
    Uses average method for ties.
    """
    return df.rank(axis=1, pct=True, method="average") * 100


def safe_division(
    numerator: pd.Series,
    denominator: pd.Series,
    fill: float = 0.0,
) -> pd.Series:
    """Safe element-wise division, filling inf/nan with fill value."""
    result = numerator / denominator
    result = result.replace([np.inf, -np.inf], fill)
    return result.fillna(fill)


def round_to_lot_size(shares: float, lot_size: int = 1) -> int:
    """Round shares down to the nearest lot size (1 for Indian equities)."""
    return max(0, int(shares // lot_size) * lot_size)


def format_indian_number(value: float) -> str:
    """Format a number in Indian notation (lakhs, crores)."""
    if abs(value) >= 1_00_00_000:
        return f"₹{value / 1_00_00_000:,.2f} Cr"
    elif abs(value) >= 1_00_000:
        return f"₹{value / 1_00_000:,.2f} L"
    else:
        return f"₹{value:,.0f}"


def pct_to_str(value: float, decimals: int = 2) -> str:
    """Convert decimal ratio to percentage string."""
    return f"{value * 100:.{decimals}f}%"
