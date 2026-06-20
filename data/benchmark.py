"""
NIFTY 500 TRI (Total Return Index) benchmark loader.

Loads historical TRI data from user-provided CSV downloaded from
the NSE Indices Historical Data portal.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import BENCHMARK_CSV_PATH, setup_logging

logger = setup_logging("benchmark")


def load_tri_csv(
    csv_path: Optional[Path] = None,
    index_name: str = "NIFTY 500",
) -> pd.DataFrame:
    """
    Load and parse NIFTY 500 TRI data from NSE CSV.

    NSE CSVs typically have these columns:
        Date, Open, High, Low, Close, Shares Traded, Turnover

    The TRI value is usually in the 'Close' column.

    Parameters
    ----------
    csv_path : Path, optional
        Path to the TRI CSV file. Defaults to BENCHMARK_CSV_PATH from config.
    index_name : str
        Name label for the index.

    Returns
    -------
    DataFrame with columns:
        - tri_value: the TRI level
        - daily_return: daily simple return
        - cumulative_return: cumulative return from start
    Index is DatetimeIndex.
    """
    csv_path = csv_path or BENCHMARK_CSV_PATH

    if not csv_path.exists():
        logger.error(
            f"Benchmark TRI CSV not found at {csv_path}. "
            f"Please download from https://www.niftyindices.com/reports/historical-data "
            f"and save as {csv_path}"
        )
        return pd.DataFrame()

    logger.info(f"Loading TRI data from {csv_path}")

    # Try reading with common NSE CSV formats
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        logger.error(f"Failed to read CSV: {e}")
        return pd.DataFrame()

    # Identify date column
    date_col = _find_column(df, ["Date", "date", "DATE", "HistoricalDate"])
    if date_col is None:
        logger.error(f"No date column found. Columns: {list(df.columns)}")
        return pd.DataFrame()

    # Identify TRI / Close column
    # NSE TRI CSVs may have "Close" or "Total Returns Index" or "TRI"
    value_col = _find_column(df, [
        "Close", "close", "CLOSE",
        "Total Returns Index", "TRI", "tri",
        "Closing Index Value", "Index Value",
    ])
    if value_col is None:
        logger.error(f"No value column found. Columns: {list(df.columns)}")
        return pd.DataFrame()

    # Parse
    result = pd.DataFrame()
    result["tri_value"] = pd.to_numeric(df[value_col], errors="coerce")

    # Parse dates. IMPORTANT: do NOT use `dayfirst=True, format="mixed"` here — for
    # ISO 'YYYY-MM-DD' strings that combination flips month/day on every row where
    # the day is <= 12 (e.g. 2011-01-03 -> 2011-03-01), scrambling the series after
    # the chronological sort and injecting spurious +/-30-40% daily "returns"
    # (benchmark vol blew up to ~77%, collapsing beta toward 0 and inflating alpha).
    # Resolve the true format ISO-first so unambiguous dates are never reinterpreted.
    result.index = _parse_dates(df[date_col])
    result.index.name = "Date"

    # Sort chronologically
    result.sort_index(inplace=True)

    # Remove duplicates and NaN
    result = result[~result.index.duplicated(keep="last")]
    result.dropna(subset=["tri_value"], inplace=True)

    # Compute returns
    result["daily_return"] = result["tri_value"].pct_change()
    result["cumulative_return"] = (1 + result["daily_return"]).cumprod() - 1
    result["index_name"] = index_name

    logger.info(
        f"Loaded {len(result)} days of TRI data: "
        f"{result.index.min().date()} to {result.index.max().date()}"
    )

    return result


def _find_column(df: pd.DataFrame, candidates: list) -> Optional[str]:
    """Find the first matching column name from a list of candidates."""
    for name in candidates:
        if name in df.columns:
            return name
    return None


def _parse_dates(raw: pd.Series) -> pd.DatetimeIndex:
    """Robustly parse a benchmark date column without ever flipping month/day.

    Tries explicit, unambiguous formats most-specific first so an ISO 'YYYY-MM-DD'
    column is parsed as ISO (never day-first). Only falls back to day-first
    inference for genuine DD/MM/YYYY numeric dates (the Indian convention), and
    never uses the `format="mixed"` per-row heuristic that caused the original bug.
    """
    s = raw.astype(str).str.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y", "%d/%m/%Y"):
        parsed = pd.to_datetime(s, format=fmt, errors="coerce")
        if parsed.notna().mean() > 0.95:
            return pd.DatetimeIndex(parsed)
    # Last resort: day-first inference for DD/MM/YYYY; still never US month-first.
    return pd.DatetimeIndex(pd.to_datetime(s, dayfirst=True, errors="coerce"))


def get_benchmark_returns(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    csv_path: Optional[Path] = None,
) -> pd.Series:
    """
    Get benchmark daily returns as a pd.Series for backtesting comparison.

    Returns
    -------
    pd.Series of daily simple returns, indexed by date.
    """
    df = load_tri_csv(csv_path)
    if df.empty:
        logger.warning("No benchmark data available. Returning empty series.")
        return pd.Series(dtype=float)

    returns = df["daily_return"]

    if start_date:
        returns = returns[returns.index >= pd.Timestamp(start_date)]
    if end_date:
        returns = returns[returns.index <= pd.Timestamp(end_date)]

    return returns


def get_benchmark_equity_curve(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    initial_value: float = 100_000.0,
    csv_path: Optional[Path] = None,
) -> pd.Series:
    """
    Get benchmark equity curve starting from initial_value.

    Returns
    -------
    pd.Series of portfolio value, indexed by date.
    """
    returns = get_benchmark_returns(start_date, end_date, csv_path)
    if returns.empty:
        return pd.Series(dtype=float)

    equity = initial_value * (1 + returns).cumprod()
    equity.iloc[0] = initial_value  # first value before any return
    return equity


if __name__ == "__main__":
    df = load_tri_csv()
    if not df.empty:
        print(f"TRI range: {df.index.min().date()} to {df.index.max().date()}")
        print(f"Total rows: {len(df)}")
        print(f"\nLast 5 values:")
        print(df.tail())
    else:
        print("No benchmark data found. Please download TRI CSV.")
