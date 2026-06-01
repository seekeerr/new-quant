"""
Data quality assurance module.

Validates downloaded data, detects anomalies, and reports completeness.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import setup_logging

logger = setup_logging("quality")


@dataclass
class QualityReport:
    """Quality report for a single stock."""
    symbol: str
    total_rows: int = 0
    date_range: str = ""
    missing_days: int = 0
    completeness_pct: float = 0.0
    zero_volume_days: int = 0
    negative_prices: int = 0
    ohlc_violations: int = 0
    suspicious_jumps: int = 0
    issues: List[str] = field(default_factory=list)
    is_usable: bool = True


def check_single_stock(
    symbol: str,
    df: pd.DataFrame,
    trading_dates: Optional[pd.DatetimeIndex] = None,
    min_history_days: int = 252,
) -> QualityReport:
    """
    Run quality checks on a single stock's data.

    Parameters
    ----------
    symbol : str
    df : DataFrame with OHLCV columns and DatetimeIndex
    trading_dates : DatetimeIndex, optional
        Reference trading dates. If None, uses business days.
    min_history_days : int
        Minimum number of data points required.

    Returns
    -------
    QualityReport
    """
    report = QualityReport(symbol=symbol)

    if df.empty:
        report.is_usable = False
        report.issues.append("Empty DataFrame")
        return report

    # Ensure datetime index
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    report.total_rows = len(df)
    report.date_range = f"{df.index.min().date()} to {df.index.max().date()}"

    # ── Check 1: Minimum history ──
    if len(df) < min_history_days:
        report.issues.append(
            f"Insufficient history: {len(df)} days (need {min_history_days})"
        )
        report.is_usable = False

    # ── Check 2: Missing trading days ──
    if trading_dates is not None:
        expected = trading_dates[
            (trading_dates >= df.index.min()) & (trading_dates <= df.index.max())
        ]
        actual = df.index
        missing = expected.difference(actual)
        report.missing_days = len(missing)
        report.completeness_pct = (
            len(actual) / len(expected) * 100 if len(expected) > 0 else 0
        )
        if report.completeness_pct < 80:
            report.issues.append(
                f"Low completeness: {report.completeness_pct:.1f}%"
            )
    else:
        # Approximate using business days
        bdays = pd.bdate_range(df.index.min(), df.index.max())
        report.missing_days = max(0, len(bdays) - len(df))
        report.completeness_pct = (
            len(df) / len(bdays) * 100 if len(bdays) > 0 else 0
        )

    # ── Check 3: Zero volume days ──
    if "Volume" in df.columns:
        zero_vol = (df["Volume"] == 0) | df["Volume"].isna()
        report.zero_volume_days = int(zero_vol.sum())
        if report.zero_volume_days > len(df) * 0.1:
            report.issues.append(
                f"High zero-volume days: {report.zero_volume_days} "
                f"({report.zero_volume_days / len(df) * 100:.1f}%)"
            )

    # ── Check 4: Negative prices ──
    price_cols = [c for c in ["Open", "High", "Low", "Close"] if c in df.columns]
    neg_count = 0
    for col in price_cols:
        neg_count += int((df[col] < 0).sum())
    report.negative_prices = neg_count
    if neg_count > 0:
        report.issues.append(f"Negative prices found: {neg_count}")

    # ── Check 5: OHLC relationship violations ──
    if all(c in df.columns for c in ["Open", "High", "Low", "Close"]):
        violations = (
            (df["Low"] > df["Open"]) |
            (df["Low"] > df["Close"]) |
            (df["High"] < df["Open"]) |
            (df["High"] < df["Close"]) |
            (df["Low"] > df["High"])
        )
        report.ohlc_violations = int(violations.sum())
        if report.ohlc_violations > 10:
            report.issues.append(
                f"OHLC violations: {report.ohlc_violations}"
            )

    # ── Check 6: Suspicious price jumps ──
    if "Close" in df.columns:
        returns = df["Close"].pct_change().abs()
        big_jumps = returns > 0.40  # >40% in a day
        report.suspicious_jumps = int(big_jumps.sum())
        if report.suspicious_jumps > 5:
            report.issues.append(
                f"Suspicious jumps (>40%): {report.suspicious_jumps}"
            )

    return report


def check_all_stocks(
    stock_data: Dict[str, pd.DataFrame],
    min_history_days: int = 252,
) -> Tuple[List[QualityReport], List[str]]:
    """
    Run quality checks on all stocks.

    Returns
    -------
    Tuple of:
        - List of QualityReport objects
        - List of usable symbols (passed all critical checks)
    """
    # Build reference trading dates from the union of all stock dates
    all_dates = pd.DatetimeIndex([])
    for df in stock_data.values():
        if not df.empty:
            idx = pd.to_datetime(df.index)
            all_dates = all_dates.union(idx)
    all_dates = all_dates.sort_values()

    reports = []
    usable_symbols = []

    for sym, df in stock_data.items():
        report = check_single_stock(sym, df, all_dates, min_history_days)
        reports.append(report)
        if report.is_usable:
            usable_symbols.append(sym)

    # Summary
    total = len(reports)
    usable = len(usable_symbols)
    logger.info(
        f"Quality check complete: {usable}/{total} stocks usable "
        f"({total - usable} rejected)"
    )

    # Log rejected stocks
    for r in reports:
        if not r.is_usable:
            logger.debug(f"Rejected {r.symbol}: {', '.join(r.issues)}")

    return reports, usable_symbols


def clean_stock_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean a stock's DataFrame:
    - Forward-fill small gaps (≤3 days)
    - Fix OHLC violations
    - Remove zero/negative close prices

    Returns cleaned DataFrame.
    """
    if df.empty:
        return df

    df = df.copy()

    # Forward-fill small gaps
    df = df.asfreq("B")  # business day frequency
    gap_mask = df["Close"].isna()
    gap_groups = (gap_mask != gap_mask.shift()).cumsum()
    gap_sizes = gap_mask.groupby(gap_groups).transform("sum")
    # Only fill gaps of 3 days or less
    fill_mask = gap_mask & (gap_sizes <= 3)
    df.loc[fill_mask] = df.loc[fill_mask].ffill()

    # Drop remaining NaN rows
    df.dropna(subset=["Close"], inplace=True)

    # Remove zero/negative close
    df = df[df["Close"] > 0]

    # Fix OHLC: ensure Low ≤ Open, Close ≤ High
    if all(c in df.columns for c in ["Open", "High", "Low", "Close"]):
        df["Low"] = df[["Open", "High", "Low", "Close"]].min(axis=1)
        df["High"] = df[["Open", "High", "Low", "Close"]].max(axis=1)

    return df


def print_quality_summary(reports: List[QualityReport]):
    """Print a formatted quality summary table."""
    print(f"\n{'='*80}")
    print(f"{'DATA QUALITY SUMMARY':^80}")
    print(f"{'='*80}")
    print(f"{'Symbol':<12} {'Rows':>6} {'Complete%':>10} {'Zero Vol':>9} "
          f"{'Jumps':>6} {'Issues':>8} {'Status':>8}")
    print(f"{'-'*80}")

    for r in sorted(reports, key=lambda x: x.symbol):
        status = "✓ OK" if r.is_usable else "✗ FAIL"
        print(
            f"{r.symbol:<12} {r.total_rows:>6} {r.completeness_pct:>9.1f}% "
            f"{r.zero_volume_days:>9} {r.suspicious_jumps:>6} "
            f"{len(r.issues):>8} {status:>8}"
        )

    usable = sum(1 for r in reports if r.is_usable)
    print(f"{'-'*80}")
    print(f"Total: {len(reports)} stocks, {usable} usable, "
          f"{len(reports) - usable} rejected")
