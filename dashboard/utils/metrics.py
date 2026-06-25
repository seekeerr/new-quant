"""Derived numbers from an equity curve and holdings.

Pure pandas/numpy. No strategy logic, no signal recomputation — these are the
same definitions used elsewhere in the project, applied to the *paper* curve.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

TARGET_WEIGHT = 0.10  # frozen champion: equal weight, 10% per name (Top10).


def drawdown_series(equity: pd.Series) -> pd.Series:
    """Drawdown fraction (<= 0) vs running peak."""
    if equity is None or equity.empty:
        return pd.Series(dtype=float)
    peak = equity.cummax()
    return (equity - peak) / peak


def current_drawdown(equity: pd.Series) -> Optional[float]:
    """Latest drawdown fraction (<= 0), or None if no data."""
    dd = drawdown_series(equity)
    return float(dd.iloc[-1]) if not dd.empty else None


def max_drawdown(equity: pd.Series) -> Optional[float]:
    dd = drawdown_series(equity)
    return float(dd.min()) if not dd.empty else None


def cagr(equity: pd.Series) -> Optional[float]:
    """Annualised compound growth from first to last point of a dated series."""
    if equity is None or equity.empty or len(equity) < 2:
        return None
    start_val, end_val = equity.iloc[0], equity.iloc[-1]
    if start_val <= 0:
        return None
    try:
        days = (equity.index[-1] - equity.index[0]).days
    except Exception:
        return None
    if days <= 0:
        return None
    years = days / 365.25
    return float((end_val / start_val) ** (1 / years) - 1)


def total_return(equity: pd.Series) -> Optional[float]:
    if equity is None or equity.empty or equity.iloc[0] <= 0:
        return None
    return float(equity.iloc[-1] / equity.iloc[0] - 1)


def enrich_holdings(holdings: pd.DataFrame, prices: pd.Series,
                    cash: float = 0.0) -> pd.DataFrame:
    """Add current_price, market_value, weight, pnl_pct to a holdings frame.

    Missing prices yield NaN (rendered as '—'), never an exception. Weight is
    of total portfolio value (holdings market value + cash).
    """
    if holdings is None or holdings.empty:
        return holdings.copy() if holdings is not None else pd.DataFrame()

    df = holdings.copy()
    df["current_price"] = df["symbol"].map(lambda s: prices.get(s, np.nan)
                                           if prices is not None else np.nan)
    df["market_value"] = df["quantity"] * df["current_price"]
    df["cost_value"] = df["quantity"] * df["cost_price"]

    invested = float(np.nansum(df["market_value"].to_numpy()))
    total_value = invested + float(cash or 0.0)
    df["weight"] = df["market_value"] / total_value if total_value > 0 else np.nan
    df["pnl_pct"] = (df["current_price"] - df["cost_price"]) / df["cost_price"]
    df["pnl_value"] = df["market_value"] - df["cost_value"]
    return df


def portfolio_value(holdings_enriched: pd.DataFrame, cash: float = 0.0) -> float:
    """Total NAV = sum of holding market values (NaN-safe) + cash."""
    invested = 0.0
    if holdings_enriched is not None and not holdings_enriched.empty \
            and "market_value" in holdings_enriched:
        invested = float(np.nansum(holdings_enriched["market_value"].to_numpy()))
    return invested + float(cash or 0.0)
