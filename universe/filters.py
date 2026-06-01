"""
Universe filters for selecting tradeable stocks.

Applies liquidity, quality, and anti-manipulation filters to
narrow down the NIFTY 500 universe to tradeable stocks.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import UniverseConfig, setup_logging

logger = setup_logging("filters")


@dataclass
class FilterResult:
    """Result of applying filters to the universe."""
    date: pd.Timestamp
    initial_count: int = 0
    after_price: int = 0
    after_liquidity: int = 0
    after_trading_days: int = 0
    after_circuit: int = 0
    after_spread: int = 0
    after_volume_cv: int = 0
    final_count: int = 0
    passed_symbols: List[str] = field(default_factory=list)


def apply_price_filter(
    close_prices: pd.Series,
    min_price: float = 10.0,
    max_price: float = 50_000.0,
) -> pd.Index:
    """
    Filter stocks by price range.

    Parameters
    ----------
    close_prices : Series
        Close prices for all stocks on the filter date (index = symbols).
    """
    mask = (close_prices >= min_price) & (close_prices <= max_price) & close_prices.notna()
    return close_prices[mask].index


def apply_liquidity_filter(
    close_panel: pd.DataFrame,
    volume_panel: pd.DataFrame,
    date: pd.Timestamp,
    min_adtv: float = 50_00_000,
    lookback: int = 20,
    symbols: Optional[List[str]] = None,
) -> List[str]:
    """
    Filter stocks by Average Daily Turnover Value (ADTV).

    ADTV = mean(Close × Volume) over trailing `lookback` days.
    Stocks with ADTV < min_adtv are excluded.

    Parameters
    ----------
    close_panel : DataFrame
        Wide-format close prices (dates × symbols).
    volume_panel : DataFrame
        Wide-format volume (dates × symbols).
    date : Timestamp
        Filter as of this date (point-in-time).
    min_adtv : float
        Minimum average daily turnover in ₹.
    lookback : int
        Number of trailing days for ADTV calculation.
    symbols : list, optional
        Restrict to these symbols.
    """
    # Get data up to the filter date
    mask = close_panel.index <= date
    close = close_panel.loc[mask].tail(lookback)
    vol = volume_panel.loc[mask].tail(lookback)

    if symbols:
        close = close[[s for s in symbols if s in close.columns]]
        vol = vol[[s for s in symbols if s in vol.columns]]

    # Common columns
    common = close.columns.intersection(vol.columns)
    close = close[common]
    vol = vol[common]

    # ADTV = mean(close × volume)
    turnover = close * vol
    adtv = turnover.mean()

    passed = adtv[adtv >= min_adtv].index.tolist()
    return passed


def apply_trading_days_filter(
    close_panel: pd.DataFrame,
    date: pd.Timestamp,
    min_pct: float = 0.90,
    lookback: int = 60,
    symbols: Optional[List[str]] = None,
) -> List[str]:
    """
    Filter stocks that haven't traded on enough days.

    A stock must have non-NaN close on ≥ min_pct of the last `lookback`
    trading days.
    """
    mask = close_panel.index <= date
    window = close_panel.loc[mask].tail(lookback)

    if symbols:
        window = window[[s for s in symbols if s in window.columns]]

    # Count non-NaN days per stock
    non_nan_count = window.notna().sum()
    total_days = len(window)

    if total_days == 0:
        return []

    pct_traded = non_nan_count / total_days
    passed = pct_traded[pct_traded >= min_pct].index.tolist()
    return passed


def apply_circuit_filter(
    high_panel: pd.DataFrame,
    low_panel: pd.DataFrame,
    close_panel: pd.DataFrame,
    date: pd.Timestamp,
    max_circuit_pct: float = 0.05,
    lookback: int = 20,
    symbols: Optional[List[str]] = None,
) -> List[str]:
    """
    Filter stocks that hit circuit limits too often.

    A circuit hit is approximated as: (High == Low) or
    daily return exactly matches common circuit percentages (±5%, ±10%, ±20%).
    """
    mask = close_panel.index <= date
    close = close_panel.loc[mask].tail(lookback + 1)
    high = high_panel.loc[mask].tail(lookback)
    low = low_panel.loc[mask].tail(lookback)

    if symbols:
        cols = [s for s in symbols if s in close.columns]
        close = close[cols]
        high = high[cols]
        low = low[cols]

    # Approximate circuit detection: High == Low (locked)
    locked = (high == low) & high.notna()
    circuit_pct = locked.sum() / locked.count()

    passed = circuit_pct[circuit_pct <= max_circuit_pct].index.tolist()
    return passed


def apply_spread_filter(
    high_panel: pd.DataFrame,
    low_panel: pd.DataFrame,
    close_panel: pd.DataFrame,
    date: pd.Timestamp,
    max_spread_pct: float = 0.10,
    lookback: int = 20,
    symbols: Optional[List[str]] = None,
) -> List[str]:
    """
    Filter stocks with excessively wide bid-ask spread proxy.

    Spread proxy = mean((High - Low) / Close) over lookback period.
    """
    mask = close_panel.index <= date
    close = close_panel.loc[mask].tail(lookback)
    high = high_panel.loc[mask].tail(lookback)
    low = low_panel.loc[mask].tail(lookback)

    if symbols:
        cols = [s for s in symbols if s in close.columns]
        close = close[cols]
        high = high[cols]
        low = low[cols]

    spread = ((high - low) / close.replace(0, np.nan)).mean()
    passed = spread[spread <= max_spread_pct].index.tolist()
    return passed


def apply_volume_consistency_filter(
    volume_panel: pd.DataFrame,
    date: pd.Timestamp,
    max_cv: float = 3.0,
    lookback: int = 60,
    symbols: Optional[List[str]] = None,
) -> List[str]:
    """
    Filter stocks with inconsistent volume (operator-driven spikes).

    CV (Coefficient of Variation) = StdDev(Volume) / Mean(Volume).
    High CV indicates manipulation-style volume spikes.
    """
    mask = volume_panel.index <= date
    window = volume_panel.loc[mask].tail(lookback)

    if symbols:
        window = window[[s for s in symbols if s in window.columns]]

    vol_mean = window.mean()
    vol_std = window.std()
    cv = vol_std / vol_mean.replace(0, np.nan)

    passed = cv[cv <= max_cv].dropna().index.tolist()
    return passed


def classify_liquidity_tier(
    close_panel: pd.DataFrame,
    volume_panel: pd.DataFrame,
    date: pd.Timestamp,
    symbols: List[str],
    lookback: int = 20,
) -> Dict[str, int]:
    """
    Classify stocks into liquidity tiers.

    Tier 1: ADTV > ₹5 Cr
    Tier 2: ADTV ₹1-5 Cr
    Tier 3: ADTV ₹50L-1 Cr

    Returns dict mapping symbol -> tier (1, 2, or 3).
    """
    mask = close_panel.index <= date
    close = close_panel.loc[mask].tail(lookback)
    vol = volume_panel.loc[mask].tail(lookback)

    common = [s for s in symbols if s in close.columns and s in vol.columns]
    turnover = close[common] * vol[common]
    adtv = turnover.mean()

    tiers = {}
    for sym in common:
        val = adtv.get(sym, 0)
        if val >= 5_00_00_000:      # ₹5 Cr
            tiers[sym] = 1
        elif val >= 1_00_00_000:    # ₹1 Cr
            tiers[sym] = 2
        else:
            tiers[sym] = 3

    return tiers


def apply_all_filters(
    close_panel: pd.DataFrame,
    high_panel: pd.DataFrame,
    low_panel: pd.DataFrame,
    volume_panel: pd.DataFrame,
    date: pd.Timestamp,
    config: Optional[UniverseConfig] = None,
) -> FilterResult:
    """
    Apply all universe filters sequentially for a given date.

    This is the main entry point for universe construction.
    All filters are point-in-time (only use data up to `date`).

    Returns FilterResult with the list of passed symbols.
    """
    config = config or UniverseConfig()
    result = FilterResult(date=date)

    # All available symbols
    all_symbols = close_panel.columns.tolist()
    result.initial_count = len(all_symbols)

    # 1. Price filter (on latest close as of date)
    mask = close_panel.index <= date
    latest_close = close_panel.loc[mask].iloc[-1] if mask.any() else pd.Series()
    price_passed = apply_price_filter(
        latest_close, config.min_price, config.max_price
    ).tolist()
    result.after_price = len(price_passed)
    logger.debug(f"After price filter: {result.after_price}")

    # 2. Liquidity filter (ADTV)
    liq_passed = apply_liquidity_filter(
        close_panel, volume_panel, date,
        config.min_avg_daily_turnover,
        config.turnover_lookback,
        symbols=price_passed,
    )
    result.after_liquidity = len(liq_passed)
    logger.debug(f"After liquidity filter: {result.after_liquidity}")

    # 3. Trading days filter
    td_passed = apply_trading_days_filter(
        close_panel, date,
        config.min_trading_days_pct,
        config.trading_days_lookback,
        symbols=liq_passed,
    )
    result.after_trading_days = len(td_passed)
    logger.debug(f"After trading days filter: {result.after_trading_days}")

    # 4. Circuit filter
    circ_passed = apply_circuit_filter(
        high_panel, low_panel, close_panel, date,
        config.max_circuit_hit_pct,
        config.circuit_lookback,
        symbols=td_passed,
    )
    result.after_circuit = len(circ_passed)
    logger.debug(f"After circuit filter: {result.after_circuit}")

    # 5. Spread filter
    spread_passed = apply_spread_filter(
        high_panel, low_panel, close_panel, date,
        config.max_spread_pct,
        config.spread_lookback,
        symbols=circ_passed,
    )
    result.after_spread = len(spread_passed)
    logger.debug(f"After spread filter: {result.after_spread}")

    # 6. Volume consistency filter
    vol_passed = apply_volume_consistency_filter(
        volume_panel, date,
        config.max_volume_cv,
        config.volume_cv_lookback,
        symbols=spread_passed,
    )
    result.after_volume_cv = len(vol_passed)
    result.final_count = len(vol_passed)
    result.passed_symbols = vol_passed

    logger.info(
        f"Universe for {date.date()}: "
        f"{result.initial_count} → {result.final_count} stocks "
        f"(price:{result.after_price}, liq:{result.after_liquidity}, "
        f"td:{result.after_trading_days}, circ:{result.after_circuit}, "
        f"spread:{result.after_spread}, volcv:{result.after_volume_cv})"
    )

    return result
